from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .context import resolve_context
from .directives import parse_directive
from .errors import SopError
from .registry import RECIPES, RecipeDefinition, validate_recipe_catalog


MINIMUM_SCORE = 120
SELECTION_MARGIN = 30
MAX_CANDIDATES = 5
MAX_REJECTION_DETAILS = 20


def _normalize(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def _contains(query: str, value: str) -> bool:
    normalized = _normalize(value)
    return bool(normalized) and normalized in query


def _score(recipe: RecipeDefinition, request: str, request_risk: str) -> tuple[int, list[dict[str, Any]]]:
    query = _normalize(request)
    if not query:
        return 0, []
    score = 0
    evidence: list[dict[str, Any]] = []

    def add(points: int, kind: str, value: str) -> None:
        nonlocal score
        score += points
        evidence.append({"kind": kind, "value": value, "points": points})

    normalized_id = _normalize(recipe.id)
    if query == normalized_id:
        add(1000, "exact_id", recipe.id)
    elif normalized_id in query:
        add(650, "id_in_request", recipe.id)

    for alias in recipe.aliases:
        normalized_alias = _normalize(alias)
        if not normalized_alias:
            continue
        if query == normalized_alias:
            add(900, "exact_alias", alias)
        elif normalized_alias in query:
            add(500 + min(len(normalized_alias), 100), "alias_in_request", alias)

    for intent in recipe.intents:
        if _contains(query, intent.replace("_", " ")):
            add(160, "intent", intent)
    for domain in recipe.domains:
        if _contains(query, domain):
            add(90, "domain", domain)
    if _contains(query, recipe.family):
        add(60, "family", recipe.family)
    if recipe.risk == request_risk:
        add(20, "risk_match", request_risk)
    return score, evidence


def _hard_filter(recipe: RecipeDefinition, request_risk: str, capabilities: set[str]) -> list[str]:
    reasons: list[str] = []
    if request_risk == "read_only" and recipe.mutates:
        reasons.append("risk:read_only_request")
    elif request_risk == "write" and recipe.risk == "high":
        reasons.append("risk:high_approval_required")
    elif request_risk == "high" and recipe.risk != "high":
        reasons.append("risk:high_request_requires_exact_recipe")
    for capability in recipe.required_capabilities:
        if capability not in capabilities:
            reasons.append(f"missing_capability:{capability}")
    return reasons


def _candidate(recipe: RecipeDefinition, score: int, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "family": recipe.family,
        "summary": recipe.summary,
        "risk": recipe.risk,
        "mutates": recipe.mutates,
        "scope": recipe.scope,
        "required_capabilities": list(recipe.required_capabilities),
        "command": list(recipe.command),
        "score": score,
        "score_evidence": evidence,
    }


def search_recipes(
    request: str,
    *,
    cwd: Path | str | None = None,
    limit: int = 3,
    profile_dir: Path | None = None,
    ps_text: str | None = None,
    recipes: Iterable[RecipeDefinition] = RECIPES,
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_CANDIDATES:
        raise SopError(
            "INVALID_RECIPE_SEARCH_LIMIT",
            f"limit must be between 1 and {MAX_CANDIDATES}",
            details={"limit": limit, "minimum": 1, "maximum": MAX_CANDIDATES},
        )
    catalog = tuple(recipes)
    validate_recipe_catalog(catalog)
    directive = parse_directive(request)
    if directive["status"] != "success":
        return {
            "status": "needs_confirmation",
            "schema": "sop.recipe-search.v1",
            "message": directive["message"],
            "directive": directive,
            "selected": None,
            "candidates": [],
            "executed": False,
        }

    request_risk = str(directive["risk"])
    actionable = str(directive.get("actionable_text") or request)
    global_ranked = sorted(
        (
            (recipe, *_score(recipe, actionable, request_risk))
            for recipe in catalog
            if recipe.scope == "global" and not _hard_filter(recipe, request_risk, set())
        ),
        key=lambda item: (-item[1], item[0].id),
    )
    global_match = bool(
        global_ranked
        and global_ranked[0][1] >= MINIMUM_SCORE
        and (len(global_ranked) == 1 or global_ranked[0][1] - global_ranked[1][1] >= SELECTION_MARGIN)
    )
    context = resolve_context(cwd=cwd, request=directive["normalized_text"], profile_dir=profile_dir, ps_text=ps_text)
    if context["status"] != "success":
        if global_match:
            context = {
                **context,
                "status": "success",
                "message": "已唯一匹配全局配方；本次检索不需要项目上下文。",
                "project": None,
                "operation_project": None,
                "active_project": None,
                "context_mismatch": False,
                "project_context_bypassed": True,
            }
        else:
            return {
                "status": "needs_confirmation",
                "schema": "sop.recipe-search.v1",
                "message": context["message"],
                "directive": directive,
                "context": context,
                "selected": None,
                "candidates": [],
                "executed": False,
            }

    project = context.get("operation_project") or context.get("project") or {}
    capabilities = set(project.get("capabilities") or [])
    actionable = str(directive.get("actionable_text") or context.get("request_text", {}).get("actionable") or request)
    eligible: list[tuple[RecipeDefinition, int, list[dict[str, Any]]]] = []
    rejected: list[dict[str, Any]] = []
    for recipe in catalog:
        reasons = _hard_filter(recipe, request_risk, capabilities)
        if reasons:
            rejected.append({"id": recipe.id, "reasons": reasons})
            continue
        score, evidence = _score(recipe, actionable, request_risk)
        eligible.append((recipe, score, evidence))

    ranked = sorted(eligible, key=lambda item: (-item[1], item[0].id))
    relevant = [item for item in ranked if item[1] > 0]
    candidates = [_candidate(*item) for item in relevant[:limit]]
    selected: dict[str, Any] | None = None
    status = "no_match"
    message = "没有兼容且足够相关的 SOP recipe；未执行任何操作。"
    if candidates and candidates[0]["score"] >= MINIMUM_SCORE:
        top_score = int(candidates[0]["score"])
        runner_up_score = int(candidates[1]["score"]) if len(candidates) > 1 else 0
        if len(candidates) == 1 or top_score - runner_up_score >= SELECTION_MARGIN:
            status = "success"
            selected = candidates[0]
            message = f"已唯一匹配 recipe：{selected['summary']}"
        else:
            status = "needs_confirmation"
            message = f"请求同时匹配“{candidates[0]['summary']}”和“{candidates[1]['summary']}”，请说明要检查哪一类对象。"

    return {
        "status": status,
        "schema": "sop.recipe-search.v1",
        "message": message,
        "request": request,
        "directive": directive,
        "context": context,
        "selected": selected,
        "candidates": candidates,
        "eligible_count": len(eligible),
        "rejected_count": len(rejected),
        "rejections": sorted(rejected, key=lambda item: item["id"])[:MAX_REJECTION_DETAILS],
        "thresholds": {
            "minimum_score": MINIMUM_SCORE,
            "selection_margin": SELECTION_MARGIN,
            "candidate_limit": limit,
        },
        "executed": False,
    }
