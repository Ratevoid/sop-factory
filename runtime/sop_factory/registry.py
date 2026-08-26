from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import SopError


SUPPORTED_RISKS = {"read_only", "write", "high"}
SUPPORTED_SCOPES = {"global", "engine", "project"}


@dataclass(frozen=True)
class RecipeDefinition:
    id: str
    family: str
    version: str
    summary: str
    risk: str
    mutates: bool
    domains: tuple[str, ...]
    intents: tuple[str, ...]
    aliases: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    scope: str
    input_schema: str
    output_schema: str
    fixtures: tuple[str, ...]
    completion_check: str
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "version": self.version,
            "summary": self.summary,
            "risk": self.risk,
            "mutates": self.mutates,
            "domains": list(self.domains),
            "intents": list(self.intents),
            "aliases": list(self.aliases),
            "required_capabilities": list(self.required_capabilities),
            "scope": self.scope,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "fixtures": list(self.fixtures),
            "completion_check": self.completion_check,
            "command": list(self.command),
        }


def _recipe(
    recipe_id: str,
    family: str,
    summary: str,
    *,
    risk: str = "read_only",
    domains: tuple[str, ...],
    intents: tuple[str, ...],
    aliases: tuple[str, ...],
    required_capabilities: tuple[str, ...] = (),
    scope: str = "global",
    input_schema: str,
    output_schema: str,
    fixtures: tuple[str, ...],
    completion_check: str,
    command: tuple[str, ...],
) -> RecipeDefinition:
    return RecipeDefinition(
        id=recipe_id,
        family=family,
        version="1.0.0",
        summary=summary,
        risk=risk,
        mutates=risk != "read_only",
        domains=domains,
        intents=intents,
        aliases=aliases,
        required_capabilities=required_capabilities,
        scope=scope,
        input_schema=input_schema,
        output_schema=output_schema,
        fixtures=fixtures,
        completion_check=completion_check,
        command=command,
    )


