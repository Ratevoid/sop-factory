#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sop_factory.capability_audit import audit_project_capabilities
from sop_factory.context import resolve_context
from sop_factory.contracts import ContractError
from sop_factory.directives import parse_directive
from sop_factory.delivery_audit import audit_delivery
from sop_factory.errors import SopError
from sop_factory.inspectors import inspect_image
from sop_factory.pipeline import normalize_asset
from sop_factory.profiles import load_profiles, validate_profiles
from sop_factory.framework_package import package_framework
from sop_factory.source_learning import build_source_learning_package, verify_source_learning_package
from sop_factory.human_output import render_human
from sop_factory.registry import RECIPES, list_recipes, validate_public_recipe_ids
from sop_factory.retrieval import search_recipes
from sop_factory.state import read_state, record_action


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return (
            super()
            .format_help()
            .replace("usage:", "用法:")
            .replace("options:", "选项:")
            .replace("optional arguments:", "选项:")
            .replace("positional arguments:", "位置参数:")
            .replace("show this help message and exit", "显示帮助并退出")
        )

    def error(self, message: str) -> None:
        translated = (
            message.replace("the following arguments are required:", "缺少必需参数:")
            .replace("invalid choice:", "无效选项:")
            .replace("unrecognized arguments:", "无法识别的参数:")
            .replace("expected one argument", "需要一个参数")
        )
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: 错误: {translated}\n")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，供 Agent 和脚本使用")


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


PUBLIC_RECIPE_IDS = {
    "context.resolve",
    "config.validate",
    "directive.parse",
    "delivery.audit",
    "project.capability-audit",
    "asset.inspect",
    "asset.normalize",
    "framework.package",
    "source.learn",
    "source.verify",
}


def build_parser() -> argparse.ArgumentParser:
    validate_public_recipe_ids(PUBLIC_RECIPE_IDS)
    parser = ChineseArgumentParser(prog="sop", description="项目中立、可验证、可重复执行的 SOP 工具箱")
    commands = parser.add_subparsers(dest="group", title="可用命令", metavar="子命令")

    status = commands.add_parser("status", help="查看当前环境、工作模式和建议操作")
    status.add_argument("--cwd", type=_path, help="指定工作目录")
    _add_common(status)

    usage = commands.add_parser("usage", help="查看各项 SOP 的聚合使用次数")
    _add_common(usage)

    context = commands.add_parser("context", help="识别本次操作目标和当前运行工程")
    context.add_argument("--cwd", type=_path, help="指定工作目录")
    context.add_argument("--request", default="", help="用户的自然语言请求")
    _add_common(context)

    project = commands.add_parser("project", help="查看已注册项目及其能力")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_list = project_commands.add_parser("list")
    project_list.add_argument("--cwd", type=_path)
    _add_common(project_list)
    project_current = project_commands.add_parser("current")
    project_current.add_argument("--cwd", type=_path)
    _add_common(project_current)
    project_capabilities = project_commands.add_parser("capabilities")
    project_capabilities.add_argument("--cwd", type=_path)
    project_capabilities.add_argument("--request", default="")
    _add_common(project_capabilities)

    config = commands.add_parser("config", help="检查 SOP 配置")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_validate = config_commands.add_parser("validate")
    config_validate.add_argument("--cwd", type=_path)
    _add_common(config_validate)

    directive = commands.add_parser("directive", help="解析自然语言请求的意图、风险和范围")
    directive.add_argument("text", help="要解析的自然语言请求")
    _add_common(directive)

    delivery = commands.add_parser("delivery", help="审计最终交付物")
    delivery_commands = delivery.add_subparsers(dest="delivery_command", required=True)
    delivery_audit = delivery_commands.add_parser("audit")
    delivery_audit.add_argument("artifact", type=_path)
    delivery_audit.add_argument("--contract", type=_path)
    _add_common(delivery_audit)

    recipe = commands.add_parser("recipe", help="查看和搜索确定性 SOP 配方")
    recipe_commands = recipe.add_subparsers(dest="recipe_command", required=True)
    recipe_list = recipe_commands.add_parser("list")
    _add_common(recipe_list)
    recipe_search = recipe_commands.add_parser("search")
    recipe_search.add_argument("--request", required=True, help="用自然语言描述要做的事")
    recipe_search.add_argument("--cwd", type=_path)
    recipe_search.add_argument("--limit", type=int, default=3)
    _add_common(recipe_search)

    asset = commands.add_parser("asset", help="检查和归一化视觉素材")
    asset_commands = asset.add_subparsers(dest="asset_command", required=True)
    inspect_parser = asset_commands.add_parser("inspect")
    inspect_parser.add_argument("source", type=_path)
    _add_common(inspect_parser)
    normalize_parser = asset_commands.add_parser("normalize")
    normalize_parser.add_argument("source", type=_path)
    normalize_parser.add_argument("--contract", type=_path, required=True)
    normalize_parser.add_argument("--out", type=_path, required=True)
    _add_common(normalize_parser)

    source = commands.add_parser("source", help="编译和验证具备覆盖门禁的源码学习能力包")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    source_learn = source_commands.add_parser("learn")
    source_learn.add_argument("--contract", type=_path, required=True)
    source_learn.add_argument("--out", type=_path, required=True)
    source_learn.add_argument("--apply", action="store_true", help="原子创建能力包")
    _add_common(source_learn)
    source_verify = source_commands.add_parser("verify")
    source_verify.add_argument("package", type=_path)
    _add_common(source_verify)

    framework = commands.add_parser("framework", help="生成不含项目知识的完整 SOP 框架包")
    framework_commands = framework.add_subparsers(dest="framework_command", required=True)
    framework_package = framework_commands.add_parser("package")
    framework_package.add_argument("--out", type=_path, required=True)
    framework_package.add_argument("--policy", type=_path)
    framework_package.add_argument("--apply", action="store_true", help="原子创建经过知识隔离检查的 ZIP")
    _add_common(framework_package)
    return parser


