from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from sop_factory.inspectors import inspect_image
from sop_factory.pipeline import normalize_asset
import sop as sop_cli


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]


def make_image(path: Path) -> Path:
    image = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 10, 69, 59), fill=(220, 80, 40, 255))
    image.save(path)
    return path


def test_asset_inspection_keeps_original_pixel_contract(tmp_path: Path) -> None:
    report = inspect_image(make_image(tmp_path / "source.png"))

    assert report["pixel_size"] == {"width": 100, "height": 80}
    assert report["alpha_content_bbox"] == {"x": 20, "y": 10, "width": 50, "height": 50}


def test_normalize_is_atomic_and_cacheable(tmp_path: Path) -> None:
    source = make_image(tmp_path / "source.png")
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema": "sop.asset-contract.v1",
                "id": "test",
                "target": {"canvas": {"width": 60, "height": 60}, "content_box": {"x": 5, "y": 5, "width": 50, "height": 50}},
                "transform": {"mode": "contain", "anchor": "center", "allow_upscale": False},
            }
        ),
        encoding="utf-8",
    )

    first = normalize_asset(source, contract, tmp_path / "out")
    second = normalize_asset(source, contract, tmp_path / "out")

    assert first.output_path.is_file()
    assert second.cache_hit is True


def test_legacy_exampleproject_asset_contract_remains_supported(tmp_path: Path) -> None:
    source = make_image(tmp_path / "source.png")
    contract = tmp_path / "legacy-contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema": "legacy.asset-contract.v1",
                "id": "legacy-test",
                "target": {"canvas": {"width": 100, "height": 80}},
                "transform": {"mode": "strict"},
            }
        ),
        encoding="utf-8",
    )

    result = normalize_asset(source, contract, tmp_path / "legacy-out")

    assert result.output_path.is_file()


def test_cli_returns_stable_json_and_known_exit_code(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    completed = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "directive", "修改 cooos 工程配置", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload["status"] == "needs_confirmation"
    assert payload["intent"] == "confirm_correction"


def test_cli_recipe_search_is_read_only_and_bounded(tmp_path: Path) -> None:
    project = tmp_path / "fixture-project"
    (project / "assets").mkdir(parents=True)
    (project / "package.json").write_text(
        json.dumps({"name": "fixture-project", "uuid": "fixture-uuid", "creator": {"version": "3.8.8"}}),
        encoding="utf-8",
    )
    profile_dir = project / ".sop" / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "fixture-project.json").write_text(
        json.dumps(
            {
                "schema": "sop.project-profile.v1",
                "id": "fixture-project",
                "display_name": "Fixture Cocos Project",
                "lifecycle": "formal",
                "aliases": ["fixture-project"],
                "path_hints": ["../.."],
                "fingerprints": {
                    "required_files": ["package.json", "assets"],
                    "package_json": {"name": "fixture-project", "uuid": "fixture-uuid"},
                },
                "cocos": {"creator_version": "3.8.8"},
                "capabilities": ["engine:cocos", "cocos:mcp"],
                "adapters": ["cocos-3.8"],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    completed = subprocess.run(
        [
            sys.executable,
            str(AUTOMATION_ROOT / "sop.py"),
            "recipe",
            "search",
            "--request",
            "验证配置",
            "--cwd",
            str(project),
            "--limit",
            "3",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "success"
    assert payload["selected"]["id"] == "config.validate"
    assert len(payload["candidates"]) <= 3
    assert payload["executed"] is False


def test_cli_usage_counts_success_and_known_boundaries(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "directive", "检查当前工程", "--json"],
        capture_output=True, text=True, env=env, check=True,
    )
    boundary = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "directive", "修改 cooos 工程配置", "--json"],
        capture_output=True, text=True, env=env, check=False,
    )
    report = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "usage", "--json"],
        capture_output=True, text=True, env=env, check=True,
    )

    assert boundary.returncode == 2
    payload = json.loads(report.stdout)
    directive = next(item for item in payload["actions"] if item["action"] == "directive.parse")
    assert payload["total_calls"] == 3
    assert directive["calls"] == 2
    assert directive["statuses"] == {"success": 1, "needs_confirmation": 1}
    assert next(item for item in payload["actions"] if item["action"] == "usage")["calls"] == 1
    assert "asset.inspect" in payload["unused_recipes"]
    assert payload["privacy"].startswith("Stores aggregate")


def test_cli_status_keeps_usage_details_out_of_recent_action(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "directive", "检查当前工程", "--json"],
        capture_output=True, text=True, env=env, check=True,
    )
    completed = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "status", "--cwd", str(tmp_path), "--json"],
        capture_output=True, text=True, env=env, check=False,
    )

    payload = json.loads(completed.stdout)
    assert "usage" not in payload["recent_action"]
    assert set(payload["recent_action"]) == {"last_action", "last_status", "last_project", "updated_at"}


def test_cli_contract_failure_is_counted_once(tmp_path: Path) -> None:
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

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    usage = state["usage"]["actions"]["asset.inspect"]
    assert failed.returncode == 2
    assert usage["calls"] == 1
    assert usage["statuses"] == {"failure": 1}


def test_usage_write_failure_does_not_change_command_result(capsys) -> None:
    with patch.object(sop_cli, "record_action", side_effect=OSError("read only")):
        exit_code = sop_cli.main(["directive", "检查当前工程", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "success"


def test_cli_parse_failures_and_help_are_counted_without_input_text(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AUTOMATION_ROOT)
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    secret_like_typo = "private-token-command"
    failed = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), secret_like_typo],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    helped = subprocess.run(
        [sys.executable, str(AUTOMATION_ROOT / "sop.py"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    state_text = (tmp_path / "state.json").read_text(encoding="utf-8")
    usage = json.loads(state_text)["usage"]["actions"]["cli.parse"]
    assert failed.returncode == 2
    assert helped.returncode == 0
    assert usage["calls"] == 2
    assert usage["statuses"] == {"parse_error": 1, "help": 1}
    assert secret_like_typo not in state_text
