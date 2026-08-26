from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from pathlib import Path
from typing import Any


def state_path() -> Path:
    override = os.environ.get("SOP_STATE_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".codex" / "sop-factory" / "state.json"


def read_state() -> dict[str, Any]:
    return _read_state_file(state_path())


def _read_state_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


@contextmanager
def _state_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_action(action: str, status: str, project: str | None = None) -> dict[str, Any]:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _state_lock(path):
        payload = _read_state_file(path)
        now = datetime.now(timezone.utc).isoformat()
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        actions = usage.get("actions")
        if not isinstance(actions, dict):
            actions = {}
        action_usage = actions.get(action)
        if not isinstance(action_usage, dict):
            action_usage = {}
        statuses = action_usage.get("statuses")
        if not isinstance(statuses, dict):
            statuses = {}

        statuses[status] = int(statuses.get(status, 0)) + 1
        action_usage.update(
            {
                "calls": int(action_usage.get("calls", 0)) + 1,
                "statuses": statuses,
                "last_status": status,
                "last_called_at": now,
            }
        )
        if project:
            action_usage["last_project"] = project
        actions[action] = action_usage
        usage.update(
            {
                "schema": "sop.usage.v1",
                "total_calls": int(usage.get("total_calls", 0)) + 1,
                "started_at": usage.get("started_at") or now,
                "updated_at": now,
                "actions": actions,
            }
        )
        payload.update(
            {
                "last_action": action,
                "last_status": status,
                "last_project": project,
                "updated_at": now,
                "usage": usage,
            }
        )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return payload
