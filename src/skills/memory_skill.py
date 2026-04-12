from __future__ import annotations

from typing import ClassVar

from ..memory_store import forget_core_rule, list_core_rules, memorize_core_rule, memory_db_path
from ..repl_slash_helpers import msg
from ..scream_theme import ScreamTheme, Variant, skill_panel
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class MemorySkill(BaseSkill):
    name: ClassVar[str] = 'memory'
    description: ClassVar[str] = 'SQLite 长期记忆：list · set <key> <content> · drop <key>'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        raw = (args or '').strip()
        if not raw:
            return self._list(context.console)
        head, _, tail = raw.partition(' ')
        sub = head.strip().lower()
        rest = tail.strip()
        if sub == 'list':
            return self._list(context.console)
        if sub == 'set':
            return self._set(context.console, rest)
        if sub == 'drop':
            return self._drop(context.console, rest)
        self._unknown(context.console, head)
        return SkillOutcome()

    def _list(self, console: object | None) -> SkillOutcome:
        rows = list_core_rules()
        db = memory_db_path()
        if console is not None:
            from rich.table import Table

            t = Table(
                title='[bold cyan]◆ NEURAL_BUFFER · core_memory[/bold cyan]',
                caption=f'[dim]sink: {db}  ·  {len(rows)} slot(s)[/dim]',
                box=ScreamTheme.BOX,
                show_header=True,
                header_style=ScreamTheme.TABLE_HEADER,
                border_style=ScreamTheme.border('info'),
                expand=True,
                show_lines=True,
            )
            t.add_column('key_name', style=ScreamTheme.TABLE_COL_CMD, no_wrap=True, overflow='fold', max_width=30)
            t.add_column('content', style=ScreamTheme.TABLE_COL_VAL, ratio=1, overflow='fold')
            t.add_column('updated_at', style=ScreamTheme.TEXT_MUTED, no_wrap=True, max_width=28, overflow='ellipsis')
            if not rows:
                t.add_row(
                    '[dim]— empty —[/dim]',
                    '[dim]尚无持久化规则；使用 /memory set 或工具 memorize_project_rule[/dim]',
                    '—',
                )
            else:
                for r in rows:
                    t.add_row(r['key_name'], r['content'], r['updated_at'])
            console.print(
                skill_panel(
                    t,
                    title=f'[{ScreamTheme.TEXT_ACCENT}]/memory · LONG-TERM[/{ScreamTheme.TEXT_ACCENT}]',
                    subtitle=f'[{ScreamTheme.TEXT_MUTED}]injected into system prompt as XML[/{ScreamTheme.TEXT_MUTED}]',
                    variant='accent',
                )
            )
        else:
            print(f'— core_memory @ {db} — ({len(rows)} 条)')
            for r in rows:
                print(f"{r['key_name']}\t{r['updated_at']}\n  {r['content']}\n")
        return SkillOutcome()

    def _set(self, console: object | None, rest: str) -> SkillOutcome:
        parts = rest.split(None, 1)
        if len(parts) < 2:
            msg(
                console,
                '用法: /memory set <key_name> <content…>（content 可含空格）',
                style='yellow',
            )
            return SkillOutcome()
        key, content = parts[0], parts[1]
        result = memorize_core_rule(key, content)
        ok = result.startswith('已记入')
        if console is not None:
            from rich.text import Text

            st = ScreamTheme.TEXT_SUCCESS if ok else ScreamTheme.TEXT_ERROR
            write_var: Variant = 'success' if ok else 'error'
            console.print(
                skill_panel(
                    Text.from_markup(f'[{st}]{result}[/{st}]'),
                    title=f'[{ScreamTheme.TEXT_INFO}]/memory · WRITE[/{ScreamTheme.TEXT_INFO}]',
                    variant=write_var,
                )
            )
        else:
            print(result)
        return SkillOutcome()

    def _drop(self, console: object | None, rest: str) -> SkillOutcome:
        key = rest.strip()
        if not key:
            msg(console, '用法: /memory drop <key_name>', style='yellow')
            return SkillOutcome()
        result = forget_core_rule(key)
        ok = result.startswith('已从长期记忆库删除')
        if console is not None:
            from rich.text import Text

            st = ScreamTheme.TEXT_SUCCESS if ok else ScreamTheme.TEXT_WARNING
            purge_var: Variant = 'success' if ok else 'warning'
            console.print(
                skill_panel(
                    Text.from_markup(f'[{st}]{result}[/{st}]'),
                    title=f'[{ScreamTheme.TEXT_INFO}]/memory · PURGE[/{ScreamTheme.TEXT_INFO}]',
                    variant=purge_var,
                )
            )
        else:
            print(result)
        return SkillOutcome()

    def _unknown(self, console: object | None, token: str) -> None:
        hint = (
            f'未知子命令 [yellow]{token}[/yellow]。'
            '[dim]list | set <key> <content> | drop <key>[/dim]'
        )
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(hint),
                    title=f'[{ScreamTheme.TEXT_WARNING}]/memory · 用法[/{ScreamTheme.TEXT_WARNING}]',
                    variant='warning',
                )
            )
        else:
            msg(console, f'未知子命令 {token!r}。用法: list | set | drop', style='yellow')
