from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar

from ..repl_slash_helpers import msg
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class DiffSkill(BaseSkill):
    """``git status --short`` + ``git diff --stat``，Rich 渲染；与旧版 REPL 行为一致。"""

    name: ClassVar[str] = 'diff'
    description: ClassVar[str] = 'Git 工作区改动 (git diff --stat)'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from rich import box
        from rich.panel import Panel
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
                Panel(
                    status_body,
                    title='git status --short',
                    border_style='dim',
                    box=box.ROUNDED,
                    padding=(0, 1),
                    expand=True,
                )
            )
        panels.append(
            Panel(
                stat_body,
                title='git diff --stat',
                border_style='cyan',
                box=box.ROUNDED,
                padding=(0, 1),
                expand=True,
            )
        )

        if console is not None:
            from rich.console import Group

            console.print(
                Panel(
                    Group(*panels),
                    title='[bold cyan]/diff · 工作区[/bold cyan]',
                    border_style='cyan',
                    box=box.ROUNDED,
                    expand=True,
                )
            )
        else:
            for p in panels:
                print(p)

        return SkillOutcome()
