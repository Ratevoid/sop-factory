from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sop_factory.errors import SopError
from sop_factory.registry import RECIPES, RecipeDefinition, list_recipes, validate_public_recipe_ids, validate_recipe_catalog
from sop_factory.retrieval import search_recipes


def _project(root: Path, name: str, uuid: str) -> Path:
    root.mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "package.json").write_text(
        json.dumps({"name": name, "uuid": uuid, "creator": {"version": "3.8.8"}}),
        encoding="utf-8",
    )
    return root


def _profile(profile_dir: Path, project: Path, *, capabilities: list[str]) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "sop.project-profile.v1",
        "id": "fixture-project",
        "display_name": "Fixture Project",
        "lifecycle": "formal",
        "aliases": ["fixture", "测试工程"],
        "path_hints": [str(project)],
        "fingerprints": {
            "required_files": ["package.json", "assets"],
            "package_json": {"name": "fixture", "uuid": "fixture-uuid"},
        },
        "cocos": {"creator_version": "3.8.8"},
        "capabilities": capabilities,
        "adapters": ["cocos-3.8"],
    }
    (profile_dir / "fixture-project.json").write_text(json.dumps(payload), encoding="utf-8")


def _recipe(recipe_id: str, alias: str, *, risk: str = "read_only", capability: str | None = None) -> RecipeDefinition:
    return RecipeDefinition(
        id=recipe_id,
        family="fixture",
        version="1.0.0",
        summary=f"Fixture {alias}",
        risk=risk,
        mutates=risk != "read_only",
        domains=("fixture",),
        intents=("fixture_check",),
        aliases=(alias,),
        required_capabilities=(capability,) if capability else (),
        scope="engine" if capability else "global",
        input_schema="fixture.input.v1",
        output_schema="fixture.output.v1",
        fixtures=("tests/test_recipe_registry_and_retrieval.py",),
        completion_check="fixture result is deterministic",
        command=("fixture", recipe_id),
    )


def test_catalog_exposes_complete_metadata_and_legacy_fields() -> None:
    result = list_recipes()

    assert result["status"] == "success"
    assert result["recipe_count"] == len(RECIPES)
    assert result["validation"]["status"] == "success"
    for recipe in result["recipes"]:
        assert {"id", "risk", "summary", "family", "version", "mutates", "domains", "intents"} <= recipe.keys()
        assert recipe["fixtures"]
        assert recipe["completion_check"]


def test_catalog_rejects_duplicate_ids_and_invalid_enums() -> None:
    with pytest.raises(SopError) as duplicate:
        validate_recipe_catalog((RECIPES[0], RECIPES[0]))
    with pytest.raises(SopError) as invalid:
        validate_recipe_catalog((replace(RECIPES[0], risk="sometimes"),))

    assert duplicate.value.code == "INVALID_RECIPE_CATALOG"
    assert invalid.value.code == "INVALID_RECIPE_CATALOG"


def test_public_command_consistency_rejects_registry_drift() -> None:
    with pytest.raises(SopError) as error:
        validate_public_recipe_ids({recipe.id for recipe in RECIPES} - {RECIPES[0].id})

    assert error.value.code == "RECIPE_COMMAND_REGISTRY_DRIFT"


def test_search_selects_unique_compatible_recipe(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "cocos:mcp", "asset:bitmap", "asset:spine"])

    result = search_recipes(
        "验证配置",
        cwd=project,
        profile_dir=profile_dir,
        ps_text=f" 10 /Applications/CocosCreator --project {project}\n",
    )

    assert result["status"] == "success"
    assert result["selected"]["id"] == "config.validate"
    assert result["selected"]["score"] >= result["thresholds"]["minimum_score"]
    assert result["selected"]["score_evidence"]


def test_search_routes_standalone_ui_chroma_edge_to_shared_auto_recipe(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "cocos:mcp", "asset:bitmap"])

    result = search_recipes(
        "检查图片尺寸和透明边界",
        cwd=project,
        profile_dir=profile_dir,
        ps_text=f" 10 /Applications/CocosCreator --project {project}\n",
    )

    assert result["status"] == "success"
    assert result["selected"]["id"] == "asset.inspect"


def test_search_routes_user_reported_purple_impurity_to_shared_auto_recipe(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "cocos:mcp", "asset:bitmap"])

    result = search_recipes(
        "生成归一化图片",
        cwd=project,
        profile_dir=profile_dir,
        ps_text=f" 10 /Applications/CocosCreator --project {project}\n",
    )

    assert result["status"] == "success"
    assert result["selected"]["id"] == "asset.normalize"


