from __future__ import annotations

from typing import ClassVar

from ..repl_slash_helpers import msg
from ..scream_theme import ScreamTheme, skill_panel
from ..services.feishu_manager import FeishuManager
from ..session_store import purge_feishu_channel_artifacts
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class FeishuSkill(BaseSkill):
    name: ClassVar[str] = 'feishu'
    description: ClassVar[str] = '🚀 飞书侧车 (config/start/stop/delete/status/log)'
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
                outcome = mgr.start()
                if context.console is not None:
                    from rich.panel import Panel
                    from rich.text import Text

                    if outcome == 'already_running':
                        context.console.print(
                            Panel(
                                Text(
                                    '飞书侧车已在运行中，无需重复拉起。',
                                    style='bold #a1a1aa',
                                ),
                                title='[dim]Feishu · 已在线[/dim]',
                                border_style='#52525b',
                                style='on #09090b',
                            )
                        )
                    else:
                        context.console.print(
                            Panel(
                                Text(
                                    '🚀 飞书独立子通道已成功唤醒驻留后台',
                                    style='bold #22c55e',
                                ),
                                subtitle=f'[dim]{mgr.status()}[/dim]',
                                border_style='#22c55e',
                                style='on #0c0c0f',
                            )
                        )
                else:
                    print('🚀 飞书独立子通道已成功唤醒驻留后台' if outcome == 'started' else '侧车已在运行')
                return SkillOutcome()
            if cmd == 'stop':
                mgr.stop()
                if context.console is not None:
                    from rich.panel import Panel
                    from rich.text import Text

                    context.console.print(
                        Panel(
                            Text(
                                '🛑 飞书通道已关闭并切断连接',
                                style='bold #f59e0b',
                            ),
                            border_style='#f59e0b',
                            style='on #0c0c0f',
                        )
                    )
                else:
                    print('🛑 飞书通道已关闭并切断连接')
                return SkillOutcome()
            if cmd in ('delete', 'clear'):
                if mgr.is_sidecar_running():
                    msg(
                        context.console,
                        '⚠️ 侧车进程仍在运行中，建议先执行 `/feishu stop` 以确保缓存彻底清理。',
                        style='yellow',
                    )
                report = purge_feishu_channel_artifacts()
                err_n = len(report.get('errors') or ())
                if context.console is not None:
                    from rich.panel import Panel
                    from rich.text import Text

                    markup = (
                        '[bold #a78bfa]🗑️ 飞书子通道的所有记忆与物理缓存附件已彻底销毁！'
                        '通道恢复为出厂状态。[/bold #a78bfa]'
                    )
                    if err_n:
                        markup += (
                            f'\n\n[dim yellow]部分路径清理时出现 {err_n} 条警告（可稍后重试）[/dim yellow]'
                        )
                    context.console.print(
                        Panel(
                            Text.from_markup(markup),
                            title='[bold #7c3aed]Feishu · Purge[/bold #7c3aed]',
                            subtitle=f'[dim]已删会话文件: {report.get("removed_feishu_session_files", 0)}[/dim]',
                            border_style='#6366f1',
                            style='on #09090b',
                        )
                    )
                else:
                    print('🗑️ 飞书子通道的所有记忆与物理缓存附件已彻底销毁！通道恢复为出厂状态。')
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
            t.add_row('/feishu start', '后台启动侧车（已运行则跳过）')
            t.add_row('/feishu stop', '终止侧车并切断连接')
            t.add_row('/feishu delete 或 /feishu clear', '删除所有 feishu_*.json 会话并清空 inbox/outbox 缓存')
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
            '/feishu delete | /feishu clear\n'
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
