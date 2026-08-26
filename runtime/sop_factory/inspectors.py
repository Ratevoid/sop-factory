from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image

from .contracts import ContractError


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_image(path: Path | str) -> dict[str, Any]:
    image_path = Path(path).expanduser().resolve()
    if not image_path.is_file():
        raise ContractError("SOURCE_NOT_FOUND", str(image_path))
    try:
        with Image.open(image_path) as opened:
            image = opened.convert("RGBA")
            source_format = opened.format or image_path.suffix.lstrip(".").upper()
    except Exception as exc:
        raise ContractError("UNSUPPORTED_IMAGE", f"{image_path}: {exc}") from exc

    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    content_bbox = None
    if bbox is not None:
        left, top, right, bottom = bbox
        content_bbox = {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }

    extrema = alpha.getextrema()
    minimum_alpha = int(extrema[0]) if not isinstance(extrema[0], tuple) else int(extrema[0][0])
    has_alpha = minimum_alpha < 255
    return {
        "path": str(image_path),
        "format": source_format,
        "pixel_size": {"width": image.width, "height": image.height},
        "aspect_ratio": image.width / image.height,
        "color_mode": "RGBA",
        "has_alpha": has_alpha,
        "alpha_content_bbox": content_bbox,
        "sha256": file_sha256(image_path),
    }
