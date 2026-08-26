from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import SopError
from .profiles import ProjectProfile, load_profiles
from .request_text import RequestText, split_request_text


GENERIC_PROJECT_ALIASES = {"cocos", "cocos creator", "creator", "正式工程", "工程", "项目"}
PROJECT_TOKEN_RE = re.compile(r"(?i)\bproject\s*[-_a-z0-9]+\b|项目\s*[0-9]+(?:[-_a-z0-9]+)?")
MISROUTING_DESTINATION_RE = re.compile(
    r"(?i)(?:经常|总是|老是|反复|错误地?|误|不该)\s*(?:会|被)?\s*"
    r"(?:导航|跳转|进入|打开|识别|路由|定位)\s*(?:到|至|为|成)?\s*$|"
    r"(?:often|always|repeatedly|wrongly|incorrectly|mistakenly)\s+"
    r"(?:routes?|navigates?|redirects?|opens?|resolves?|detects?)\s+(?:to|as)\s*$"
)
MISROUTING_FIX_RE = re.compile(
    r"(?i)(?:修复|解决|避免|防止|fix|prevent).{0,24}"
    r"(?:导航|跳转|进入|打开|识别|路由|定位|route|navigate|redirect|open|resolve|detect)"
    r"\s*(?:到|至|为|成|to|as)?\s*$"
)
MISROUTING_ISSUE_RE = re.compile(r"(?i)^\s*(?:的)?(?:问题|异常|故障|bug|issue)(?:\b|$)")


