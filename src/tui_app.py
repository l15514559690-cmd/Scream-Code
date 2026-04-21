"""
纯 Python 终端 UI：``prompt_toolkit`` + ``rich``，替代 macOS 上易受 PTY EOF 影响的 crossterm 路径。

- **流式丝滑管线**（经 ``replLauncher._run_streaming_turn`` + ``repl_ui_render``）：
  ``Live(auto_refresh=False)`` 仅在我们节流后的帧上 ``update``；15ms 时间片 + 字形批处理，
  避免每 token 全量 Markdown 重排；终端高度绑定的**尾部视口**把滚动锁在 Live 区，scrollback 不乱跳；
  未闭合 `` ``` `` 在解析前虚拟闭合，Pygments 结构不塌。
- **定稿**：瞬态 Live 结束后靛紫 ``Panel`` / ``print_solidified_assistant_markdown`` 写入历史；首包前 ``console.status``。
- **生成中输入**：流式回合走 ``replLauncher._run_streaming_turn_tui_concurrent``：``asyncio`` + ``patch_stdout`` + ``prompt_async``，
  底部输入框在思考/输出期间仍可用；生成中仅 ``/stop`` 生效，其他输入会给出提示并继续等待；``/stop`` 与 Ctrl+C 触发 ``engine.request_stream_abort()``；回合结束 ``tcflush`` stdin 丢弃幽灵回车。
- **神经底栏**：输入行右侧 ``rprompt`` 为状态（待机不显示；活动期单格 braille 旋转）；其下 ``bottom_toolbar`` 单行指标（模型 / 沙箱 / Token 等）。旋转线程约 10fps ``invalidate``，仅在非待机标签时启动。流式时 ``Live`` 内可叠 Rich 页脚。
- **斜杠补全**：``/`` 菜单；**Enter** 在补全打开时只确认补全（见 ``repl_slash_helpers``）。
- **PTY 断开**：``EOFError`` → ``sys.exit(0)``。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

# 品牌色（Tailwind Indigo / 紫系）
_BRAND_HEX = '#4F46E5'
_BRAND_MUTED = '#6366f1'
_BRAND_SOFT = '#A5B4FC'
_ASSISTANT_SURFACE = '#161622'
_USER_ACCENT = '#c4b5fd'
_current_team_agent: str | None = None
_FEISHU_STATUS_DEBOUNCE_SEC = 3.0
_feishu_last_raw: bool = False
_feishu_last_change: float = 0.0

# 流式回合专用：底部固定「状态块」文案（与 Rich 输出分离，避免 patch_stdout 混入 scrollback）
_tui_stream_label: str = '等待指令'
_tui_prompt_invalidate: Any | None = None

# 不旋转点阵、不启动画线程的标签（待机或回合已结束）
_TUI_SPIN_IDLE_LABELS = frozenset({'等待指令', '已完成', '失败', '已中断'})


def tui_stream_label_should_spin(label: str) -> bool:
    """仅在神经活动期旋转点阵；待机/终态不转。"""
    s = (label or '').strip()
    return s not in _TUI_SPIN_IDLE_LABELS


def tui_stream_label_is_standby_idle() -> bool:
    """与「尖叫>」主循环待机一致：仅 ``等待指令`` 时右侧 rprompt 不展示。"""
    return (get_tui_stream_label() or '').strip() == '等待指令'


def register_tui_prompt_invalidate(fn: Any | None) -> None:
    """注册在状态变更时刷新 prompt_toolkit（通常为 session.app.invalidate）。"""
    global _tui_prompt_invalidate
    _tui_prompt_invalidate = fn


def set_tui_stream_label(label: str) -> None:
    """由 replLauncher 在流式各阶段更新；回合结束须回到「等待指令」。"""
    global _tui_stream_label
    _tui_stream_label = (label or '等待指令').strip() or '等待指令'
    if tui_stream_label_should_spin(_tui_stream_label):
        start_bottom_toolbar_spin_animation()
    else:
        stop_bottom_toolbar_spin_animation()
    inv = _tui_prompt_invalidate
    if callable(inv):
        try:
            inv()
        except Exception:
            pass


def get_tui_stream_label() -> str:
    return _tui_stream_label


# 输入行右侧点阵（braille）；底栏指标为单行 FormattedText
_BOTTOM_SPIN_FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
_tui_spin_frame_index = 0
_tui_spin_lock = threading.Lock()
_tui_spin_thread: threading.Thread | None = None
_tui_spin_stop = threading.Event()


def _tick_bottom_spin_frame() -> None:
    global _tui_spin_frame_index
    with _tui_spin_lock:
        _tui_spin_frame_index = (1 + _tui_spin_frame_index) % len(_BOTTOM_SPIN_FRAMES)


def _current_bottom_spin_char() -> str:
    with _tui_spin_lock:
        return _BOTTOM_SPIN_FRAMES[_tui_spin_frame_index % len(_BOTTOM_SPIN_FRAMES)]


def _bottom_toolbar_spin_loop() -> None:
    """约 10fps 刷新，仅驱动输入行右侧点阵动画（``rprompt``）。"""
    while not _tui_spin_stop.wait(0.1):
        _tick_bottom_spin_frame()
        inv = _tui_prompt_invalidate
        if callable(inv):
            try:
                inv()
            except Exception:
                pass


def start_bottom_toolbar_spin_animation() -> None:
    """在 register_tui_prompt_invalidate 之后调用；守护线程随进程退出。"""
    global _tui_spin_thread
    if _tui_spin_thread is not None and _tui_spin_thread.is_alive():
        return
    _tui_spin_stop.clear()
    _tui_spin_thread = threading.Thread(
        target=_bottom_toolbar_spin_loop,
        name='tui-bottom-spin',
        daemon=True,
    )
    _tui_spin_thread.start()


def stop_bottom_toolbar_spin_animation() -> None:
    _tui_spin_stop.set()


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


def _build_tui_prompt_session(engine: Any) -> Any:
    """
    与 ``replLauncher._build_prompt_session`` 对齐的 stdin/stdout 绑定，并挂载斜杠补全与样式。
    engine 作为必传参数，供给 rprompt lambda 闭包使用。
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
    神经状态栏数据源：供 ``bottom_toolbar``（FormattedText）与 Rich 流式页脚共用。
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


