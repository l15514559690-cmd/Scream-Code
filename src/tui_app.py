"""
纯 Python 终端 UI：``prompt_toolkit`` + ``rich``，替代 macOS 上易受 PTY EOF 影响的 crossterm 路径。

- **流式 + 代码高亮**：``_run_streaming_turn`` 中 ``Live`` 仅裸 ``ScreamMarkdown``（``transient=True``），
  定稿为固定靛紫 ``Panel``；首包前 ``console.status`` 思考动画；**不用** ``patch_stdout``。
- **视觉**：靛紫品牌色、欢迎 Panel；协议/模式/模型与 Token 费用固定在 prompt **底部工具栏**，不污染 scrollback。
- **斜杠补全**：输入 ``/`` 后弹出指令补全菜单（紫色选中项）。
- **PTY 断开**：主输入循环捕获 ``EOFError`` 后直接 ``sys.exit(0)``，不做复杂清理，避免死循环占满 CPU。
"""

from __future__ import annotations

import os
import sys
from typing import Any, ClassVar, Sequence

# 品牌色（Tailwind Indigo / 紫系）
_BRAND_HEX = '#4F46E5'
_BRAND_MUTED = '#6366f1'
_BRAND_SOFT = '#A5B4FC'
_ASSISTANT_SURFACE = '#161622'
_USER_ACCENT = '#c4b5fd'

# ---------------------------------------------------------------------------
# 斜杠指令补全（prompt_toolkit 悬浮菜单）
# ---------------------------------------------------------------------------

SLASH_COMMANDS: tuple[str, ...] = (
    '/team',
    '/memo',
    '/summary',
    '/stop',
    '/new',
    '/flush',
    '/help',
    '/cost',
    '/status',
    '/diff',
    '/sessions',
    '/load',
    '/doctor',
    '/audit',
    '/report',
    '/subsystems',
    '/graph',
    '/config',
    '/skills',
    '/clear',
)

# 悬浮补全菜单右侧 meta（与 SLASH_COMMANDS 一一对应；缺键时回退默认文案）
SLASH_COMMAND_META: dict[str, str] = {
    '/team': '群狼模式 (多智能体协作)',
    '/memo': '项目记忆 (查看/编辑文档)',
    '/summary': '总结并压缩当前上下文',
    '/stop': '中断当前模型生成',
    '/new': '开启全新对话 (清空上下文)',
    '/flush': '清理底层缓存与临时文件',
    '/help': '查看所有指令帮助',
    '/cost': '查看当前 Token 消耗与账单',
    '/status': '沙箱、工具、模型与项目状态',
    '/diff': 'Git 工作区改动一览',
    '/sessions': '列出历史会话存档',
    '/load': '恢复指定会话 id',
    '/doctor': '依赖与路径快速体检',
    '/audit': '归档与源码一致性审计',
    '/report': '环境与启动体检报告',
    '/subsystems': '顶层 Python 子系统模块',
    '/graph': '命令与引导关系树状图',
    '/config': '查看当前大模型与 API 配置 (JSON)',
    '/skills': '查看当前挂载的扩展技能与插件',
    '/clear': '清屏（原生桥接未实现时请用 /help）',
}


class SlashCommandCompleter:
    """
    当光标前文本从某处起以 ``/`` 为前缀时，按前缀过滤 ``SLASH_COMMANDS``。

    实现 ``prompt_toolkit.completion.Completer`` 协议，供 ``ThreadedCompleter`` 包装。
    """

    commands: ClassVar[Sequence[str]] = SLASH_COMMANDS
    meta: ClassVar[dict[str, str]] = SLASH_COMMAND_META

    def get_completions(self, document: Any, complete_event: Any):
        from prompt_toolkit.completion import Completion

        text = document.text_before_cursor
        slash = text.rfind('/')
        if slash < 0:
            return
        fragment = text[slash:]
        if not fragment.startswith('/'):
            return
        for cmd in self.commands:
            if cmd.startswith(fragment):
                yield Completion(
                    cmd,
                    start_position=-len(fragment),
                    display_meta=self.meta.get(cmd, '斜杠指令'),
                )


def _prompt_toolkit_style() -> Any:
    """补全菜单：选中行紫底白字。"""
    from prompt_toolkit.styles import Style

    return Style.from_dict(
        {
            # 菜单底色
            'completion-menu': f'bg:{_ASSISTANT_SURFACE}',
            'completion-menu.completion': f'bg:{_ASSISTANT_SURFACE} fg:#e2e8f0',
            'completion-menu.completion.current': f'bg:{_BRAND_HEX} fg:#ffffff bold',
            # meta 略暗，突出左侧命令主体；选中行保持靛紫底
            'completion-menu.meta.completion': 'fg:#64748b',
            'completion-menu.meta.completion.current': f'bg:{_BRAND_HEX} fg:#a5b4fc',
            # 光标行与提示
            '': f'fg:#e2e8f0',
            'bottom-toolbar': 'bg:#1e1e2e fg:#e2e8f0',
        }
    )


