"""
纯 Python 终端 UI：``prompt_toolkit`` + ``rich``，替代 macOS 上易受 PTY EOF 影响的 crossterm 路径。

- **流式丝滑管线**（经 ``replLauncher._run_streaming_turn`` + ``repl_ui_render``）：
  ``Live(auto_refresh=False)`` 仅在我们节流后的帧上 ``update``；15ms 时间片 + 字形批处理，
  避免每 token 全量 Markdown 重排；终端高度绑定的**尾部视口**把滚动锁在 Live 区，scrollback 不乱跳；
  未闭合 `` ``` `` 在解析前虚拟闭合，Pygments 结构不塌。
- **定稿**：瞬态 Live 结束后靛紫 ``Panel`` / ``print_solidified_assistant_markdown`` 写入历史；首包前 ``console.status``。
- **生成中输入**：流式回合走 ``replLauncher._run_streaming_turn_tui_concurrent``：``asyncio`` + ``patch_stdout`` + ``prompt_async``，
  底部输入框在思考/输出期间仍可用；生成中仅 ``/stop`` 生效，其他输入会给出提示并继续等待；``/stop`` 与 Ctrl+C 触发 ``engine.request_stream_abort()``；回合结束 ``tcflush`` stdin 丢弃幽灵回车。
- **神经底栏**：``prompt_toolkit`` 的 ``bottom_toolbar`` 全宽深色条 + 青/绿高亮；TUI 流式时在 ``Live`` 内用 ``Group`` 叠一行 Rich 页脚，与输入态信息同源（模型 / 沙箱 / 记忆条数 / Token%）。
- **斜杠补全**：``/`` 菜单；**Enter** 在补全打开时只确认补全（见 ``repl_slash_helpers``）。
- **PTY 断开**：``EOFError`` → ``sys.exit(0)``。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

# 品牌色（Tailwind Indigo / 紫系）
_BRAND_HEX = '#4F46E5'
_BRAND_MUTED = '#6366f1'
_BRAND_SOFT = '#A5B4FC'
_ASSISTANT_SURFACE = '#161622'
_USER_ACCENT = '#c4b5fd'
_current_team_agent: str | None = None
_FEISHU_STATUS_CACHE: dict[str, Any] = {
    'status': False,
    'raw_status': False,
    'last_raw_change': 0.0,
}
_FEISHU_STATUS_DEBOUNCE_SEC = 3.0


def set_current_team_agent(agent_name: str | None) -> None:
    global _current_team_agent
    raw = '' if agent_name is None else str(agent_name).strip()
    _current_team_agent = raw or None


def get_current_team_agent() -> str | None:
    return _current_team_agent


def _prompt_toolkit_style() -> Any:
    """补全菜单：选中行紫底白字（与 ``repl_slash_helpers.prompt_toolkit_scream_slash_style`` 同源）。"""
    from .repl_slash_helpers import prompt_toolkit_scream_slash_style

    return prompt_toolkit_scream_slash_style()


def _build_tui_prompt_session() -> Any:
    """
    与 ``replLauncher._build_prompt_session`` 对齐的 stdin/stdout 绑定，并挂载斜杠补全与样式。
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.completion import ThreadedCompleter
        from prompt_toolkit.history import InMemoryHistory
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('需要安装 prompt_toolkit（见 requirements.txt）') from exc

    from .repl_slash_helpers import (
        SlashCommandCompleter,
        prompt_toolkit_slash_completion_enter_bindings,
    )

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
        'complete_style': CompleteStyle.MULTI_COLUMN,
        'reserve_space_for_menu': 8,
        'validate_while_typing': False,
        # 禁用鼠标协议，滚动交给 macOS Terminal / iTerm 等原生处理，避免滚轮「卡死」
        'mouse_support': False,
        'enable_suspend': False,
        'style': _prompt_toolkit_style(),
        'key_bindings': prompt_toolkit_slash_completion_enter_bindings(),
    }
    if create_input is not None and create_output is not None:
        kw['input'] = create_input()
        kw['output'] = create_output()
    return PromptSession(**kw)


