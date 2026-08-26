from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility for the installed launcher.
    tomllib = None  # type: ignore[assignment]

from .errors import SopError


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = AUTOMATION_ROOT / "framework" / "package-policy.json"
POLICY_SCHEMA = "sop.framework-package-policy.v1"
RESULT_SCHEMA = "sop.framework-package-result.v1"
MANIFEST_SCHEMA = "sop.framework-package-manifest.v1"
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SopError("FRAMEWORK_POLICY_NOT_FOUND", str(path)) from exc
    except json.JSONDecodeError as exc:
        raise SopError("INVALID_FRAMEWORK_POLICY", f"{path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != POLICY_SCHEMA:
        raise SopError("INVALID_FRAMEWORK_POLICY", f"{path}: unsupported or missing schema")
    for key in ("archive_root", "include_files", "include_globs", "exclude_parts", "replacements", "forbidden_terms"):
        if key not in payload:
            raise SopError("INVALID_FRAMEWORK_POLICY", f"{path}: missing {key}")
    if not isinstance(payload["archive_root"], str) or not payload["archive_root"].strip():
        raise SopError("INVALID_FRAMEWORK_POLICY", f"{path}: archive_root must be a non-empty string")
    list_fields = ("include_files", "include_globs", "exclude_parts", "forbidden_terms", "forbidden_regex")
    for key in list_fields:
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise SopError("INVALID_FRAMEWORK_POLICY", f"{path}: {key} must contain non-empty strings")
    replacements = payload["replacements"]
    if not isinstance(replacements, list) or not all(
        isinstance(item, list)
        and len(item) == 2
        and all(isinstance(part, str) and part for part in item)
        for item in replacements
    ):
        raise SopError("INVALID_FRAMEWORK_POLICY", f"{path}: replacements must contain [source, replacement] pairs")
    return payload


def _source_files(source_root: Path, policy: dict[str, Any]) -> list[Path]:
    paths: set[Path] = set()
    for relative in policy["include_files"]:
        candidate = (source_root / relative).resolve()
        if not candidate.is_file():
            raise SopError("FRAMEWORK_SOURCE_INCOMPLETE", f"required source file is missing: {relative}")
        paths.add(candidate)
    for pattern in policy["include_globs"]:
        paths.update(path.resolve() for path in source_root.glob(pattern) if path.is_file())

    exclude_parts = set(policy["exclude_parts"])
    selected = [
        path
        for path in paths
        if not exclude_parts.intersection(path.relative_to(source_root).parts)
    ]
    return sorted(selected, key=lambda path: path.relative_to(source_root).as_posix())


def _sanitize_text(text: str, policy: dict[str, Any]) -> str:
    sanitized = text
    for source, replacement in policy["replacements"]:
        sanitized = sanitized.replace(source, replacement)
    return sanitized


def _runtime_readme() -> str:
    return """# SOP Factory Framework Runtime

This runtime contains the complete deterministic CLI and recipe implementation without bundled
project profiles, adapters, business contracts, learned models, local state, caches, credentials,
or generated artifacts.

Run `python3 sop.py recipe list --json` to inspect capabilities. Add project knowledge through
`profiles/`, `.sop/profiles/`, user configuration, or the adapter directories described in the
root README. Writes remain dry-run by default where supported, and packaging remains high risk.
"""


def _root_readme() -> str:
    return """# SOP Factory Framework Edition

This is a project-neutral, self-contained framework package. It includes the deterministic SOP
runtime, all recipe implementations, tests, a Codex plugin entry, and empty extension surfaces.
It intentionally contains no real project profile, project adapter, business contract, learned
example, usage state, cache, credential, absolute workstation path, or generated project output.

## Layout

- `runtime/`: Python CLI, recipes, tests, and empty extension directories.
- `.codex-plugin/`, `skills/`, `scripts/`: Codex plugin surface, SOP router, learning closeout, and bundled launcher.
- `FRAMEWORK_MANIFEST.json`: deterministic file inventory and knowledge-isolation claims.

## Run

```bash
./scripts/run-sop recipe list --json
./scripts/run-sop config validate --json
```

Install Python 3.11+ and Pillow before using image recipes. Project knowledge is injected later
through a project-owned `.sop/` directory, user configuration, or explicitly configured extension
directories. Keep real profiles, adapters, contracts, models, secrets, and outputs outside this
framework package.
"""


def _plugin_manifest() -> str:
    payload = {
        "name": "sop-factory-framework",
        "version": "1.0.1",
        "description": "Project-neutral deterministic SOP framework with empty knowledge extensions.",
        "author": {"name": "Local developer"},
        "skills": "./skills/",
        "interface": {
            "displayName": "SOP Framework",
            "shortDescription": "Route work to deterministic recipes without bundled project knowledge.",
            "longDescription": "Provides the complete SOP runtime, risk gates, evidence contracts, and empty Profile and Adapter extension surfaces.",
            "developerName": "Local developer",
            "category": "Productivity",
            "capabilities": [
                "Natural-language SOP routing",
                "Project Profile injection",
                "Deterministic recipe execution",
                "Dry-run and atomic write gates",
                "Framework package auditing",
                "Verified learning closeout",
            ],
            "defaultPrompt": [
                "Inspect the available project-neutral SOP recipes.",
                "Validate the current project's locally supplied Profile.",
                "Turn a repeatable operation into a verified recipe candidate.",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _plugin_skill() -> str:
    return """---
name: sop
description: Route project work through the bundled project-neutral deterministic SOP runtime.
---

# SOP Framework Router

Use the plugin root's `scripts/run-sop` launcher as the deterministic evidence layer.

1. For an empty or capability question, run `scripts/run-sop status --json`.
2. Otherwise run `scripts/run-sop directive '<original request>' --json` safely.
3. For project-scoped work, run `scripts/run-sop context --request '<normalized request>' --json`.
4. Search registered recipes with `scripts/run-sop recipe search --request '<request>' --json`.
5. Only execute a unique compatible recipe. Stop on confirmation, no-match, or known contract errors.

Disclose each real SOP call with its action, purpose, risk, result, counters, and one decisive fact.
Read-only checks do not authorize writes. Delete, package, publish, push, permissions, and secrets
remain high risk and require explicit approval for the exact current target. Project knowledge must
come from an injected Profile, Adapter, contract, or runtime fingerprint, never from this package.

When promoting a repeatable operation, follow `references/recipe-policy.md`.
"""


def _recipe_policy() -> str:
    return """# Recipe Promotion Policy

Every recipe needs stable JSON output, stable error codes, an explicit risk level, representative
fixtures, documented completion criteria, and dry-run for writes. Normal writes also require atomic
commit, input/output conflict protection, and idempotency. High-risk operations may generate and
validate a candidate only until the user approves the exact target. Project differences belong in
Profiles, Adapters, contracts, or fixtures; core code must not contain real project paths or knowledge.
"""


def _learning_closeout_skill() -> str:
    return """---
name: learning-closeout
description: Run the mandatory learning closeout after corrections, preventable mistakes, rework, failed routes, rollback, incidents, or verified better methods.
---

# Learning Closeout

Use this skill as a final-response gate. It does not replace requested work or expand permission for external actions.

## Trigger Audit

Run the closeout when the task includes a user correction, an agent-caused mistake or omission,
retry or reroute, rollback, security or remote-write incident, disproved assumption, or verified
better method. The user must not need to request it.

## Learning Decision

1. Record the incident or route change in the governed diary.
2. Assess mechanism-level facts separately from reusable control-level rules.
3. Require current evidence; do not persist guesses, logs, secrets, temporary state, or ordinary progress.
4. Search the governed memory narrowly for three to five same-scope results.
5. Deduplicate each verified reusable lesson before writing one semantic conclusion per lesson item.
6. Read back every new item and run a narrow recall query that finds it.
7. If no durable lesson qualifies, write `LESSON_DECISION:none|trigger=<signal>|reason=<specific boundary>|evidence=<checked evidence>` to the diary.

Use only the configured governed public MemPalace MCP and its active governance policy. If it is
unavailable, report that once and continue the main task without bypassing the guard.

## Completion Gate

Do not send the final response until the final diary status is written and every qualifying lesson
has passed deduplication, write, readback, and recall testing, or every trigger has an evidence-backed
structured no-lesson decision. Briefly report what was persisted or why nothing qualified.
"""


def _learning_closeout_agent() -> str:
    return """interface:
  display_name: "Learning Closeout"
  short_description: "Persist verified lessons before task completion"
  default_prompt: "Use $learning-closeout to audit this task for errors, corrections, and reusable lessons before finalizing."
"""


def _launcher() -> str:
    return """#!/bin/zsh
set -euo pipefail

PLUGIN_ROOT="${0:A:h:h}"
SOP_AUTOMATION_ROOT="$PLUGIN_ROOT/runtime"
SOP_MAIN="$SOP_AUTOMATION_ROOT/sop.py"
if [[ ! -f "$SOP_MAIN" ]]; then
  print -u2 "SOP_INSTALLATION_NOT_FOUND: expected bundled runtime/sop.py"
  exit 127
fi
export PYTHONPATH="$SOP_AUTOMATION_ROOT"
exec python3 "$SOP_MAIN" "$@"
"""


def _empty_extension_readme(kind: str, environment: str) -> str:
    return f"""# Empty {kind} Extension Surface

No project knowledge is bundled here. Supply validated {kind} files through a project-owned `.sop/`
directory, user configuration, or `{environment}`. Keep paths relative where portability matters.
"""


def _neutral_policy() -> str:
    payload = {
        "schema": POLICY_SCHEMA,
        "archive_root": "sop-factory-framework",
        "include_files": ["sop.py", "sop.command", "pyproject.toml", "uv.lock"],
        "include_globs": ["sop_factory/**/*.py", "tests/**/*.py", "tests/fixtures/**/*"],
        "exclude_parts": ["__pycache__", ".pytest_cache", ".venv"],
        "replacements": [],
        "forbidden_terms": [],
        "forbidden_regex": [r"/(?:Users|home)/[^\s\"']+", r"[A-Za-z]:\\\\Users\\[^\s\"']+"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _generated_files() -> dict[str, bytes]:
    return {
        "README.md": _root_readme().encode(),
        ".codex-plugin/plugin.json": _plugin_manifest().encode(),
        "skills/sop/SKILL.md": _plugin_skill().encode(),
        "skills/sop/agents/openai.yaml": b'interface:\n  display_name: "SOP Framework"\n  short_description: "Project-neutral deterministic SOP routing"\n  brand_color: "#008C95"\n  default_prompt: "Use $sop to inspect the available project-neutral recipes."\n',
        "skills/sop/references/recipe-policy.md": _recipe_policy().encode(),
        "skills/learning-closeout/SKILL.md": _learning_closeout_skill().encode(),
        "skills/learning-closeout/agents/openai.yaml": _learning_closeout_agent().encode(),
        "scripts/run-sop": _launcher().encode(),
        "runtime/README.md": _runtime_readme().encode(),
        "runtime/profiles/README.md": _empty_extension_readme("Profile", "SOP_PROFILE_DIRS").encode(),
        "runtime/adapters/card-edge/README.md": _empty_extension_readme("card-edge Adapter", "SOP_CARD_EDGE_ADAPTER_DIRS").encode(),
        "runtime/adapters/reel-cell/README.md": _empty_extension_readme("reel-cell Adapter", "SOP_REEL_CELL_ADAPTER_DIRS").encode(),
        "runtime/adapters/reward-spine/README.md": _empty_extension_readme("reward-spine Adapter", "SOP_REWARD_SPINE_ADAPTER_DIRS").encode(),
        "runtime/contracts/README.md": _empty_extension_readme("contract", "project configuration").encode(),
        "runtime/models/card_frame_models.json": b'{"schema":"sop.card-frame-model-registry.v1","models":[]}\n',
        "runtime/framework/package-policy.json": _neutral_policy().encode(),
    }


def _build_entries(source_root: Path, policy: dict[str, Any]) -> dict[str, bytes]:
    entries = _generated_files()
    for path in _source_files(source_root, policy):
        relative = path.relative_to(source_root).as_posix()
        archive_path = f"runtime/{relative}"
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            entries[archive_path] = data
        else:
            sanitized = _sanitize_text(text, policy)
            if archive_path.endswith(".py"):
                try:
                    compile(sanitized, archive_path, "exec")
                except SyntaxError as exc:
                    raise SopError(
                        "FRAMEWORK_SANITIZED_SOURCE_INVALID",
                        f"sanitized Python source does not compile: {archive_path}:{exc.lineno}",
                        details={"path": archive_path, "line": exc.lineno, "offset": exc.offset},
                    ) from exc
            entries[archive_path] = sanitized.encode("utf-8")
    return entries


def _scan_entries(entries: dict[str, bytes], policy: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    forbidden_terms = tuple(policy["forbidden_terms"])
    forbidden_regex = tuple(re.compile(pattern) for pattern in policy.get("forbidden_regex", []))
    forbidden_member_patterns = (
        re.compile(r"^runtime/profiles/.*\.json$"),
        re.compile(r"^runtime/adapters/.*\.json$"),
        re.compile(r"^runtime/contracts/.*\.json$"),
    )
    for name, data in sorted(entries.items()):
        if any(pattern.search(name) for pattern in forbidden_member_patterns):
            violations.append({"path": name, "reason": "bundled_project_knowledge_file"})
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for term in forbidden_terms:
            if term.casefold() in text.casefold() or term.casefold() in name.casefold():
                violations.append({"path": name, "reason": f"forbidden_term:{term}"})
        for pattern in forbidden_regex:
            if pattern.search(text) or pattern.search(name):
                violations.append({"path": name, "reason": f"forbidden_pattern:{pattern.pattern}"})
    return violations


def _manifest(entries: dict[str, bytes], policy: dict[str, Any], source_root: Path) -> dict[str, Any]:
    version = "unknown"
    try:
        pyproject_text = (source_root / "pyproject.toml").read_text(encoding="utf-8")
        if tomllib is not None:
            version = str(tomllib.loads(pyproject_text)["project"]["version"])
        else:
            match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject_text, flags=re.MULTILINE)
            if match:
                version = match.group(1)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        pass
    return {
        "schema": MANIFEST_SCHEMA,
        "framework_version": version,
        "archive_root": policy["archive_root"],
        "deterministic": True,
        "knowledge_isolation": {
            "bundled_profiles": 0,
            "bundled_project_adapters": 0,
            "bundled_business_contracts": 0,
            "bundled_learned_examples": 0,
            "bundled_usage_state": False,
            "absolute_workstation_paths": False,
        },
        "files": [
            {"path": name, "bytes": len(data), "sha256": _sha256(data)}
            for name, data in sorted(entries.items())
        ],
    }


def _zip_bytes(root_name: str, entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(entries.items()):
            name = (PurePosixPath(root_name) / relative).as_posix()
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((0o755 if relative in {"scripts/run-sop", "runtime/sop.command"} else 0o644) & 0xFFFF) << 16
            info.create_system = 3
            archive.writestr(info, data)
    return buffer.getvalue()


def package_framework(
    output: Path,
    *,
    apply: bool = False,
    source_root: Path | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    root = (source_root or AUTOMATION_ROOT).expanduser().resolve()
    target = output.expanduser().resolve()
    if target.suffix.casefold() != ".zip":
        raise SopError("INVALID_FRAMEWORK_OUTPUT", "framework output must be a .zip file")
    if not root.is_dir():
        raise SopError("FRAMEWORK_SOURCE_NOT_FOUND", str(root))
    policy = _load_policy((policy_path or DEFAULT_POLICY_PATH).expanduser().resolve())
    entries = _build_entries(root, policy)
    violations = _scan_entries(entries, policy)
    if violations:
        raise SopError(
            "FRAMEWORK_KNOWLEDGE_LEAK",
            "project knowledge or workstation-specific data remains in the candidate",
            details={"violations": violations[:50], "violation_count": len(violations)},
        )
    manifest = _manifest(entries, policy, root)
    entries["FRAMEWORK_MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    archive_bytes = _zip_bytes(policy["archive_root"], entries)
    archive_sha256 = _sha256(archive_bytes)

    cache_hit = False
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or _sha256(target.read_bytes()) != archive_sha256:
                raise SopError("FRAMEWORK_OUTPUT_CONFLICT", f"refusing to overwrite existing output: {target}")
            cache_hit = True
        else:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".tmp", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(archive_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

    return {
        "status": "success",
        "schema": RESULT_SCHEMA,
        "mode": "apply" if apply else "dry_run",
        "applied": apply,
        "cache_hit": cache_hit,
        "output": str(target),
        "archive_root": policy["archive_root"],
        "archive_bytes": len(archive_bytes),
        "archive_sha256": archive_sha256,
        "entry_count": len(entries),
        "knowledge_scan": {
            "status": "pass",
            "violation_count": 0,
            "bundled_profiles": 0,
            "bundled_project_adapters": 0,
            "bundled_business_contracts": 0,
            "bundled_learned_examples": 0,
        },
        "checks": {
            "source_allowlist": "pass",
            "project_knowledge_excluded": "pass",
            "absolute_paths_excluded": "pass",
            "python_sources_compile": "pass",
            "plugin_surface_included": "pass",
            "deterministic_zip": "pass",
            "atomic_output": "pass" if apply else "not_run",
        },
        "completion": {
            "package_created": apply,
            "plugin_validation_required": apply,
            "unpacked_test_required": apply,
        },
    }