@dataclass
class Candidate:
    profile: ProjectProfile
    root: Path | None
    score: int = 0
    evidence: list[str] = field(default_factory=list)

    def add(self, score: int, evidence: str, root: Path | None = None) -> None:
        self.score += score
        if evidence not in self.evidence:
            self.evidence.append(evidence)
        if root is not None:
            self.root = root.resolve()

    def clone(self) -> Candidate:
        return Candidate(self.profile, self.root, self.score, list(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile.id,
            "display_name": self.profile.display_name,
            "lifecycle": self.profile.lifecycle,
            "root": str(self.root) if self.root else None,
            "score": self.score,
            "evidence": self.evidence,
            "capabilities": list(self.profile.effective_capabilities),
            "adapters": list(self.profile.adapters),
        }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_nearby_child(path: Path, workspace: Path, *, max_depth: int = 2) -> bool:
    try:
        relative = path.resolve().relative_to(workspace.resolve())
    except ValueError:
        return False
    return 0 < len(relative.parts) <= max_depth


def _read_package(path: Path) -> dict[str, Any] | None:
    package_path = path / "package.json"
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _fingerprint_matches(profile: ProjectProfile, root: Path) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    required = profile.fingerprints.get("required_files", [])
    if isinstance(required, list):
        missing = [item for item in required if isinstance(item, str) and not (root / item).exists()]
        if missing:
            return False, []
        if required:
            evidence.append("工程结构指纹匹配")
    expected_package = profile.fingerprints.get("package_json", {})
    if expected_package:
        package = _read_package(root)
        if package is None:
            return False, []
        for key, value in expected_package.items():
            if package.get(key) != value:
                return False, []
        evidence.append("package.json 身份匹配")
    return bool(evidence), evidence


def _ancestor_roots(path: Path) -> list[Path]:
    resolved = path.expanduser().resolve()
    return [resolved, *resolved.parents]


def creator_processes(ps_text: str | None = None) -> list[dict[str, str]]:
    if ps_text is None:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        ps_text = completed.stdout
    found: list[dict[str, str]] = []
    for line in ps_text.splitlines():
        if "CocosCreator" not in line or "--project" not in line:
            continue
        match = re.match(r"\s*(\d+)\s+(.+?)\s+--project\s+(.+)$", line)
        if not match:
            continue
        project_text = match.group(3).strip()
        if " --" in project_text:
            project_text = project_text.split(" --", 1)[0]
        found.append({"pid": match.group(1), "project": project_text.strip("'\"")})
    return found


def _dynamic_profile(root: Path) -> ProjectProfile | None:
    package = _read_package(root)
    if package is None or not isinstance(package.get("creator"), dict):
        return None
    name = str(package.get("name") or root.name)
    identity = str(package.get("uuid") or root)
    profile_id = "detected-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    creator_version = package.get("creator", {}).get("version")
    return ProjectProfile(
        id=profile_id,
        display_name=f"{name}（当前检测到的 Cocos 工程）",
        lifecycle="detected",
        aliases=(name,),
        path_hints=(root,),
        fingerprints={"package_json": {"name": name}, "required_files": ["package.json", "assets"]},
        cocos={"creator_version": creator_version} if creator_version else {},
        capabilities=("engine:cocos",),
        adapters=(),
        source_path=Path("<runtime>"),
    )


def _build_candidates(
    current: Path,
    profiles: list[ProjectProfile],
    creator_entries: list[dict[str, str]],
) -> dict[str, Candidate]:
    candidates = {profile.id: Candidate(profile, None) for profile in profiles}
    creator_roots = {Path(entry["project"]).expanduser().resolve() for entry in creator_entries}

    for profile in profiles:
        candidate = candidates[profile.id]
        for root in profile.path_hints:
            if _is_within(current, root):
                candidate.add(300, "当前工作目录位于该工程", root)
            elif _is_nearby_child(root, current):
                candidate.add(240, "Profile 工程位于当前工作区", root)
            matched, match_evidence = _fingerprint_matches(profile, root)
            if matched:
                candidate.add(20, "；".join(match_evidence), root)
            if root in creator_roots:
                candidate.add(80, "Cocos Creator 当前打开该工程", root)

    discovered_roots: list[Path] = []
    for ancestor in _ancestor_roots(current):
        if (ancestor / "package.json").is_file() and (ancestor / "assets").is_dir():
            discovered_roots.append(ancestor)
            break
    for root in creator_roots:
        if root not in discovered_roots:
            discovered_roots.append(root)

    for root in discovered_roots:
        matched_known = False
        for profile in profiles:
            if not profile.selectable and root not in profile.path_hints:
                continue
            matched, evidence = _fingerprint_matches(profile, root)
            if matched:
                matched_known = True
                candidate = candidates[profile.id]
                points = 300 if _is_within(current, root) else 55
                candidate.add(points, "动态路径的" + "；".join(evidence), root)
                if root in creator_roots:
                    candidate.add(25, "运行中的 Creator 路径已由指纹复核", root)
        if not matched_known:
            dynamic = _dynamic_profile(root)
            if dynamic:
                candidate = Candidate(dynamic, root)
                if _is_within(current, root):
                    candidate.add(300, "发现当前目录中的未注册 Cocos 工程", root)
                elif root in creator_roots:
                    candidate.add(90, "Creator 当前打开未注册但结构完整的 Cocos 工程", root)
                else:
                    candidate.add(70, "发现未注册但结构完整的 Cocos 工程", root)
                candidates[dynamic.id] = candidate

    for candidate in candidates.values():
        if candidate.profile.lifecycle == "formal" and candidate.score > 0:
            candidate.add(40, "Profile 标记为当前正式工程")
    return candidates


def _profile_aliases(profiles: list[ProjectProfile]) -> dict[str, list[tuple[ProjectProfile, str]]]:
    owners: dict[str, list[tuple[ProjectProfile, str]]] = {}
    for profile in profiles:
        values = (profile.id, profile.display_name, *profile.aliases)
        for value in values:
            normalized = value.casefold().strip()
            if normalized and normalized not in GENERIC_PROJECT_ALIASES:
                owners.setdefault(normalized, []).append((profile, value))
    return owners


def _is_incident_destination(text: str, start: int, end: int) -> bool:
    prefix = text[max(0, start - 48) : start]
    suffix = text[end : end + 16]
    if MISROUTING_DESTINATION_RE.search(prefix):
        return True
    return bool(MISROUTING_FIX_RE.search(prefix) and MISROUTING_ISSUE_RE.search(suffix))


def _find_mentions(
    text: str,
    profiles: list[ProjectProfile],
    source: str,
    *,
    incident_destinations: bool | None = None,
) -> list[dict[str, str]]:
    lowered = text.casefold()
    matches: dict[str, dict[str, str]] = {}
    for normalized, owners in _profile_aliases(profiles).items():
        if len(owners) != 1:
            continue
        positions = [match.start() for match in re.finditer(re.escape(normalized), lowered)]
        if incident_destinations is not None:
            positions = [
                start
                for start in positions
                if _is_incident_destination(lowered, start, start + len(normalized)) is incident_destinations
            ]
        if not positions:
            continue
        profile, alias = owners[0]
        current = matches.get(profile.id)
        if current is None or len(alias) > len(current["alias"]):
            matches[profile.id] = {
                "profile_id": profile.id,
                "display_name": profile.display_name,
                "alias": alias,
                "source": source,
            }
    return sorted(matches.values(), key=lambda item: item["profile_id"])


def _merge_mentions(*groups: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for group in groups:
        for item in group:
            current = merged.get(item["profile_id"])
            if current is None or len(item["alias"]) > len(current["alias"]):
                merged[item["profile_id"]] = item
    return sorted(merged.values(), key=lambda item: item["profile_id"])


def _unresolved_tokens(request_text: RequestText, profiles: list[ProjectProfile]) -> list[str]:
    resolved_aliases = set(_profile_aliases(profiles))
    unresolved: set[str] = set()
    for match in PROJECT_TOKEN_RE.finditer(request_text.actionable):
        token = re.sub(r"\s+", "", match.group(0)).casefold()
        if token not in {re.sub(r"\s+", "", alias) for alias in resolved_aliases}:
            unresolved.add(match.group(0).strip())
    return sorted(unresolved)


def _ranked(candidates: dict[str, Candidate]) -> list[Candidate]:
    return sorted(
        (candidate for candidate in candidates.values() if candidate.score > 0 and candidate.root is not None),
        key=lambda candidate: (-candidate.score, candidate.profile.id),
    )


def _ambiguous(ranked: list[Candidate]) -> bool:
    return len(ranked) > 1 and ranked[1].score >= ranked[0].score - 15 and ranked[1].root != ranked[0].root


def _confirmation(
    ranked: list[Candidate],
    *,
    actionable_mentions: list[dict[str, str]],
    reference_mentions: list[dict[str, str]],
    unresolved_mentions: list[str],
    request_text: RequestText,
) -> dict[str, Any]:
    if not ranked:
        message = "没有足够证据确定当前工程。请告诉我你要操作哪个工程，我会自动建立或匹配配置。"
        candidates: list[dict[str, Any]] = []
    elif len(ranked) == 1:
        top = ranked[0]
        message = f"请求点名了 {top.profile.display_name}，但还需要确认这是本次要操作的工程。"
        candidates = [top.to_dict()]
    else:
        top = ranked[0]
        second = ranked[1]
        message = (
            f"我同时检测到 {top.profile.display_name} 和 {second.profile.display_name}。"
            f"建议使用 {top.profile.display_name}，因为：{'；'.join(top.evidence)}。你要操作这个工程吗？"
        )
        candidates = [item.to_dict() for item in ranked[:3]]
    return {
        "status": "needs_confirmation",
        "schema": "sop.context.v1",
        "message": message,
        "candidates": candidates,
        "actionable_mentions": actionable_mentions,
        "reference_mentions": reference_mentions,
        "unresolved_project_mentions": unresolved_mentions,
        "request_text": {"actionable": request_text.actionable, "reference": request_text.reference},
    }


def resolve_context(
    *,
    cwd: Path | str | None = None,
    request: str = "",
    profile_dir: Path | None = None,
    ps_text: str | None = None,
) -> dict[str, Any]:
    current = Path(cwd or Path.cwd()).expanduser().resolve()
    profiles = load_profiles(profile_dir, cwd=current)
    creator_entries = creator_processes(ps_text)
    candidates = _build_candidates(current, profiles, creator_entries)
    ranked_active = _ranked(candidates)
    request_text = split_request_text(request)
    actionable_mentions = _find_mentions(
        request_text.actionable,
        profiles,
        "actionable",
        incident_destinations=False,
    )
    incident_mentions = _find_mentions(
        request_text.actionable,
        profiles,
        "incident",
        incident_destinations=True,
    )
    reference_mentions = _merge_mentions(
        _find_mentions(request_text.reference, profiles, "reference"),
        incident_mentions,
    )
    unresolved_mentions = _unresolved_tokens(request_text, profiles)

    if not ranked_active:
        return _confirmation(
            ranked_active,
            actionable_mentions=actionable_mentions,
            reference_mentions=reference_mentions,
            unresolved_mentions=unresolved_mentions,
            request_text=request_text,
        )

    active_project = ranked_active[0]
    operation_project: Candidate | None = None
    mentioned_ids = {item["profile_id"] for item in actionable_mentions}
    if len(mentioned_ids) > 1:
        explicitly_ranked = [candidates[item].clone() for item in sorted(mentioned_ids) if candidates[item].root is not None]
        for candidate in explicitly_ranked:
            candidate.add(500, "请求在可执行正文中明确点名该工程")
        return _confirmation(
            sorted(explicitly_ranked, key=lambda item: item.profile.id),
            actionable_mentions=actionable_mentions,
            reference_mentions=reference_mentions,
            unresolved_mentions=unresolved_mentions,
            request_text=request_text,
        )
    if len(mentioned_ids) == 1:
        mentioned_id = next(iter(mentioned_ids))
        candidate = candidates[mentioned_id]
        if candidate.root is None or candidate.score <= 0:
            result = _confirmation(
                [],
                actionable_mentions=actionable_mentions,
                reference_mentions=reference_mentions,
                unresolved_mentions=unresolved_mentions,
                request_text=request_text,
            )
            result["message"] = f"请求点名了 {candidate.profile.display_name}，但当前文件指纹不足以验证该工程。请提供或打开正确工程。"
            return result
        operation_project = candidate.clone()
        operation_project.add(500, "请求在可执行正文中明确点名该工程")
    elif _ambiguous(ranked_active):
        return _confirmation(
            ranked_active,
            actionable_mentions=actionable_mentions,
            reference_mentions=reference_mentions,
            unresolved_mentions=unresolved_mentions,
            request_text=request_text,
        )
    else:
        operation_project = active_project.clone()

    operation = operation_project.to_dict()
    active = active_project.to_dict()
    context_mismatch = operation.get("root") != active.get("root")
    if context_mismatch:
        message = f"已识别操作目标：{operation['display_name']}；当前运行工程：{active['display_name']}。"
    else:
        message = f"已识别当前工程：{operation['display_name']}"
    return {
        "status": "success",
        "schema": "sop.context.v1",
        "message": message,
        "project": operation,
        "operation_project": operation,
        "active_project": active,
        "context_mismatch": context_mismatch,
        "actionable_mentions": actionable_mentions,
        "reference_mentions": reference_mentions,
        "unresolved_project_mentions": unresolved_mentions,
        "request_text": {"actionable": request_text.actionable, "reference": request_text.reference},
        "alternatives": [item.to_dict() for item in ranked_active[1:3]],
    }


def require_resolved_context(**kwargs: Any) -> dict[str, Any]:
    result = resolve_context(**kwargs)
    if result["status"] != "success":
        raise SopError("PROJECT_AMBIGUOUS", result["message"], details=result)
    return result