def _bottom_toolbar_token_fragments(f: dict[str, Any]) -> list[tuple[str, str]]:
    """底栏 Token：图标 + █/░ 进度条 + 当前累计用量（相对预算的比例仍由进度条表示）。"""
    total = int(f['total_tokens'])
    total_disp = f'{total:,}'

    info = _token_progress_bar(f['token_pct'])
    tok_color = str(info['html_color']).strip()
    if tok_color not in ('ansigreen', 'ansiyellow', 'ansired'):
        tok_color = 'ansigreen'
    filled_st = f'fg:{tok_color} bold'
    num_st = f'fg:{tok_color}'
    return [
        ('', '💰'),
        ('', ' '),
        (filled_st, info['filled']),
        ('fg:ansibrightblack', info['empty']),
        ('', ' '),
        (num_st, total_disp),
    ]


def neural_status_stream_footer_markup(engine: Any) -> str:
    """极简单行状态栏：去装饰线，字段用 │ 分隔。"""
    f = neural_status_fields(engine)
    m = f['model']

    mcp_on = getattr(engine, 'mcp_online_mode', False)
    mcp_txt = '[#4ade80]🛜 浏览器MCP.on[/#4ade80]' if mcp_on else '[dim]🛜 浏览器MCP.off[/dim]'

    sb_txt = '[#4ade80]🔒沙箱.on[/#4ade80]' if f['sandbox_on'] else '[dim]🔒沙箱.off[/dim]'
    team_txt = '[#facc15]🐺群狼.on[/#facc15]' if f['team'] else '[dim]🐺群狼.off[/dim]'

    fs_on = _debounced_feishu_running()
    fs_txt = '[#818cf8]📟飞书.on[/#818cf8]' if fs_on else '[dim]📟飞书.off[/dim]'

    total = int(f['total_tokens'])
    total_disp = f'{total:,}'

    info = _token_progress_bar(f['token_pct'])
    rich_c = info['rich_color']
    tok_txt = (
        f'[{rich_c}]💰 {info["filled"]}[/{rich_c}]'
        f'[dim]{info["empty"]}[/dim] '
        f'[{rich_c}]{total_disp}[/{rich_c}]'
    )

    sep = ' │ '

    return (
        f'{mcp_txt}{sep}'
        f'[bold #2dd4bf]【{m}】[/bold #2dd4bf]{sep}'
        f'{sb_txt}{sep}'
        f'[#5eead4]🧠记忆.{f["memory_n"]}条[/#5eead4]{sep}'
        f'{team_txt}{sep}'
        f'{fs_txt}{sep}'
        f'{tok_txt}'
    )


