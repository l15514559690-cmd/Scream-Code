from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar

from ..repl_slash_helpers import msg
from ..scream_theme import ScreamTheme, nested_skill_panel, skill_panel
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class DiffSkill(BaseSkill):
    """``git status --short`` + ``git diff --stat``，Rich 渲染；与旧版 REPL 行为一致。"""

    name: ClassVar[str] = 'diff'
    description: ClassVar[str] = 'Git 工作区改动 (git diff --stat)'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from rich.syntax import Syntax

        console = context.console
        root = Path.cwd()
        try:
            st = subprocess.run(
                ['git', 'status', '--short'],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            full_diff = subprocess.run(
                ['git', 'diff', '--stat'],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg(console, f'git 调用失败: {exc}', style='red')
            return SkillOutcome()

        if st.returncode != 0 and st.stderr:
            msg(console, st.stderr.strip(), style='yellow')
        if full_diff.returncode != 0 and full_diff.stderr:
            msg(console, full_diff.stderr.strip(), style='yellow')

        out_status = (st.stdout or '').strip()
        stat_lines = (full_diff.stdout or '').strip()

        stat_body: Any
        if stat_lines:
            stat_body = Syntax(
                stat_lines[:200_000],
                lexer='diff',
                theme='monokai',
                background_color='#09090B',
                word_wrap=True,
            )
        else:
            from rich.text import Text

            stat_body = Text('（无 diff — 工作区干净）', style='dim')

        panels: list[Any] = []
        if out_status:
            status_body = Syntax(
                out_status[:200_000],
                lexer='bash',
                theme='monokai',
                background_color='#09090B',
                word_wrap=True,
            )
            panels.append(
                nested_skill_panel(
                    status_body,
                    title=f'[{ScreamTheme.TEXT_MUTED}]git status --short[/{ScreamTheme.TEXT_MUTED}]',
                    variant='neutral',
                )
            )
        panels.append(
            nested_skill_panel(
                stat_body,
                title=f'[{ScreamTheme.TEXT_INFO}]git diff --stat[/{ScreamTheme.TEXT_INFO}]',
                variant='info',
            )
        )

        if console is not None:
            from rich.console import Group

            console.print(
                skill_panel(
                    Group(*panels),
                    title=f'[{ScreamTheme.TEXT_INFO}]/diff · 工作区[/{ScreamTheme.TEXT_INFO}]',
                    variant='info',
                )
            )
        else:
            for p in panels:
                print(p)

        return SkillOutcome()
