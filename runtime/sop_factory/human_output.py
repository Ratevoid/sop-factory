from __future__ import annotations

from typing import Any


STATUS_LABELS = {
    "success": "通过",
    "partial": "部分通过",
    "failure": "失败",
    "needs_confirmation": "需要确认",
    "no_match": "未找到匹配项",
    "unknown": "未知",
}

RISK_LABELS = {
    "read_only": "只读",
    "write": "会修改文件",
    "high": "高风险，必须明确批准",
}

SCOPE_LABELS = {
    "session": "本次会话",
    "project": "当前项目",
    "engine": "同类引擎项目",
    "global": "全局",
}

INTENT_LABELS = {
    "status": "查看状态",
    "route_request": "路由自然语言请求",
    "confirm_correction": "确认拼写纠正",
    "exact_target_required": "要求精确目标",
    "stop": "停止当前操作",
    "undo": "检查并撤销上次操作",
    "explain_route": "解释路由依据",
    "create_recipe_candidate": "创建可复用能力候选",
}

GATE_LABELS = {
    "package_approval": "打包批准",
    "creator_playback": "Creator 实际播放",
    "visual_review": "视觉验收",
    "device_runtime": "设备实机运行",
    "user_acceptance": "用户验收",
}

FAMILY_LABELS = {
    "core": "核心路由",
    "project-capability": "项目能力",
    "delivery": "交付审计",
    "asset": "图片素材",
    "framework-distribution": "框架分发",
    "source-learning": "源码学习",
}

FIELD_LABELS = {
    "status": "状态",
    "message": "说明",
    "error_code": "错误代码",
    "project": "项目",
    "display_name": "名称",
    "root": "路径",
    "lifecycle": "生命周期",
    "score": "可信分数",
    "evidence": "证据",
    "capabilities": "能力",
    "adapters": "适配器",
    "risk": "风险",
    "scope": "作用范围",
    "intent": "请求类型",
    "normalized_text": "规范化请求",
    "actionable_text": "可执行正文",
    "reference_text": "引用内容",
    "warnings": "提醒",
    "requires_explicit_approval": "需要明确批准",
    "source_path": "源文件",
    "output_path": "输出文件",
    "pixel_size": "像素尺寸",
    "alpha_content_bbox": "非透明内容边界",
    "sha256": "SHA-256",
    "cache_hit": "命中缓存",
    "missing_capabilities": "缺少能力",
    "external_gates": "外部验收门禁",
    "invocation": "调用记录",
    "action": "能力标识",
    "action_calls": "该能力累计调用",
    "total_calls": "SOP 总累计调用",
    "recorded": "已记入统计",
}


def _yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"


def _status(value: Any) -> str:
    text = str(value)
    return STATUS_LABELS.get(text, text)


def _project_lines(project: Any, *, prefix: str = "") -> list[str]:
    if not isinstance(project, dict):
        return []
    name = project.get("display_name") or project.get("id") or "未命名项目"
    lines = [f"{prefix}工程：{name}"]
    if project.get("root"):
        lines.append(f"{prefix}路径：{project['root']}")
    capabilities = project.get("capabilities") or []
    if capabilities:
        lines.append(f"{prefix}已声明能力：{', '.join(map(str, capabilities))}")
    return lines


def _render_status(payload: dict[str, Any]) -> str:
    lines = [payload.get("message") or f"状态：{_status(payload.get('status'))}"]
    lines.extend(_project_lines(payload.get("project")))
    if payload.get("mode"):
        lines.append(f"工作模式：{payload['mode']}")
    suggestions = payload.get("suggestions") or []
    if suggestions:
        lines.append("可以直接这样说：")
        lines.extend(f"- {item}" for item in suggestions)
    return "\n".join(lines)


