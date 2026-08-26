from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """A deterministic contract violation with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContractError("INVALID_CONTRACT", f"{field} must be a positive integer")
    return value


def load_contract(path: Path | str) -> dict[str, Any]:
    contract_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError("CONTRACT_NOT_FOUND", str(contract_path)) from exc
    except json.JSONDecodeError as exc:
        raise ContractError("INVALID_CONTRACT", f"JSON parse error: {exc}") from exc

    if not isinstance(payload, dict):
        raise ContractError("INVALID_CONTRACT", "contract root must be a JSON object")
    if payload.get("schema") not in {"sop.asset-contract.v1", "legacy.asset-contract.v1"}:
        raise ContractError("INVALID_CONTRACT", "unsupported or missing schema")
    if not isinstance(payload.get("id"), str) or not payload["id"].strip():
        raise ContractError("INVALID_CONTRACT", "id must be a non-empty string")

    target = payload.get("target")
    canvas = target.get("canvas") if isinstance(target, dict) else None
    if not isinstance(canvas, dict):
        raise ContractError("INVALID_CONTRACT", "target.canvas is required")
    width = _require_positive_int(canvas.get("width"), "target.canvas.width")
    height = _require_positive_int(canvas.get("height"), "target.canvas.height")

    transform = payload.get("transform")
    if not isinstance(transform, dict):
        raise ContractError("INVALID_CONTRACT", "transform is required")
    mode = transform.get("mode")
    if mode not in {"strict", "contain", "cover", "pad", "nine-slice"}:
        raise ContractError("INVALID_CONTRACT", f"unsupported transform mode: {mode!r}")
    if "max_upscale" in transform:
        max_upscale = transform["max_upscale"]
        if not isinstance(max_upscale, (int, float)) or isinstance(max_upscale, bool) or max_upscale <= 0:
            raise ContractError("INVALID_CONTRACT", "transform.max_upscale must be a positive number")
    if mode == "cover" and "focal_point" in transform:
        focal_point = transform["focal_point"]
        if not isinstance(focal_point, dict):
            raise ContractError("INVALID_CONTRACT", "transform.focal_point must be an object")
        for key in ("x", "y"):
            value = focal_point.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                raise ContractError("INVALID_CONTRACT", f"transform.focal_point.{key} must be between 0 and 1")

    content_box = target.get("content_box", {"x": 0, "y": 0, "width": width, "height": height})
    if not isinstance(content_box, dict):
        raise ContractError("INVALID_CONTRACT", "target.content_box must be an object")
    for key in ("x", "y"):
        value = content_box.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractError("INVALID_CONTRACT", f"target.content_box.{key} must be a non-negative integer")
    for key in ("width", "height"):
        _require_positive_int(content_box.get(key), f"target.content_box.{key}")
    if content_box["x"] + content_box["width"] > width or content_box["y"] + content_box["height"] > height:
        raise ContractError("INVALID_CONTRACT", "content_box must fit inside target canvas")

    if mode == "nine-slice":
        insets = transform.get("insets")
        if not isinstance(insets, dict):
            raise ContractError("INVALID_CONTRACT", "nine-slice requires transform.insets")
        for key in ("left", "right", "top", "bottom"):
            _require_positive_int(insets.get(key), f"transform.insets.{key}")
        if insets["left"] + insets["right"] >= width or insets["top"] + insets["bottom"] >= height:
            raise ContractError("INVALID_CONTRACT", "nine-slice insets leave no stretchable target center")

    payload["_path"] = str(contract_path)
    payload["target"]["content_box"] = content_box
    return payload