def test_search_routes_reel_cell_border_check_to_read_only_recipe(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "asset:bitmap"])

    result = search_recipes(
        "审计最终包",
        cwd=project,
        profile_dir=profile_dir,
        ps_text=f" 10 /Applications/CocosCreator --project {project}\n",
    )

    assert result["status"] == "success"
    assert result["selected"]["id"] == "delivery.audit"


def test_search_routes_project_conversion_to_capability_audit(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos"])

    result = search_recipes(
        "整体项目能力转化为 SOP",
        cwd=project,
        profile_dir=profile_dir,
        ps_text="",
    )

    assert result["status"] == "success"
    assert result["selected"]["id"] == "project.capability-audit"


def test_search_rejects_missing_project_capability(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos"])

    result = search_recipes(
        "检查当前 Cocos 工程和 MCP",
        cwd=project,
        profile_dir=profile_dir,
        ps_text="",
        recipes=(_recipe("fixture.mcp", "检查当前 Cocos 工程和 MCP", capability="cocos:mcp"),),
    )

    assert result["status"] == "no_match"
    assert result["rejected_count"] == 1
    assert "missing_capability:cocos:mcp" in result["rejections"][0]["reasons"]


def test_read_only_request_cannot_select_mutating_recipe(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos"])

    result = search_recipes(
        "只读检查边框修复工具",
        cwd=project,
        profile_dir=profile_dir,
        ps_text="",
        recipes=(_recipe("fixture.write", "边框修复工具", risk="write"),),
    )

    assert result["status"] == "no_match"
    assert "risk:read_only_request" in result["rejections"][0]["reasons"]


def test_search_returns_ambiguity_without_execution(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos"])
    recipes = (_recipe("fixture.a", "共同检查"), _recipe("fixture.b", "共同检查"))

    result = search_recipes("共同检查", cwd=project, profile_dir=profile_dir, ps_text="", recipes=recipes)

    assert result["status"] == "needs_confirmation"
    assert result["selected"] is None
    assert [item["id"] for item in result["candidates"]] == ["fixture.a", "fixture.b"]


def test_search_is_deterministic_and_caps_candidates_at_five(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos"])
    recipes = tuple(_recipe(f"fixture.{index}", "共同工具") for index in range(7))

    first = search_recipes("共同工具", cwd=project, profile_dir=profile_dir, ps_text="", recipes=recipes, limit=5)
    second = search_recipes("共同工具", cwd=project, profile_dir=profile_dir, ps_text="", recipes=recipes, limit=5)

    assert len(first["candidates"]) == 5
    assert first["candidates"] == second["candidates"]
    assert first["eligible_count"] == 7


def test_search_limit_is_a_known_contract_boundary(tmp_path: Path) -> None:
    with pytest.raises(SopError) as error:
        search_recipes("检查工具", cwd=tmp_path, limit=6)

    assert error.value.code == "INVALID_RECIPE_SEARCH_LIMIT"


def test_search_routes_learning_closeout_folder_to_framework_package(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()

    result = search_recipes(
        "把 learning-closeout 作为独立 Skill 文件夹加入无项目知识 SOP Framework 并打包 1.0.1",
        cwd=tmp_path,
        profile_dir=profile_dir,
        ps_text="",
    )

    assert result["status"] == "success"
    assert result["directive"]["risk"] == "high"
    assert result["selected"]["id"] == "framework.package"
    assert result["context"]["project_context_bypassed"] is True


def test_search_keeps_project_confirmation_when_no_global_recipe_matches(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()

    result = search_recipes(
        "检查当前 Cocos 工程和 MCP",
        cwd=tmp_path,
        profile_dir=profile_dir,
        ps_text="",
    )

    assert result["status"] == "needs_confirmation"
    assert result["selected"] is None


def test_search_routes_fishing_reskin_to_fishing_factory(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "game:fishing"])
    result = search_recipes("建立源码能力包", cwd=project, profile_dir=profile_dir, ps_text="")
    assert result["status"] == "success"
    assert result["directive"]["risk"] == "write"
    assert result["selected"]["id"] == "source.learn"


def test_search_routes_full_reference_runtime_runtime_sop_request(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "game:fishing"])
    result = search_recipes("打包 SOP 框架版", cwd=project, profile_dir=profile_dir, ps_text="")
    assert result["status"] == "success"
    assert result["selected"]["id"] == "framework.package"


def test_search_routes_full_source_learning_to_learning_compiler(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", "fixture", "fixture-uuid")
    profile_dir = tmp_path / "profiles"
    _profile(profile_dir, project, capabilities=["engine:cocos", "game:fishing"])
    result = search_recipes("建立外部捕鱼源码的全量行为覆盖矩阵和可执行学习能力包", cwd=project, profile_dir=profile_dir, ps_text="")
    assert result["status"] == "success"
    assert result["directive"]["risk"] == "write"
    assert result["selected"]["id"] == "source.learn"