RECIPES: tuple[RecipeDefinition, ...] = (
    _recipe(
        "framework.package",
        "framework-distribution",
        "将完整 SOP 执行层、测试和插件入口打包为不含项目知识的可复现框架 ZIP",
        risk="high",
        domains=("framework", "package", "distribution", "plugin", "skill", "learning-closeout", "knowledge-isolation"),
        intents=("package_framework", "package_skill_folder", "export_project_neutral_sop", "build_clean_sop_distribution"),
        aliases=(
            "打包 SOP 框架版",
            "导出无项目知识 SOP",
            "SOP framework package",
            "完整框架包",
            "learning-closeout 打包",
            "打包 Skill 文件夹",
        ),
        scope="global",
        input_schema="sop.framework-package-policy.v1",
        output_schema="sop.framework-package-result.v1",
        fixtures=("tests/test_framework_package.py",),
        completion_check="dry-run, allowlist, knowledge scan, deterministic archive, atomic apply, plugin validation and unpacked tests pass",
        command=("framework", "package"),
    ),
    _recipe(
        "context.resolve",
        "core",
        "识别操作目标和当前运行工程；歧义时生成人类可读确认问题",
        domains=("project", "routing"),
        intents=("resolve_context", "identify_project", "current_project"),
        aliases=("识别当前工程", "当前项目", "当前工程", "项目识别", "工程路由"),
        input_schema="sop.context-request.v1",
        output_schema="sop.context.v1",
        fixtures=("tests/test_context_and_directives.py",),
        completion_check="operation and active projects are resolved or a confirmation boundary is returned",
        command=("context",),
    ),
    _recipe(
        "config.validate",
        "core",
        "验证 Profile 配置、能力声明与唯一性",
        domains=("project", "configuration"),
        intents=("validate_config", "validate_profile"),
        aliases=("验证配置", "检查 Profile", "Profile 配置", "项目配置校验"),
        input_schema="sop.profile-validation-request.v1",
        output_schema="sop.profile-validation.v1",
        fixtures=("tests/test_context_and_directives.py", "tests/test_recipe_registry_and_retrieval.py"),
        completion_check="all profiles load and unique identifiers are confirmed",
        command=("config", "validate"),
    ),
    _recipe(
        "directive.parse",
        "core",
        "解析自然语言、引用文本、作用域、风险与拼写纠正策略",
        domains=("routing", "risk"),
        intents=("parse_directive", "classify_risk", "explain_route"),
        aliases=("解析指令", "判断风险", "解释路由", "检查操作风险"),
        input_schema="sop.directive-request.v1",
        output_schema="sop.directive.v1",
        fixtures=("tests/test_context_and_directives.py",),
        completion_check="risk, scope, actionable text and confirmation policy are explicit",
        command=("directive",),
    ),
    _recipe(
        "project.capability-audit",
        "project-capability",
        "盘点当前项目声明能力、Adapter、兼容 recipe 与外部验收门禁",
        domains=("project", "capability", "recipe", "adapter", "audit"),
        intents=("audit_project_capabilities", "inventory_project_automation", "convert_project_to_sop"),
        aliases=("盘点项目能力", "项目能力转 SOP", "整体项目能力转化为 SOP", "查看可复用能力", "项目自动化能力"),
        input_schema="sop.project-capability-audit-request.v1",
        output_schema="sop.project-capability-audit.v1",
        fixtures=("tests/test_capability_audit.py",),
        completion_check="profile capabilities, adapters, compatible recipes, missing prerequisites and external gates are explicit",
        command=("project", "capabilities"),
    ),
    _recipe(
        "delivery.audit",
        "delivery",
        "只读审计 ZIP、APK 或目录的完整性、安全路径、合同闭合与交付污染",
        domains=("delivery", "package", "zip", "apk", "manifest", "audit"),
        intents=("audit_delivery", "verify_package", "check_final_artifact"),
        aliases=("审计最终包", "检查交付包", "验证 APK 完整性", "验证 ZIP 完整性", "交付物完整性检查"),
        input_schema="sop.delivery-contract.v1",
        output_schema="sop.delivery-audit.v1",
        fixtures=("tests/test_delivery_audit.py",),
        completion_check="artifact integrity, safe paths, optional manifest and format contracts pass while runtime acceptance remains external",
        command=("delivery", "audit"),
    ),
    _recipe(
        "asset.inspect",
        "asset",
        "检查位图尺寸、透明边界和 SHA-256",
        domains=("asset", "bitmap", "image"),
        intents=("inspect_asset", "inspect_image", "check_bitmap"),
        aliases=("检查图片", "检查位图", "图片尺寸", "透明边界", "图片哈希"),
        input_schema="sop.asset-inspection-request.v1",
        output_schema="sop.asset-inspection.v1",
        fixtures=("tests/test_cli_and_assets.py",),
        completion_check="pixel dimensions, alpha bounds and SHA-256 are reported",
        command=("asset", "inspect"),
    ),
    _recipe(
        "asset.normalize",
        "asset",
        "按合同确定性归一化位图并生成验证报告",
        risk="write",
        domains=("asset", "bitmap", "image"),
        intents=("normalize_asset", "resize_asset", "apply_asset_contract"),
        aliases=("归一化图片", "归一化位图", "调整图片尺寸", "按合同处理图片"),
        input_schema="sop.asset-contract.v1",
        output_schema="sop.asset-result.v1",
        fixtures=("tests/test_cli_and_assets.py",),
        completion_check="output size and transform contract pass with a cacheable report",
        command=("asset", "normalize"),
    ),
    _recipe(
        "source.learn",
        "source-learning",
        "把完整源码定义域编译成带覆盖矩阵、行为合同、差分证据和未知项门禁的能力包",
        risk="write",
        domains=("source", "learning", "code", "coverage", "behavior", "capability"),
        intents=("learn_source", "compile_source_capability", "build_learning_cortex", "audit_behavior_coverage"),
        aliases=("全量学习源码", "源码学习编译器", "修复学习能力", "建立本地学习皮层", "源码能力包", "行为覆盖矩阵", "source learning", "compile learned capability"),
        scope="global",
        input_schema="sop.source-learning-contract.v1",
        output_schema="sop.source-learning-result.v1",
        fixtures=("tests/test_source_learning.py", "tests/test_recipe_registry_and_retrieval.py"),
        completion_check=(
            "closed scope and corpus hashes are explicit; verified behaviors own causal, procedural, contract and executable evidence; "
            "manual paths cannot be replaced by auto demos; unknown surfaces or unmapped code block full-learning claims"
        ),
        command=("source", "learn"),
    ),
    _recipe(
        "source.verify",
        "source-learning",
        "回读并验证源码学习能力包的文件闭合、哈希与完成声明边界",
        domains=("source", "learning", "code", "coverage", "verify", "capability"),
        intents=("verify_source_capability", "check_learning_package", "audit_learning_evidence"),
        aliases=("验证源码能力包", "检查学习覆盖", "验证学习结果", "source learning verify"),
        scope="global",
        input_schema="sop.source-learning-package.v1",
        output_schema="sop.source-learning-verify.v1",
        fixtures=("tests/test_source_learning.py",),
        completion_check="all manifest files and hashes close while the package's original completion blockers remain unchanged",
        command=("source", "verify"),
    ),
)


