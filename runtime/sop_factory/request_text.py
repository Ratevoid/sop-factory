from __future__ import annotations

from dataclasses import dataclass


REFERENCE_MARKERS = (
    "下面是我的对话记录",
    "下面是对话记录",
    "以下是我的对话记录",
    "以下是对话记录",
    "下面是聊天记录",
    "以下是聊天记录",
    "下面是日志",
    "以下是日志",
    "日志如下",
    "引用如下",
    "原文如下",
    "示例如下",
    "conversation follows",
    "transcript follows",
    "log follows",
    "example follows",
)


@dataclass(frozen=True)
class RequestText:
    original: str
    actionable: str
    reference: str


def _marker_index(line: str) -> int | None:
    lowered = line.casefold()
    positions = [lowered.find(marker.casefold()) for marker in REFERENCE_MARKERS]
    found = [position for position in positions if position >= 0]
    return min(found) if found else None


def split_request_text(text: str) -> RequestText:
    actionable: list[str] = []
    reference: list[str] = []
    in_fence = False
    reference_tail = False

    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if reference_tail:
            reference.append(line)
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            reference.append(line)
            continue
        if in_fence or stripped.startswith(">"):
            reference.append(line)
            continue
        marker_at = _marker_index(line)
        if marker_at is not None:
            actionable.append(line[:marker_at])
            reference.append(line[marker_at:])
            reference_tail = True
            continue
        actionable.append(line)

    return RequestText(
        original=text,
        actionable="".join(actionable).strip(),
        reference="".join(reference).strip(),
    )
