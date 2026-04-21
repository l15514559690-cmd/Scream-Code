from __future__ import annotations

import os
from typing import ClassVar

from ..repl_slash_helpers import msg
from ..sandbox_env import SANDBOX_DOCKER_IMAGE_DEFAULT, SandboxManager
from ..scream_theme import ScreamTheme, skill_panel
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class SandboxSkill(BaseSkill):
    name: ClassVar[str] = 'sandbox'
    description: ClassVar[str] = '切换 Docker 沙箱：on / off / status（默认查看状态）'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        console = context.console
        mgr = SandboxManager.instance()
        raw = (args or '').strip()
        first = raw.split(None, 1)[0].lower() if raw else ''

        if first in ('', 'status'):
            return self._emit_status(console, mgr)
        if first == 'on':
            mgr.is_sandbox_enabled = True
            return self._emit_on(console)
        if first == 'off':
            mgr.is_sandbox_enabled = False
            return self._emit_off(console)
        self._emit_usage(console, first)
        return SkillOutcome()

    def _image_line(self) -> str:
        custom = os.environ.get('SCREAM_SANDBOX_IMAGE', '').strip()
        return custom if custom else SANDBOX_DOCKER_IMAGE_DEFAULT

    def _emit_on(self, console: object | None) -> SkillOutcome:
        img = self._image_line()
        body = (
            f'[bold yellow]🛡️ 沙箱模式已激活[/bold yellow]\n\n'
            f'[white]AI 终端指令（[cyan]execute_mac_bash[/cyan]）将被隔离在 '
            f'[bold]Docker[/bold] 容器中执行，工作区挂载为 [cyan]/workspace[/cyan]。[/white]\n\n'
            f'[dim red]警告：[/dim red][dim] 请确保本机已安装 Docker 且可拉取镜像 '
            f'[cyan]{img}[/cyan]；容器环境与宿主机不一致可能导致命令行为差异。[/dim]'
        )
        title = f'[{ScreamTheme.TEXT_INFO}]/sandbox · ON[/{ScreamTheme.TEXT_INFO}]'
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(body),
                    title=title,
                    variant='warning',
                )
            )
        else:
            print(
                '🛡️ 沙箱模式已激活：AI 终端指令将被隔离在 Docker 容器中执行 '
                f'（镜像: {img}）。警告：需已安装 Docker；容器环境与宿主机可能不同。'
            )
        return SkillOutcome()

    def _emit_off(self, console: object | None) -> SkillOutcome:
        body = (
            '[bold green]🔓 沙箱模式已关闭[/bold green]\n\n'
            '[white]终端命令恢复在[bold] 宿主机 [/bold]上通过 bash 执行（仍受工作区 / 越狱策略约束）。[/white]'
        )
        title = f'[{ScreamTheme.TEXT_INFO}]/sandbox · OFF[/{ScreamTheme.TEXT_INFO}]'
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(body),
                    title=title,
                    variant='success',
                )
            )
        else:
            print('🔓 沙箱模式已关闭：终端命令恢复在宿主机上执行。')
        return SkillOutcome()

    def _emit_status(self, console: object | None, mgr: SandboxManager) -> SkillOutcome:
        on = mgr.is_sandbox_enabled
        state = '[bold yellow]开启[/bold yellow]' if on else '[dim]关闭[/dim]'
        img = self._image_line()
        body = (
            f'当前沙箱：{state}\n\n'
            f'[dim]镜像（环境变量 SCREAM_SANDBOX_IMAGE 可覆盖）：[/dim][cyan]{img}[/cyan]'
        )
        title = f'[{ScreamTheme.TEXT_INFO}]/sandbox · STATUS[/{ScreamTheme.TEXT_INFO}]'
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(body),
                    title=title,
                    variant='info',
                )
            )
        else:
            st = '开启' if on else '关闭'
            print(f'沙箱状态: {st} | 镜像: {img}')
        return SkillOutcome()

    def _emit_usage(self, console: object | None, bad: str) -> None:
        hint = (
            f'未知子命令 [yellow]{bad}[/yellow]。用法：'
            '[bold]/sandbox[/bold]、[bold]/sandbox status[/bold]、'
            '[bold]/sandbox on[/bold]、[bold]/sandbox off[/bold]'
        )
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(hint),
                    title=f'[{ScreamTheme.TEXT_WARNING}]/sandbox · 用法[/{ScreamTheme.TEXT_WARNING}]',
                    variant='warning',
                )
            )
        else:
            msg(console, f'未知子命令 {bad!r}。用法: /sandbox | status | on | off', style='yellow')
