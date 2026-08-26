from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sop_factory.errors import SopError
from sop_factory.source_learning import build_source_learning_package, verify_source_learning_package


def _fixture(tmp_path: Path, *, behavior_status: str = "verified", execution_paths: list[str] | None = None) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "ReferenceAim.ts").write_text("const point = event.touch.getLocation();\nconst local = node.convertToNodeSpaceAR(point);\n", encoding="utf-8")
    (source / "CandidateAim.ts").write_text("const point = event.getUILocation();\nfireAt(point.x, point.y);\n", encoding="utf-8")
    (source / "Unused.ts").write_text("export const unused = true;\n", encoding="utf-8")
    differential = {
        "schema": "sop.source-learning-differential.v1",
        "cases": [
            {"id": "center", "reference": {"direction": [0, 1], "events": ["touch", "aim", "fire"]}, "candidate": {"direction": [0, 5], "events": ["touch", "aim", "fire"]}},
            {"id": "right", "reference": {"direction": [1, 1]}, "candidate": {"direction": [2, 2]}},
        ],
    }
    (tmp_path / "aim-diff.json").write_text(json.dumps(differential), encoding="utf-8")
    (tmp_path / "runtime.json").write_text(json.dumps({"manualAim": {"passed": True}}), encoding="utf-8")
    behavior = {
        "id": "manual-aim",
        "title": "Manual pointer aim",
        "status": behavior_status,
        "source_evidence": [{"root_id": "source", "path": "ReferenceAim.ts", "line_start": 1, "line_end": 2}],
        "blocker": "manual path still needs proof",
    }
    if behavior_status == "verified":
        behavior.update({
            "why": "The barrel and projectile must share the pointer direction.",
            "procedure": [{"action": "Read the UI pointer coordinate once."}, {"action": "Compute and apply one normalized direction."}],
            "required_contract_kinds": ["coordinate_space", "state"],
            "contracts": [
                {"kind": "coordinate_space", "input_api": "getUILocation", "input_space": "ui", "target_space": "ui", "conversion": "identity", "implementation": {"root_id": "source", "path": "CandidateAim.ts"}},
                {"kind": "state", "precondition": "running", "postcondition": "aim applied"},
            ],
            "required_paths": ["manual_touch"],
            "tests": [
                {"id": "aim-diff", "kind": "differential", "status": "pass", "execution_paths": execution_paths or ["manual_touch"], "fixture": "aim-diff.json", "tolerance": 1e-6},
                {"id": "aim-runtime", "kind": "runtime", "status": "pass", "execution_paths": ["manual_touch"], "report": "runtime.json", "assertions": {"manualAim.passed": True}},
            ],
        })
    contract = {
        "schema": "sop.source-learning-contract.v1",
        "capability": {"id": "fixture-aim", "title": "Fixture Aim", "closed_scope": "Three fixture TypeScript files and one manual aim surface."},
        "corpus_roots": [{"id": "source", "path": str(source), "role": "reference-and-port", "include": ["**/*.ts"], "exclude": []}],
        "surfaces": [{"id": "input-aim", "title": "Input and aim", "behavior_ids": ["manual-aim"]}],
        "behaviors": [behavior],
        "excluded_code": [{"root_id": "source", "path": "Unused.ts", "reason": "Fixture-only unrelated constant."}],
        "completion_policy": {"require_all_surfaces_verified": True, "require_all_code_files_mapped": True},
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def test_compile_apply_verify_and_idempotent_rerun(tmp_path: Path) -> None:
    contract = _fixture(tmp_path)
    output = tmp_path / "package"
    dry = build_source_learning_package(contract, output)
    assert dry["status"] == "success" and not output.exists()
    first = build_source_learning_package(contract, output, apply=True)
    second = build_source_learning_package(contract, output, apply=True)
    verified = verify_source_learning_package(output)
    assert first["verification"]["atomic_output_commit"] == "pass"
    assert second["writes_planned"] == [] and second["verification"]["idempotent_rerun"] is True
    assert verified["completion_claim_allowed"] is True and verified["hashes"] == "pass"


def test_unknown_surface_compiles_but_blocks_completion_claim(tmp_path: Path) -> None:
    contract = _fixture(tmp_path, behavior_status="unknown")
    result = build_source_learning_package(contract, tmp_path / "package")
    assert result["status"] == "partial"
    assert result["verification"]["completion_claim_allowed"] is False
    assert result["verification"]["blockers"][0]["code"] == "SOURCE_LEARNING_SURFACES_INCOMPLETE"


def test_verified_manual_path_cannot_be_replaced_by_auto_demo(tmp_path: Path) -> None:
    contract = _fixture(tmp_path, execution_paths=["auto_loop"])
    payload = json.loads(contract.read_text())
    payload["behaviors"][0]["tests"] = payload["behaviors"][0]["tests"][:1]
    contract.write_text(json.dumps(payload))
    with pytest.raises(SopError) as caught:
        build_source_learning_package(contract, tmp_path / "package")
    assert caught.value.code == "SOURCE_LEARNING_USER_PATH_UNTESTED"


def test_get_ui_location_browser_rescale_is_rejected(tmp_path: Path) -> None:
    contract = _fixture(tmp_path)
    candidate = tmp_path / "source" / "CandidateAim.ts"
    candidate.write_text("const p = event.getUILocation();\nfireAt(p.x / window.innerWidth, p.y / window.innerHeight);\n", encoding="utf-8")
    with pytest.raises(SopError) as caught:
        build_source_learning_package(contract, tmp_path / "package")
    assert caught.value.code == "SOURCE_LEARNING_COORDINATE_DOUBLE_SCALE"


def test_package_drift_is_rejected(tmp_path: Path) -> None:
    contract = _fixture(tmp_path)
    output = tmp_path / "package"
    build_source_learning_package(contract, output, apply=True)
    (output / "coverage-matrix.json").write_text("changed")
    with pytest.raises(SopError) as caught:
        verify_source_learning_package(output)
    assert caught.value.code == "SOURCE_LEARNING_PACKAGE_DRIFT"


def test_legacy_gb18030_source_line_evidence_is_supported(tmp_path: Path) -> None:
    contract = _fixture(tmp_path)
    reference = tmp_path / "source" / "ReferenceAim.ts"
    reference.write_bytes("// 炮台瞄准\nconst point = event.touch.getLocation();\n".encode("gb18030"))
    payload = json.loads(contract.read_text())
    payload["behaviors"][0]["source_evidence"][0]["line_end"] = 2
    contract.write_text(json.dumps(payload))
    result = build_source_learning_package(contract, tmp_path / "package")
    assert result["status"] == "success"


def test_cli_dry_run_and_verify_are_wired(tmp_path: Path) -> None:
    contract = _fixture(tmp_path)
    output = tmp_path / "package"
    cli = Path(__file__).parents[1] / "sop.py"
    env = {**os.environ, "SOP_STATE_PATH": str(tmp_path / "sop-state.json")}
    dry = subprocess.run([sys.executable, str(cli), "source", "learn", "--contract", str(contract), "--out", str(output), "--json"], check=True, capture_output=True, text=True, env=env)
    assert json.loads(dry.stdout)["schema"] == "sop.source-learning-result.v1"
    subprocess.run([sys.executable, str(cli), "source", "learn", "--contract", str(contract), "--out", str(output), "--apply", "--json"], check=True, capture_output=True, text=True, env=env)
    verify = subprocess.run([sys.executable, str(cli), "source", "verify", str(output), "--json"], check=True, capture_output=True, text=True, env=env)
    assert json.loads(verify.stdout)["hashes"] == "pass"