def _ascii_logo_lines() -> tuple[str, ...]:
    return (
        r'  ███████╗ ██████╗██████╗ ███████╗ █████╗ ███╗   ███╗    ██████╗ ██████╗ ██████╗ ███████╗',
        r'  ██╔════╝██╔════╝██╔══██╗██╔════╝██╔══██╗████╗ ████║   ██╔════╝██╔═══██╗██╔══██╗██╔════╝',
        r'  ███████╗██║     ██████╔╝█████╗  ███████║██╔████╔██║   ██║     ██║   ██║██║  ██║█████╗  ',
        r'  ╚════██║██║     ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║   ██║     ██║   ██║██║  ██║██╔══╝  ',
        r'  ███████║╚██████╗██║  ██║███████╗██║  ██║██║ ╚═╝ ██║   ╚██████╗╚██████╔╝██████╔╝███████╗',
        r'  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝    ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝',
    )


def _print_welcome_panel(console: Any) -> None:
    from rich import box
    from rich.align import Align
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    logo = Text('\n'.join(_ascii_logo_lines()), style=f'bold {_BRAND_SOFT}')
    tag = Text.from_markup(
        f'[bold {_BRAND_HEX}]Scream Code[/bold {_BRAND_HEX}]  ·  '
        f'[dim]Python TUI[/dim]  ·  '
        f'[dim]Rich + prompt_toolkit[/dim]\n'
        f'[dim]输入 [bold]/[/bold] 打开斜杠指令 · EOF 关窗安全退出 · 生成中可 [bold]/stop[/bold] 或 Ctrl+C 终止[/dim]'
    )
    body = Group(
        Align.center(logo),
        Text(''),
        Align.center(tag),
    )
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


