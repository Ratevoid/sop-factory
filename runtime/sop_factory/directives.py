from __future__ import annotations

import difflib
import re
from typing import Any

from .request_text import split_request_text


ENGINE_ALIASES = ("cocos", "cocos creator", "creator")
READ_WORDS = ("检查", "检测", "看看", "查看", "审计", "状态", "verify", "check", "inspect", "status", "doctor")
WRITE_WORDS = ("修改", "修复", "替换", "写入", "生成", "制作", "做出", "汉化", "中文化", "本地化", "新增", "增加", "添加", "创建", "建立", "清理", "接入", "改成", "对齐", "同步", "change", "edit", "fix", "write", "generate", "add", "create", "build", "clean", "align", "sync", "apply")
HIGH_RISK_WORDS = ("删除", "清空", "打包", "发布", "推送", "权限", "delete", "remove", "package", "publish", "push", "permission")
READ_ONLY_CONSTRAINTS = ("只读", "不要改变", "不要修改", "先别改", "先不改", "不做修改", "read only", "read-only", "do not modify")
RECIPE_WRITE_WORDS = (
    "做老虎机工厂",
    "来做老虎机工厂",
    "build slot factory",
    "做成sop",
    "做成 sop",
    "转化为sop",
    "转化为 sop",
    "做成工具",
    "固化成脚本",
    "脚本化",
    "加入工具箱",
    "写出程序",
    "写个程序",
    "工具脚本",
    "写脚本",
    "新增adapter",
    "新增 adapter",
    "增加adapter",
    "增加 adapter",
    "添加adapter",
    "添加 adapter",
    "一工具多用",
    "add adapter",
    "机械学习",
    "训练模型",
    "make recipe",
    "scriptize",
    "machine learning",
)
COMPLETED_HIGH_RISK_PATTERNS = (
    r"(?:已经|已)(?:做完|完成)?打包(?:完成|好了|了)?",
    r"打包(?:已经|已)完成",
    r"(?:already\s+packaged|packaging\s+(?:is\s+)?complete)",
)


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(word.casefold() in lowered for word in words)


def _scope(text: str) -> str:
    if _contains_any(text, ("这个项目以后", "本项目以后", "当前项目以后", "for this project")):
        return "project"
    if _contains_any(text, ("所有项目", "全部项目", "全局", "以后都", "globally", "all projects")):
        return "global"
    return "session"


def _risk(text: str) -> str:
    if _contains_any(text, READ_ONLY_CONSTRAINTS):
        return "read_only"
    active_text = text
    for pattern in COMPLETED_HIGH_RISK_PATTERNS:
        active_text = re.sub(pattern, "", active_text, flags=re.IGNORECASE)
    if _contains_any(active_text, HIGH_RISK_WORDS):
        return "high"
    if _contains_any(text, RECIPE_WRITE_WORDS):
        return "write"
    if _contains_any(text, WRITE_WORDS):
        return "write"
    return "read_only"


def _typo_candidate(text: str) -> tuple[str, str] | None:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.casefold())
    for token in tokens:
        if token in {"cocos", "creator"}:
            continue
        match = difflib.get_close_matches(token, ["cocos", "creator"], n=1, cutoff=0.72)
        if match:
            return token, match[0]
    return None


def parse_directive(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("/sop"):
        cleaned = cleaned[4:].strip()
    if not cleaned:
        return {
            "status": "success",
            "schema": "sop.directive.v1",
            "intent": "status",
            "risk": "read_only",
            "scope": "session",
            "normalized_text": "",
            "warnings": [],
        }

    request_text = split_request_text(cleaned)
    actionable = request_text.actionable
    risk = _risk(actionable)
    scope = _scope(actionable)
    typo = _typo_candidate(actionable)
    warnings: list[str] = []
    normalized = cleaned
    if typo:
        original, correction = typo
        if risk == "read_only":
            normalized = re.sub(rf"\b{re.escape(original)}\b", correction, cleaned, flags=re.IGNORECASE)
            warnings.append(f"已将“{original}”按“{correction}”理解，仅用于本次只读检查。")
        elif risk == "write":
            return {
                "status": "needs_confirmation",
                "schema": "sop.directive.v1",
                "intent": "confirm_correction",
                "risk": risk,
                "scope": scope,
                "message": f"你写的是“{original}”。我猜你指的是“{correction}”，但这次会修改文件；要按“{correction}”继续吗？",
                "original_text": cleaned,
                "suggested_text": re.sub(rf"\b{re.escape(original)}\b", correction, cleaned, flags=re.IGNORECASE),
            }
        else:
            return {
                "status": "needs_confirmation",
                "schema": "sop.directive.v1",
                "intent": "exact_target_required",
                "risk": risk,
                "scope": scope,
                "message": f"这是高风险操作，我不会把“{original}”模糊匹配成工程或工具名。请确认准确名称后再继续。",
                "original_text": cleaned,
            }

    intent = "route_request"
    normalized_actionable = split_request_text(normalized).actionable
    if _contains_any(normalized_actionable, ("停止", "取消", "先别做", "stop", "cancel")):
        intent = "stop"
    elif _contains_any(normalized_actionable, ("撤销", "回退刚才", "undo")):
        intent = "undo"
    elif _contains_any(normalized_actionable, ("为什么这样判断", "解释路由", "怎么判断", "explain route")):
        intent = "explain_route"
    elif _contains_any(normalized_actionable, RECIPE_WRITE_WORDS):
        intent = "create_recipe_candidate"

    return {
        "status": "success",
        "schema": "sop.directive.v1",
        "intent": intent,
        "risk": risk,
        "scope": scope,
        "normalized_text": normalized,
        "actionable_text": normalized_actionable,
        "reference_text": split_request_text(normalized).reference,
        "warnings": warnings,
        "requires_explicit_approval": risk == "high",
    }
