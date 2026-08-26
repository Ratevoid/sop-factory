from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .errors import SopError


CONTRACT_SCHEMA = "sop.source-learning-contract.v1"
RESULT_SCHEMA = "sop.source-learning-result.v1"
PACKAGE_SCHEMA = "sop.source-learning-package.v1"
DIFFERENTIAL_SCHEMA = "sop.source-learning-differential.v1"
CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".lua", ".java", ".kt", ".cpp", ".cc", ".c", ".h", ".hpp"}
TEXT_SUFFIXES = CODE_SUFFIXES | {".json", ".fire", ".scene", ".prefab", ".atlas", ".plist", ".xml", ".yaml", ".yml", ".md", ".txt"}
BEHAVIOR_STATUSES = {"unknown", "discovered", "invalidated", "verified"}
TEST_KINDS = {"static", "differential", "runtime", "negative"}


def _fail(code: str, message: str, **details: Any) -> None:
    raise SopError(code, message, details=details)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _decode_text(data: bytes, path: Path) -> tuple[str, str]:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    _fail("SOURCE_LEARNING_EVIDENCE_NOT_TEXT", f"cannot decode text evidence: {path}")


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        _fail("SOURCE_LEARNING_CONTRACT_MISSING", f"contract does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("SOURCE_LEARNING_CONTRACT_INVALID_JSON", str(exc))
    if not isinstance(value, dict):
        _fail("SOURCE_LEARNING_CONTRACT_INVALID", "contract root must be an object")
    if value.get("schema") != CONTRACT_SCHEMA:
        _fail("SOURCE_LEARNING_CONTRACT_VERSION_UNSUPPORTED", f"expected {CONTRACT_SCHEMA}")
    return value


def _obj(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("SOURCE_LEARNING_CONTRACT_INVALID", f"{field} must be an object")
    return value


def _arr(value: Any, field: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("SOURCE_LEARNING_CONTRACT_INVALID", f"{field} must be a{' possibly empty' if allow_empty else ' non-empty'} array")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("SOURCE_LEARNING_CONTRACT_INVALID", f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,95}", result):
        _fail("SOURCE_LEARNING_CONTRACT_INVALID", f"{field} is not a stable identifier: {result}")
    return result


def _resolve(base: Path, value: Any, field: str) -> Path:
    raw = _text(value, field)
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])) for pattern in patterns)


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in CODE_SUFFIXES:
        return "code"
    if suffix in {".json", ".yaml", ".yml", ".xml", ".plist"}:
        return "config"
    if suffix in {".fire", ".scene", ".prefab"}:
        return "scene"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".atlas", ".skel"}:
        return "visual"
    if suffix in {".mp3", ".wav", ".ogg", ".m4a"}:
        return "audio"
    return "other"