def _build_tui_prompt_session() -> Any:
    """
    与 ``replLauncher._build_prompt_session`` 对齐的 stdin/stdout 绑定，并挂载斜杠补全与样式。
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import ThreadedCompleter
        from prompt_toolkit.history import InMemoryHistory
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('需要安装 prompt_toolkit（见 requirements.txt）') from exc

    try:
        from prompt_toolkit.input.defaults import create_input
        from prompt_toolkit.output.defaults import create_output
    except ImportError:
        create_input = None  # type: ignore[misc, assignment]
        create_output = None  # type: ignore[misc, assignment]

    class _BoundedInMemoryHistory(InMemoryHistory):
        def __init__(self, cap: int = 512) -> None:
            super().__init__()
            self._cap = max(32, cap)

        def store_string(self, string: str) -> None:
            super().store_string(string)
            over = len(self._storage) - self._cap
            if over > 0:
                del self._storage[0:over]

    history = _BoundedInMemoryHistory()
    completer = ThreadedCompleter(SlashCommandCompleter())

    kw: dict[str, Any] = {
        'history': history,
        'completer': completer,
        'complete_while_typing': True,
        'validate_while_typing': False,
        # 禁用鼠标协议，滚动交给 macOS Terminal / iTerm 等原生处理，避免滚轮「卡死」
        'mouse_support': False,
        'enable_suspend': False,
        'style': _prompt_toolkit_style(),
    }
    if create_input is not None and create_output is not None:
        kw['input'] = create_input()
        kw['output'] = create_output()
    return PromptSession(**kw)


def _ascii_logo_lines() -> tuple[str, ...]:
    return (
        r'  ███████╗ ██████╗██████╗ ███████╗ █████╗ ███╗   ███╗',
        r'  ██╔════╝██╔════╝██╔══██╗██╔════╝██╔══██╗████╗ ████║',
        r'  ███████╗██║     ██████╔╝█████╗  ███████║██╔████╔██║',
        r'  ╚════██║██║     ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║',
        r'  ███████║╚██████╗██║  ██║███████╗██║  ██║██║ ╚═╝ ██║',
        r'  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝',
    )


def _print_welcome_panel(console: Any) -> None:
    from rich import box
    from rich.align import Align
    from rich.panel import Panel
    from rich.text import Text

    logo = Text('\n'.join(_ascii_logo_lines()), style=f'bold {_BRAND_SOFT}')
    tag = Text.from_markup(
        f'\n[bold {_BRAND_HEX}]Scream Code[/bold {_BRAND_HEX}]  ·  '
        f'[dim]Python TUI[/dim]  ·  '
        f'[dim]Rich + prompt_toolkit[/dim]\n'
        f'[dim]输入 [bold]/[/bold] 打开斜杠指令 · EOF 关窗安全退出 · Ctrl+C 中断生成[/dim]\n'
    )
    body = Align.center(Text.assemble(logo, tag))
    console.print(
        Panel(
            body,
            title=f'[bold {_BRAND_SOFT}]WELCOME[/bold {_BRAND_SOFT}]',
            subtitle=f'[dim {_BRAND_MUTED}]neural interface v1[/dim {_BRAND_MUTED}]',
            subtitle_align='right',
            border_style=_BRAND_HEX,
            box=box.ROUNDED,
            padding=(1, 2),
            style=f'on {_ASSISTANT_SURFACE}',
        )
    )


def _apply_tui_assistant_panel_theme() -> None:
    """
    在本进程内替换 ``repl_ui_render.assistant_panel``：欢迎/错误等仍用靛紫系圆角 ``Panel``。
    助手流式定稿由 ``final_assistant_markdown_panel`` 固定样式，不经此函数。
    """
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    from . import repl_ui_render as rur

    def _patched(inner: Any) -> Any:
        return Panel(
            inner,
            title=Text.from_markup(f'[bold {_BRAND_SOFT}]◆ ASSISTANT[/bold {_BRAND_SOFT}]'),
            subtitle=f'[dim {_BRAND_MUTED}]stream · markdown · syntax[/dim {_BRAND_MUTED}]',
            subtitle_align='right',
            border_style=_BRAND_HEX,
            box=box.ROUNDED,
            expand=True,
            padding=(1, 2),
            style=f'on {_ASSISTANT_SURFACE}',
        )

    rur.assistant_panel = _patched  # type: ignore[assignment]


def _infer_protocol_label() -> str:
    """优先 ``llm_config.json`` 激活项，再回退环境变量。"""
    try:
        from .llm_settings import read_llm_connection_settings

        c = read_llm_connection_settings()
        proto = (c.api_protocol or '').strip().lower()
        if proto == 'anthropic':
            return 'Anthropic'
        if proto == 'openai':
            return 'OpenAI-compat'
    except Exception:
        pass
    if (os.environ.get('ANTHROPIC_API_KEY') or '').strip():
        return 'Anthropic'
    if (os.environ.get('OPENAI_API_KEY') or '').strip():
        return 'OpenAI-compat'
    if (os.environ.get('SCREAM_LLM_BASE_URL') or '').strip():
        return 'Custom'
    return '—'


def _status_model(engine: Any) -> str:
    """状态栏模型名以 ``engine.config.llm_model`` 为准（由下方与项目配置同步）。"""
    cfg = getattr(engine, 'config', None)
    raw = (getattr(cfg, 'llm_model', None) or '').strip()
    return raw if raw else '(default)'


def _tui_load_dotenv_layers() -> None:
    """PromptSession 之前：项目根 `.env` + 当前工作目录 `.env`（不覆盖已注入变量）。"""
    from .llm_settings import load_project_dotenv

    load_project_dotenv()
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    cwd_env = os.path.join(os.getcwd(), '.env')
    if os.path.isfile(cwd_env):
        load_dotenv(cwd_env, override=False)


def _tui_engine_autoresume() -> Any:
    """
    加载最近会话；损坏（JSON/XML/Expat 等）时重置为空会话并提示，不中断 TUI。

    ``from_saved_session`` 内含 ``load_session`` 与记忆重建；任一步失败即放弃该快照。
    """
    from .query_engine import QueryEnginePort
    from .session_store import most_recent_saved_session_id

    sid = most_recent_saved_session_id()
    if not sid:
        return QueryEnginePort.from_workspace()
    try:
        return QueryEnginePort.from_saved_session(sid)
    except Exception:
        # json.JSONDecodeError、xml.parsers.expat.ExpatError、KeyError 等一律视为损坏
        print('[!] 发现损坏的会话记录，已自动重置。', flush=True)
        return QueryEnginePort.from_workspace()


def _print_user_message(console: Any, text: str) -> None:
    from rich import box
    from rich.markup import escape
    from rich.panel import Panel

    safe = escape(text or '')
    console.print(
        Panel(
            f'[bold white]{safe}[/bold white]',
            title=f'[bold {_USER_ACCENT}]YOU[/bold {_USER_ACCENT}]',
            border_style=_BRAND_MUTED,
            box=box.ROUNDED,
            padding=(0, 1),
            style='on #1a1825',
        )
    )


def _get_bottom_toolbar(engine: Any) -> Any:
    from prompt_toolkit.formatted_text import HTML
    import html

    # 1. 协议
    try:
        from .llm_settings import read_llm_connection_settings
        c = read_llm_connection_settings()
        proto = (c.api_protocol or '').strip().lower()
        if proto == 'anthropic':
            protocol = 'Anthropic'
        elif proto == 'openai':
            protocol = 'OpenAI-compat'
        else:
            protocol = 'Custom'
    except Exception:
        protocol = '—'

    # 2. 模型
    cfg = getattr(engine, 'config', None)
    raw_model = (getattr(cfg, 'llm_model', None) or '').strip()
    model = raw_model if raw_model else '(default)'

    # 3. 消耗
    u = getattr(engine, 'total_usage', None)
    inp = int(getattr(u, 'input_tokens', 0) or 0) if u is not None else 0
    outp = int(getattr(u, 'output_tokens', 0) or 0) if u is not None else 0
    total = inp + outp
    usd = (inp * 3.0 + outp * 15.0) / 1_000_000.0
    usd_s = f'{usd:.4f}' if usd >= 0.0001 else f'{usd:.6f}'

    # 4. 模式
    use_team = bool(getattr(engine, 'repl_team_mode', False))
    if use_team:
        mode_html = '<ansiyellow><b>🐺 群狼模式</b></ansiyellow>'
    else:
        mode_html = '<ansigray><b>👤 单人模式</b></ansigray>'

    return HTML(
        f'  <ansicyan><b>协议:</b></ansicyan> {html.escape(protocol)}  <ansiblue>│</ansiblue>  '
        f'{mode_html}  <ansiblue>│</ansiblue>  '
        f'<ansicyan><b>模型:</b></ansicyan> {html.escape(model)}  <ansiblue>│</ansiblue>  '
        f'<ansicyan><b>消耗:</b></ansicyan> Σ {total} (↑{inp} ↓{outp}) ≈ ${usd_s}  '
    )


def run_python_tui_repl(*, llm_enabled: bool = True, route_limit: int = 5) -> int:
    """
    进入 Python TUI 主循环，并与 ``QueryEnginePort.iter_repl_assistant_events_with_runtime`` 桥接。

    返回进程退出码；``EOFError``（PTY 关闭）时直接 ``sys.exit(0)``，不返回。
    """
    from dataclasses import replace

    from rich.rule import Rule

    from .agent_cancel import reset_agent_cancel
    from .llm_settings import read_llm_connection_settings
    from .replLauncher import (
        _ensure_stdio_utf8,
        _maybe_print_repl_memory_load_warning,
        _print_graceful_interrupt,
        _run_streaming_turn,
        _try_persist_repl_session,
        build_repl_banner,
    )
    from .repl_slash_commands import dispatch_repl_slash_command
    from .runtime import PortRuntime

    _ensure_stdio_utf8()
    _tui_load_dotenv_layers()
    # 品牌与欢迎仅由本模块 Rich 面板呈现，不打印 Rust/print_startup_banner 等重复 Logo。

    if not llm_enabled:
        print(build_repl_banner())
        return 0

    try:
        from prompt_toolkit.formatted_text import HTML
    except ImportError:
        print('缺少 prompt_toolkit，无法启动 Python TUI。', flush=True)
        return 1

    from rich.console import Console

    # prompt 返回后由 Rich 直连 TTY；禁用 patch_stdout，避免 ANSI 与 toolkit 代理互相破坏
    console = Console(force_terminal=True, color_system='truecolor')
    _apply_tui_assistant_panel_theme()

    # 第一屏：靛紫 WELCOME（再建会话与输入循环）
    _print_welcome_panel(console)

    runtime = PortRuntime()
    engine = _tui_engine_autoresume()
    conn = read_llm_connection_settings()
    cfg_model = (engine.config.llm_model or '').strip()
    profile_model = (conn.model or '').strip()
    merged_model = (cfg_model or profile_model or '').strip()
    if merged_model:
        engine.config = replace(
            engine.config, llm_enabled=True, llm_model=merged_model
        )
    else:
        engine.config = replace(engine.config, llm_enabled=True)
    engine.ui_console = console

    session = _build_tui_prompt_session()

    # 靛蓝品牌提示符：须为严格 XML（勿用 `<style ... bold>` 无值属性，会触发 ExpatError）
    prompt_html = HTML(f'<style fg="{_BRAND_HEX}"><b>尖叫&gt; </b></style>')

    while True:
        try:
            line = session.prompt(
                prompt_html,
                bottom_toolbar=lambda: _get_bottom_toolbar(engine),
            ).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            if isinstance(exc, EOFError):
                sys.exit(0)
            console.print()
            continue

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

        reset_agent_cancel()
        _print_user_message(console, line)
        # 用户消息 ↔ 模型输出：极简分隔线（避免与状态栏前重复堆叠 Rule）
        console.print(Rule(style=_BRAND_MUTED))
        try:
            _run_streaming_turn(
                engine, runtime, msg, console, route_limit=route_limit, team=use_team
            )
        except KeyboardInterrupt:
            _print_graceful_interrupt(console, use_rich=True)
            continue
        except Exception as exc:
            try:
                console.print(
                    f'[bold red]本回合展示层异常: {type(exc).__name__}: {exc}[/bold red]'
                )
            except Exception:
                print(f'本回合异常: {type(exc).__name__}: {exc}', flush=True)
            continue

        _maybe_print_repl_memory_load_warning(console, engine, use_rich=True)
        _try_persist_repl_session(engine)
        # 本轮助手输出结束 ↔ 下一轮状态栏：一层留白
        console.print()


def _bootstrap_and_run() -> int:
    """供 ``python -m src.tui_app`` 使用。"""
    from .claw_config import load_project_claw_json
    from .llm_onboarding import ensure_llm_ready_interactive
    from .llm_settings import load_project_dotenv
    from .main import check_and_install_dependencies

    check_and_install_dependencies()
    load_project_dotenv()
    load_project_claw_json()
    if not ensure_llm_ready_interactive():
        return 1
    try:
        return run_python_tui_repl(llm_enabled=True, route_limit=5)
    except KeyboardInterrupt:
        print('\n已中断。', flush=True)
        return 130


if __name__ == '__main__':
    raise SystemExit(_bootstrap_and_run())
