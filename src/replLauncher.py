from __future__ import annotations

import sys
from typing import Any

# Slant 风格 ASCII（用户指定，勿改字符结构）
_SLANT_LOGO_LINES = (
    '_____  __________  _________    __  ___     __________  ____  ______',
    '  / ___/ / ____/ __ \\/ ____/   |  /  |/  /    / ____/ __ \\/ __ \\/ ____/',
    '  \\__ \\ / /   / /_/ / __/ / /| | / /|_/ /    / /   / / / / / / / __/   ',
    ' ___/ // /___/ _, _/ /___/ ___ |/ /  / /    / /___/ /_/ / /_/ / /___   ',
    '/____/ \\____/_/ |_/_____/_/  |_/_/  /_/     \\____/\\____/_____/_____/',
)


def build_repl_banner() -> str:
    return (
        '未加 --llm 时仅显示本说明。要进入可对话的交互循环并调用大模型，请执行：'
        '`python3 -m src.main repl --llm`（密钥见 llm_config.json / .env）。'
        '也可使用 `summary` 或 `config`。'
    )


def _logo_plain() -> str:
    return '\n'.join(_SLANT_LOGO_LINES)


def print_project_memory_loaded_notice() -> None:
    """Logo 之后调用：若 cwd 下存在可用的项目记忆文件，打印一行绿色提示。"""
    from .project_memory import read_first_available_project_memory

    name, _ = read_first_available_project_memory()
    if not name:
        return
    msg = f'[+] 已加载项目记忆文档: {name}'
    try:
        from rich.console import Console

        Console().print(f'[bold green]{msg}[/bold green]')
    except ImportError:
        if sys.stdout.isatty():
            print(f'\033[1;32m{msg}\033[0m', flush=True)
        else:
            print(msg, flush=True)