def _scan_roots(contract: dict[str, Any], contract_file: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    roots: dict[str, dict[str, Any]] = {}
    inventory: list[dict[str, Any]] = []
    for index, raw in enumerate(_arr(contract.get("corpus_roots"), "corpus_roots")):
        item = _obj(raw, f"corpus_roots[{index}]")
        root_id = _identifier(item.get("id"), "corpus_root.id")
        if root_id in roots:
            _fail("SOURCE_LEARNING_DUPLICATE_ROOT", f"duplicate corpus root: {root_id}")
        path = _resolve(contract_file.parent, item.get("path"), "corpus_root.path")
        if not path.is_dir():
            _fail("SOURCE_LEARNING_ROOT_MISSING", f"corpus root does not exist: {path}", root_id=root_id)
        includes = [_text(value, "corpus_root.include") for value in _arr(item.get("include", ["**/*"]), "corpus_root.include")]
        excludes = [_text(value, "corpus_root.exclude") for value in _arr(item.get("exclude", []), "corpus_root.exclude", allow_empty=True)]
        roots[root_id] = {"id": root_id, "path": path, "role": _text(item.get("role", "source"), "corpus_root.role"), "include": includes, "exclude": excludes}
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            relative = candidate.relative_to(path).as_posix()
            if not _matches(relative, includes) or _matches(relative, excludes):
                continue
            data = candidate.read_bytes()
            inventory.append({"root_id": root_id, "path": relative, "kind": _kind(candidate), "suffix": candidate.suffix.lower(), "bytes": len(data), "sha256": _sha(data)})
    if not inventory:
        _fail("SOURCE_LEARNING_EMPTY_CORPUS", "corpus roots matched no files")
    return roots, inventory


def _source_path(roots: dict[str, dict[str, Any]], root_id: Any, relative: Any, field: str) -> tuple[Path, str, str]:
    root_key = _identifier(root_id, f"{field}.root_id")
    if root_key not in roots:
        _fail("SOURCE_LEARNING_UNKNOWN_ROOT", f"unknown corpus root: {root_key}")
    rel = _text(relative, f"{field}.path").replace("\\", "/")
    candidate = (roots[root_key]["path"] / rel).resolve()
    if not _inside(candidate, roots[root_key]["path"]):
        _fail("SOURCE_LEARNING_PATH_ESCAPE", f"{field}.path escapes corpus root", path=rel)
    if not candidate.is_file():
        _fail("SOURCE_LEARNING_EVIDENCE_MISSING", f"evidence file does not exist: {candidate}")
    return candidate, root_key, rel


def _anchor(raw: Any, roots: dict[str, dict[str, Any]], field: str) -> dict[str, Any]:
    item = _obj(raw, field)
    path, root_id, relative = _source_path(roots, item.get("root_id"), item.get("path"), field)
    data = path.read_bytes()
    expected = item.get("sha256")
    if expected is not None and expected != _sha(data):
        _fail("SOURCE_LEARNING_EVIDENCE_DRIFT", f"evidence hash drifted: {path}", expected=expected, actual=_sha(data))
    start = item.get("line_start")
    end = item.get("line_end", start)
    snippet_hash = None
    if start is not None:
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            _fail("SOURCE_LEARNING_EVIDENCE_RANGE_INVALID", f"invalid line range for {path}")
        decoded, encoding = _decode_text(data, path)
        lines = decoded.splitlines()
        if end > len(lines):
            _fail("SOURCE_LEARNING_EVIDENCE_RANGE_INVALID", f"line range exceeds file: {path}", line_count=len(lines))
        snippet_hash = _sha("\n".join(lines[start - 1:end]).encode("utf-8"))
    return {"root_id": root_id, "path": relative, "sha256": _sha(data), "line_start": start, "line_end": end, "snippet_sha256": snippet_hash, "encoding": encoding if start is not None else None}


def _lookup(value: Any, dotted: str) -> Any:
    current = value
    for part in dotted.split("."):
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _unit(vector: list[Any], field: str) -> tuple[float, float]:
    if len(vector) != 2 or not all(isinstance(value, (int, float)) for value in vector):
        _fail("SOURCE_LEARNING_DIFFERENTIAL_INVALID", f"{field} must be a numeric 2D vector")
    length = math.hypot(float(vector[0]), float(vector[1]))
    if length <= 1e-12:
        _fail("SOURCE_LEARNING_DIFFERENTIAL_INVALID", f"{field} must be non-zero")
    return float(vector[0]) / length, float(vector[1]) / length


def _differential(path: Path, tolerance: float) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("SOURCE_LEARNING_DIFFERENTIAL_INVALID", str(exc))
    if not isinstance(payload, dict) or payload.get("schema") != DIFFERENTIAL_SCHEMA:
        _fail("SOURCE_LEARNING_DIFFERENTIAL_INVALID", f"expected {DIFFERENTIAL_SCHEMA}: {path}")
    cases = _arr(payload.get("cases"), "differential.cases")
    failures: list[str] = []
    for index, raw in enumerate(cases):
        case = _obj(raw, f"differential.cases[{index}]")
        case_id = _identifier(case.get("id"), "differential.case.id")
        reference = _obj(case.get("reference"), "differential.reference")
        candidate = _obj(case.get("candidate"), "differential.candidate")
        if "direction" in reference or "direction" in candidate:
            a = _unit(_arr(reference.get("direction"), "reference.direction"), "reference.direction")
            b = _unit(_arr(candidate.get("direction"), "candidate.direction"), "candidate.direction")
            if a[0] * b[0] + a[1] * b[1] < 1.0 - tolerance:
                failures.append(case_id)
        if "events" in reference or "events" in candidate:
            if reference.get("events") != candidate.get("events"):
                failures.append(case_id)
        if "value" in reference or "value" in candidate:
            left, right = reference.get("value"), candidate.get("value")
            if not isinstance(left, (int, float)) or not isinstance(right, (int, float)) or abs(float(left) - float(right)) > tolerance:
                failures.append(case_id)
    if failures:
        _fail("SOURCE_LEARNING_DIFFERENTIAL_FAILED", "reference and candidate behavior differ", cases=sorted(set(failures)), fixture=str(path))
    return {"fixture": str(path), "sha256": _sha(path.read_bytes()), "cases": len(cases), "status": "pass"}


def _test(raw: Any, roots: dict[str, dict[str, Any]], contract_file: Path, field: str) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    item = _obj(raw, field)
    test_id = _identifier(item.get("id"), f"{field}.id")
    kind = _text(item.get("kind"), f"{field}.kind")
    if kind not in TEST_KINDS:
        _fail("SOURCE_LEARNING_TEST_KIND_INVALID", f"unsupported test kind: {kind}")
    if item.get("status") != "pass":
        _fail("SOURCE_LEARNING_VERIFIED_TEST_NOT_PASSING", f"verified behavior test must pass: {test_id}")
    execution_paths = [_identifier(value, f"{field}.execution_paths") for value in _arr(item.get("execution_paths"), f"{field}.execution_paths")]
    evidence: dict[str, Any] = {"id": test_id, "kind": kind, "status": "pass", "execution_paths": execution_paths}
    mapped: set[tuple[str, str]] = set()
    if kind == "differential":
        fixture = _resolve(contract_file.parent, item.get("fixture"), f"{field}.fixture")
        if not fixture.is_file():
            _fail("SOURCE_LEARNING_DIFFERENTIAL_MISSING", f"differential fixture does not exist: {fixture}")
        tolerance = item.get("tolerance", 1e-6)
        if not isinstance(tolerance, (int, float)) or tolerance < 0:
            _fail("SOURCE_LEARNING_DIFFERENTIAL_INVALID", "tolerance must be non-negative")
        evidence["result"] = _differential(fixture, float(tolerance))
    if kind == "runtime":
        report_path = _resolve(contract_file.parent, item.get("report"), f"{field}.report")
        if not report_path.is_file():
            _fail("SOURCE_LEARNING_RUNTIME_REPORT_MISSING", f"runtime report does not exist: {report_path}")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _fail("SOURCE_LEARNING_RUNTIME_REPORT_INVALID", str(exc))
        assertions = _obj(item.get("assertions"), f"{field}.assertions")
        failed = {key: {"expected": expected, "actual": _lookup(report, key)} for key, expected in assertions.items() if _lookup(report, key) != expected}
        if failed:
            _fail("SOURCE_LEARNING_RUNTIME_ASSERTION_FAILED", f"runtime assertions failed: {test_id}", assertions=failed)
        evidence["result"] = {"report": str(report_path), "sha256": _sha(report_path.read_bytes()), "assertions": assertions, "status": "pass"}
    for index, assertion_raw in enumerate(_arr(item.get("source_assertions", []), f"{field}.source_assertions", allow_empty=True)):
        assertion = _obj(assertion_raw, f"{field}.source_assertions[{index}]")
        path, root_id, relative = _source_path(roots, assertion.get("root_id"), assertion.get("path"), f"{field}.source_assertions[{index}]")
        source, _ = _decode_text(path.read_bytes(), path)
        missing = [pattern for pattern in assertion.get("contains", []) if pattern not in source]
        forbidden = [pattern for pattern in assertion.get("contains_none", []) if pattern in source]
        if missing or forbidden:
            _fail("SOURCE_LEARNING_SOURCE_ASSERTION_FAILED", f"source assertions failed: {path}", missing=missing, forbidden=forbidden)
        mapped.add((root_id, relative))
    return evidence, mapped


def _coordinate_contract(item: dict[str, Any], roots: dict[str, dict[str, Any]], behavior_id: str) -> set[tuple[str, str]]:
    required = ("input_api", "input_space", "target_space", "conversion", "implementation")
    for field in required:
        if field not in item:
            _fail("SOURCE_LEARNING_COORDINATE_CONTRACT_MISSING", f"{behavior_id} coordinate contract missing {field}")
    api = _text(item.get("input_api"), "coordinate.input_api")
    conversion = _text(item.get("conversion"), "coordinate.conversion")
    implementation = _obj(item.get("implementation"), "coordinate.implementation")
    path, root_id, relative = _source_path(roots, implementation.get("root_id"), implementation.get("path"), "coordinate.implementation")
    source, _ = _decode_text(path.read_bytes(), path)
    if api == "getUILocation" and conversion != "identity":
        _fail("SOURCE_LEARNING_COORDINATE_DOUBLE_SCALE", "getUILocation already returns UI coordinates; extra screen scaling is forbidden", behavior_id=behavior_id, conversion=conversion)
    if api == "getUILocation" and "getUILocation" in source and re.search(r"window\.(?:innerWidth|innerHeight)", source):
        _fail("SOURCE_LEARNING_COORDINATE_DOUBLE_SCALE", "getUILocation implementation rescales by browser dimensions", behavior_id=behavior_id, path=str(path))
    return {(root_id, relative)}


def _behavior(raw: Any, roots: dict[str, dict[str, Any]], contract_file: Path, field: str) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    item = _obj(raw, field)
    behavior_id = _identifier(item.get("id"), f"{field}.id")
    status = _text(item.get("status"), f"{field}.status")
    if status not in BEHAVIOR_STATUSES:
        _fail("SOURCE_LEARNING_BEHAVIOR_STATUS_INVALID", f"unsupported behavior status: {status}")
    evidence = [_anchor(value, roots, f"{field}.source_evidence") for value in _arr(item.get("source_evidence", []), f"{field}.source_evidence", allow_empty=True)]
    mapped = {(anchor["root_id"], anchor["path"]) for anchor in evidence}
    result: dict[str, Any] = {"id": behavior_id, "title": _text(item.get("title"), f"{field}.title"), "status": status, "source_evidence": evidence}
    if status != "verified":
        result["blocker"] = _text(item.get("blocker", "not yet verified"), f"{field}.blocker")
        return result, mapped
    result["why"] = _text(item.get("why"), f"{field}.why")
    procedure = [_obj(value, f"{field}.procedure") for value in _arr(item.get("procedure"), f"{field}.procedure")]
    result["procedure"] = [{"step": index + 1, "action": _text(value.get("action"), f"{field}.procedure.action")} for index, value in enumerate(procedure)]
    if not evidence:
        _fail("SOURCE_LEARNING_VERIFIED_WITHOUT_SOURCE", f"verified behavior has no source evidence: {behavior_id}")
    contracts = [_obj(value, f"{field}.contracts") for value in _arr(item.get("contracts"), f"{field}.contracts")]
    kinds = {_text(value.get("kind"), f"{field}.contracts.kind") for value in contracts}
    required_kinds = {_text(value, f"{field}.required_contract_kinds") for value in _arr(item.get("required_contract_kinds"), f"{field}.required_contract_kinds")}
    missing_kinds = sorted(required_kinds - kinds)
    if missing_kinds:
        _fail("SOURCE_LEARNING_BEHAVIOR_CONTRACT_INCOMPLETE", f"verified behavior is missing required contracts: {behavior_id}", missing=missing_kinds)
    for contract in contracts:
        if contract.get("kind") == "coordinate_space":
            mapped.update(_coordinate_contract(contract, roots, behavior_id))
    tests: list[dict[str, Any]] = []
    covered_paths: set[str] = set()
    for index, test_raw in enumerate(_arr(item.get("tests"), f"{field}.tests")):
        test, test_mapped = _test(test_raw, roots, contract_file, f"{field}.tests[{index}]")
        tests.append(test)
        covered_paths.update(test["execution_paths"])
        mapped.update(test_mapped)
    required_paths = {_identifier(value, f"{field}.required_paths") for value in _arr(item.get("required_paths"), f"{field}.required_paths")}
    missing_paths = sorted(required_paths - covered_paths)
    if missing_paths:
        _fail("SOURCE_LEARNING_USER_PATH_UNTESTED", f"verified behavior bypasses required execution paths: {behavior_id}", missing=missing_paths, covered=sorted(covered_paths))
    result.update({"contracts": contracts, "required_contract_kinds": sorted(required_kinds), "required_paths": sorted(required_paths), "tests": tests})
    return result, mapped


def _build(contract: dict[str, Any], contract_file: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    capability = _obj(contract.get("capability"), "capability")
    capability_id = _identifier(capability.get("id"), "capability.id")
    title = _text(capability.get("title"), "capability.title")
    scope = _text(capability.get("closed_scope"), "capability.closed_scope")
    roots, inventory = _scan_roots(contract, contract_file)
    behavior_items = _arr(contract.get("behaviors"), "behaviors")
    behaviors: list[dict[str, Any]] = []
    behavior_ids: set[str] = set()
    mapped: set[tuple[str, str]] = set()
    for index, raw in enumerate(behavior_items):
        behavior, behavior_mapped = _behavior(raw, roots, contract_file, f"behaviors[{index}]")
        if behavior["id"] in behavior_ids:
            _fail("SOURCE_LEARNING_DUPLICATE_BEHAVIOR", f"duplicate behavior: {behavior['id']}")
        behavior_ids.add(behavior["id"])
        behaviors.append(behavior)
        mapped.update(behavior_mapped)
    surfaces: list[dict[str, Any]] = []
    referenced_behaviors: set[str] = set()
    for index, raw in enumerate(_arr(contract.get("surfaces"), "surfaces")):
        item = _obj(raw, f"surfaces[{index}]")
        surface_id = _identifier(item.get("id"), f"surfaces[{index}].id")
        linked = [_identifier(value, f"surfaces[{index}].behavior_ids") for value in _arr(item.get("behavior_ids"), f"surfaces[{index}].behavior_ids")]
        missing = sorted(set(linked) - behavior_ids)
        if missing:
            _fail("SOURCE_LEARNING_SURFACE_BEHAVIOR_MISSING", f"surface references unknown behavior: {surface_id}", missing=missing)
        referenced_behaviors.update(linked)
        statuses = [next(value["status"] for value in behaviors if value["id"] == behavior_id) for behavior_id in linked]
        status = "verified" if all(value == "verified" for value in statuses) else "invalidated" if "invalidated" in statuses else "partial" if "verified" in statuses or "discovered" in statuses else "unknown"
        surfaces.append({"id": surface_id, "title": _text(item.get("title"), f"surfaces[{index}].title"), "status": status, "behavior_ids": linked})
    orphaned = sorted(behavior_ids - referenced_behaviors)
    if orphaned:
        _fail("SOURCE_LEARNING_ORPHANED_BEHAVIOR", "behaviors must belong to a declared surface", behaviors=orphaned)
    excluded: set[tuple[str, str]] = set()
    exclusion_records: list[dict[str, Any]] = []
    for index, raw in enumerate(_arr(contract.get("excluded_code", []), "excluded_code", allow_empty=True)):
        item = _obj(raw, f"excluded_code[{index}]")
        path, root_id, relative = _source_path(roots, item.get("root_id"), item.get("path"), f"excluded_code[{index}]")
        if path.suffix.lower() not in CODE_SUFFIXES:
            _fail("SOURCE_LEARNING_EXCLUSION_NOT_CODE", f"excluded_code must refer to code: {path}")
        reason = _text(item.get("reason"), f"excluded_code[{index}].reason")
        excluded.add((root_id, relative))
        exclusion_records.append({"root_id": root_id, "path": relative, "sha256": _sha(path.read_bytes()), "reason": reason})
    code_files = {(item["root_id"], item["path"]) for item in inventory if item["kind"] == "code"}
    unmapped = sorted(code_files - mapped - excluded)
    unknowns = [{"kind": "surface", "id": item["id"], "status": item["status"]} for item in surfaces if item["status"] != "verified"]
    unknowns.extend({"kind": "code_file", "root_id": root_id, "path": path, "status": "unmapped"} for root_id, path in unmapped)
    policy = _obj(contract.get("completion_policy"), "completion_policy")
    require_all_surfaces = policy.get("require_all_surfaces_verified") is True
    require_all_code = policy.get("require_all_code_files_mapped") is True
    blockers: list[dict[str, Any]] = []
    if require_all_surfaces and any(item["status"] != "verified" for item in surfaces):
        blockers.append({"code": "SOURCE_LEARNING_SURFACES_INCOMPLETE", "count": sum(item["status"] != "verified" for item in surfaces)})
    if require_all_code and unmapped:
        blockers.append({"code": "SOURCE_LEARNING_CODE_COVERAGE_INCOMPLETE", "count": len(unmapped)})
    completion_allowed = not blockers
    counts = {status: sum(item["status"] == status for item in behaviors) for status in sorted(BEHAVIOR_STATUSES)}
    coverage = {
        "schema": "sop.source-learning-coverage.v1",
        "capability_id": capability_id,
        "closed_scope": scope,
        "behavior_counts": counts,
        "surface_count": len(surfaces),
        "verified_surface_count": sum(item["status"] == "verified" for item in surfaces),
        "code_file_count": len(code_files),
        "mapped_code_file_count": len(code_files - set(unmapped)),
        "unmapped_code_file_count": len(unmapped),
        "completion_claim_allowed": completion_allowed,
        "blockers": blockers,
        "surfaces": surfaces,
        "behaviors": behaviors,
    }
    corpus = {
        "schema": "sop.source-learning-corpus.v1",
        "roots": [{"id": item["id"], "path": str(item["path"]), "role": item["role"], "include": item["include"], "exclude": item["exclude"]} for item in roots.values()],
        "file_count": len(inventory),
        "bytes": sum(item["bytes"] for item in inventory),
        "by_kind": {kind: sum(item["kind"] == kind for item in inventory) for kind in sorted({item["kind"] for item in inventory})},
        "files": inventory,
        "excluded_code": exclusion_records,
    }
    package = {"schema": PACKAGE_SCHEMA, "capability": {"id": capability_id, "title": title, "closed_scope": scope}, "coverage": coverage, "corpus": {"file_count": corpus["file_count"], "bytes": corpus["bytes"], "by_kind": corpus["by_kind"]}}
    report = {"schema": "sop.source-learning-qa.v1", "status": "complete" if completion_allowed else "partial", "completion_claim_allowed": completion_allowed, "blockers": blockers, "unknown_count": len(unknowns), "checks": {"closed_scope_declared": True, "corpus_fingerprinted": True, "behaviors_have_surface_owners": True, "verified_behaviors_have_executable_evidence": True, "unknowns_are_explicit": True}}
    files: dict[str, bytes] = {
        "capability.json": _json(package),
        "contract.snapshot.json": _json(contract),
        "corpus-manifest.json": _json(corpus),
        "coverage-matrix.json": _json(coverage),
        "unknowns.json": _json({"schema": "sop.source-learning-unknowns.v1", "items": unknowns}),
        "qa/source-learning-report.json": _json(report),
        "README.md": (f"# {title}\n\nCompiled by source.learn. Scope: {scope}\n\nCompletion claim allowed: {'yes' if completion_allowed else 'no'}. Unknowns and blockers are machine-readable; this package is evidence, not a prompt summary.\n").encode("utf-8"),
    }
    manifest = {"schema": "sop.source-learning-build-manifest.v1", "capability_id": capability_id, "contract_sha256": _sha(contract_file.read_bytes()), "files": [{"path": path, "sha256": _sha(data), "bytes": len(data)} for path, data in sorted(files.items())], "completion": report}
    files["build-manifest.json"] = _json(manifest)
    return files, {"capability_id": capability_id, "coverage": coverage, "report": report, "manifest": manifest}


def _disk(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def build_source_learning_package(contract_path: Path | str, output_dir: Path | str, *, apply: bool = False) -> dict[str, Any]:
    contract_file = Path(contract_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output == contract_file or _inside(contract_file, output):
        _fail("SOURCE_OUTPUT_COLLISION", "contract must not be inside output")
    files, result = _build(_load(contract_file), contract_file)
    applied: list[str] = []
    idempotent = False
    if apply and output.exists():
        if not output.is_dir():
            _fail("SOURCE_LEARNING_OUTPUT_NOT_DIRECTORY", f"output is not a directory: {output}")
        disk = _disk(output)
        if disk != files:
            _fail("SOURCE_LEARNING_OUTPUT_DRIFT", "existing package differs from deterministic plan", missing=sorted(set(files) - set(disk)), unexpected=sorted(set(disk) - set(files)), changed=sorted(path for path in set(files) & set(disk) if files[path] != disk[path]))
        idempotent = True
    elif apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-stage-", dir=output.parent))
        try:
            for relative, data in files.items():
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            os.replace(stage, output)
            applied = sorted(files)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
    return {
        "status": "success" if result["report"]["completion_claim_allowed"] else "partial",
        "schema": RESULT_SCHEMA,
        "mode": "apply" if apply else "dry_run",
        "capability_id": result["capability_id"],
        "output": str(output),
        "writes_planned": [] if idempotent else sorted(files),
        "writes_applied": applied,
        "verification": {"dry_run_wrote_nothing": not apply, "atomic_output_commit": "pass" if apply and not idempotent else "not_required", "idempotent_rerun": idempotent, "completion_claim_allowed": result["report"]["completion_claim_allowed"], "blockers": result["report"]["blockers"]},
        "coverage": {key: result["coverage"][key] for key in ("behavior_counts", "surface_count", "verified_surface_count", "code_file_count", "mapped_code_file_count", "unmapped_code_file_count")},
        "manifest": result["manifest"],
    }


def verify_source_learning_package(package_dir: Path | str) -> dict[str, Any]:
    root = Path(package_dir).expanduser().resolve()
    manifest_path = root / "build-manifest.json"
    if not manifest_path.is_file():
        _fail("SOURCE_LEARNING_PACKAGE_MANIFEST_MISSING", f"build manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("SOURCE_LEARNING_PACKAGE_MANIFEST_INVALID", str(exc))
    if manifest.get("schema") != "sop.source-learning-build-manifest.v1":
        _fail("SOURCE_LEARNING_PACKAGE_MANIFEST_INVALID", "unsupported build manifest schema")
    missing: list[str] = []
    changed: list[str] = []
    for item in manifest.get("files", []):
        path = root / item["path"]
        if not path.is_file():
            missing.append(item["path"])
        elif _sha(path.read_bytes()) != item["sha256"]:
            changed.append(item["path"])
    expected = {item["path"] for item in manifest.get("files", [])} | {"build-manifest.json"}
    unexpected = sorted(set(_disk(root)) - expected)
    if missing or changed or unexpected:
        _fail("SOURCE_LEARNING_PACKAGE_DRIFT", "capability package has drifted", missing=missing, changed=changed, unexpected=unexpected)
    completion = _obj(manifest.get("completion"), "manifest.completion")
    return {"status": "success" if completion.get("completion_claim_allowed") else "partial", "schema": "sop.source-learning-verify.v1", "package": str(root), "capability_id": manifest.get("capability_id"), "file_count": len(expected), "hashes": "pass", "completion_claim_allowed": bool(completion.get("completion_claim_allowed")), "blockers": completion.get("blockers", [])}
