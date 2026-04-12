from __future__ import annotations

import copy
from typing import Any

from .query_engine import QueryEnginePort
from .repl_slash_helpers import msg
from .skills.base_skill import ReplSkillContext, SkillOutcome
from .skills_registry import get_skills_registry


def dispatch_repl_slash_command(
    line: str,
    *,
    console: Any | None,
    engine: QueryEnginePort,
) -> tuple[bool, QueryEnginePort | None, SkillOutcome | None]:
    """
    已注册斜杠技能由 ``SkillsRegistry`` 动态路由；未知 ``/`` 指令拦截以免误送模型。

    第三项：未命中斜杠时为 ``None``；命中时为 ``SkillOutcome``（可能含 ``append_llm_messages`` 等）。
    """
    raw = (line or '').strip()
    if not raw.startswith('/'):
        return False, None, None

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ''
    key = cmd[1:] if len(cmd) > 1 else ''

    reg = get_skills_registry()
    skill = reg.get(key)
    if skill is None:
        msg(
            console,
            f'未知斜杠指令 {cmd!r}。输入 /help 查看原生桥接命令。',
            style='yellow',
        )
        return True, None, SkillOutcome()

    ctx = ReplSkillContext(console=console, engine=engine)
    outcome = skill.execute(ctx, rest)
    target = outcome.new_engine if outcome.new_engine is not None else engine
    if outcome.append_llm_messages:
        target.llm_conversation_messages.extend(
            copy.deepcopy(m) for m in outcome.append_llm_messages
        )
    return True, outcome.new_engine, outcome