def _debounced_feishu_running() -> bool:
    global _feishu_last_raw, _feishu_last_change
    from .ui.status_bar import is_feishu_running

    now = time.monotonic()
    prev_raw = _feishu_last_raw
    raw = bool(is_feishu_running())
    if raw != _feishu_last_raw:
        _feishu_last_raw = raw
        _feishu_last_change = now
    effective = raw
    if not raw and prev_raw and (now - _feishu_last_change) < _FEISHU_STATUS_DEBOUNCE_SEC:
        effective = True
    return bool(effective)


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


_RPROMPT_STATUS_MAX_CHARS = 52


def _get_rprompt(engine: Any) -> Any:
    """
    与输入缓冲同一行、右对齐。待机（``等待指令``）整段不显示；否则活动期单格 braille + 状态，
    非活动标签仅状态字（无点阵）。
    """
    from prompt_toolkit.formatted_text import FormattedText

    _ = engine  # 预留与引擎态联动
    if tui_stream_label_is_standby_idle():
        return FormattedText([])
    status = get_tui_stream_label().replace('\n', ' ')
    if len(status) > _RPROMPT_STATUS_MAX_CHARS:
        status = status[: _RPROMPT_STATUS_MAX_CHARS - 1] + '…'
    if tui_stream_label_should_spin(get_tui_stream_label()):
        c = _current_bottom_spin_char()
        return FormattedText(
            [
                ('fg:ansicyan bold', f' {c} '),
                ('fg:ansicyan', status),
            ]
        )
    return FormattedText([('fg:ansicyan', status)])


def _get_bottom_toolbar(engine: Any) -> Any:
    """
    单行底栏：MCP / 模型 / 沙箱 / 记忆 / 群狼 / 飞书 / Token（█/░ 进度条 + 当前累计用量）。

    状态与点阵在输入行 ``rprompt``，此处不重复。
    """
    from prompt_toolkit.formatted_text import FormattedText

    f = neural_status_fields(engine)
    m = str(f['model'])

    mcp_on = getattr(engine, 'mcp_online_mode', False)
    mcp_st = 'fg:ansigreen' if mcp_on else 'fg:ansibrightblack'
    mcp_txt = '🛜 浏览器MCP.on' if mcp_on else '🛜 浏览器MCP.off'

    sb_st = 'fg:ansigreen' if f['sandbox_on'] else 'fg:ansibrightblack'
    sb_txt = '🔒沙箱.on' if f['sandbox_on'] else '🔒沙箱.off'

    team_st = 'fg:ansiyellow' if f['team'] else 'fg:ansibrightblack'
    team_txt = '🐺群狼.on' if f['team'] else '🐺群狼.off'

    fs_on = _debounced_feishu_running()
    fs_st = 'fg:ansipurple' if fs_on else 'fg:ansibrightblack'
    fs_txt = '📟飞书.on' if fs_on else '📟飞书.off'

    sep = ' │ '

    parts: list[tuple[str, str]] = [
        (mcp_st, mcp_txt),
        ('', sep),
        ('fg:ansicyan', f'【{m}】'),
        ('', sep),
        (sb_st, sb_txt),
        ('', sep),
        ('fg:ansicyan', f'🧠记忆.{f["memory_n"]}条'),
        ('', sep),
        (team_st, team_txt),
        ('', sep),
        (fs_st, fs_txt),
        ('', sep),
    ]
    parts.extend(_bottom_toolbar_token_fragments(f))
    return FormattedText(parts)


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


def _render_context_tray_html_one_line(engine: Any) -> str:
    """与 idle 提示同源，但无换行，供生成中与 patch_stdout 共存时避免多行提示与 Rich 交错。"""
    raw = _render_context_tray_html(engine).strip()
    return raw.replace('\n', ' ')


