from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sop_factory.directives import parse_directive
from sop_factory.human_output import render_human


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]


def test_chinese_localization_request_is_a_write() -> None:
    result = parse_directive("sop能做出中文版吗 我看不懂目前版本")

    assert result["status"] == "success"
    assert result["risk"] == "write"


def test_recipe_catalog_human_output_is_chinese() -> None:
    output = render_human(
        {
            "status": "success",
            "schema": "sop.recipe-registry.v1",
            "validation": {"status": "success"},
            "recipes": [
                {
                    "id": "asset.inspect",
                    "family": "asset",
                    "summary": "检查图片尺寸",
                    "risk": "read_only",
                    "scope": "global",
                    "command": ["asset", "inspect"],
                }
            ],
        }
    )

    assert "SOP 配方清单（1 项）" in output
    assert "风险：只读" in output
    assert "范围：全局" in output
    assert "sop asset inspect" in output


def test_generic_human_output_translates_common_fields() -> None:
    output = render_human(
        {
            "status": "success",
            "schema": "sop.asset-inspection.v1",
            "pixel_size": {"width": 100, "height": 80},
            "cache_hit": False,
        }
    )

    assert "状态：通过" in output
    assert "像素尺寸：" in output
    assert "命中缓存：否" in output
    assert "schema" not in output


def test_cli_help_and_default_recipe_list_are_chinese(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    help_result = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    list_result = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "recipe", "list"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert "项目中立、可验证、可重复执行的 SOP 工具箱" in help_result.stdout
    assert "查看和搜索确定性 SOP 配方" in help_result.stdout
    from sop_factory.registry import RECIPES

    assert f"SOP 配方清单（{len(RECIPES)} 项）" in list_result.stdout
    assert "目录校验：通过" in list_result.stdout


def test_json_contract_remains_machine_compatible(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    completed = subprocess.run(
        [
            sys.executable,
            str(AUTOMATION_ROOT / "sop.py"),
            "directive",
            "制作中文版",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["schema"] == "sop.directive.v1"
    assert payload["status"] == "success"
    assert payload["risk"] == "write"


def test_each_json_response_reports_its_own_aggregate_count(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")

    first = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "directive", "检查当前工程", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    second = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "directive", "检查图片尺寸", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    first_invocation = json.loads(first.stdout)["invocation"]
    second_invocation = json.loads(second.stdout)["invocation"]
    assert first_invocation == {
        "schema": "sop.invocation.v1",
        "action": "directive.parse",
        "risk": "read_only",
        "status": "success",
        "action_calls": 1,
        "total_calls": 1,
        "recorded": True,
    }
    assert second_invocation["action_calls"] == 2
    assert second_invocation["total_calls"] == 2


def test_failed_response_still_reports_invocation_count(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    failed = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "asset", "inspect", str(tmp_path / "missing.png"), "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    payload = json.loads(failed.stdout)
    assert failed.returncode == 2
    assert payload["status"] == "failure"
    assert payload["invocation"]["action"] == "asset.inspect"
    assert payload["invocation"]["status"] == "failure"
    assert payload["invocation"]["action_calls"] == 1
    assert payload["invocation"]["total_calls"] == 1


def test_human_output_shows_invocation_count() -> None:
    output = render_human(
        {
            "status": "success",
            "schema": "sop.directive.v1",
            "intent": "route_request",
            "risk": "read_only",
            "scope": "session",
            "actionable_text": "检查图片",
            "invocation": {
                "schema": "sop.invocation.v1",
                "action": "directive.parse",
                "risk": "read_only",
                "status": "success",
                "action_calls": 8,
                "total_calls": 21,
                "recorded": True,
            },
        }
    )

    assert "调用记录｜directive.parse" in output
    assert "该能力累计 8 次" in output
    assert "SOP 总累计 21 次" in output
