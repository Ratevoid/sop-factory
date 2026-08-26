from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import SopError


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = AUTOMATION_ROOT / "profiles"


def config_home() -> Path:
    override = os.environ.get("SOP_CONFIG_HOME")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return (base / "sop-factory").resolve()


def extension_directories(
    relative_path: Path | str,
    *,
    bundled: Path,
    cwd: Path | str | None = None,
    environment_variable: str,
) -> list[Path]:
    relative = Path(relative_path)
    directories = [bundled, config_home() / relative]
    configured = os.environ.get(environment_variable, "")
    directories.extend(Path(item).expanduser().resolve() for item in configured.split(os.pathsep) if item.strip())

    current = Path(cwd or Path.cwd()).expanduser().resolve()
    for root in (current, *current.parents):
        project_extensions = root / ".sop" / relative
        if project_extensions.is_dir():
            directories.append(project_extensions)
            break

    unique: list[Path] = []
    for directory in directories:
        resolved = directory.expanduser().resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def profile_directories(cwd: Path | str | None = None) -> list[Path]:
    return extension_directories(
        "profiles",
        bundled=DEFAULT_PROFILE_DIR,
        cwd=cwd,
        environment_variable="SOP_PROFILE_DIRS",
    )


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    display_name: str
    lifecycle: str
    aliases: tuple[str, ...]
    path_hints: tuple[Path, ...]
    fingerprints: dict[str, Any]
    cocos: dict[str, Any]
    capabilities: tuple[str, ...]
    adapters: tuple[str, ...]
    source_path: Path

    @property
    def selectable(self) -> bool:
        return self.lifecycle in {"formal", "active"}

    @property
    def effective_capabilities(self) -> tuple[str, ...]:
        capabilities = set(self.capabilities)
        if self.cocos:
            capabilities.add("engine:cocos")
        return tuple(sorted(capabilities))

    def to_dict(self, *, include_internal: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "display_name": self.display_name,
            "lifecycle": self.lifecycle,
            "aliases": list(self.aliases),
            "path_hints": [str(path) for path in self.path_hints],
            "fingerprints": self.fingerprints,
            "cocos": self.cocos,
            "capabilities": list(self.effective_capabilities),
            "adapters": list(self.adapters),
        }
        if include_internal:
            result["id"] = self.id
        return result


def _require_string(payload: dict[str, Any], key: str, source: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SopError("INVALID_PROFILE", f"{source}: {key} must be a non-empty string")
    return value.strip()


def load_profile(path: Path) -> ProjectProfile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SopError("PROFILE_NOT_FOUND", str(path)) from exc
    except json.JSONDecodeError as exc:
        raise SopError("INVALID_PROFILE", f"{path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "sop.project-profile.v1":
        raise SopError("INVALID_PROFILE", f"{path}: unsupported or missing schema")
    aliases = payload.get("aliases", [])
    path_hints = payload.get("path_hints", [])
    fingerprints = payload.get("fingerprints", {})
    cocos = payload.get("cocos", {})
    capabilities = payload.get("capabilities", [])
    adapters = payload.get("adapters", [])
    if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
        raise SopError("INVALID_PROFILE", f"{path}: aliases must be strings")
    if not isinstance(path_hints, list) or not all(isinstance(item, str) for item in path_hints):
        raise SopError("INVALID_PROFILE", f"{path}: path_hints must be strings")
    if not isinstance(fingerprints, dict) or not isinstance(cocos, dict):
        raise SopError("INVALID_PROFILE", f"{path}: fingerprints and cocos must be objects")
    if not isinstance(capabilities, list) or not all(isinstance(item, str) and item.strip() for item in capabilities):
        raise SopError("INVALID_PROFILE", f"{path}: capabilities must be non-empty strings")
    if not isinstance(adapters, list) or not all(isinstance(item, str) and item.strip() for item in adapters):
        raise SopError("INVALID_PROFILE", f"{path}: adapters must be non-empty strings")
    return ProjectProfile(
        id=_require_string(payload, "id", path),
        display_name=_require_string(payload, "display_name", path),
        lifecycle=_require_string(payload, "lifecycle", path),
        aliases=tuple(item.strip() for item in aliases if item.strip()),
        path_hints=tuple(
            (Path(item).expanduser() if Path(item).expanduser().is_absolute() else path.parent / item).resolve()
            for item in path_hints
        ),
        fingerprints=fingerprints,
        cocos=cocos,
        capabilities=tuple(sorted({item.strip() for item in capabilities})),
        adapters=tuple(sorted({item.strip() for item in adapters})),
        source_path=path.resolve(),
    )


def load_profiles(profile_dir: Path | None = None, *, cwd: Path | str | None = None) -> list[ProjectProfile]:
    roots = [profile_dir.expanduser().resolve()] if profile_dir else profile_directories(cwd)
    paths = sorted({path.resolve() for root in roots for path in root.glob("*.json")})
    profiles = [load_profile(path) for path in paths]
    ids = [profile.id for profile in profiles]
    if len(ids) != len(set(ids)):
        duplicates = sorted({profile_id for profile_id in ids if ids.count(profile_id) > 1})
        raise SopError("DUPLICATE_PROFILE", f"profile ids must be unique: {', '.join(duplicates)}")
    return profiles


def validate_profiles(profile_dir: Path | None = None, *, cwd: Path | str | None = None) -> dict[str, Any]:
    profiles = load_profiles(profile_dir, cwd=cwd)
    return {
        "status": "success",
        "schema": "sop.profile-validation.v1",
        "profile_count": len(profiles),
        "profile_directories": [str(path) for path in ([profile_dir] if profile_dir else profile_directories(cwd))],
        "profiles": [profile.to_dict() for profile in profiles],
    }
