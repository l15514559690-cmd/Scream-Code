"""
Scream-Code Rich 视觉规范：斜杠指令与技能输出统一边框、语义色与自适应宽度。

- 外层面板：统一 ``box.ROUNDED`` + 语义色描边。
- 成功 ``green``、警告 ``yellow``、错误 ``red``、系统/信息 ``cyan`` / ``blue``（accent）。
"""

from __future__ import annotations

from typing import Any, Literal

from rich import box

Variant = Literal['info', 'success', 'warning', 'error', 'accent', 'neutral']


class ScreamTheme:
    """Panel / Table 的边框与文字语义（Rich 样式名）。"""

    BOX = box.ROUNDED
    #: 嵌套在 Panel 内的紧凑表（如 /help 行表），减少双边框视觉噪音
    BOX_COMPACT = box.SIMPLE

    BORDER_INFO = 'cyan'
    BORDER_SUCCESS = 'green'
    BORDER_WARNING = 'yellow'
    BORDER_ERROR = 'red'
    BORDER_ACCENT = 'blue'
    BORDER_NEUTRAL = 'bright_black'

    TEXT_SUCCESS = 'bold green'
    TEXT_WARNING = 'bold yellow'
    TEXT_ERROR = 'bold red'
    TEXT_INFO = 'bold cyan'
    TEXT_ACCENT = 'bold blue'
    TEXT_MUTED = 'dim'
    TEXT_BODY = 'white'

    TABLE_HEADER = 'bold cyan'
    TABLE_COL_CMD = 'bold green'
    TABLE_COL_DESC = 'dim'
    TABLE_COL_KEY = 'cyan'
    TABLE_COL_VAL = 'white'

    _BORDER_MAP: dict[Variant, str] = {
        'info': BORDER_INFO,
        'success': BORDER_SUCCESS,
        'warning': BORDER_WARNING,
        'error': BORDER_ERROR,
        'accent': BORDER_ACCENT,
        'neutral': BORDER_NEUTRAL,
    }

    @classmethod
    def border(cls, variant: Variant) -> str:
        return cls._BORDER_MAP.get(variant, cls.BORDER_INFO)


def skill_panel(
    renderable: Any,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    variant: Variant = 'info',
    padding: tuple[int, int] = (1, 2),
    expand: bool = True,
) -> Any:
    """
    标准斜杠/技能 ``Panel``：圆角 + 语义色边框 + 默认占满终端宽度以便重排时换行。
    """
    from rich.panel import Panel

    return Panel(
        renderable,
        title=title,
        subtitle=subtitle,
        border_style=ScreamTheme.border(variant),
        box=ScreamTheme.BOX,
        expand=expand,
        padding=padding,
    )


def nested_skill_panel(
    renderable: Any,
    *,
    title: str | None = None,
    variant: Variant = 'neutral',
    padding: tuple[int, int] = (0, 1),
    expand: bool = True,
) -> Any:
    """外层 ``skill_panel`` 内的子块（略紧凑）。"""
    from rich.panel import Panel

    return Panel(
        renderable,
        title=title,
        border_style=ScreamTheme.border(variant),
        box=ScreamTheme.BOX,
        expand=expand,
        padding=padding,
    )
