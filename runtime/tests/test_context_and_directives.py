from __future__ import annotations

import json
from pathlib import Path

from sop_factory.context import resolve_context
from sop_factory.directives import parse_directive


def make_project(root: Path, name: str, uuid: str) -> Path:
    root.mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "package.json").write_text(
        json.dumps({"name": name, "uuid": uuid, "creator": {"version": "3.8.8"}}),
        encoding="utf-8",
    )
    return root


def write_profile(
    profile_dir: Path,
    project: Path,
    name: str,
    uuid: str,
    display_name: str,
    *,
    aliases: list[str] | None = None,
    capabilities: list[str] | None = None,
) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "sop.project-profile.v1",
        "id": name,
        "display_name": display_name,
        "lifecycle": "formal",
        "aliases": aliases or [name],
        "path_hints": [str(project)],
        "fingerprints": {
            "required_files": ["package.json", "assets"],
            "package_json": {"name": name, "uuid": uuid},
        },
        "cocos": {"creator_version": "3.8.8"},
        "capabilities": capabilities or ["engine:cocos"],
        "adapters": ["cocos-3.8"],
    }
    (profile_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_resolves_project_from_cwd_process_and_fingerprint(tmp_path: Path) -> None:
    project = make_project(tmp_path / "moved-anywhere", "formal-game", "uuid-a")
    profile_dir = tmp_path / "profiles"
    write_profile(profile_dir, project, "formal-game", "uuid-a", "正式游戏工程")
    ps_text = f" 123 /Applications/CocosCreator --project {project}\n"

    result = resolve_context(cwd=project / "assets", profile_dir=profile_dir, ps_text=ps_text)

    assert result["status"] == "success"
    assert result["project"]["display_name"] == "正式游戏工程"
    assert result["project"]["root"] == str(project)
    assert any("Creator" in item for item in result["project"]["evidence"])


def test_discovers_project_local_profile_outside_builtin_projects(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path / "independent-game", "independent-game", "uuid-global")
    write_profile(
        project / ".sop" / "profiles",
        project,
        "independent-game",
        "uuid-global",
        "独立游戏工程",
        capabilities=["engine:cocos", "asset:bitmap"],
    )
    monkeypatch.setenv("SOP_CONFIG_HOME", str(tmp_path / "empty-user-config"))

    result = resolve_context(cwd=project / "assets", ps_text="")

    assert result["status"] == "success"
    assert result["project"]["display_name"] == "独立游戏工程"
    assert result["project"]["capabilities"] == ["asset:bitmap", "engine:cocos"]


def test_profile_relative_path_hints_are_resolved_from_profile_file(tmp_path: Path) -> None:
    project = make_project(tmp_path / "portable-game", "portable-game", "uuid-portable")
    profile_dir = project / ".sop" / "profiles"
    write_profile(profile_dir, project, "portable-game", "uuid-portable", "可搬迁游戏工程")
    profile_path = profile_dir / "portable-game.json"
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["path_hints"] = ["../.."]
    profile_path.write_text(json.dumps(payload), encoding="utf-8")

    result = resolve_context(cwd=project, profile_dir=profile_dir, ps_text="")

    assert result["status"] == "success"
    assert result["project"]["root"] == str(project)


def test_ambiguous_projects_return_natural_question(tmp_path: Path) -> None:
    project_a = make_project(tmp_path / "a", "game-a", "uuid-a")
    project_b = make_project(tmp_path / "b", "game-b", "uuid-b")
    profile_dir = tmp_path / "profiles"
    write_profile(profile_dir, project_a, "game-a", "uuid-a", "公司游戏 A")
    write_profile(profile_dir, project_b, "game-b", "uuid-b", "公司游戏 B")
    ps_text = (
        f" 101 /Applications/CocosCreator --project {project_a}\n"
        f" 102 /Applications/CocosCreator --project {project_b}\n"
    )

    result = resolve_context(cwd=tmp_path, profile_dir=profile_dir, ps_text=ps_text)

    assert result["status"] == "needs_confirmation"
    assert "公司游戏 A" in result["message"]
    assert "公司游戏 B" in result["message"]
    assert "profile_id" not in result["message"]


def test_explicit_operation_target_outranks_active_runtime(tmp_path: Path) -> None:
    project_a = make_project(tmp_path / "a", "game-a", "uuid-a")
    project_b = make_project(tmp_path / "b", "game-b", "uuid-b")
    profile_dir = tmp_path / "profiles"
    write_profile(profile_dir, project_a, "game-a", "uuid-a", "公司游戏 A", aliases=["项目A"])
    write_profile(profile_dir, project_b, "game-b", "uuid-b", "公司游戏 B", aliases=["项目B"])

    result = resolve_context(
        cwd=tmp_path,
        request="检查项目B的 Cocos 工程",
        profile_dir=profile_dir,
        ps_text=f" 101 /Applications/CocosCreator --project {project_a}\n",
    )

    assert result["status"] == "success"
    assert result["operation_project"]["display_name"] == "公司游戏 B"
    assert result["active_project"]["display_name"] == "公司游戏 A"
    assert result["project"] == result["operation_project"]
    assert result["context_mismatch"] is True


def test_project_mention_inside_transcript_is_reference_only(tmp_path: Path) -> None:
    project_a = make_project(tmp_path / "a", "game-a", "uuid-a")
    project_b = make_project(tmp_path / "b", "game-b", "uuid-b")
    profile_dir = tmp_path / "profiles"
    write_profile(profile_dir, project_a, "game-a", "uuid-a", "公司游戏 A", aliases=["项目A"])
    write_profile(profile_dir, project_b, "game-b", "uuid-b", "公司游戏 B", aliases=["项目B"])

    result = resolve_context(
        cwd=tmp_path,
        request="只分析，不操作。下面是我的对话记录：当前打开项目B。",
        profile_dir=profile_dir,
        ps_text=f" 101 /Applications/CocosCreator --project {project_a}\n",
    )

    assert result["status"] == "success"
    assert result["operation_project"]["display_name"] == "公司游戏 A"
    assert result["active_project"]["display_name"] == "公司游戏 A"
    assert any(item["profile_id"] == "game-b" for item in result["reference_mentions"])
    assert not any(item["profile_id"] == "game-b" for item in result["actionable_mentions"])


def test_unregistered_explicit_project_is_reported_without_overriding_active(tmp_path: Path) -> None:
    project = make_project(tmp_path / "a", "game-a", "uuid-a")
    profile_dir = tmp_path / "profiles"
    write_profile(profile_dir, project, "game-a", "uuid-a", "公司游戏 A", aliases=["项目A"])

    result = resolve_context(
        cwd=tmp_path,
        request="检查项目99的资源",
        profile_dir=profile_dir,
        ps_text=f" 101 /Applications/CocosCreator --project {project}\n",
    )

    assert result["status"] == "success"
    assert result["operation_project"]["display_name"] == "公司游戏 A"
    assert "项目99" in result["unresolved_project_mentions"]


def test_read_only_typo_is_corrected_with_warning() -> None:
    result = parse_directive("检查 cooos 工程是否打开")

    assert result["status"] == "success"
    assert "cocos" in result["normalized_text"]
    assert result["warnings"]


def test_write_typo_requires_confirmation() -> None:
    result = parse_directive("修改 cooos 工程配置")

    assert result["status"] == "needs_confirmation"
    assert result["risk"] == "write"
    assert "要按“cocos”继续吗" in result["message"]


def test_high_risk_typo_never_fuzzy_matches() -> None:
    result = parse_directive("删除 cooos 打包文件")

    assert result["status"] == "needs_confirmation"
    assert result["intent"] == "exact_target_required"


def test_scope_defaults_to_session_and_requires_explicit_persistence() -> None:
    assert parse_directive("检查 Cocos 工程")["scope"] == "session"
    assert parse_directive("这个项目以后都检查 Cocos 工程")["scope"] == "project"
    assert parse_directive("以后所有项目都检查 Cocos 工程")["scope"] == "global"


def test_make_sop_and_scriptize_is_a_recipe_write_intent() -> None:
    result = parse_directive("可以的 然后把前面能力做成sop 能脚本就脚本化")

    assert result["status"] == "success"
    assert result["intent"] == "create_recipe_candidate"
    assert result["risk"] == "write"


def test_build_slot_factory_is_a_recipe_write_intent() -> None:
    result = parse_directive("好的你来做老虎机工厂")

    assert result["status"] == "success"
    assert result["intent"] == "create_recipe_candidate"
    assert result["risk"] == "write"


def test_completed_packaging_context_does_not_raise_new_high_risk_action() -> None:
    result = parse_directive("示例项目我已经做完打包了 整体项目能力转化为sop")

    assert result["intent"] == "create_recipe_candidate"
    assert result["risk"] == "write"
    assert result["requires_explicit_approval"] is False


def test_active_packaging_request_remains_high_risk() -> None:
    result = parse_directive("请重新打包并发布")

    assert result["risk"] == "high"
    assert result["requires_explicit_approval"] is True


def test_align_card_frame_is_a_write_request() -> None:
    result = parse_directive("测试sop，把狮子卡片的边框对齐comingsoon")

    assert result["status"] == "success"
    assert result["intent"] == "route_request"
    assert result["risk"] == "write"


def test_program_and_project_learning_is_a_recipe_write_intent() -> None:
    result = parse_directive("你需要更多写出程序判断和工具脚本，甚至机械学习我们的项目")

    assert result["status"] == "success"
    assert result["intent"] == "create_recipe_candidate"
    assert result["risk"] == "write"


def test_add_adapter_and_reuse_tool_is_a_recipe_write_intent() -> None:
    result = parse_directive("新增adapter，我们最终目标是一工具多用，而不是一个一用")

    assert result["status"] == "success"
    assert result["intent"] == "create_recipe_candidate"
    assert result["risk"] == "write"


def test_transcript_write_words_do_not_override_read_only_constraint() -> None:
    result = parse_directive("先不要改变，只讨论。下面是我的对话记录：修改并生成文件")

    assert result["status"] == "success"
    assert result["risk"] == "read_only"


def test_approved_apply_is_a_write_directive() -> None:
    result = parse_directive("批准 apply")

    assert result["status"] == "success"
    assert result["risk"] == "write"
