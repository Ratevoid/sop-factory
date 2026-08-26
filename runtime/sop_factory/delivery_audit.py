from __future__ import annotations

import fnmatch
import hashlib
import json
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .errors import SopError


CONTRACT_SCHEMA = "sop.delivery-contract.v1"
RESULT_SCHEMA = "sop.delivery-audit.v1"
JUNK_PARTS = {".DS_Store", "__MACOSX", ".git", ".svn", "Thumbs.db"}
JUNK_SUFFIXES = (".tmp", ".bak", ".swp", "~")


def _fail(code: str, message: str, **details: Any) -> None:
    raise SopError(code, message, details=details)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _junk(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return any(part in JUNK_PARTS for part in parts) or name.endswith(JUNK_SUFFIXES)


def _load_contract(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("DELIVERY_CONTRACT_UNREADABLE", f"{path}: {exc}")
    if not isinstance(payload, dict) or payload.get("schema") != CONTRACT_SCHEMA:
        _fail("INVALID_DELIVERY_CONTRACT", f"{path}: expected {CONTRACT_SCHEMA}")
    for key in ("required_paths", "forbidden_paths"):
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            _fail("INVALID_DELIVERY_CONTRACT", f"{key} must contain non-empty strings")
    spine_sets = payload.get("spine_sets", [])
    if not isinstance(spine_sets, list):
        _fail("INVALID_DELIVERY_CONTRACT", "spine_sets must be an array")
    for index, item in enumerate(spine_sets):
        if not isinstance(item, dict):
            _fail("INVALID_DELIVERY_CONTRACT", f"spine_sets[{index}] must be an object")
        skeleton = item.get("skeleton")
        atlas = item.get("atlas")
        textures = item.get("textures")
        if not isinstance(skeleton, str) or not skeleton:
            _fail("INVALID_DELIVERY_CONTRACT", f"spine_sets[{index}].skeleton must be a non-empty string")
        if not isinstance(atlas, str) or not atlas:
            _fail("INVALID_DELIVERY_CONTRACT", f"spine_sets[{index}].atlas must be a non-empty string")
        if not isinstance(textures, list) or not textures or not all(isinstance(value, str) and value for value in textures):
            _fail("INVALID_DELIVERY_CONTRACT", f"spine_sets[{index}].textures must contain non-empty strings")
    return payload


def _directory_entries(root: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    names: list[str] = []
    details: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            names.append(path.relative_to(root).as_posix())
            details[names[-1]] = {"symlink": True, "size": 0}
        elif path.is_file():
            name = path.relative_to(root).as_posix()
            names.append(name)
            details[name] = {"size": path.stat().st_size, "path": path}
    return names, details


def _zip_entries(path: Path) -> tuple[list[str], dict[str, dict[str, Any]], list[str], str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            names = [item.filename for item in infos]
            details = {
                item.filename: {
                    "size": item.file_size,
                    "compressed_size": item.compress_size,
                    "mode": stat.S_IFMT(item.external_attr >> 16),
                    "zip_info": item,
                }
                for item in infos
            }
            duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
            corrupt = archive.testzip()
            return names, details, duplicates, corrupt
    except (OSError, zipfile.BadZipFile) as exc:
        _fail("DELIVERY_ARCHIVE_UNREADABLE", f"{path}: {exc}")


def _matches(names: Iterable[str], pattern: str) -> bool:
    normalized = pattern.lstrip("/")
    return any(name == normalized or fnmatch.fnmatchcase(name, normalized) for name in names)


def _entry_hash(artifact: Path, name: str, details: dict[str, dict[str, Any]], is_archive: bool) -> str:
    digest = hashlib.sha256()
    if is_archive:
        with zipfile.ZipFile(artifact) as archive, archive.open(details[name]["zip_info"]) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        with details[name]["path"].open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def audit_delivery(artifact: Path, contract_path: Path | None = None) -> dict[str, Any]:
    artifact = artifact.expanduser().resolve()
    if not artifact.exists():
        _fail("DELIVERY_ARTIFACT_NOT_FOUND", str(artifact))
    contract = _load_contract(contract_path)
    is_directory = artifact.is_dir()
    is_archive = artifact.is_file() and zipfile.is_zipfile(artifact)
    if not is_directory and not is_archive:
        _fail("DELIVERY_ARTIFACT_UNSUPPORTED", "expected a ZIP, APK or directory", path=str(artifact))

    if is_archive:
        names, details, duplicates, corrupt = _zip_entries(artifact)
    else:
        names, details = _directory_entries(artifact)
        duplicates, corrupt = [], None
    unique_names = sorted(set(names))
    issues: list[dict[str, Any]] = []
    for name in unique_names:
        if not _safe_name(name):
            issues.append({"code": "DELIVERY_UNSAFE_PATH", "path": name})
        if _junk(name):
            issues.append({"code": "DELIVERY_JUNK_FILE", "path": name})
        if details[name].get("symlink"):
            issues.append({"code": "DELIVERY_SYMLINK", "path": name})
        if is_archive and details[name].get("mode") == stat.S_IFLNK:
            issues.append({"code": "DELIVERY_SYMLINK", "path": name})
    issues.extend({"code": "DELIVERY_DUPLICATE_PATH", "path": name} for name in duplicates)
    if corrupt:
        issues.append({"code": "DELIVERY_CRC_FAILURE", "path": corrupt})

    for pattern in contract.get("required_paths", []):
        if not _matches(unique_names, pattern):
            issues.append({"code": "DELIVERY_REQUIRED_PATH_MISSING", "pattern": pattern})
    for pattern in contract.get("forbidden_paths", []):
        matches = [name for name in unique_names if name == pattern or fnmatch.fnmatchcase(name, pattern)]
        issues.extend({"code": "DELIVERY_FORBIDDEN_PATH", "pattern": pattern, "path": name} for name in matches)

    expected_hash = contract.get("expected_sha256")
    artifact_hash = _sha256(artifact) if artifact.is_file() else None
    if expected_hash is not None and expected_hash != artifact_hash:
        issues.append({"code": "DELIVERY_HASH_MISMATCH", "expected": expected_hash, "actual": artifact_hash})

    roots = sorted({PurePosixPath(name).parts[0] for name in unique_names if PurePosixPath(name).parts})
    if contract.get("single_root") is True and len(roots) != 1:
        issues.append({"code": "DELIVERY_SINGLE_ROOT_REQUIRED", "roots": roots})

    manifest = contract.get("manifest", {})
    if manifest and not isinstance(manifest, dict):
        _fail("INVALID_DELIVERY_CONTRACT", "manifest must be an object")
    manifest_files = manifest.get("files", []) if isinstance(manifest, dict) else []
    if not isinstance(manifest_files, list):
        _fail("INVALID_DELIVERY_CONTRACT", "manifest.files must be an array")
    manifest_paths: set[str] = set()
    for item in manifest_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            _fail("INVALID_DELIVERY_CONTRACT", "manifest.files entries require path")
        name = item["path"].lstrip("/")
        manifest_paths.add(name)
        if name not in details:
            issues.append({"code": "DELIVERY_MANIFEST_FILE_MISSING", "path": name})
            continue
        if "size" in item and item["size"] != details[name]["size"]:
            issues.append({"code": "DELIVERY_MANIFEST_SIZE_MISMATCH", "path": name})
        if "sha256" in item and item["sha256"] != _entry_hash(artifact, name, details, is_archive):
            issues.append({"code": "DELIVERY_MANIFEST_HASH_MISMATCH", "path": name})
    if manifest.get("exact") is True:
        ignored = set(manifest.get("ignore", []))
        extra = sorted(set(unique_names) - manifest_paths - ignored)
        issues.extend({"code": "DELIVERY_MANIFEST_EXTRA_FILE", "path": name} for name in extra)

    spine_folder = contract.get("spine_folder_name")
    spine_files = [name for name in unique_names if Path(name).suffix.casefold() in {".skel", ".atlas"}]
    if spine_folder is not None:
        if not isinstance(spine_folder, str) or not spine_folder:
            _fail("INVALID_DELIVERY_CONTRACT", "spine_folder_name must be a non-empty string")
        for name in spine_files:
            if spine_folder not in PurePosixPath(name).parts:
                issues.append({"code": "DELIVERY_SPINE_FOLDER_NAME_INVALID", "path": name, "expected": spine_folder})

    spine_sets: list[dict[str, Any]] = []
    for index, item in enumerate(contract.get("spine_sets", [])):
        set_id = item.get("id", f"spine-set-{index + 1}")
        paths = {
            "skeleton": item["skeleton"].lstrip("/"),
            "atlas": item["atlas"].lstrip("/"),
            "textures": [value.lstrip("/") for value in item["textures"]],
        }
        missing = [paths["skeleton"], paths["atlas"], *paths["textures"]]
        missing = [name for name in missing if name not in details]
        for name in missing:
            issues.append({"code": "DELIVERY_SPINE_SET_FILE_MISSING", "set_id": set_id, "path": name})
        spine_sets.append({"id": set_id, "paths": paths, "complete": not missing})

    artifact_type = "directory"
    format_checks: dict[str, Any] = {}
    if is_archive:
        artifact_type = "apk" if artifact.suffix.casefold() == ".apk" else "zip"
    if artifact_type == "apk":
        required = ["AndroidManifest.xml", "classes.dex"]
        missing = [name for name in required if name not in unique_names]
        issues.extend({"code": "DELIVERY_APK_REQUIRED_ENTRY_MISSING", "path": name} for name in missing)
        format_checks = {
            "manifest": "AndroidManifest.xml" in unique_names,
            "dex_files": sorted(name for name in unique_names if name.startswith("classes") and name.endswith(".dex")),
            "native_abis": sorted({PurePosixPath(name).parts[1] for name in unique_names if name.startswith("lib/") and len(PurePosixPath(name).parts) > 2}),
            "asset_file_count": sum(name.startswith("assets/") for name in unique_names),
        }

    result = {
        "status": "success" if not issues else "failure",
        "schema": RESULT_SCHEMA,
        "artifact": {"path": str(artifact), "type": artifact_type, "sha256": artifact_hash},
        "summary": {
            "file_count": len(names),
            "unique_file_count": len(unique_names),
            "uncompressed_bytes": sum(int(item.get("size", 0)) for item in details.values()),
            "root_entries": roots,
            "spine_file_count": len(spine_files),
        },
        "format_checks": format_checks,
        "spine_sets": spine_sets,
        "contract": {"applied": bool(contract), "path": str(contract_path) if contract_path else None},
        "issues": issues,
        "external_gates": ["runtime_install", "runtime_launch", "visual_review", "user_acceptance"],
    }
    if issues:
        _fail("DELIVERY_AUDIT_FAILED", "delivery artifact did not satisfy the audit contract", **result)
    return result
