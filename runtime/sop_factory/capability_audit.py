from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .context import require_resolved_context
from .registry import RECIPES, RecipeDefinition


EXTERNAL_GATES = (
    "package_approval",
    "creator_playback",
    "visual_review",
    "device_runtime",
    "user_acceptance",
)


def audit_project_capabilities(
    *,
    cwd: Path | str | None = None,
    request: str = "",
    profile_dir: Path | None = None,
    ps_text: str | None = None,
    recipes: Iterable[RecipeDefinition] = RECIPES,
) -> dict[str, Any]:
    context = require_resolved_context(cwd=cwd, request=request, profile_dir=profile_dir, ps_text=ps_text)
    project = context["project"]
    capabilities = set(project.get("capabilities", []))
    compatible: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for recipe in sorted(recipes, key=lambda item: item.id):
        missing = sorted(set(recipe.required_capabilities) - capabilities)
        item = {
            "id": recipe.id,
            "risk": recipe.risk,
            "scope": recipe.scope,
            "command": list(recipe.command),
            "required_capabilities": list(recipe.required_capabilities),
        }
        if missing:
            unavailable.append({**item, "missing_capabilities": missing})
        else:
            compatible.append(item)
    return {
        "status": "success",
        "schema": "sop.project-capability-audit.v1",
        "project": project,
        "declared_capabilities": sorted(capabilities),
        "registered_adapters": sorted(project.get("adapters", [])),
        "compatible_recipes": compatible,
        "unavailable_recipes": unavailable,
        "external_gates": list(EXTERNAL_GATES),
        "claims": {
            "recipe_compatibility": "verified_from_profile_prerequisites",
            "runtime_acceptance": "pending_or_external",
            "visual_acceptance": "pending_or_external",
        },
    }