def _fail(recipe_id: str, field: str, detail: str) -> None:
    raise SopError(
        "INVALID_RECIPE_CATALOG",
        f"{recipe_id or '<unknown>'}: {field} {detail}",
        details={"recipe_id": recipe_id or None, "field": field, "detail": detail},
    )


def validate_recipe_catalog(recipes: Iterable[RecipeDefinition] = RECIPES) -> dict[str, Any]:
    items = tuple(recipes)
    seen: set[str] = set()
    alias_owners: dict[str, set[str]] = {}
    for recipe in items:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,95}", recipe.id):
            _fail(recipe.id, "id", "must be lowercase dot-separated ASCII")
        if recipe.id in seen:
            _fail(recipe.id, "id", "must be unique")
        seen.add(recipe.id)
        if recipe.risk not in SUPPORTED_RISKS:
            _fail(recipe.id, "risk", f"must be one of {sorted(SUPPORTED_RISKS)}")
        if recipe.scope not in SUPPORTED_SCOPES:
            _fail(recipe.id, "scope", f"must be one of {sorted(SUPPORTED_SCOPES)}")
        if recipe.mutates != (recipe.risk != "read_only"):
            _fail(recipe.id, "mutates", "must agree with risk")
        scalar_fields = {
            "family": recipe.family,
            "version": recipe.version,
            "summary": recipe.summary,
            "input_schema": recipe.input_schema,
            "output_schema": recipe.output_schema,
            "completion_check": recipe.completion_check,
        }
        for field, value in scalar_fields.items():
            if not isinstance(value, str) or not value.strip():
                _fail(recipe.id, field, "must be a non-empty string")
        for field, values in {
            "domains": recipe.domains,
            "intents": recipe.intents,
            "aliases": recipe.aliases,
            "fixtures": recipe.fixtures,
            "command": recipe.command,
        }.items():
            if not values or any(not isinstance(value, str) or not value.strip() for value in values):
                _fail(recipe.id, field, "must contain non-empty strings")
        for alias in recipe.aliases:
            alias_owners.setdefault(alias.casefold().strip(), set()).add(recipe.id)

    collisions = [
        {"alias": alias, "recipe_ids": sorted(owners)}
        for alias, owners in sorted(alias_owners.items())
        if len(owners) > 1
    ]
    return {
        "status": "success",
        "schema": "sop.recipe-catalog-validation.v1",
        "recipe_count": len(items),
        "warnings": [{"code": "RECIPE_ALIAS_COLLISION", **item} for item in collisions],
    }


def validate_public_recipe_ids(public_ids: set[str]) -> None:
    catalog_ids = {recipe.id for recipe in RECIPES}
    if public_ids != catalog_ids:
        raise SopError(
            "RECIPE_COMMAND_REGISTRY_DRIFT",
            "public recipe commands and catalog identifiers differ",
            details={
                "missing_commands": sorted(catalog_ids - public_ids),
                "unregistered_commands": sorted(public_ids - catalog_ids),
            },
        )


def list_recipes() -> dict[str, Any]:
    validation = validate_recipe_catalog()
    return {
        "status": "success",
        "schema": "sop.recipe-registry.v1",
        "recipe_count": len(RECIPES),
        "validation": validation,
        "recipes": [recipe.to_dict() for recipe in RECIPES],
    }
