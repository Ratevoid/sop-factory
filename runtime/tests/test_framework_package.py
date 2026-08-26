from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from sop_factory.errors import SopError
from sop_factory.framework_package import AUTOMATION_ROOT, package_framework


def _entries(path: Path) -> tuple[str, set[str]]:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in sorted(names)
        )
    return text, names


def test_framework_package_dry_run_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "framework.zip"

    result = package_framework(target)

    assert result["status"] == "success"
    assert result["mode"] == "dry_run"
    assert result["knowledge_scan"]["status"] == "pass"
    assert not target.exists()


def test_framework_package_is_atomic_reproducible_and_project_neutral(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_result = package_framework(first, apply=True)
    second_result = package_framework(second, apply=True)
    repeat_result = package_framework(first, apply=True)

    assert first.read_bytes() == second.read_bytes()
    assert first_result["archive_sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_result["archive_sha256"] == second_result["archive_sha256"]
    assert repeat_result["cache_hit"] is True

    text, names = _entries(first)
    prefix = "sop-factory-framework/"
    assert prefix + ".codex-plugin/plugin.json" in names
    assert prefix + "scripts/run-sop" in names
    assert prefix + "skills/sop/SKILL.md" in names
    assert prefix + "skills/learning-closeout/SKILL.md" in names
    assert prefix + "skills/learning-closeout/agents/openai.yaml" in names
    assert prefix + "runtime/sop.py" in names
    assert prefix + "runtime/sop_factory/registry.py" in names
    assert prefix + "runtime/sop_factory/source_learning.py" in names
    assert prefix + "runtime/profiles/README.md" in names
    assert not any(name.startswith(prefix + "runtime/profiles/") and name.endswith(".json") for name in names)
    assert not any(name.startswith(prefix + "runtime/adapters/") and name.endswith(".json") for name in names)
    assert not any(name.startswith(prefix + "runtime/contracts/") and name.endswith(".json") for name in names)
    workstation_home_marker = "/" + "Users" + "/"
    policy = json.loads((AUTOMATION_ROOT / "framework/package-policy.json").read_text(encoding="utf-8"))
    for forbidden in (*policy["forbidden_terms"], workstation_home_marker):
        assert forbidden.casefold() not in text.casefold()

    with zipfile.ZipFile(first) as archive:
        manifest = json.loads(archive.read(prefix + "FRAMEWORK_MANIFEST.json"))
    assert manifest["knowledge_isolation"]["bundled_profiles"] == 0
    assert manifest["knowledge_isolation"]["bundled_project_adapters"] == 0
    assert manifest["knowledge_isolation"]["absolute_workstation_paths"] is False


def test_system_launcher_can_load_framework_recipe_without_tomllib(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["SOP_STATE_PATH"] = str(tmp_path / "state.json")
    completed = subprocess.run(
        ["zsh", str(AUTOMATION_ROOT / "sop.command"), "recipe", "list", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "success"
    assert "framework.package" in {item["id"] for item in payload["recipes"]}


def test_framework_package_refuses_conflicting_output(tmp_path: Path) -> None:
    target = tmp_path / "framework.zip"
    target.write_bytes(b"not the framework")

    with pytest.raises(SopError) as error:
        package_framework(target, apply=True)

    assert error.value.code == "FRAMEWORK_OUTPUT_CONFLICT"


def test_framework_package_rejects_non_zip_output(tmp_path: Path) -> None:
    with pytest.raises(SopError) as error:
        package_framework(tmp_path / "framework.tar", source_root=AUTOMATION_ROOT)

    assert error.value.code == "INVALID_FRAMEWORK_OUTPUT"


def test_framework_package_rejects_sanitizer_that_breaks_python(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("def neutral_name():\n    return True\n", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema": "sop.framework-package-policy.v1",
                "archive_root": "neutral-framework",
                "include_files": ["module.py"],
                "include_globs": [],
                "exclude_parts": [],
                "replacements": [["neutral_name", "neutral-name"]],
                "forbidden_terms": [],
                "forbidden_regex": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SopError) as error:
        package_framework(tmp_path / "bad.zip", source_root=source, policy_path=policy)

    assert error.value.code == "FRAMEWORK_SANITIZED_SOURCE_INVALID"
