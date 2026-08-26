from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

from sop_factory import state


def test_concurrent_state_writes_use_distinct_temporary_files(tmp_path: Path, monkeypatch) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setenv("SOP_STATE_PATH", str(state_file))
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(state.record_action, "asset.inspect", "success", f"project-{index}")
            for index in range(20)
        ]
        for future in futures:
            future.result(timeout=3)

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["last_action"] == "asset.inspect"
    assert payload["last_status"] == "success"
    assert payload["last_project"] in {f"project-{index}" for index in range(20)}
    assert payload["usage"]["total_calls"] == 20
    assert payload["usage"]["actions"]["asset.inspect"]["calls"] == 20
    assert payload["usage"]["actions"]["asset.inspect"]["statuses"] == {"success": 20}
    assert list(tmp_path.glob("*.tmp")) == []


def test_record_action_preserves_legacy_recent_action_fields(tmp_path: Path, monkeypatch) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text('{"last_action":"old","custom":"keep"}', encoding="utf-8")
    monkeypatch.setenv("SOP_STATE_PATH", str(state_file))

    result = state.record_action("cocos.doctor", "failure", "Demo")

    assert result["custom"] == "keep"
    assert result["last_action"] == "cocos.doctor"
    assert result["usage"]["actions"]["cocos.doctor"]["statuses"] == {"failure": 1}