def _status(cwd: Path | None) -> dict[str, Any]:
    context = resolve_context(cwd=cwd)
    state = read_state()
    recent_action = {
        key: state.get(key)
        for key in ("last_action", "last_status", "last_project", "updated_at")
        if key in state
    }
    project = context.get("project") or context.get("recommended")
    capabilities = set(project.get("capabilities", [])) if isinstance(project, dict) else set()
    suggestions = ["识别当前工程", "查看可用工具", "验证项目配置"]
    return {
        "status": context["status"],
        "schema": "sop.status.v1",
        "message": context["message"],
        "project": project,
        "mode": "自然语言无感路由；写入按风险确认",
        "recent_action": recent_action or None,
        "suggestions": suggestions[:3],
    }


def _usage_report(state: dict[str, Any] | None = None) -> dict[str, Any]:
    usage = (state or read_state()).get("usage", {})
    actions = usage.get("actions", {}) if isinstance(usage, dict) else {}
    if not isinstance(actions, dict):
        actions = {}
    ranked = [
        {"action": action, **details}
        for action, details in actions.items()
        if isinstance(details, dict)
    ]
    ranked.sort(key=lambda item: (-int(item.get("calls", 0)), str(item["action"])))
    recipe_ids = sorted(PUBLIC_RECIPE_IDS)
    return {
        "status": "success",
        "schema": "sop.usage-report.v1",
        "total_calls": int(usage.get("total_calls", 0)) if isinstance(usage, dict) else 0,
        "started_at": usage.get("started_at") if isinstance(usage, dict) else None,
        "updated_at": usage.get("updated_at") if isinstance(usage, dict) else None,
        "actions": ranked,
        "recipe_usage": [
            {"action": recipe_id, **actions.get(recipe_id, {"calls": 0, "statuses": {}})}
            for recipe_id in recipe_ids
        ],
        "unused_recipes": [recipe_id for recipe_id in recipe_ids if recipe_id not in actions],
        "privacy": "Stores aggregate action and result counts only; request text, arguments and paths are not recorded.",
    }