def run_python_tui_repl(*, llm_enabled: bool = True, route_limit: int = 5) -> int:
    """
    进入 Python TUI 主循环，并与 ``QueryEnginePort.iter_repl_assistant_events_with_runtime`` 桥接。

    返回进程退出码；``EOFError``（PTY 关闭）时直接 ``sys.exit(0)``，不返回。
    """
    from dataclasses import replace

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

    session = _build_tui_prompt_session(engine)

    def _invalidate_tui_app() -> None:
        try:
            app = getattr(session, 'app', None)
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    register_tui_prompt_invalidate(_invalidate_tui_app)
    set_tui_stream_label('等待指令')

    current_error_msg = ''

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

    _stream_toolbar_sig: tuple[Any, ...] | None = None

    def _toolbar_refresh_signature() -> tuple[Any, ...]:
        """与底部状态栏展示相关的字段快照；仅当变化时才应触发 invalidate，避免流式期间整屏闪烁。"""
        f = neural_status_fields(engine)
        mcp_on = getattr(engine, 'mcp_online_mode', False)
        fs_on = _debounced_feishu_running()
        try:
            budget = int(getattr(getattr(engine, 'config', None), 'max_budget_tokens', 12000000))
        except Exception:
            budget = 12000000
        return (
            f['model'],
            f['sandbox_on'],
            f['memory_n'],
            f['token_pct'],
            f['total_tokens'],
            f['team'],
            mcp_on,
            fs_on,
            budget,
            get_tui_stream_label(),
        )

    def _on_stream_heartbeat_refresh_if_changed() -> None:
        nonlocal _stream_toolbar_sig
        try:
            sig = _toolbar_refresh_signature()
            if _stream_toolbar_sig is None:
                _stream_toolbar_sig = sig
                return
            if sig != _stream_toolbar_sig:
                _stream_toolbar_sig = sig
                _invalidate_prompt()
        except Exception:
            pass

    def _on_team_agent(agent_name: str | None) -> None:
        set_current_team_agent(agent_name)
        _invalidate_prompt()

    def idle_prompt_html() -> Any:
        tray = _render_context_tray_html(engine)
        return HTML(
            f'{tray}<style fg="{_BRAND_HEX}"><b>尖叫&gt; </b></style>'
        )

    def generating_prompt_html() -> Any:
        # 流式状态由输入行 rprompt 展示；此处只保留上下文托盘等，不再叠「尖叫>」以免与 Rich / patch_stdout 交错
        err_html = (
            f'<style fg="ansired"><b>{current_error_msg}</b></style> '
            if current_error_msg
            else ''
        )
        is_approving = getattr(engine, 'pending_tool_approval', None) is not None
        if is_approving:
            return HTML('<style fg="ansired"><b>[Y/n/a] 审批&gt; </b></style>')
        tray = _render_context_tray_html_one_line(engine)
        tray_sep = f'{tray} ' if tray else ''
        combined = f'{err_html}{tray_sep}'.strip()
        if not combined:
            return HTML('')
        return HTML(combined)

    while True:
        try:
            line = session.prompt(
                idle_prompt_html(),
                rprompt=lambda: _get_rprompt(engine),
                bottom_toolbar=lambda: _get_bottom_toolbar(engine),
            ).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            if isinstance(exc, EOFError):
                stop_bottom_toolbar_spin_animation()
                sys.exit(0)
            console.print()
            continue

        if line == '':
            continue
        if line.lower() in ('exit', 'quit', 'q'):
            console.print('[dim]再见。[/dim]')
            stop_bottom_toolbar_spin_animation()
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
                        rprompt=lambda: _get_rprompt(engine),
                        on_stream_input_feedback=_set_stream_input_feedback,
                        on_stream_heartbeat=_on_stream_heartbeat_refresh_if_changed,
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
        # 分隔线由流式回合内 print_cyber_turn_divider 统一打印，此处不再叠一条以免双横线
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
                rprompt=lambda: _get_rprompt(engine),
                on_stream_input_feedback=_set_stream_input_feedback,
                on_stream_heartbeat=_on_stream_heartbeat_refresh_if_changed,
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
