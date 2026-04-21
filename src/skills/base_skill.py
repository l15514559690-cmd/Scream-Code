from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..query_engine import QueryEnginePort

SLASH_CATEGORY_ORDER = ('core', 'memory', 'vision', 'system')
SLASH_CATEGORY_TITLE = {
    'core': '核心功能 (Core)',
    'memory': '上下文与记忆 (Memory)',
    'vision': '视觉 / 浏览器 (Vision)',
    'system': '系统与扩展 (System)',
}


@dataclass(frozen=True)
class ReplSkillContext:
    """REPL 斜杠技能执行期上下文。"""

    console: Any | None
    engine: QueryEnginePort


@dataclass(frozen=True)
class SkillOutcome:
    """斜杠技能执行结果；可追加 LLM 消息并触发紧随其后的模型回合（如 ``/look``）。"""

    new_engine: QueryEnginePort | None = None
    append_llm_messages: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    trigger_llm_followup: bool = False
    followup_prompt: str = ''


class BaseSkill(ABC):
    """内置或用户自定义 REPL 斜杠技能；与 LLM ``ToolsRegistry`` 无耦合。"""

    name: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[str] = 'system'
    aliases: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        raise NotImplementedError
