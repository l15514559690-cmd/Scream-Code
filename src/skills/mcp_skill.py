from __future__ import annotations

from typing import ClassVar

from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class MCPSkill(BaseSkill):
    name: ClassVar[str] = 'mcp'
    description: ClassVar[str] = 'MCP 状态/重启/工具；/mcp browser 切换浏览器MCP模式 ON/OFF'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        parts = (args or '').strip().split(None, 1)
        sub = parts[0].lower() if parts else 'status'
        if sub in ('status', 'stat'):
            self._print_status(context)
            return SkillOutcome()
        if sub in ('restart', 'rs'):
            self._restart(context)
            return SkillOutcome()
        if sub in ('tools', 'list'):
            self._print_tools(context)
            return SkillOutcome()
        if sub in ('browser', 'web', 'online'):
            self._toggle_web_mode(context)
            return SkillOutcome()
        self._print_usage(context)
        return SkillOutcome()

    @staticmethod
    def _print_usage(context: ReplSkillContext) -> None:
        msg = '用法: /mcp status | /mcp restart | /mcp tools | /mcp browser'
        if context.console is not None:
            context.console.print(f'[yellow]{msg}[/yellow]')
        else:
            print(msg)

    @staticmethod
    def _print_status(context: ReplSkillContext) -> None:
        snap = context.engine.mcp_status_snapshot()
        running = bool(snap.get('running'))
        indicator = '🟢 RUNNING' if running else '🔴 STOPPED'
        tools_n = int(snap.get('tools_count') or 0)
        cmd = str(snap.get('command') or '').strip() or '(未配置 MCP_SERVER_COMMAND)'
        enabled = '是' if snap.get('enabled') else '否'
        browser_mode = '🌐 ON' if snap.get('web_mode') else 'OFF'
        lifecycle = str(snap.get('status') or 'idle')
        if context.console is None:
            print(
                f'[MCP] 状态={indicator} | 生命周期={lifecycle} | 启用={enabled} | 浏览器MCP模式={browser_mode} | '
                f'工具数={tools_n} | 命令={cmd}'
            )
            if lifecycle == 'error':
                mcp = context.engine.get_mcp_client()
                logs = []
                if mcp is not None and hasattr(mcp, 'get_recent_errors'):
                    try:
                        logs = list(mcp.get_recent_errors())
                    except Exception:
                        logs = []
                if logs:
                    print('[💥 最近错误日志 (stderr)]')
                    for row in logs:
                        print(f'  {row}')
            return
        from rich.panel import Panel
        from rich.table import Table

        tb = Table.grid(padding=(0, 2))
        tb.add_column(style='bold cyan', no_wrap=True)
        tb.add_column(style='white')
        tb.add_row('运行状态', indicator)
        tb.add_row('生命周期', lifecycle)
        tb.add_row('已启用', enabled)
        tb.add_row('浏览器MCP模式', browser_mode)
        tb.add_row('挂载工具', f'{tools_n} 个')
        tb.add_row('命令行', cmd)
        context.console.print(
            Panel(
                tb,
                title='[bold magenta]⟁ MCP Control Plane[/bold magenta]',
                border_style='bright_magenta',
                padding=(1, 2),
            )
        )
        if lifecycle == 'error':
            mcp = context.engine.get_mcp_client()
            logs = []
            if mcp is not None and hasattr(mcp, 'get_recent_errors'):
                try:
                    logs = list(mcp.get_recent_errors())
                except Exception:
                    logs = []
            from rich.panel import Panel

            if logs:
                body = '\n'.join(f'• {line}' for line in logs)
            else:
                body = '(暂无 stderr 输出)'
            context.console.print(
                Panel(
                    body,
                    title='[bold red]💥 最近错误日志 (stderr)[/bold red]',
                    border_style='red',
                    padding=(1, 2),
                )
            )

    @staticmethod
    def _restart(context: ReplSkillContext) -> None:
        if context.console is not None:
            context.console.print('[dim]重启 MCP server 中…[/dim]')
        ok = context.engine.restart_mcp_client()
        if context.console is None:
            print('[MCP] 已重启并进入后台加载。' if ok else '[MCP] 重启失败，请检查 MCP_SERVER_COMMAND。')
            return
        if ok:
            context.console.print('[bold green]✓ MCP 已重启，工具加载在后台进行中。[/bold green]')
            MCPSkill._print_status(context)
        else:
            context.console.print('[bold red]✗ MCP 重启失败，请检查 MCP_SERVER_COMMAND 或外部依赖。[/bold red]')

    @staticmethod
    def _print_tools(context: ReplSkillContext) -> None:
        snap = context.engine.mcp_status_snapshot()
        tools = snap.get('tools') or []
        if not isinstance(tools, list):
            tools = []
        if context.console is None:
            if not tools:
                print('[MCP] 当前无可用工具。')
                return
            for i, row in enumerate(tools, start=1):
                if not isinstance(row, dict):
                    continue
                n = str(row.get('name') or '')
                d = str(row.get('description') or '')
                print(f'{i}. {n} - {d}')
            return
        from rich.panel import Panel
        from rich.table import Table

        if not tools:
            context.console.print(
                Panel(
                    '[yellow]当前 MCP 未同步到任何外部工具。[/yellow]',
                    title='[bold magenta]⟁ MCP Tools[/bold magenta]',
                    border_style='magenta',
                )
            )
            return
        t = Table(show_header=True, header_style='bold magenta')
        t.add_column('#', width=4, justify='right')
        t.add_column('Tool', style='bold cyan')
        t.add_column('Description', style='white')
        for idx, row in enumerate(tools, start=1):
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or '').strip() or '-'
            desc = str(row.get('description') or '').strip() or '(无描述)'
            t.add_row(str(idx), name, desc)
        context.console.print(
            Panel(
                t,
                title='[bold magenta]⟁ MCP Tools[/bold magenta]',
                subtitle=f"[dim]{len(tools)} mounted[/dim]",
                border_style='bright_magenta',
                padding=(1, 1),
            )
        )

    @staticmethod
    def _toggle_web_mode(context: ReplSkillContext) -> None:
        now = context.engine.toggle_mcp_online_mode()
        try:
            context.engine.persist_session()
        except Exception:
            pass
        if context.console is None:
            if now:
                print(
                    '[🌐 浏览器MCP模式已激活] 提示：大模型现在会优先通过 Browser MCP 获取网络信息。'
                    '使用前请先在浏览器安装并连接 browser-mcp 插件。'
                )
            else:
                print('[🚫 浏览器MCP模式已禁用] 提示：大模型将不再强制优先使用 Browser MCP。')
            return
        if now:
            context.console.print(
                '[bold cyan][🌐 浏览器MCP模式已激活] 提示：大模型现在会优先通过 Browser MCP 获取网络信息。'
                '使用前请先在浏览器安装并连接 browser-mcp 插件。[/bold cyan]'
            )
        else:
            context.console.print(
                '[bold yellow][🚫 浏览器MCP模式已禁用] 提示：大模型将不再强制优先使用 Browser MCP。[/bold yellow]'
            )


# 向后兼容：旧类名仍可被测试或外部引用。
McpSkill = MCPSkill

