"""
发往 LLM 前的历史消息内存修剪：滑动窗口 + 长 tool 输出折叠，不修改落盘与会话内完整快照。

尖叫 Code 产品参数（勿用上游 claw-code Python stub 的保守默认覆盖本模块常量）：

- 与 ``QueryEngineConfig.max_turns``（默认 400）及 ``max_budget_tokens``（默认 12_000_000，不低于 8_000_000
  的长上下文底线）配套；折叠只减轻中间段**极长** tool 文本，触顶仍由引擎 token 预算与模型窗口兜底。
- ``_TAIL_PRESERVE_COUNT`` / ``_TOOL_FOLD_THRESHOLD_CHARS`` 等为刻意放宽的熔断阈值，合并上游时须保留。
"""

from __future__ import annotations

import copy
import json
from typing import Any

# 仅压缩「中间段」里超过此长度的 tool 内容（字符数按统一文本化后计量；提高阈值以减少误折叠）
_TOOL_FOLD_THRESHOLD_CHARS = 32_000
# 折叠后展示的前缀长度
_TOOL_FOLD_PREVIEW_CHARS = 2400
# 尾部原样保留的消息条数（不含头部 system 段）
_TAIL_PRESERVE_COUNT = 256


def _content_as_text(content: Any) -> str:
    """将 message content 转为用于测长与截断预览的纯文本（类型安全）。"""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def _message_content_len(msg: dict[str, Any]) -> int:
    return len(_content_as_text(msg.get('content')))


def _fold_tool_content(msg: dict[str, Any]) -> dict[str, Any]:
    """返回新 dict：tool 的 content 替换为折叠说明（不修改入参）。"""
    out = copy.deepcopy(msg)
    raw = _content_as_text(out.get('content'))
    prefix = raw[:_TOOL_FOLD_PREVIEW_CHARS]
    out['content'] = (
        f'[历史执行输出过长已折叠，前 {_TOOL_FOLD_PREVIEW_CHARS} 字符: {prefix}...]'
    )
    return out


def prune_historical_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    对即将发往模型的消息列表做**内存副本**修剪：

    - 头部：从索引 0 起连续 ``role == 'system'`` 的消息原样保留；
    - 尾部：紧接在头部之后的子数组中，**最后** ``_TAIL_PRESERVE_COUNT``（默认 256）条原样保留；
    - 中间：其余消息里，若 ``role == 'tool'`` 且内容文本化后长度超过阈值，则折叠为短前缀说明。

    若中间段为空（总消息过少），则返回深拷贝后的原列表（无折叠）。
    """
    if not messages:
        return []

    out = copy.deepcopy(messages)

    head_len = 0
    for m in out:
        if (m.get('role') or '').strip().lower() == 'system':
            head_len += 1
        else:
            break

    body = out[head_len:]
    if len(body) <= _TAIL_PRESERVE_COUNT:
        return out

    middle_end = len(out) - _TAIL_PRESERVE_COUNT
    for i in range(head_len, middle_end):
        m = out[i]
        if (m.get('role') or '').strip().lower() != 'tool':
            continue
        if _message_content_len(m) <= _TOOL_FOLD_THRESHOLD_CHARS:
            continue
        folded = _fold_tool_content(m)
        out[i] = folded

    return out
