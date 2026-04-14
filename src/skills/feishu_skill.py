from __future__ import annotations

from typing import ClassVar

from ..repl_slash_helpers import msg
from ..scream_theme import ScreamTheme, skill_panel
from ..services.feishu_manager import FeishuManager
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class FeishuSkill(BaseSkill):
    name: ClassVar[str] = 'feishu'
    description: ClassVar[str] = '🚀 飞书长连接侧车控制台 (config/start/stop/status/log)'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        mgr = FeishuManager()
        raw = (args or '').strip()
        if not raw or raw.lower() == 'help':
            self._print_help(context)
            return SkillOutcome()

        parts = raw.split()
        cmd = parts[0].lower()
        try:
            if cmd == 'config':
                if len(parts) < 3:
                    msg(context.console, '用法: /feishu config <AppID> <AppSecret>', style='yellow')
                    return SkillOutcome()
                mgr.config(parts[1], parts[2])
                msg(context.console, '✅ 飞书凭据已保存至 .env', style='bold green')
                return SkillOutcome()
            if cmd == 'start':
                mgr.start()
                msg(context.console, f'✅ 飞书侧车启动成功，{mgr.status()}', style='bold green')
                return SkillOutcome()
            if cmd == 'stop':
                mgr.stop()
                msg(context.console, '🛑 飞书侧车已停止', style='bold yellow')
                return SkillOutcome()
            if cmd == 'status':
                msg(context.console, mgr.status(), style='bold cyan')
                return SkillOutcome()
            if cmd == 'log':
                logs = mgr.tail_log()
                self._print_log_panel(context, logs)
                return SkillOutcome()
            msg(context.console, f'未知子命令: {cmd}', style='bold red')
            self._print_help(context)
            return SkillOutcome()
        except Exception as exc:
            msg(context.console, f'/feishu 执行失败: {exc}', style='bold red')
            return SkillOutcome()

    def _print_help(self, context: ReplSkillContext) -> None:
        if context.console is not None:
            from rich.table import Table

            t = Table(show_lines=True, expand=True, box=ScreamTheme.BOX_COMPACT)
            t.add_column('子命令', style=ScreamTheme.TABLE_COL_CMD, no_wrap=True, overflow='fold')
            t.add_column('说明', style=ScreamTheme.TABLE_COL_DESC, overflow='fold')
            t.add_row('/feishu config <AppID> <AppSecret>', '写入/更新飞书凭据到项目 .env 并同步环境变量')
            t.add_row('/feishu start', '后台启动 bots/feishu_ws_bot.py 侧车进程')
            t.add_row('/feishu stop', '安全终止侧车进程')
            t.add_row('/feishu status', '查看当前进程状态')
            t.add_row('/feishu log', '查看侧车后台运行日志')
            context.console.print(
                skill_panel(
                    t,
                    title=f'[{ScreamTheme.TEXT_ACCENT}]/feishu · 侧车控制台[/{ScreamTheme.TEXT_ACCENT}]',
                    variant='accent',
                )
            )
            return
        msg(
            context.console,
            '用法:\n'
            '/feishu config <AppID> <AppSecret>\n'
            '/feishu start\n'
            '/feishu stop\n'
            '/feishu status\n'
            '/feishu log',
            style='dim',
        )

    def _print_log_panel(self, context: ReplSkillContext, logs: str) -> None:
        if context.console is not None:
            from rich.markdown import Markdown

            body = logs.strip() or '（空）'
            md = Markdown(f'```text\n{body}\n```')
            context.console.print(
                skill_panel(
                    md,
                    title=f'[{ScreamTheme.TEXT_ACCENT}]📄 飞书侧车最近日志[/{ScreamTheme.TEXT_ACCENT}]',
                    variant='info',
                )
            )
            return
        print(logs or '暂无日志文件')
