from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .contracts import ContractError, load_contract
from .inspectors import inspect_image


@dataclass(frozen=True)
class PipelineResult:
    status: str
    output_path: Path
    report_path: Path
    cache_hit: bool
    source: dict[str, Any]
    contract: dict[str, Any]
    transform: dict[str, Any]
    verification: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_path"] = str(self.output_path)
        payload["report_path"] = str(self.report_path)
        return payload


def _canonical_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in contract.items() if not key.startswith("_")}


def _cache_key(source_sha: str, contract: dict[str, Any]) -> str:
    encoded = json.dumps(_canonical_contract(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"sop-asset-pipeline-v1\0")
    digest.update(source_sha.encode("ascii"))
    digest.update(b"\0")
    digest.update(encoded)
    return digest.hexdigest()


def _anchor_offset(anchor: str, box: dict[str, int], size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    horizontal, vertical = "center", "center"
    if anchor in {"left", "right", "center"}:
        horizontal = anchor
    elif "-" in anchor:
        horizontal, vertical = anchor.split("-", 1)
    elif anchor in {"top", "bottom"}:
        vertical = anchor
    elif anchor != "center":
        raise ContractError("INVALID_CONTRACT", f"unsupported anchor: {anchor}")

    x = box["x"]
    if horizontal == "center":
        x += (box["width"] - width) // 2
    elif horizontal == "right":
        x += box["width"] - width
    elif horizontal != "left":
        raise ContractError("INVALID_CONTRACT", f"unsupported horizontal anchor: {horizontal}")

    y = box["y"]
    if vertical == "center":
        y += (box["height"] - height) // 2
    elif vertical == "bottom":
        y += box["height"] - height
    elif vertical != "top":
        raise ContractError("INVALID_CONTRACT", f"unsupported vertical anchor: {vertical}")
    return x, y


def _visible_crop(image: Image.Image, inspection: dict[str, Any]) -> Image.Image:
    bbox = inspection["alpha_content_bbox"]
    if bbox is None:
        raise ContractError("EMPTY_IMAGE", "source image contains no visible pixels")
    return image.crop((bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]))


def _contain(image: Image.Image, inspection: dict[str, Any], contract: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    canvas = contract["target"]["canvas"]
    box = contract["target"]["content_box"]
    transform = contract["transform"]
    visible = _visible_crop(image, inspection)
    scale = min(box["width"] / visible.width, box["height"] / visible.height)
    if not transform.get("allow_upscale", False):
        scale = min(scale, 1.0)
    max_upscale = float(transform.get("max_upscale", scale if scale > 1.0 else 1.0))
    scale = min(scale, max_upscale)
    target_size = (max(1, round(visible.width * scale)), max(1, round(visible.height * scale)))
    resized = visible if target_size == visible.size else visible.resize(target_size, Image.Resampling.LANCZOS)
    output = Image.new("RGBA", (canvas["width"], canvas["height"]), (0, 0, 0, 0))
    offset = _anchor_offset(transform.get("anchor", "center"), box, target_size)
    output.alpha_composite(resized, offset)
    return output, {"mode": "contain", "scale": scale, "offset": {"x": offset[0], "y": offset[1]}, "source_content_bbox": inspection["alpha_content_bbox"]}


def _cover(image: Image.Image, contract: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    canvas = contract["target"]["canvas"]
    target_width, target_height = canvas["width"], canvas["height"]
    scale = max(target_width / image.width, target_height / image.height)
    resized_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(resized_size, Image.Resampling.LANCZOS)
    focus = contract["transform"].get("focal_point", {"x": 0.5, "y": 0.5})
    focus_x, focus_y = float(focus.get("x", 0.5)), float(focus.get("y", 0.5))
    if not 0 <= focus_x <= 1 or not 0 <= focus_y <= 1:
        raise ContractError("INVALID_CONTRACT", "focal_point values must be between 0 and 1")
    left = round(focus_x * resized.width - focus_x * target_width)
    top = round(focus_y * resized.height - focus_y * target_height)
    left = max(0, min(left, resized.width - target_width))
    top = max(0, min(top, resized.height - target_height))
    output = resized.crop((left, top, left + target_width, top + target_height))
    return output, {"mode": "cover", "scale": scale, "crop": {"x": left, "y": top, "width": target_width, "height": target_height}}


def _nine_slice(image: Image.Image, contract: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    canvas = contract["target"]["canvas"]
    insets = contract["transform"]["insets"]
    left, right, top, bottom = (insets["left"], insets["right"], insets["top"], insets["bottom"])
    if left + right >= image.width or top + bottom >= image.height:
        raise ContractError("NINE_SLICE_SOURCE_TOO_SMALL", f"source must leave a positive center region; source={image.width}x{image.height}, insets={insets}")
    src_x = (0, left, image.width - right, image.width)
    src_y = (0, top, image.height - bottom, image.height)
    dst_x = (0, left, canvas["width"] - right, canvas["width"])
    dst_y = (0, top, canvas["height"] - bottom, canvas["height"])
    output = Image.new("RGBA", (canvas["width"], canvas["height"]), (0, 0, 0, 0))
    for row in range(3):
        for column in range(3):
            patch = image.crop((src_x[column], src_y[row], src_x[column + 1], src_y[row + 1]))
            target_size = (dst_x[column + 1] - dst_x[column], dst_y[row + 1] - dst_y[row])
            if patch.size != target_size:
                patch = patch.resize(target_size, Image.Resampling.LANCZOS)
            output.alpha_composite(patch, (dst_x[column], dst_y[row]))
    return output, {"mode": "nine-slice", "insets": insets.copy()}


def _write_image_atomic(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=destination.suffix, dir=destination.parent)
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, "PNG", optimize=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(payload: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".json", dir=destination.parent)
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary_name, destination)


def normalize_asset(source_path: Path | str, contract_path: Path | str, output_dir: Path | str) -> PipelineResult:
    source = Path(source_path).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    inspection = inspect_image(source)
    contract = load_contract(contract_path)
    cache_key = _cache_key(inspection["sha256"], contract)
    artifact_dir = output_root / f"{source.stem}-{cache_key[:12]}"
    destination = artifact_dir / source.with_suffix(".png").name
    report_path = artifact_dir / f"{destination.stem}.result.json"
    if destination == source:
        raise ContractError("SOURCE_OUTPUT_COLLISION", "output path resolves to the source image; choose a separate --out directory")

    if report_path.is_file() and destination.is_file():
        try:
            cached = json.loads(report_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") == cache_key and cached.get("output_sha256") == inspect_image(destination)["sha256"]:
                return PipelineResult("success", destination, report_path, True, inspection, _canonical_contract(contract), cached["transform"], cached["verification"])
        except (OSError, ValueError, KeyError):
            pass

    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    canvas = contract["target"]["canvas"]
    mode = contract["transform"]["mode"]
    if mode == "strict":
        if image.size != (canvas["width"], canvas["height"]):
            raise ContractError("ASSET_SIZE_MISMATCH", f"expected={canvas['width']}x{canvas['height']}, actual={image.width}x{image.height}")
        output, transform = image.copy(), {"mode": "strict", "scale": 1.0}
    elif mode in {"contain", "pad"}:
        output, transform = _contain(image, inspection, contract)
        transform["mode"] = mode
    elif mode == "cover":
        output, transform = _cover(image, contract)
    elif mode == "nine-slice":
        output, transform = _nine_slice(image, contract)
    else:
        raise ContractError("INVALID_CONTRACT", f"unsupported mode: {mode}")

    if output.size != (canvas["width"], canvas["height"]):
        raise ContractError("OUTPUT_SIZE_MISMATCH", f"expected={canvas['width']}x{canvas['height']}, actual={output.width}x{output.height}")
    verification = {"canvas_size": "pass"}
    if mode in {"contain", "pad"}:
        box = contract["target"]["content_box"]
        bbox = output.getchannel("A").getbbox()
        if bbox is None:
            raise ContractError("EMPTY_OUTPUT", "normalized output contains no visible pixels")
        if bbox[0] < box["x"] or bbox[1] < box["y"] or bbox[2] > box["x"] + box["width"] or bbox[3] > box["y"] + box["height"]:
            raise ContractError("VISIBLE_CONTENT_CLIPPED", f"visible_bbox={bbox}, content_box={box}")
        verification["visible_content_within_box"] = "pass"
    if mode == "nine-slice":
        insets = contract["transform"]["insets"]
        corners = ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1))
        output_corners = ((0, 0), (output.width - 1, 0), (0, output.height - 1), (output.width - 1, output.height - 1))
        if any(image.getpixel(source_point) != output.getpixel(output_point) for source_point, output_point in zip(corners, output_corners)):
            raise ContractError("NINE_SLICE_CORNER_CHANGED", str(insets))
        verification["corner_preservation"] = "pass"

    _write_image_atomic(output, destination)
    output_sha = inspect_image(destination)["sha256"]
    report = {
        "schema": "sop.asset-result.v1",
        "status": "success",
        "cache_key": cache_key,
        "source": inspection,
        "contract": _canonical_contract(contract),
        "output_path": str(destination),
        "output_sha256": output_sha,
        "transform": transform,
        "verification": verification,
    }
    _write_json_atomic(report, report_path)
    return PipelineResult("success", destination, report_path, False, inspection, _canonical_contract(contract), transform, verification)