def _render_directive(payload: dict[str, Any]) -> str:
    lines = [f"解析结果：{_status(payload.get('status'))}"]
    if payload.get("message"):
        lines.append(str(payload["message"]))
    if payload.get("actionable_text") is not None:
        lines.append(f"要处理的内容：{payload.get('actionable_text') or '查看 SOP 状态'}")
    lines.append(f"请求类型：{INTENT_LABELS.get(str(payload.get('intent')), payload.get('intent', '未知'))}")
    lines.append(f"风险：{RISK_LABELS.get(str(payload.get('risk')), payload.get('risk', '未知'))}")
    lines.append(f"作用范围：{SCOPE_LABELS.get(str(payload.get('scope')), payload.get('scope', '未知'))}")
    lines.append(f"需要明确批准：{_yes_no(payload.get('requires_explicit_approval'))}")
    for warning in payload.get("warnings") or []:
        lines.append(f"提醒：{warning}")
    return "\n".join(lines)


def _render_recipe_list(payload: dict[str, Any]) -> str:
    recipes = payload.get("recipes") or []
    lines = [f"SOP 配方清单（{len(recipes)} 项）"]
    validation = payload.get("validation") or {}
    lines.append(f"目录校验：{_status(validation.get('status', payload.get('status')))}")
    current_family: str | None = None
    for recipe in recipes:
        family = str(recipe.get("family") or "其他")
        if family != current_family:
            lines.append(f"\n[{FAMILY_LABELS.get(family, family)}]")
            current_family = family
        command = "sop " + " ".join(map(str, recipe.get("command") or []))
        risk = RISK_LABELS.get(str(recipe.get("risk")), str(recipe.get("risk")))
        scope = SCOPE_LABELS.get(str(recipe.get("scope")), str(recipe.get("scope")))
        lines.append(f"- {recipe.get('summary', recipe.get('id'))}")
        lines.append(f"  稳定命令：{command}｜风险：{risk}｜范围：{scope}")
    return "\n".join(lines)


def _render_usage(payload: dict[str, Any]) -> str:
    lines = ["SOP 使用情况", f"累计调用：{payload.get('total_calls', 0)} 次"]
    used = [item for item in payload.get("recipe_usage") or [] if int(item.get("calls", 0)) > 0]
    used.sort(key=lambda item: (-int(item.get("calls", 0)), str(item.get("action", ""))))
    if used:
        lines.append("\n使用过的配方：")
        for item in used:
            statuses = "、".join(
                f"{_status(name)} {count}" for name, count in (item.get("statuses") or {}).items()
            )
            lines.append(f"- {item.get('action')}：{item.get('calls', 0)} 次（{statuses or '无结果记录'}）")
    unused = payload.get("unused_recipes") or []
    if unused:
        lines.append("\n尚未使用：" + "、".join(map(str, unused)))
    lines.append("\n隐私：只保存聚合次数和结果状态，不保存请求正文、参数或路径。")
    return "\n".join(lines)


def _render_recipe_search(payload: dict[str, Any]) -> str:
    lines = [payload.get("message") or f"匹配结果：{_status(payload.get('status'))}"]
    selected = payload.get("selected")
    if isinstance(selected, dict):
        lines.append(f"选中配方：{selected.get('summary', selected.get('id'))}")
        lines.append("命令：sop " + " ".join(map(str, selected.get("command") or [])))
        lines.append(f"风险：{RISK_LABELS.get(str(selected.get('risk')), selected.get('risk'))}")
    candidates = payload.get("candidates") or []
    if candidates and not selected:
        lines.append("候选配方：")
        lines.extend(f"- {item.get('summary', item.get('id'))}" for item in candidates)
    lines.append("本次只做匹配，没有执行配方。")
    return "\n".join(lines)


def _render_profile_validation(payload: dict[str, Any]) -> str:
    profiles = payload.get("profiles") or []
    lines = [f"项目配置校验：{_status(payload.get('status'))}", f"已注册项目：{len(profiles)} 个"]
    for profile in profiles:
        lines.append(f"\n- {profile.get('display_name', profile.get('id'))}")
        lines.append(f"  生命周期：{profile.get('lifecycle', '未知')}")
        if profile.get("path_hints"):
            lines.append(f"  路径提示：{', '.join(map(str, profile['path_hints']))}")
        if profile.get("capabilities"):
            lines.append(f"  能力：{', '.join(map(str, profile['capabilities']))}")
    return "\n".join(lines)