def print_startup_banner(*, ensure_config: bool = True) -> None:
    if ensure_config:
        try:
            from . import model_manager

            model_manager.ensure_default_config_file()
        except OSError:
            pass

    try:
        from rich.align import Align
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
    except ImportError:
        print(_logo_plain())
        print()
        return

    console = Console()
    art = Text(_logo_plain(), style='bold cyan')
    panel = Panel.fit(
        Align.center(art),
        border_style='bold cyan',
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def print_repl_llm_driver_banner(*, console: Any | None) -> None:
    """REPL + --llm：Logo 之后展示当前激活模型或黄色未配置警告。"""
    try:
        from . import model_manager
    except ImportError:
        return

    model_manager.ensure_default_config_file()
    raw = model_manager.read_persisted_config_raw()
    profile = model_manager.get_active_profile(raw) if raw else None

    if console is None:
        if profile is None:
            print('⚠️ 当前无激活的大模型，请配置后再使用！')
        else:
            proto = profile.api_protocol if profile.api_protocol in ('openai', 'anthropic') else 'openai'
            print(
                f'协议: {proto} | 模型: {profile.model_name} | 状态: 已就绪'
            )
        print()
        return

    from rich.markup import escape
    from rich.panel import Panel
    from rich.text import Text

    if profile is None:
        body = Text.from_markup(
            '[bold yellow]⚠️ 当前无激活的大模型，请配置后再使用！[/bold yellow]'
        )
        console.print(Panel(body, border_style='yellow', expand=True, padding=(0, 2)))
    else:
        proto = profile.api_protocol if profile.api_protocol in ('openai', 'anthropic') else 'openai'
        inner = (
            f'[bold green]协议: {escape(proto)} | '
            f'模型: {escape(profile.model_name)} | '
            f'状态: 已就绪[/bold green]'
        )
        body = Text.from_markup(inner)
        console.print(Panel(body, border_style='bold green', expand=True, padding=(0, 2)))
    console.print()


def _assistant_panel_title() -> Any:
    from rich.text import Text

    return Text.from_markup('[bold cyan]🤖 尖叫助理[/bold cyan]')


def _assistant_panel(inner: Any) -> Any:
    from rich.panel import Panel

    return Panel(
        inner,
        title=_assistant_panel_title(),
        border_style='cyan',
        expand=True,
        padding=(1, 2),
    )


def _print_assistant_output(console: object, text: str) -> None:
    from rich.markdown import Markdown

    stripped = text.strip()
    if not stripped:
        return
    console.print(_assistant_panel(Markdown(stripped, code_theme='monokai')))
    console.print()


def _print_assistant_error(console: object, message: str) -> None:
    from rich.text import Text

    console.print(_assistant_panel(Text(message, style='bold red')))
    console.print()


def _build_prompt_session() -> Any | None:
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
    except ImportError:
        return None

    if not sys.stdin.isatty():
        return None

    history = InMemoryHistory()
    # interrupt_exception 默认为 KeyboardInterrupt，便于 REPL 捕获 Ctrl+C 而不退出进程。
    return PromptSession(history=history)


def _repl_read_line(
    *,
    pt_session: Any | None,
    console: Any,
    use_rich_input: bool,
) -> str | None:
    """返回 None 表示 EOF；空串表示仅刷新提示（如 Ctrl+C 已处理）。"""
    try:
        if pt_session is not None:
            from prompt_toolkit.formatted_text import HTML

            return pt_session.prompt(
                HTML('<ansibrightmagenta><b>尖叫&gt; </b></ansibrightmagenta>')
            ).strip()
        if use_rich_input:
            return console.input('[bold magenta]尖叫> [/bold magenta]').strip()
        return input('尖叫> ').strip()
    except EOFError:
        return None
    except KeyboardInterrupt:
        console.print('[bold red]⛔ 已手动中断[/bold red]')
        return ''


def _consume_llm_events_plain(
    engine: Any,
    runtime: Any,
    line: str,
    *,
    route_limit: int,
    team: bool,
) -> None:
    """无 Rich 时仍走同一事件流（含多代理），仅打印纯文本。"""
    gen = engine.iter_repl_assistant_events_with_runtime(
        line, runtime=runtime, route_limit=route_limit, team=team
    )
    buf = ''
    try:
        for ev in gen:
            et = ev.get('type')
            if et == 'team_agent':
                print(f"\n>>> [{ev.get('agent')}]\n", flush=True)
                continue
            if et == 'text_delta':
                piece = str(ev.get('text', '') or '')
                print(piece, end='', flush=True)
                buf += piece
                continue
            if et == 'api_tool_op':
                print(
                    f"\n[tool] {ev.get('tool_name')} {ev.get('arguments', '')}\n",
                    flush=True,
                )
                continue
            if et == 'finished':
                print()
                if not buf.strip():
                    out = ev.get('output', '')
                    if isinstance(out, str) and out.strip():
                        print(out)
                print()
                return
            if et in ('blocked', 'non_llm'):
                print(ev.get('output', ''))
                print()
                return
            if et == 'llm_error':
                print(ev.get('output', ''))
                print()
                return
    except KeyboardInterrupt:
        try:
            gen.close()
        except Exception:
            pass
        print('\n⛔ 已中断')


def _run_streaming_turn(
    engine: Any,
    runtime: Any,
    line: str,
    console: Any,
    *,
    route_limit: int,
    team: bool = False,
) -> None:
    from rich.live import Live
    from rich.markdown import Markdown

    use_live = bool(
        getattr(console, 'is_terminal', False) and console.is_terminal
    )
    # 路由与权限推断统一交给 QueryEngine + PortRuntime，本层仅消费事件流。
    gen = engine.iter_repl_assistant_events_with_runtime(
        line, runtime=runtime, route_limit=route_limit, team=team
    )
    buffer = ''
    live: Any = None

    def _live_renderable() -> Any:
        return _assistant_panel(Markdown(buffer, code_theme='monokai'))

    def _stop_live() -> None:
        nonlocal live
        if live is not None:
            try:
                live.stop()
            except Exception:
                pass
            live = None

    try:
        for ev in gen:
            et = ev['type']
            if et == 'blocked':
                _stop_live()
                _print_assistant_output(console, ev['output'])
                return
            if et == 'llm_error':
                _stop_live()
                _print_assistant_error(console, ev['output'])
                return
            if et == 'team_agent':
                _stop_live()
                agent = str(ev.get('agent', 'Agent'))
                styles = {
                    'Planner': 'bold cyan',
                    'Coder': 'bold green',
                    'Reviewer': 'bold yellow',
                }
                st = styles.get(agent, 'bold white')
                console.print(f'[{st}]━━ {agent} ━━[/{st}]')
                continue
            if et == 'non_llm':
                _stop_live()
                _print_assistant_output(console, ev['output'])
                return
            if et == 'tool_phase':
                _stop_live()
                label = ', '.join(ev['tools'])
                console.print(f'[bold yellow]⚙️ 正在执行工具: {label}[/bold yellow]')
                continue
            if et == 'api_tool_op':
                _stop_live()
                buffer = ''
                console.print(
                    f'[bold yellow]🛠️ 尖叫 Code 正在操作: {ev["tool_name"]} '
                    f'-> {ev["arguments"]}[/bold yellow]'
                )
                continue
            if et == 'text_delta':
                piece = ev['text']
                buffer += piece
                if use_live:
                    if live is None:
                        live = Live(
                            console=console,
                            refresh_per_second=20,
                            transient=False,
                            vertical_overflow='visible',
                            get_renderable=_live_renderable,
                        )
                        live.start()
                    else:
                        live.refresh()
                continue
            if et == 'finished':
                _stop_live()
                if not use_live and buffer.strip():
                    _print_assistant_output(console, buffer)
                elif use_live and buffer.strip():
                    console.print()
                elif not buffer.strip():
                    out = ev.get('output', '')
                    if isinstance(out, str) and out.strip():
                        _print_assistant_output(console, out)
                return
    except KeyboardInterrupt:
        try:
            gen.close()
        except Exception:
            pass
        _stop_live()
        console.print('[bold red]⛔ 已手动中断[/bold red]')


def run_repl_interactive_loop(*, llm_enabled: bool, route_limit: int = 5) -> int:
    """打印 Logo 后进入交互：prompt_toolkit 输入 + 流式 Markdown（Rich Live）。"""
    from dataclasses import replace

    try:
        from rich.console import Console
        from rich.rule import Rule
    except ImportError:
        Console = None  # type: ignore[misc, assignment]

    from .query_engine import QueryEnginePort
    from .runtime import PortRuntime

    print_startup_banner(ensure_config=True)
    print_project_memory_loaded_notice()
    if not llm_enabled:
        print(build_repl_banner())
        return 0

    if Console is None:
        print('已启用 --llm，将调用大模型 API。输入 exit / quit 结束。')
        print(
            '斜杠指令: /help · doctor cost diff status · team · 记忆/体检/引擎类\n'
        )
        print_repl_llm_driver_banner(console=None)
        from .repl_slash_commands import dispatch_repl_slash_command

        runtime = PortRuntime()
        engine = QueryEnginePort.from_workspace()
        engine.config = replace(engine.config, llm_enabled=True)
        while True:
            try:
                line = input('尖叫> ').strip()
            except (EOFError, KeyboardInterrupt):
                print('\n再见。')
                return 0
            if not line:
                continue
            if line.lower() in ('exit', 'quit', 'q'):
                print('再见。')
                return 0
            handled, new_eng = dispatch_repl_slash_command(line, console=None, engine=engine)
            if handled:
                if new_eng is not None:
                    engine = new_eng
                continue
            use_team = bool(engine.repl_team_mode)
            msg = line
            if msg.startswith('$team'):
                msg = msg[5:].strip()
                use_team = True
            if not msg:
                continue
            _consume_llm_events_plain(
                engine, runtime, msg, route_limit=route_limit, team=use_team
            )

    console = Console()
    print_repl_llm_driver_banner(console=console)
    console.print('[dim]已启用 --llm；输入 exit / quit 结束；Ctrl+C 可中断当前生成。[/dim]')
    console.print(
        '[dim]斜杠: [bold]/help[/bold] · /doctor /cost /diff /status · /team 或 [bold]$team[/bold] 前缀 · '
        '记忆 /summary /flush /sessions /load · /audit /report · /subsystems /graph[/dim]'
    )

    pt_session = _build_prompt_session()

    from .repl_slash_commands import dispatch_repl_slash_command

    runtime = PortRuntime()
    engine = QueryEnginePort.from_workspace()
    engine.config = replace(engine.config, llm_enabled=True)
    engine.ui_console = console

    while True:
        console.print()
        console.print(Rule(style='dim'))
        console.print()
        line = _repl_read_line(
            pt_session=pt_session,
            console=console,
            use_rich_input=True,
        )
        if line is None:
            console.print('[dim]再见。[/dim]')
            return 0
        if line == '':
            continue
        if line.lower() in ('exit', 'quit', 'q'):
            console.print('[dim]再见。[/dim]')
            return 0

        handled, new_eng = dispatch_repl_slash_command(line, console=console, engine=engine)
        if handled:
            if new_eng is not None:
                engine = new_eng
            continue

        use_team = bool(engine.repl_team_mode)
        msg = line
        if msg.startswith('$team'):
            msg = msg[5:].strip()
            use_team = True
        if not msg:
            continue

        try:
            _run_streaming_turn(
                engine, runtime, msg, console, route_limit=route_limit, team=use_team
            )
        except KeyboardInterrupt:
            console.print('[bold red]⛔ 已手动中断[/bold red]')
            continue