def neural_status_fields(engine: Any) -> dict[str, Any]:
    """
    神经状态栏数据源：供 ``bottom_toolbar`` HTML 与 Rich 流式页脚共用。
    Token% 相对 ``QueryEngineConfig.max_budget_tokens``（与引擎会话预算一致）。
    """
    from .memory_store import count_core_memory_entries
    from .sandbox_env import SandboxManager

    cfg = getattr(engine, 'config', None)
    raw_model = (getattr(cfg, 'llm_model', None) or '').strip()
    if not raw_model:
        try:
            from .llm_settings import read_llm_connection_settings

            raw_model = (read_llm_connection_settings().model or '').strip()
        except Exception:
            raw_model = ''
    model = raw_model or '(default)'

    u = getattr(engine, 'total_usage', None)
    inp = int(getattr(u, 'input_tokens', 0) or 0) if u is not None else 0
    outp = int(getattr(u, 'output_tokens', 0) or 0) if u is not None else 0
    total = inp + outp

    try:
        max_budget = int(getattr(cfg, 'max_budget_tokens', 12_000_000) or 12_000_000)
    except (TypeError, ValueError):
        max_budget = 12_000_000
    if max_budget <= 0:
        max_budget = 12_000_000
    token_pct = min(100, max(0, (total * 100) // max_budget))

    return {
        'model': model,
        'sandbox_on': bool(SandboxManager.instance().is_sandbox_enabled),
        'memory_n': count_core_memory_entries(),
        'token_pct': token_pct,
        'total_tokens': total,
        'team': bool(getattr(engine, 'repl_team_mode', False)),
    }


def _token_progress_bar(token_pct: int) -> dict[str, Any]:
    """
    10 格 Token 进度条（``█`` / ``░``），并给出 HTML/Rich 对应色。

    - <50%: Safe (green)
    - 50%-85%: Warning (yellow)
    - >85%: Danger (red)
    """
    pct = max(0, min(100, int(token_pct)))
    filled = min(10, max(0, (pct + 5) // 10))
    empty = 10 - filled
    filled_bar = '█' * filled
    empty_bar = '░' * empty
    if pct < 50:
        level = 'safe'
        html_color = 'ansigreen'
        rich_color = '#4ade80'
    elif pct <= 85:
        level = 'warning'
        html_color = 'ansiyellow'
        rich_color = '#facc15'
    else:
        level = 'danger'
        html_color = 'ansired'
        rich_color = '#f87171'
    return {
        'pct': pct,
        'filled': filled_bar,
        'empty': empty_bar,
        'level': level,
        'html_color': html_color,
        'rich_color': rich_color,
    }


def _debounced_feishu_running() -> bool:
    from .ui.status_bar import is_feishu_running

    now = time.monotonic()
    raw = bool(is_feishu_running())
    if raw != bool(_FEISHU_STATUS_CACHE.get('raw_status', False)):
        _FEISHU_STATUS_CACHE['raw_status'] = raw
        _FEISHU_STATUS_CACHE['last_raw_change'] = now
    effective = raw
    if (
        not raw
        and bool(_FEISHU_STATUS_CACHE.get('status', False))
        and (now - float(_FEISHU_STATUS_CACHE.get('last_raw_change', 0.0)))
        < _FEISHU_STATUS_DEBOUNCE_SEC
    ):
        # 短时间 OFF 抖动：维持上一帧 ON，避免底栏闪烁。
        effective = True
    _FEISHU_STATUS_CACHE['status'] = bool(effective)
    return bool(effective)


def _feishu_stream_fragment_debounced() -> str:
    on = _debounced_feishu_running()
    if on:
        return '  ·  [bold #4F46E5 on #09090b][● Feishu: ON][/bold #4F46E5 on #09090b]'
    return (
        '  ·  [dim #71717a][○ Feishu: OFF][/dim #71717a] '
        '[dim #52525b]（/feishu start）[/dim #52525b]'
    )


def _feishu_toolbar_fragment_debounced() -> str:
    if _debounced_feishu_running():
        return '<style fg="#4F46E5"><b>[● Feishu: ON]</b></style>'
    return (
        '<style fg="#71717a"><b>[○ Feishu: OFF]</b></style>  '
        '<style fg="#52525b">· /feishu start 开启侧车</style>'
    )


def neural_status_stream_footer_markup(engine: Any) -> str:
    """Rich ``Text.from_markup`` 双行仪表盘；与底栏语义/层级对齐，嵌入 ``Live`` 底部。"""
    f = neural_status_fields(engine)
    sb_on = (
        '[bold #4ade80]🛡️ 沙箱: ON[/bold #4ade80]'
        if f['sandbox_on']
        else '[bold #f87171]🔓 沙箱: OFF[/bold #f87171]'
    )
    team = '[bold #fbbf24]🐺 TEAM[/bold #fbbf24]' if f['team'] else '[dim]单人[/dim]'
    tok = _token_progress_bar(f['token_pct'])
    feishu_seg = _feishu_stream_fragment_debounced()
    level_txt = (
        'Safe'
        if tok['level'] == 'safe'
        else 'Warning'
        if tok['level'] == 'warning'
        else 'Danger'
    )
    return (
        '[dim #6b7280]╭─ Neural Console ───────────────────────────────────────────────[/dim #6b7280]\n'
        f'[{_BRAND_HEX}]◈[/] [bold #2dd4bf][{f["model"]}][/bold #2dd4bf]  │  {sb_on}  │  '
        f'[bold #5eead4]🧠 记忆: {f["memory_n"]}条[/bold #5eead4]  │  {team}{feishu_seg}\n'
        f'[dim #6b7280]╰─[/dim #6b7280] '
        f'[bold {tok["rich_color"]}]📊 Token [{tok["filled"]}{tok["empty"]}] {tok["pct"]}%[/bold {tok["rich_color"]}] '
        f'[dim](Σ {f["total_tokens"]})[/dim]  [dim]|[/dim]  '
        f'[bold {tok["rich_color"]}]{level_txt}[/bold {tok["rich_color"]}]'
    )


def _tui_load_dotenv_layers() -> None:
    """PromptSession 之前：``load_project_dotenv``（含 ``~/.scream/.env``）+ cwd ``.env``（不覆盖已有变量）。"""
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

    仅恢复 ``mutable_messages`` / ``llm_conversation_messages`` 等到内存，**不会**在此路径调用
    大模型；成功恢复后丢弃 TTY 上可能误排队的 stdin，避免残留上行被当成用户首条输入。
    """
    from .query_engine import QueryEnginePort
    from .replLauncher import repl_stdin_flush_pending_if_tty
    from .session_store import most_recent_saved_session_id

    sid = most_recent_saved_session_id()
    if not sid:
        return QueryEnginePort.from_workspace()
    try:
        eng = QueryEnginePort.from_saved_session(sid)
    except Exception:
        # json.JSONDecodeError、xml.parsers.expat.ExpatError、KeyError 等一律视为损坏
        print('[!] 发现损坏的会话记录，已自动重置。', flush=True)
        return QueryEnginePort.from_workspace()
    repl_stdin_flush_pending_if_tty()
    return eng


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
    """紧贴输入行下方、全宽持久渲染；由 ``Style`` 铺深蓝近黑底。"""
    from prompt_toolkit.formatted_text import HTML

    import html as html_mod

    from .main import render_mcp_online_toolbar_badge

    f = neural_status_fields(engine)
    m = html_mod.escape(f['model'])
    sb_txt = '🛡️ 沙箱: ON' if f['sandbox_on'] else '🔓 沙箱: OFF'
    sb_cls = 'ansigreen' if f['sandbox_on'] else 'ansired'
    tok = _token_progress_bar(f['token_pct'])
    token_bar = f'[{tok["filled"]}{tok["empty"]}] {tok["pct"]}%'
    team = (
        '<ansiyellow><b>🐺 TEAM</b></ansiyellow>'
        if f['team']
        else '<ansibrightblack>单人</ansibrightblack>'
    )
    web_badge = render_mcp_online_toolbar_badge(engine)
    feishu_seg = _feishu_toolbar_fragment_debounced()
    return HTML(
        ' '
        '<ansibrightblack>╭─ Neural Console ───────────────────────────────────────────────</ansibrightblack>\n'
        f'{web_badge}'
        '<ansicyan><b>◈</b></ansicyan> '
        f'<ansigreen><b>[{m}]</b></ansigreen>  '
        '<ansiblue>║</ansiblue>  '
        f'<{sb_cls}><b>{html_mod.escape(sb_txt)}</b></{sb_cls}>  '
        '<ansiblue>║</ansiblue>  '
        '<ansicyan><b>🧠 记忆</b></ansicyan> '
        f'<ansigreen><b>{f["memory_n"]}条</b></ansigreen>  '
        '<ansiblue>║</ansiblue>  '
        f'{team}  '
        '<ansiblue>║</ansiblue>  '
        f'{feishu_seg}\n'
        ' '
        '<ansibrightblack>╰─</ansibrightblack> '
        '<ansicyan><b>📊 Token</b></ansicyan> '
        f'<{tok["html_color"]}><b>{html_mod.escape(token_bar)}</b></{tok["html_color"]}>  '
        f'<ansibrightblack>Σ {f["total_tokens"]}</ansibrightblack>  '
        '<ansibrightblack>|</ansibrightblack>  '
        f'<{tok["html_color"]}>'
        + ('Safe' if tok['level'] == 'safe' else 'Warning' if tok['level'] == 'warning' else 'Danger')
        + f'</{tok["html_color"]}>'
    )


def _active_context_files(engine: Any) -> list[str]:
    raw = getattr(engine, 'active_context_files', None)
    if not isinstance(raw, set) or not raw:
        return []
    rows = [x for x in raw if isinstance(x, str) and x.strip()]
    rows.sort()
    return rows[:6]


def _render_context_tray_html(engine: Any) -> str:
    import html as html_mod

    items = _active_context_files(engine)
    if not items:
        return ''
    max_tray_files = 5
    shown = items[:max_tray_files]
    remain = max(0, len(items) - max_tray_files)
    chips = '  '.join(
        f'<style fg="ansicyan">📎 {html_mod.escape(p)}</style>' for p in shown
    )
    if remain > 0:
        chips += (
            f'  <style fg="ansibrightblack">...另有 {remain} 个文件</style>'
        )
    return (
        '<style fg="ansibrightblack">🗂️ Context:</style> '
        f'{chips}\n'
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
        _run_streaming_turn_tui_concurrent,
        _try_persist_repl_session,
        build_repl_banner,
        repl_stdin_flush_pending_if_tty,
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
    current_error_msg = ''
    _thinking_emojis = ['🤔', '💭', '💡', '✨', '⚡️']

    def _set_stream_input_feedback(msg: str) -> None:
        nonlocal current_error_msg
        current_error_msg = (msg or '').strip()
        try:
            app = getattr(session, 'app', None)
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    def _invalidate_prompt() -> None:
        try:
            app = getattr(session, 'app', None)
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    def _on_team_agent(agent_name: str | None) -> None:
        set_current_team_agent(agent_name)
        _invalidate_prompt()

    # 靛蓝品牌提示符：须为严格 XML（勿用 `<style ... bold>` 无值属性，会触发 ExpatError）
    input_divider = '<style fg="ansibrightblack">╭─ Input ─────────────────────────────────────────────────────</style>'

    def idle_prompt_html() -> Any:
        tray = _render_context_tray_html(engine)
        return HTML(
            f'{tray}{input_divider}\n'
            f'<style fg="{_BRAND_HEX}"><b>尖叫&gt; </b></style>'
        )

    def generating_prompt_html() -> Any:
        team_agent = get_current_team_agent()
        if team_agent:
            tip = (
                f'<style fg="ansibrightblack">🐺 {team_agent} 正在思考与执行... '
                '(输入 /stop 终止)</style>'
            )
        else:
            idx = int(time.time() * 2.5) % len(_thinking_emojis)
            tip = (
                f'<style fg="ansibrightblack">{_thinking_emojis[idx]} 神经链路生成中... '
                '(输入 /stop 终止)</style>'
            )
        err = (
            f'\n<style fg="ansired"><b>{current_error_msg}</b></style>'
            if current_error_msg
            else ''
        )
        return HTML(
            '\n'
            f'{tip}'
            f'{err}\n'
            f'{_render_context_tray_html(engine)}{input_divider}\n'
            f'<style fg="{_BRAND_HEX}"><b> 尖叫&gt; </b></style>'
        )

    while True:
        try:
            line = session.prompt(
                idle_prompt_html(),
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

        handled, new_eng, slash_outcome = dispatch_repl_slash_command(
            line, console=console, engine=engine
        )
        if new_eng is not None:
            engine = new_eng
        if handled:
            want_follow = (
                slash_outcome is not None
                and slash_outcome.trigger_llm_followup
                and (slash_outcome.followup_prompt or '').strip()
            )
            if want_follow:
                reset_agent_cancel()
                fp = slash_outcome.followup_prompt.strip()
                use_team = bool(engine.repl_team_mode)
                console.print('[dim grey42]↪ 视觉快照已注入，正在请求模型分析…[/dim grey42]')
                console.print(Rule(style=_BRAND_MUTED))
                try:
                    _run_streaming_turn_tui_concurrent(
                        session,
                        engine,
                        runtime,
                        fp,
                        console,
                        route_limit=route_limit,
                        team=use_team,
                        status_engine=None,
                        prompt_message_html=generating_prompt_html,
                        bottom_toolbar=lambda: _get_bottom_toolbar(engine),
                        on_stream_input_feedback=_set_stream_input_feedback,
                        on_stream_heartbeat=_invalidate_prompt,
                        on_team_agent=_on_team_agent,
                    )
                except KeyboardInterrupt:
                    _print_graceful_interrupt(console, use_rich=True)
                except Exception as exc:
                    try:
                        console.print(
                            f'[bold red]本回合展示层异常: {type(exc).__name__}: {exc}[/bold red]'
                        )
                    except Exception:
                        print(f'本回合异常: {type(exc).__name__}: {exc}', flush=True)
                finally:
                    repl_stdin_flush_pending_if_tty()
                    set_current_team_agent(None)
                _maybe_print_repl_memory_load_warning(console, engine, use_rich=True)
                _try_persist_repl_session(engine)
                console.print()
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
            _run_streaming_turn_tui_concurrent(
                session,
                engine,
                runtime,
                msg,
                console,
                route_limit=route_limit,
                team=use_team,
                status_engine=None,
                prompt_message_html=generating_prompt_html,
                bottom_toolbar=lambda: _get_bottom_toolbar(engine),
                on_stream_input_feedback=_set_stream_input_feedback,
                on_stream_heartbeat=_invalidate_prompt,
                on_team_agent=_on_team_agent,
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
        finally:
            repl_stdin_flush_pending_if_tty()
            set_current_team_agent(None)

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