def _render_capability_audit(payload: dict[str, Any]) -> str:
    lines = [f"项目能力盘点：{_status(payload.get('status'))}"]
    lines.extend(_project_lines(payload.get("project")))
    compatible = payload.get("compatible_recipes") or []
    unavailable = payload.get("unavailable_recipes") or []
    lines.append(f"可用配方：{len(compatible)} 个")
    lines.extend(f"- {item.get('id')}（{RISK_LABELS.get(str(item.get('risk')), item.get('risk'))}）" for item in compatible)
    if unavailable:
        lines.append(f"暂不可用：{len(unavailable)} 个")
        for item in unavailable:
            missing = "、".join(map(str, item.get("missing_capabilities") or []))
            lines.append(f"- {item.get('id')}：缺少 {missing}")
    gates = payload.get("external_gates") or []
    if gates:
        lines.append("仍需人工或真实运行验收：" + "、".join(GATE_LABELS.get(str(item), str(item)) for item in gates))
    return "\n".join(lines)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return _yes_no(value)
    if value is None:
        return "无"
    return str(value)


def _render_generic(payload: dict[str, Any]) -> str:
    lines: list[str] = []

    def visit(key: str, value: Any, indent: int = 0) -> None:
        if key == "schema":
            return
        label = FIELD_LABELS.get(key, key)
        prefix = "  " * indent
        if key == "status":
            lines.append(f"{prefix}{label}：{_status(value)}")
        elif key == "risk":
            lines.append(f"{prefix}{label}：{RISK_LABELS.get(str(value), value)}")
        elif key == "scope":
            lines.append(f"{prefix}{label}：{SCOPE_LABELS.get(str(value), value)}")
        elif key == "intent":
            lines.append(f"{prefix}{label}：{INTENT_LABELS.get(str(value), value)}")
        elif isinstance(value, dict):
            lines.append(f"{prefix}{label}：")
            for child_key, child_value in value.items():
                visit(str(child_key), child_value, indent + 1)
        elif isinstance(value, list):
            lines.append(f"{prefix}{label}：")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}-")
                    for child_key, child_value in item.items():
                        visit(str(child_key), child_value, indent + 1)
                else:
                    lines.append(f"{prefix}- {_scalar(item)}")
        else:
            lines.append(f"{prefix}{label}：{_scalar(value)}")

    for field, value in payload.items():
        visit(str(field), value)
    return "\n".join(lines)


def _render_invocation(payload: dict[str, Any]) -> str:
    invocation = payload.get("invocation")
    if not isinstance(invocation, dict):
        return ""
    risk = RISK_LABELS.get(str(invocation.get("risk")), str(invocation.get("risk", "未知")))
    status = _status(invocation.get("status"))
    if invocation.get("recorded"):
        counts = f"该能力累计 {invocation.get('action_calls')} 次｜SOP 总累计 {invocation.get('total_calls')} 次"
    else:
        counts = "调用统计写入失败，累计次数不可用"
    return f"调用记录｜{invocation.get('action')}｜风险：{risk}｜结果：{status}｜{counts}"


def render_human(payload: dict[str, Any]) -> str:
    schema = str(payload.get("schema") or "")
    if schema == "sop.status.v1":
        body = _render_status(payload)
    elif schema == "sop.directive.v1":
        body = _render_directive(payload)
    elif schema == "sop.recipe-registry.v1":
        body = _render_recipe_list(payload)
    elif schema == "sop.usage-report.v1":
        body = _render_usage(payload)
    elif schema == "sop.recipe-search.v1":
        body = _render_recipe_search(payload)
    elif schema == "sop.profile-validation.v1":
        body = _render_profile_validation(payload)
    elif schema == "sop.project-capability-audit.v1":
        body = _render_capability_audit(payload)
    else:
        body = _render_generic({key: value for key, value in payload.items() if key != "invocation"})
    invocation = _render_invocation(payload)
    return f"{body}\n\n{invocation}" if invocation else body
