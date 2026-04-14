from __future__ import annotations

import copy
import json
from typing import Any

from .llm_settings import LlmConnectionSettings

MAX_HISTORY_MSGS = 15
"""除 ``role=system`` 外，超过此条数则尝试触发上下文折叠。"""

_DEFAULT_MIN_TAIL = 6
"""动态尾部至少保留的消息条数（在 API 安全前提下可拉长）。"""

_SUMMARY_USER_HEADER = (
    '请将以下历史对话提取成极度凝练的纯文本摘要（必须丢弃所有客套话、尝试和失败的错误日志）：'
)

_SUMMARY_SYSTEM = (
    '你是一个极其严苛的「上下文压缩引擎」。你的唯一任务是对极长的历史对话进行「有损压缩」。\n'
    '绝对禁止原样摘抄代码块或流水账日志！不要输出任何前言或后语。\n'
    '你必须将所有内容浓缩为不到 300 字的极简要点，只保留：1. 当前核心目标 2. 已解决的关键 Bug 3. 确定的架构与方案结论。'
)


def _non_system_message_count(messages: list[dict[str, Any]]) -> int:
    return sum(
        1
        for m in messages
        if (str(m.get('role') or '').strip().lower() != 'system')
    )


def should_compress_messages(messages: list[dict[str, Any]]) -> bool:
    """与 :func:`compress_history` 相同的触发条件（非 system 条数）。"""
    return _non_system_message_count(messages) > MAX_HISTORY_MSGS


def _role(m: dict[str, Any]) -> str:
    return str(m.get('role') or '').strip().lower()


def _suffix_coherent_for_openai(work: list[dict[str, Any]], start: int) -> bool:
    """
    判断 ``work[start:]`` 是否可作为合法后缀发往 OpenAI：

    - 不得以孤立的 ``tool`` 开头；
    - 每个带 ``tool_calls`` 的 ``assistant`` 后必须紧跟足够的 ``tool`` 回复（按 id 覆盖）。
    """
    n = len(work)
    if start < 0 or start > n:
        return False
    if start == n:
        return True
    if _role(work[start]) == 'tool':
        return False
    idx = start
    while idx < n:
        role = _role(work[idx])
        if role == 'assistant':
            tcs = work[idx].get('tool_calls')
            if tcs:
                ids = {
                    str(tc.get('id') or '')
                    for tc in tcs
                    if isinstance(tc, dict)
                }
                ids.discard('')
                idx += 1
                got: set[str] = set()
                while idx < n and _role(work[idx]) == 'tool':
                    got.add(str(work[idx].get('tool_call_id') or ''))
                    idx += 1
                if ids and not ids.issubset(got):
                    return False
                continue
            idx += 1
            continue
        if role == 'tool':
            return False
        idx += 1
    return True


def _find_safe_tail_index(work: list[dict[str, Any]], min_tail: int = _DEFAULT_MIN_TAIL) -> int | None:
    """
    在 ``work`` 内找切分下标 ``split``，使 ``work[split:]`` 为保留尾部，且：

    - ``len(work) - split >= min_tail``（在可调整范围内尽量满足）；
    - 尾部满足 :func:`_suffix_coherent_for_openai`；
    - 在仍满足上述约束时，尽量让 ``work[split]`` 为 ``user``（切断在完整回合前）。
    """
    n = len(work)
    if n < min_tail + 1:
        return None

    i = max(0, n - min_tail)
    while i > 0 and not _suffix_coherent_for_openai(work, i):
        i -= 1
    if not _suffix_coherent_for_openai(work, i):
        return None

    while (
        i > 0
        and _role(work[i - 1]) == 'user'
        and (n - (i - 1)) >= min_tail
        and _suffix_coherent_for_openai(work, i - 1)
    ):
        i -= 1

    if _role(work[i]) != 'user':
        for j in range(i - 1, -1, -1):
            if (
                _role(work[j]) == 'user'
                and (n - j) >= min_tail
                and _suffix_coherent_for_openai(work, j)
            ):
                i = j
                break

    return i


def _serialize_messages_block(chunk: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for idx, m in enumerate(chunk, start=1):
        role = (str(m.get('role') or '')).strip() or 'unknown'
        raw = m.get('content')
        if raw is None:
            body = ''
        elif isinstance(raw, (dict, list)):
            body = json.dumps(raw, ensure_ascii=False)
        else:
            body = str(raw)
        # 对长文本进行物理截断，防止总结引擎被撑爆
        if len(body) > 1500:
            body = body[:1500] + f"\n\n...[内容过长已由系统截断，原长 {len(body)} 字符]..."
        if role == 'assistant' and m.get('tool_calls'):
            try:
                body = f'{body}\n[tool_calls]\n{json.dumps(m.get("tool_calls"), ensure_ascii=False)}'
            except (TypeError, ValueError):
                body = f'{body}\n[tool_calls present]'
        if role == 'tool':
            tid = str(m.get('tool_call_id') or '')
            body = f'(tool_call_id={tid})\n{body}'
        parts.append(f'--- 消息 {idx} | {role} ---\n{body}')
    return '\n\n'.join(parts)


def _run_summary_completion(
    serialized_history: str,
    llm_client: LlmConnectionSettings,
    *,
    model: str | None,
) -> str:
    from .llm_client import iter_agent_executor_events

    pack = [
        {'role': 'system', 'content': _SUMMARY_SYSTEM},
        {
            'role': 'user',
            'content': f'{_SUMMARY_USER_HEADER}\n\n{serialized_history}',
        },
    ]
    for ev in iter_agent_executor_events(
        pack,
        llm_client,
        model=model,
        tools=[],
    ):
        if ev.get('type') == 'executor_complete':
            return str(ev.get('assistant_text') or '').strip()
        if ev.get('type') == 'llm_error':
            return ''
    return ''


def compress_history(
    messages: list[dict[str, Any]],
    llm_client: LlmConnectionSettings,
    *,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """
    折叠中间历史：保留（若存在）首条 ``system``、摘要 ``system``、以及 API 安全的动态尾部。

    ``llm_client`` 为 :class:`LlmConnectionSettings`。摘要调用同步阻塞；任意失败返回原始深拷贝，
    不抛异常。
    """
    if not messages:
        return []
    snapshot = copy.deepcopy(messages)
    try:
        if not should_compress_messages(messages):
            return snapshot

        lead_is_system = _role(messages[0]) == 'system'
        prefix: list[dict[str, Any]] = [copy.deepcopy(messages[0])] if lead_is_system else []
        work = messages[1:] if lead_is_system else list(messages)

        split = _find_safe_tail_index(work, min_tail=_DEFAULT_MIN_TAIL)
        if split is None or split < 1:
            return snapshot

        middle = work[:split]
        tail = work[split:]
        if not middle:
            return snapshot

        serialized = _serialize_messages_block(middle)
        summary_text = _run_summary_completion(serialized, llm_client, model=model)
        if not summary_text:
            return snapshot

        memory_msg: dict[str, Any] = {
            'role': 'system',
            'content': '【历史记忆摘要】\n' + summary_text,
        }
        tail_copy = copy.deepcopy(tail)
        if prefix:
            return [prefix[0], memory_msg, *tail_copy]
        return [memory_msg, *tail_copy]
    except Exception:
        return snapshot
