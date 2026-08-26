from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from sop_factory.delivery_audit import audit_delivery
from sop_factory.errors import SopError


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def _contract(path: Path, **values: object) -> Path:
    path.write_text(json.dumps({"schema": "sop.delivery-contract.v1", **values}), encoding="utf-8")
    return path


def test_audits_zip_with_required_manifest_and_spine_folder(tmp_path: Path) -> None:
    spine = b"binary skeleton"
    artifact = _zip(
        tmp_path / "delivery.zip",
        {
            "game/ui_manifest.json": b"{}",
            "game/spine/fish/fish.skel": spine,
            "game/spine/fish/fish.atlas": b"fish.png\n",
            "game/spine/fish/fish.png": b"png",
        },
    )
    contract = _contract(
        tmp_path / "contract.json",
        required_paths=["game/ui_manifest.json", "game/spine/**/*.skel"],
        forbidden_paths=["**/.DS_Store"],
        single_root=True,
        spine_folder_name="spine",
        spine_sets=[
            {
                "id": "fish",
                "skeleton": "game/spine/fish/fish.skel",
                "atlas": "game/spine/fish/fish.atlas",
                "textures": ["game/spine/fish/fish.png"],
            }
        ],
        manifest={
            "files": [
                {
                    "path": "game/spine/fish/fish.skel",
                    "size": len(spine),
                    "sha256": hashlib.sha256(spine).hexdigest(),
                }
            ]
        },
    )

    result = audit_delivery(artifact, contract)

    assert result["status"] == "success"
    assert result["artifact"]["type"] == "zip"
    assert result["summary"]["spine_file_count"] == 2
    assert result["spine_sets"] == [
        {
            "id": "fish",
            "paths": {
                "skeleton": "game/spine/fish/fish.skel",
                "atlas": "game/spine/fish/fish.atlas",
                "textures": ["game/spine/fish/fish.png"],
            },
            "complete": True,
        }
    ]
    assert result["external_gates"] == ["runtime_install", "runtime_launch", "visual_review", "user_acceptance"]


def test_rejects_unsafe_duplicate_and_junk_archive_entries(tmp_path: Path) -> None:
    artifact = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(artifact, "w") as archive, pytest.warns(UserWarning, match="Duplicate name"):
        archive.writestr("../escape.txt", b"escape")
        archive.writestr("game/.DS_Store", b"junk")
        archive.writestr("game/file.txt", b"one")
        archive.writestr("game/file.txt", b"two")

    with pytest.raises(SopError) as error:
        audit_delivery(artifact)

    assert error.value.code == "DELIVERY_AUDIT_FAILED"
    codes = {item["code"] for item in error.value.details["issues"]}
    assert {"DELIVERY_UNSAFE_PATH", "DELIVERY_JUNK_FILE", "DELIVERY_DUPLICATE_PATH"} <= codes


def test_rejects_archive_symlink(tmp_path: Path) -> None:
    artifact = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("game/link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(info, "../../outside")

    with pytest.raises(SopError) as error:
        audit_delivery(artifact)

    assert any(item["code"] == "DELIVERY_SYMLINK" for item in error.value.details["issues"])


def test_apk_structure_is_reported_without_runtime_claim(tmp_path: Path) -> None:
    artifact = _zip(
        tmp_path / "game.apk",
        {
            "AndroidManifest.xml": b"manifest",
            "classes.dex": b"dex",
            "lib/arm64-v8a/libcocos.so": b"so",
            "assets/application.js": b"js",
        },
    )

    result = audit_delivery(artifact)

    assert result["artifact"]["type"] == "apk"
    assert result["format_checks"]["native_abis"] == ["arm64-v8a"]
    assert "device_runtime" not in result
    assert "runtime_launch" in result["external_gates"]


def test_directory_contract_reports_missing_and_forbidden_paths(tmp_path: Path) -> None:
    artifact = tmp_path / "delivery"
    artifact.mkdir()
    (artifact / "debug.log").write_text("debug", encoding="utf-8")
    contract = _contract(
        tmp_path / "contract.json",
        required_paths=["ui_manifest.json"],
        forbidden_paths=["*.log"],
    )

    with pytest.raises(SopError) as error:
        audit_delivery(artifact, contract)

    codes = {item["code"] for item in error.value.details["issues"]}
    assert "DELIVERY_REQUIRED_PATH_MISSING" in codes
    assert "DELIVERY_FORBIDDEN_PATH" in codes


def test_spine_set_contract_reports_missing_dependency(tmp_path: Path) -> None:
    artifact = _zip(
        tmp_path / "delivery.zip",
        {
            "game/spine/fish/fish.skel": b"skeleton",
            "game/spine/fish/fish.atlas": b"fish.png\n",
        },
    )
    contract = _contract(
        tmp_path / "contract.json",
        spine_sets=[
            {
                "id": "fish",
                "skeleton": "game/spine/fish/fish.skel",
                "atlas": "game/spine/fish/fish.atlas",
                "textures": ["game/spine/fish/fish.png"],
            }
        ],
    )

    with pytest.raises(SopError) as error:
        audit_delivery(artifact, contract)

    assert error.value.code == "DELIVERY_AUDIT_FAILED"
    assert error.value.details["spine_sets"][0]["complete"] is False
    assert any(item["code"] == "DELIVERY_SPINE_SET_FILE_MISSING" for item in error.value.details["issues"])
