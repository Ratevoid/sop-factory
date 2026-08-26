from __future__ import annotations

import json
from pathlib import Path

from sop_factory.capability_audit import audit_project_capabilities


def _project(tmp_path: Path, capabilities: list[str]) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "assets").mkdir()
    (project / "package.json").write_text(
        json.dumps({"name": "fixture", "uuid": "fixture-uuid", "creator": {"version": "3.8.8"}}),
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "fixture.json").write_text(
        json.dumps(
            {
                "schema": "sop.project-profile.v1",
                "id": "fixture",
                "display_name": "Fixture",
                "lifecycle": "formal",
                "aliases": ["fixture"],
                "path_hints": [str(project)],
                "fingerprints": {
                    "required_files": ["package.json", "assets"],
                    "package_json": {"name": "fixture", "uuid": "fixture-uuid"},
                },
                "cocos": {"creator_version": "3.8.8"},
                "capabilities": capabilities,
                "adapters": ["fixture-adapter"],
            }
        ),
        encoding="utf-8",
    )
    return project, profiles


def test_capability_audit_lists_compatible_recipes_and_external_gates(tmp_path: Path) -> None:
    project, profiles = _project(tmp_path, ["engine:cocos", "asset:bitmap"])

    result = audit_project_capabilities(cwd=project, profile_dir=profiles, ps_text="")

    compatible = {item["id"] for item in result["compatible_recipes"]}
    assert "asset.inspect" in compatible
    assert "asset.normalize" in compatible
    assert "delivery.audit" in compatible
    assert "config.validate" in compatible
    assert result["registered_adapters"] == ["fixture-adapter"]
    assert result["claims"]["visual_acceptance"] == "pending_or_external"
    assert "user_acceptance" in result["external_gates"]


def test_capability_audit_includes_delivery_recipe_without_project_hardcoding(tmp_path: Path) -> None:
    project, profiles = _project(tmp_path, ["engine:cocos"])

    result = audit_project_capabilities(cwd=project, profile_dir=profiles, ps_text="")

    assert "delivery.audit" in {item["id"] for item in result["compatible_recipes"]}
    assert result["project"]["profile_id"] == "fixture"