def _action_id(args: argparse.Namespace) -> str:
    group = getattr(args, "group", None)
    if group is None or group == "status":
        return "status"
    if group in {"context", "directive", "usage"}:
        return {"context": "context.resolve", "directive": "directive.parse", "usage": "usage"}[group]
    subcommand = getattr(args, f"{group}_command", None)
    return f"{group}.{subcommand}" if subcommand else str(group)


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    if args.group is None or args.group == "status":
        return _status(getattr(args, "cwd", None)), "status"
    if args.group == "usage":
        return _usage_report(), "usage"
    if args.group == "context":
        return resolve_context(cwd=args.cwd, request=args.request), "context.resolve"
    if args.group == "project":
        if args.project_command == "list":
            return {
                "status": "success",
                "schema": "sop.project-list.v1",
                "projects": [profile.to_dict() for profile in load_profiles(cwd=args.cwd)],
            }, "project.list"
        if args.project_command == "current":
            return resolve_context(cwd=args.cwd), "project.current"
        return audit_project_capabilities(cwd=args.cwd, request=args.request), "project.capability-audit"
    if args.group == "config":
        return validate_profiles(cwd=args.cwd), "config.validate"
    if args.group == "directive":
        return parse_directive(args.text), "directive.parse"
    if args.group == "delivery":
        return audit_delivery(args.artifact, args.contract), "delivery.audit"
    if args.group == "recipe":
        if args.recipe_command == "list":
            return list_recipes(), "recipe.list"
        return search_recipes(args.request, cwd=args.cwd, limit=args.limit), "recipe.search"
    if args.group == "asset":
        if args.asset_command == "inspect":
            return {"status": "success", "schema": "sop.asset-inspection.v1", **inspect_image(args.source)}, "asset.inspect"
        return normalize_asset(args.source, args.contract, args.out).to_dict(), "asset.normalize"
    if args.group == "source" and args.source_command == "learn":
        return build_source_learning_package(
            args.contract,
            args.out,
            apply=args.apply,
        ), "source.learn"
    if args.group == "source" and args.source_command == "verify":
        return verify_source_learning_package(args.package), "source.verify"
    if args.group == "framework" and args.framework_command == "package":
        return package_framework(args.out, apply=args.apply, policy_path=args.policy), "framework.package"
    raise SopError("COMMAND_NOT_IMPLEMENTED", str(args.group))


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    print(render_human(payload))


def _record_action_safely(action: str, status: str, project: str | None = None) -> dict[str, Any]:
    try:
        return record_action(action, status, project)
    except OSError:
        return {}


def _action_risk(action: str) -> str:
    recipe = next((item for item in RECIPES if item.id == action), None)
    return recipe.risk if recipe is not None else "read_only"


def _invocation_report(state: dict[str, Any], action: str, status: str) -> dict[str, Any]:
    usage = state.get("usage") if isinstance(state, dict) else None
    actions = usage.get("actions") if isinstance(usage, dict) else None
    action_usage = actions.get(action) if isinstance(actions, dict) else None
    recorded = isinstance(action_usage, dict)
    return {
        "schema": "sop.invocation.v1",
        "action": action,
        "risk": _action_risk(action),
        "status": status,
        "action_calls": int(action_usage.get("calls", 0)) if recorded else None,
        "total_calls": int(usage.get("total_calls", 0)) if isinstance(usage, dict) else None,
        "recorded": recorded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        _record_action_safely("cli.parse", "help" if exc.code == 0 else "parse_error")
        raise
    as_json = bool(getattr(args, "json", False))
    action = _action_id(args)
    try:
        payload, action = _dispatch(args)
        project = payload.get("project")
        project_name = project.get("display_name") if isinstance(project, dict) else None
        state = _record_action_safely(action, str(payload.get("status", "unknown")), project_name)
        if action == "usage":
            payload = _usage_report(state) if state else payload
        payload["invocation"] = _invocation_report(state, action, str(payload.get("status", "unknown")))
        _print(payload, as_json)
        return 0 if payload.get("status") in {"success", "partial"} else 2
    except (SopError, ContractError) as exc:
        details = getattr(exc, "details", {})
        payload = {
            "status": "failure",
            "schema": "sop.error.v1",
            "error_code": exc.code,
            "message": exc.message,
            **({"details": details} if details else {}),
        }
        state = _record_action_safely(action, "failure")
        payload["invocation"] = _invocation_report(state, action, "failure")
        _print(payload, as_json)
        return 2
    except (OSError, TimeoutError) as exc:
        payload = {
            "status": "failure",
            "schema": "sop.error.v1",
            "error_code": "UNKNOWN_RUNTIME_FAILURE",
            "message": str(exc),
        }
        state = _record_action_safely(action, "failure")
        payload["invocation"] = _invocation_report(state, action, "failure")
        _print(payload, as_json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
