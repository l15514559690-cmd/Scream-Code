from __future__ import annotations

import io
import itertools
import json
import sys
import time
from typing import Any

from .agent_cancel import reset_agent_cancel

# 引入活泼的 ASCII / 全角颜文字作为思考动画（与 _poll 内 Status.update 联动）
KAWAII_FRAMES = [
    '(>_<)',
    '(^_^;)',
    '(＠_＠;)',
    '(T_T)',
    '(-_-;)',
    '(~_~;)',
    '(*_*)',
    '(°_o)',
    '(•_•)',
    '(@_@)',
    '(╯°□°）╯',
]
_kawaii_cycle = itertools.cycle(KAWAII_FRAMES)

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
        '当前为「仅说明」模式（例如使用了 `repl --no-llm`）。'
        '要进入可对话的交互循环并调用大模型，请执行不带 `--no-llm` 的 `python3 -m src.main repl`'
        '（密钥见 llm_config.json / .env）。也可使用 `summary` 或 `config`。'
    )


def _logo_plain() -> str:
    return '\n'.join(_SLANT_LOGO_LINES)


# 记忆水位（仅 REPL 展示层；不截断请求、不改写历史）
REPL_MEMORY_WARN_TOTAL_TOKENS = 800_000
REPL_MEMORY_WARN_USER_TURNS = 200
REPL_MEMORY_WARN_REPEAT_TOKEN_DELTA = 200_000
REPL_MEMORY_WARN_REPEAT_TURN_DELTA = 40
# 兼容旧名：默认 token 阈值
TOKEN_WARNING_THRESHOLD = REPL_MEMORY_WARN_TOTAL_TOKENS
# session_id -> (上次预警时的累计 tokens, 上次预警时的用户轮次数)
_REPL_MEMORY_WARN_LAST: dict[str, tuple[int, int]] = {}


def _ensure_stdio_utf8() -> None:
    """
    将标准流尽量设为 UTF-8，避免区域设置为 C/latin-1 时中文在 prompt_toolkit 中显示为乱码。
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconf = getattr(stream, 'reconfigure', None)
        if not callable(reconf):
            continue
        try:
            reconf(encoding='utf-8', errors='replace')
        except (OSError, ValueError, TypeError, io.UnsupportedOperation):
            pass


def _repl_terminal_soft_reset(console: Any | None) -> None:
    """
    Rich（Live / Status）与 prompt_toolkit 交替使用后，部分终端会残留光标或模式状态，
    导致下一行输入错位或 UTF-8 字符显示异常；在每回合结束后做一次轻量恢复。
    """
    if console is not None:
        try:
            show = getattr(console, 'show_cursor', None)
            if callable(show):
                show(True)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


def clear_all_repl_token_warnings() -> None:
    """供 ``/new`` 等硬重置：清空记忆水位预警的会话缓存（展示层）。"""
    _REPL_MEMORY_WARN_LAST.clear()


def _try_persist_repl_session(engine: Any) -> None:
    """每回合结束后写入 ``.port_sessions/``，便于关闭终端后自动续聊。"""
    try:
        engine.persist_session()
    except OSError:
        pass


def repl_stdin_flush_pending_if_tty() -> None:
    """
    丢弃内核里已为 stdin 排队、但本进程尚未读取的字节。

    在**成功从磁盘恢复会话之后**、首次 ``prompt``/``input`` 之前调用，可避免终端或宿主
    误注入的上行（例如残留换行）被当成用户主动提交的第一句话，从而意外触发 LLM 回合。
    非 TTY（管道/重定向）下不操作。
    """
    if not sys.stdin.isatty():
        return
    try:
        import termios
    except ImportError:
        return
    try:
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (OSError, AttributeError):
        pass


def _repl_engine_autoresume(console: Any | None, *, use_rich: bool) -> Any:
    """
    若 ``.port_sessions/`` 下存在最近修改的会话 JSON，则 ``from_saved_session`` 恢复；否则空会话。
    不改变 ``session_store`` 的读写格式，仅组合现有 API。
    """
    from .query_engine import QueryEnginePort
    from .session_store import most_recent_saved_session_id

    sid = most_recent_saved_session_id()
    if not sid:
        return QueryEnginePort.from_workspace()
    try:
        eng = QueryEnginePort.from_saved_session(sid)
    except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return QueryEnginePort.from_workspace()
    repl_stdin_flush_pending_if_tty()
    if use_rich and console is not None:
        console.print(
            f'[dim]已自动恢复上次会话记忆 (ID: {sid})，如需开启全新对话请输出 /new[/dim]'
        )
    else:
        print(
            f'已自动恢复上次会话记忆 (ID: {sid})；全新对话请输入 /new',
            flush=True,
        )
    return eng


def _safe_close_generator(gen: Any) -> None:
    """关闭事件生成器时吞掉各类异常，避免二次堆栈污染终端。"""
    if gen is None:
        return
    try:
        gen.close()
    except BaseException:
        pass


def _token_warning_threshold_for_engine(engine: Any) -> int:
    """优先读取 ``engine.config.token_warning_threshold``（若为正整数），否则默认 ``REPL_MEMORY_WARN_TOTAL_TOKENS``。"""
    cfg = getattr(engine, 'config', None)
    if cfg is None:
        return REPL_MEMORY_WARN_TOTAL_TOKENS
    raw = getattr(cfg, 'token_warning_threshold', None)
    if isinstance(raw, int) and raw > 0:
        return raw
    return REPL_MEMORY_WARN_TOTAL_TOKENS


def _maybe_print_repl_memory_load_warning(
    console: Any | None, engine: Any, *, use_rich: bool
) -> None:
    """
    记忆水位预警：仅 ``console.print``，不截断、不改写 engine。
    在流式回合正常结束后调用。首次在「累计 tokens ≥ 阈值」或「用户轮次 ≥ 阈值」时提示；
    之后仅当 tokens 再增 ``REPL_MEMORY_WARN_REPEAT_TOKEN_DELTA`` 或轮次再增
    ``REPL_MEMORY_WARN_REPEAT_TURN_DELTA`` 时重复提示。token 与轮次均回落至阈值以下时重置。
    """
    try:
        u = getattr(engine, 'total_usage', None)
        if u is None:
            return
        inp = int(getattr(u, 'input_tokens', 0))
        outp = int(getattr(u, 'output_tokens', 0))
        current_tokens = inp + outp
    except (TypeError, ValueError):
        return

    msgs = getattr(engine, 'mutable_messages', None) or []
    try:
        user_turns = len(msgs)
    except TypeError:
        user_turns = 0

    token_th = _token_warning_threshold_for_engine(engine)
    turn_th = REPL_MEMORY_WARN_USER_TURNS
    sid = str(getattr(engine, 'session_id', '') or '') or str(id(engine))

    below_tokens = current_tokens < token_th
    below_turns = user_turns < turn_th
    if below_tokens and below_turns:
        _REPL_MEMORY_WARN_LAST.pop(sid, None)
        return

    prev = _REPL_MEMORY_WARN_LAST.get(sid)
    if prev is None:
        should_warn = True
    else:
        last_tok, last_turn = prev
        should_warn = (
            current_tokens - last_tok >= REPL_MEMORY_WARN_REPEAT_TOKEN_DELTA
            or user_turns - last_turn >= REPL_MEMORY_WARN_REPEAT_TURN_DELTA
        )

    if not should_warn:
        return

    _REPL_MEMORY_WARN_LAST[sid] = (current_tokens, user_turns)

    from .repl_ui_render import build_token_warning_panel, format_token_warning_plain

    if use_rich and console is not None:
        console.print()
        console.print(build_token_warning_panel(current_tokens, token_th))
        return

    print(format_token_warning_plain(current_tokens, token_th), end='', flush=True)


def _print_graceful_interrupt(console: Any | None, *, use_rich: bool) -> None:
    """
    Ctrl+C 后的统一提示：保留已输出内容，REPL 不退出，会话对象不丢弃。
    """
    primary = '⏸ 已手动中断'
    hint = (
        '当前已输出内容已保留。可直接输入下一句继续；本轮若未跑完则不会写入完整对话历史。'
        '输入 exit 退出。'
    )
    if use_rich and console is not None:
        console.print(f'[bold yellow]{primary}[/bold yellow]')
        console.print(f'[dim]{hint}[/dim]')
        return
    print(f'\n{primary}。{hint}', flush=True)


def print_project_memory_loaded_notice() -> None:
    """Logo 之后调用：若工作区根下存在可用的项目记忆文件，打印一行绿色提示。"""
    from .project_memory import project_memory_workspace_root, read_first_available_project_memory

    name, _ = read_first_available_project_memory(project_memory_workspace_root())
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


def _print_assistant_output(console: object, text: str) -> None:
    from .repl_ui_render import final_assistant_markdown_panel

    stripped = text.strip()
    if not stripped:
        return
    # Live（transient）清场后，仅此一份完整 Panel 写入 scrollback
    console.print(final_assistant_markdown_panel(stripped))
    console.print()


def _print_assistant_error(console: object, message: str) -> None:
    from rich.text import Text

    from .repl_ui_render import assistant_panel

    console.print(assistant_panel(Text(message, style='bold red')))
    console.print()


def _dedupe_assistant_scrollback_echoes(text: str) -> str:
    """
    折叠展示层偶发的「同段自我介绍 / 同句」重影：相邻完全相同的段落或文本行只保留一份。
    不影响有意重复的结构化列表（仅合并**连续**相同块）。
    """
    raw = (text or '').strip()
    if not raw:
        return raw
    paras = [p.strip() for p in raw.split('\n\n') if p.strip()]
    merged_p: list[str] = []
    for p in paras:
        if merged_p and p == merged_p[-1]:
            continue
        merged_p.append(p)
    t2 = '\n\n'.join(merged_p)
    lines = t2.splitlines()
    out_ln: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s and out_ln and s == out_ln[-1].strip():
            continue
        out_ln.append(ln)
    return '\n'.join(out_ln).strip()


class _StreamingTurnSession:
    """单次 LLM 流式回合：后台线程跑事件生成器，主线程或 asyncio 驱动 Rich Live 消费队列。"""

    def __init__(
        self,
        engine: Any,
        runtime: Any,
        line: str,
        console: Any,
        *,
        route_limit: int,
        team: bool,
        status_engine: Any | None,
    ) -> None:
        self.engine = engine
        self.runtime = runtime
        self.line = line
        self.console = console
        self.route_limit = route_limit
        self.team = team
        self.status_engine = status_engine
        self.use_live = bool(
            getattr(console, 'is_terminal', False) and console.is_terminal
        )
        self.gen = engine.iter_repl_assistant_events_with_runtime(
            line, runtime=runtime, route_limit=route_limit, team=team
        )
        import queue

        self.outq: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=0)
        self.buffer = ''
        self.tool_streaming_buffer = ''
        self.live: Any = None
        self.round_saw_tool_json_stream = False
        self.last_render_time = 0.0
        self.last_painted_display_len = 0

    def start_worker(self) -> None:
        import threading

        outq = self.outq
        gen = self.gen

        def _worker() -> None:
            try:
                for ev in gen:
                    outq.put(('ok', ev))
                outq.put(('stop', None))
            except BaseException as exc:
                outq.put(('err', exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _streaming_display_payload(self) -> str:
        display_text = self.buffer
        if self.tool_streaming_buffer:
            tool_lines = self.tool_streaming_buffer.splitlines()
            if len(tool_lines) > 15:
                rolling_tool = '...\n' + '\n'.join(tool_lines[-15:])
            else:
                rolling_tool = self.tool_streaming_buffer
            display_text += (
                '\n\n> ⚙️ **正在编写代码与工具参数...**\n```json\n'
                f'{rolling_tool}\n```'
            )
        return display_text

    def _live_frame_renderable(self, display_text: str) -> Any:
        from .repl_ui_render import streaming_markdown_for_live

        md = streaming_markdown_for_live(display_text, console=self.console)
        if self.status_engine is None:
            return md
        from rich.console import Group
        from rich.text import Text

        from .tui_app import neural_status_stream_footer_markup

        try:
            w = int(
                getattr(getattr(self.console, 'size', None), 'width', None) or 80
            )
        except (TypeError, ValueError):
            w = 80
        rule_w = max(24, min(max(w - 2, 24), 120))
        rule = Text('▔' * rule_w, style='dim #0f172a')
        foot = Text.from_markup(
            neural_status_stream_footer_markup(self.status_engine)
        )
        foot.overflow = 'ellipsis'
        foot.no_wrap = True
        return Group(md, rule, foot)

    def _apply_streaming_live(self, *, force: bool, queue_quiet: bool) -> None:
        from .repl_ui_render import (
            STREAM_LIVE_MIN_CHAR_DELTA,
            STREAM_LIVE_MIN_INTERVAL_SEC,
        )
        from rich.live import Live

        if not self.use_live:
            return
        display_text = self._streaming_display_payload()
        if not display_text.strip():
            return
        dlen = len(display_text)
        now = time.time()
        if not force:
            if dlen == self.last_painted_display_len:
                return
            delta = dlen - self.last_painted_display_len
            elapsed = now - self.last_render_time
            if self.live is not None:
                if (
                    delta < STREAM_LIVE_MIN_CHAR_DELTA
                    and elapsed < STREAM_LIVE_MIN_INTERVAL_SEC
                    and not queue_quiet
                ):
                    return
        frame = self._live_frame_renderable(display_text)
        if self.live is None:
            self.live = Live(
                frame,
                console=self.console,
                auto_refresh=True,
                refresh_per_second=30,
                transient=True,
                vertical_overflow='ellipsis',
            )
            self.live.start(refresh=True)
        else:
            try:
                self.live.update(frame)
            except BaseException:
                pass
        self.last_render_time = now
        self.last_painted_display_len = dlen

    def _squash_live_for_halt(self) -> None:
        if self.use_live and self._streaming_display_payload().strip():
            self._apply_streaming_live(force=True, queue_quiet=True)

    def _stop_live(self) -> None:
        if self.live is not None:
            try:
                self.live.stop()
            except BaseException:
                pass
            self.live = None
        self.last_render_time = 0.0
        self.last_painted_display_len = 0

    @staticmethod
    def _queue_try_get(outq: Any) -> tuple[str, Any] | None:
        import queue

        try:
            return outq.get(timeout=0.12)
        except queue.Empty:
            return None

    def _poll_sync(self, *, show_thinking_status: bool) -> dict[str, Any] | None:
        from contextlib import nullcontext

        status_obj: Any = None
        if show_thinking_status and self.live is None and self.use_live:
            status_obj = self.console.status(
                f'[bold #a5b4fc]⟁ 神经链路同步中 {next(_kawaii_cycle)}[/]',
                spinner='point',
            )
            status_ctx: Any = status_obj
        else:
            status_ctx = nullcontext()

        with status_ctx:
            last_status_anim = time.time()
            while True:
                if (
                    status_obj is not None
                    and self.use_live
                    and (time.time() - last_status_anim > 0.3)
                ):
                    status_obj.update(
                        f'[bold #a5b4fc]⟁ 神经链路同步中 {next(_kawaii_cycle)}[/]'
                    )
                    last_status_anim = time.time()

                item = self._queue_try_get(self.outq)
                if item is None:
                    continue
                kind, payload = item
                if kind == 'ok':
                    return payload
                if kind == 'stop':
                    return None
                if kind == 'err':
                    if isinstance(payload, GeneratorExit):
                        raise KeyboardInterrupt from None
                    raise payload

    async def _poll_async(self, *, show_thinking_status: bool) -> dict[str, Any] | None:
        import asyncio
        from contextlib import nullcontext

        status_obj: Any = None
        if show_thinking_status and self.live is None and self.use_live:
            status_obj = self.console.status(
                f'[bold #a5b4fc]⟁ 神经链路同步中 {next(_kawaii_cycle)}[/]',
                spinner='point',
            )
            status_ctx: Any = status_obj
        else:
            status_ctx = nullcontext()

        with status_ctx:
            last_status_anim = time.time()
            while True:
                if (
                    status_obj is not None
                    and self.use_live
                    and (time.time() - last_status_anim > 0.3)
                ):
                    status_obj.update(
                        f'[bold #a5b4fc]⟁ 神经链路同步中 {next(_kawaii_cycle)}[/]'
                    )
                    last_status_anim = time.time()

                item = await asyncio.to_thread(self._queue_try_get, self.outq)
                if item is None:
                    await asyncio.sleep(0)
                    continue
                kind, payload = item
                if kind == 'ok':
                    return payload
                if kind == 'stop':
                    return None
                if kind == 'err':
                    if isinstance(payload, GeneratorExit):
                        raise KeyboardInterrupt from None
                    raise payload

    def _drain_queue_after_interrupt(self) -> None:
        import queue

        try:
            while True:
                self.outq.get_nowait()
        except queue.Empty:
            pass

    def _process_stream_deltas(self, ev: dict[str, Any]) -> None:
        et = ev['type']
        if et == 'text_delta':
            self.buffer += ev.get('text', '')
        else:
            self.tool_streaming_buffer += ev.get('fragment', '')
            self.round_saw_tool_json_stream = True

        while not self.outq.empty():
            try:
                kind, payload = self.outq.queue[0]
                if kind == 'ok' and payload.get('type') in ('text_delta', 'tool_delta'):
                    self.outq.get_nowait()
                    if payload['type'] == 'text_delta':
                        self.buffer += payload.get('text', '')
                    else:
                        self.tool_streaming_buffer += payload.get('fragment', '')
                        self.round_saw_tool_json_stream = True
                else:
                    break
            except Exception:
                break

        queue_quiet = self.outq.empty()
        self._apply_streaming_live(force=False, queue_quiet=queue_quiet)

    def _finish_turn_success(self, ev: dict[str, Any]) -> None:
        from .repl_ui_render import (
            print_cyber_turn_divider,
            print_solidified_assistant_markdown,
            tool_params_stream_collapsed_panel,
        )

        # 不在此再 squash Live：最后一帧若经 transient Live 与定稿 Panel 双写，易造成 scrollback 重影。
        self._stop_live()
        out = ev.get('output', '')
        show_tool_collapse = self.round_saw_tool_json_stream or bool(
            self.tool_streaming_buffer.strip()
        )
        body = ''
        if self.buffer.strip():
            body = self.buffer.strip()
        elif isinstance(out, str) and out.strip():
            body = out.strip()
        body = _dedupe_assistant_scrollback_echoes(body) if body else body
        if body:
            print_solidified_assistant_markdown(self.console, body)
        if show_tool_collapse:
            self.console.print(
                tool_params_stream_collapsed_panel(
                    self.tool_streaming_buffer.strip() or None
                )
            )
        if body or show_tool_collapse:
            self.console.print()
        print_cyber_turn_divider(self.console)

    def run_sync_loop(self) -> None:
        from .repl_ui_render import (
            build_api_tool_op_renderable,
            print_cyber_turn_divider,
            tool_execution_status_message,
        )

        if self.use_live:
            print_cyber_turn_divider(self.console)

        pending: dict[str, Any] | None = self._poll_sync(
            show_thinking_status=self.use_live and self.live is None
        )
        while pending is not None:
            ev = pending
            pending = None
            et = ev['type']

            if et == 'blocked':
                self._squash_live_for_halt()
                self._stop_live()
                _print_assistant_output(self.console, ev['output'])
                return
            if et == 'llm_error':
                self._squash_live_for_halt()
                self._stop_live()
                _print_assistant_error(self.console, ev['output'])
                return
            if et == 'team_agent':
                self._squash_live_for_halt()
                self._stop_live()
                agent = str(ev.get('agent', 'Agent'))
                styles = {
                    'Planner': 'bold cyan',
                    'Coder': 'bold green',
                    'Reviewer': 'bold yellow',
                }
                st = styles.get(agent, 'bold white')
                self.console.print(f'[{st}]━━ {agent} ━━[/{st}]')
                pending = self._poll_sync(
                    show_thinking_status=self.use_live and self.live is None
                )
                continue
            if et == 'non_llm':
                self._squash_live_for_halt()
                self._stop_live()
                _print_assistant_output(self.console, ev['output'])
                return
            if et == 'tool_phase':
                self._squash_live_for_halt()
                self._stop_live()
                label = ', '.join(ev['tools'])
                self.console.print(
                    f'[bold yellow]⚙️ 正在执行工具: {label}[/bold yellow]'
                )
                pending = self._poll_sync(
                    show_thinking_status=self.use_live and self.live is None
                )
                continue
            if et == 'api_tool_op':
                self._squash_live_for_halt()
                self._stop_live()
                if self.buffer.strip():
                    _print_assistant_output(self.console, self.buffer)
                self.buffer = ''
                self.tool_streaming_buffer = ''
                self.console.print(build_api_tool_op_renderable(ev))
                self.console.print()
                tool_name = str(ev.get('tool_name', 'tool'))
                with self.console.status(
                    tool_execution_status_message(tool_name),
                    spinner='dots12',
                    spinner_style='cyan',
                ):
                    pending = self._poll_sync(show_thinking_status=False)
                continue
            if et in ('text_delta', 'tool_delta'):
                self._process_stream_deltas(ev)
                pending = self._poll_sync(show_thinking_status=False)
                continue
            if et == 'finished':
                self._finish_turn_success(ev)
                return

            pending = self._poll_sync(
                show_thinking_status=self.use_live and self.live is None
            )

    async def run_async_loop(self) -> None:
        from .repl_ui_render import (
            build_api_tool_op_renderable,
            print_cyber_turn_divider,
            tool_execution_status_message,
        )

        if self.use_live:
            print_cyber_turn_divider(self.console)

        pending: dict[str, Any] | None = await self._poll_async(
            show_thinking_status=self.use_live and self.live is None
        )
        while pending is not None:
            ev = pending
            pending = None
            et = ev['type']

            if et == 'blocked':
                self._squash_live_for_halt()
                self._stop_live()
                _print_assistant_output(self.console, ev['output'])
                return
            if et == 'llm_error':
                self._squash_live_for_halt()
                self._stop_live()
                _print_assistant_error(self.console, ev['output'])
                return
            if et == 'team_agent':
                self._squash_live_for_halt()
                self._stop_live()
                agent = str(ev.get('agent', 'Agent'))
                styles = {
                    'Planner': 'bold cyan',
                    'Coder': 'bold green',
                    'Reviewer': 'bold yellow',
                }
                st = styles.get(agent, 'bold white')
                self.console.print(f'[{st}]━━ {agent} ━━[/{st}]')
                pending = await self._poll_async(
                    show_thinking_status=self.use_live and self.live is None
                )
                continue
            if et == 'non_llm':
                self._squash_live_for_halt()
                self._stop_live()
                _print_assistant_output(self.console, ev['output'])
                return
            if et == 'tool_phase':
                self._squash_live_for_halt()
                self._stop_live()
                label = ', '.join(ev['tools'])
                self.console.print(
                    f'[bold yellow]⚙️ 正在执行工具: {label}[/bold yellow]'
                )
                pending = await self._poll_async(
                    show_thinking_status=self.use_live and self.live is None
                )
                continue
            if et == 'api_tool_op':
                self._squash_live_for_halt()
                self._stop_live()
                if self.buffer.strip():
                    _print_assistant_output(self.console, self.buffer)
                self.buffer = ''
                self.tool_streaming_buffer = ''
                self.console.print(build_api_tool_op_renderable(ev))
                self.console.print()
                tool_name = str(ev.get('tool_name', 'tool'))
                with self.console.status(
                    tool_execution_status_message(tool_name),
                    spinner='dots12',
                    spinner_style='cyan',
                ):
                    pending = await self._poll_async(show_thinking_status=False)
                continue
            if et in ('text_delta', 'tool_delta'):
                self._process_stream_deltas(ev)
                pending = await self._poll_async(show_thinking_status=False)
                continue
            if et == 'finished':
                self._finish_turn_success(ev)
                return

            pending = await self._poll_async(
                show_thinking_status=self.use_live and self.live is None
            )

    def finalize(self) -> None:
        self._stop_live()
        _repl_terminal_soft_reset(self.console)


# REPL 单行历史仅驻内存；限制条数避免极长会话下 list 膨胀拖慢 prompt_toolkit
_REPL_HISTORY_MAX_ITEMS = 512


def _build_prompt_session() -> Any | None:
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import ThreadedCompleter
        from prompt_toolkit.history import InMemoryHistory
    except ImportError:
        return None

    if not sys.stdin.isatty():
        return None

    from .repl_slash_helpers import (
        SlashCommandCompleter,
        prompt_toolkit_scream_slash_style,
        prompt_toolkit_slash_completion_enter_bindings,
    )

    class _BoundedInMemoryHistory(InMemoryHistory):
        """不启用 FileHistory；超限时丢弃最旧条目，避免历史列表无限增长。"""

        def __init__(self, cap: int) -> None:
            super().__init__()
            self._cap = max(32, cap)

        def store_string(self, string: str) -> None:
            super().store_string(string)
            over = len(self._storage) - self._cap
            if over > 0:
                del self._storage[0:over]

    history = _BoundedInMemoryHistory(_REPL_HISTORY_MAX_ITEMS)
    # 与 Rich 共用同一 stdin/stdout 句柄，避免编码/缓冲与 PTY 状态分裂导致中文乱码
    try:
        from prompt_toolkit.input.defaults import create_input
        from prompt_toolkit.output.defaults import create_output
    except ImportError:
        create_input = None  # type: ignore[misc, assignment]
        create_output = None  # type: ignore[misc, assignment]

    kw: dict[str, Any] = {
        'history': history,
        'completer': ThreadedCompleter(SlashCommandCompleter()),
        'complete_while_typing': True,
        'validate_while_typing': False,
        'mouse_support': False,
        'enable_suspend': False,
        'style': prompt_toolkit_scream_slash_style(),
        'key_bindings': prompt_toolkit_slash_completion_enter_bindings(),
    }
    if create_input is not None and create_output is not None:
        kw['input'] = create_input()
        kw['output'] = create_output()
    # 斜杠指令：边输边弹出补全（与 ``tui_app`` 一致）；mouse/suspend 仍关闭以免与 Rich 争用终端
    return PromptSession(**kw)


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
        _print_graceful_interrupt(console, use_rich=use_rich_input)
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
        _safe_close_generator(gen)
        _print_graceful_interrupt(None, use_rich=False)
    except Exception as exc:
        _safe_close_generator(gen)
        print(f'[LLM] 事件流异常: {type(exc).__name__}: {exc}', flush=True)


def _run_streaming_turn(
    engine: Any,
    runtime: Any,
    line: str,
    console: Any,
    *,
    route_limit: int,
    team: bool = False,
    status_engine: Any | None = None,
) -> None:
    from .agent_cancel import request_agent_cancel

    sess = _StreamingTurnSession(
        engine,
        runtime,
        line,
        console,
        route_limit=route_limit,
        team=team,
        status_engine=status_engine,
    )
    sess.start_worker()
    try:
        sess.run_sync_loop()
    except KeyboardInterrupt:
        _safe_close_generator(sess.gen)
        sess._drain_queue_after_interrupt()
        sess._squash_live_for_halt()
        sess._stop_live()
        try:
            engine.request_stream_abort()
        except Exception:
            request_agent_cancel()
        _print_graceful_interrupt(console, use_rich=True)
    finally:
        sess.finalize()


def _reset_prompt_session_validator_after_stream(session: Any) -> None:
    """
    ``PromptSession.prompt_async(..., validator=…)`` 在 prompt_toolkit 内会**持久写入**
    ``session.validator``（仅当参数非 None 时赋值，传 None 不会清除旧值）。
    并发流式回合结束后必须清空，否则下一轮 ``prompt()`` 仍套用「仅 /stop」校验，用户无法输入。
    """
    try:
        session.validator = None
    except Exception:
        pass


def _run_streaming_turn_tui_concurrent(
    session: Any,
    engine: Any,
    runtime: Any,
    line: str,
    console: Any,
    *,
    route_limit: int,
    team: bool,
    status_engine: Any | None,
    prompt_message_html: Any,
    bottom_toolbar: Any,
) -> None:
    import asyncio

    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.validation import Validator

    from .agent_cancel import request_agent_cancel

    # 并发 TUI 模式下底部交互由 prompt_toolkit 独占，避免与 Rich Live 页脚双层叠加。
    sess = _StreamingTurnSession(
        engine,
        runtime,
        line,
        console,
        route_limit=route_limit,
        team=team,
        status_engine=None,
    )
    sess.start_worker()
    turn_done = asyncio.Event()
    active_prompt_task: asyncio.Task[str] | None = None

    async def _cancel_active_prompt_task() -> None:
        nonlocal active_prompt_task
        t = active_prompt_task
        if t is None:
            return
        if not t.done():
            t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        active_prompt_task = None

    async def _drive_input() -> None:
        nonlocal active_prompt_task
        stop_only_validator = Validator.from_callable(
            lambda text: (text or '').strip() == '/stop',
            error_message='当前正在生成响应，仅支持输入 /stop 终止任务',
            move_cursor_to_end=True,
        )
        prompt_task = asyncio.create_task(
            session.prompt_async(
                prompt_message_html,
                bottom_toolbar=bottom_toolbar,
                handle_sigint=True,
                validator=stop_only_validator,
                validate_while_typing=False,
            )
        )
        active_prompt_task = prompt_task
        wait_turn = asyncio.create_task(turn_done.wait())
        done, _ = await asyncio.wait(
            {prompt_task, wait_turn},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if wait_turn in done:
            await _cancel_active_prompt_task()
            return
        wait_turn.cancel()
        try:
            await wait_turn
        except asyncio.CancelledError:
            pass
        try:
            text = prompt_task.result()
        except asyncio.CancelledError:
            active_prompt_task = None
            return
        except KeyboardInterrupt:
            active_prompt_task = None
            try:
                engine.request_stream_abort()
            except Exception:
                request_agent_cancel()
            await turn_done.wait()
            return
        active_prompt_task = None
        if turn_done.is_set():
            return
        if (text or '').strip() == '/stop':
            try:
                engine.request_stream_abort()
            except Exception:
                request_agent_cancel()
            await turn_done.wait()

    async def _drive_stream() -> None:
        try:
            with patch_stdout(raw=True):
                await sess.run_async_loop()
        finally:
            turn_done.set()
            await _cancel_active_prompt_task()

    async def _runner() -> None:
        stream_task = asyncio.create_task(_drive_stream())
        input_task = asyncio.create_task(_drive_input())
        try:
            await stream_task
        finally:
            turn_done.set()
            await _cancel_active_prompt_task()
            input_task.cancel()
            try:
                await input_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        _safe_close_generator(sess.gen)
        sess._drain_queue_after_interrupt()
        try:
            engine.request_stream_abort()
        except Exception:
            request_agent_cancel()
        sess._squash_live_for_halt()
        sess._stop_live()
        _print_graceful_interrupt(console, use_rich=True)
    finally:
        _reset_prompt_session_validator_after_stream(session)
        sess.finalize()


def run_repl_interactive_loop(*, llm_enabled: bool, route_limit: int = 5) -> int:
    """打印 Logo 后进入交互：默认可用大模型路径为 prompt_toolkit + Rich Live 流式 Markdown。"""
    from dataclasses import replace

    try:
        from rich.console import Console
        from rich.rule import Rule
    except ImportError:
        Console = None  # type: ignore[misc, assignment]

    from .runtime import PortRuntime

    print_startup_banner(ensure_config=True)
    print_project_memory_loaded_notice()
    if not llm_enabled:
        print(build_repl_banner())
        return 0

    if Console is None:
        print('大模型 REPL：将调用 API。输入 exit / quit 结束。')
        print(
            '斜杠指令: /help · /new /memo · doctor cost diff status · team · 记忆/体检/引擎类\n'
        )
        print_repl_llm_driver_banner(console=None)
        from .repl_slash_commands import dispatch_repl_slash_command

        runtime = PortRuntime()
        engine = _repl_engine_autoresume(None, use_rich=False)
        engine.config = replace(engine.config, llm_enabled=True)
        while True:
            try:
                line = input('尖叫> ').strip()
            except EOFError:
                print('\n再见。')
                return 0
            except KeyboardInterrupt:
                _print_graceful_interrupt(None, use_rich=False)
                continue
            if not line:
                continue
            if line.lower() in ('exit', 'quit', 'q'):
                print('再见。')
                return 0
            handled, new_eng, slash_outcome = dispatch_repl_slash_command(
                line, console=None, engine=engine
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
                    _consume_llm_events_plain(
                        engine, runtime, fp, route_limit=route_limit, team=use_team
                    )
                    _maybe_print_repl_memory_load_warning(None, engine, use_rich=False)
                    _try_persist_repl_session(engine)
                continue
            use_team = bool(engine.repl_team_mode)
            msg = line
            if msg.startswith('$team'):
                msg = msg[5:].strip()
                use_team = True
            if not msg:
                continue
            reset_agent_cancel()
            _consume_llm_events_plain(
                engine, runtime, msg, route_limit=route_limit, team=use_team
            )
            _maybe_print_repl_memory_load_warning(None, engine, use_rich=False)
            _try_persist_repl_session(engine)

    _ensure_stdio_utf8()
    console = Console(force_terminal=True, color_system='truecolor')
    print_repl_llm_driver_banner(console=console)
    console.print(
        '[dim]大模型 REPL；exit / quit 退出；Ctrl+C 中断当前生成（保留已输出，REPL 不退出）。[/dim]'
    )
    console.print(
        '[dim]斜杠: [bold]/help[/bold] · [bold]/new[/bold] [bold]/memo[/bold] · /doctor /cost /diff /status · '
        '/team 或 [bold]$team[/bold] 前缀 · 记忆 /summary /flush /stop /sessions /load · '
        '/audit /report · /subsystems /graph[/dim]'
    )

    pt_session = _build_prompt_session()

    from .repl_slash_commands import dispatch_repl_slash_command

    runtime = PortRuntime()
    engine = _repl_engine_autoresume(console, use_rich=True)
    engine.config = replace(engine.config, llm_enabled=True)
    engine.ui_console = console

    while True:
        console.print()
        console.print(Rule(style='dim #334155'))
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
                try:
                    _run_streaming_turn(
                        engine, runtime, fp, console, route_limit=route_limit, team=use_team
                    )
                except KeyboardInterrupt:
                    _print_graceful_interrupt(console, use_rich=True)
                except Exception as exc:
                    try:
                        console.print(
                            f'[bold red]本回合展示层异常（已释放 Live/Status）: '
                            f'{type(exc).__name__}: {exc}[/bold red]'
                        )
                    except Exception:
                        print(f'本回合异常: {type(exc).__name__}: {exc}', flush=True)
                finally:
                    repl_stdin_flush_pending_if_tty()
                _maybe_print_repl_memory_load_warning(console, engine, use_rich=True)
                _try_persist_repl_session(engine)
            continue

        use_team = bool(engine.repl_team_mode)
        msg = line
        if msg.startswith('$team'):
            msg = msg[5:].strip()
            use_team = True
        if not msg:
            continue

        reset_agent_cancel()
        try:
            _run_streaming_turn(
                engine, runtime, msg, console, route_limit=route_limit, team=use_team
            )
        except KeyboardInterrupt:
            # 理论上由内层 _run_streaming_turn 已处理；此处兜底防止遗漏路径导致进程退出
            _print_graceful_interrupt(console, use_rich=True)
            continue
        except Exception as exc:
            # Rich / prompt_toolkit 混用时，Python 层渲染异常不应整进程退出（无法拦截原生 SIGSEGV）
            try:
                console.print(
                    f'[bold red]本回合展示层异常（已释放 Live/Status）: '
                    f'{type(exc).__name__}: {exc}[/bold red]'
                )
            except Exception:
                print(f'本回合异常: {type(exc).__name__}: {exc}', flush=True)
            continue
        finally:
            repl_stdin_flush_pending_if_tty()
        _maybe_print_repl_memory_load_warning(console, engine, use_rich=True)
        _try_persist_repl_session(engine)


def _repl_engine_json_resume() -> Any:
    """恢复最近会话但不打印横幅（供 Rust TUI 的 json-stdio 后端）。"""
    from .query_engine import QueryEnginePort
    from .session_store import most_recent_saved_session_id

    sid = most_recent_saved_session_id()
    if not sid:
        return QueryEnginePort.from_workspace()
    try:
        return QueryEnginePort.from_saved_session(sid)
    except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return QueryEnginePort.from_workspace()


def run_repl_json_stdio_loop(*, llm_enabled: bool, route_limit: int = 5) -> int:
    """
    行协议 JSON over stdio：Rust 全屏 TUI 等前端专用。

    - stdin：每行一个 JSON 对象，例如 ``{"op":"submit","text":"你好"}``、``{"op":"stop"}``、
      ``{"op":"shutdown"}``。
    - stdout：每行一个 JSON；首条为 ``{"type":"ready",...}``；LLM 事件与
      :meth:`QueryEnginePort.iter_repl_assistant_events_with_runtime` 产出一致；每回合以
      ``{"type":"turn_done"}`` 结束。
    """
    import os
    import queue
    import threading
    from dataclasses import replace

    from rich.console import Console

    from .repl_slash_commands import dispatch_repl_slash_command
    from .runtime import PortRuntime

    os.environ['SCREAM_REPL_JSON_STDIO'] = '1'
    _ensure_stdio_utf8()

    cmd_q: queue.Queue[str | None] = queue.Queue()

    def _stdin_reader() -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError, RuntimeError):
                cmd_q.put(None)
                return
            if line == '':
                cmd_q.put(None)
                return
            cmd_q.put(line.rstrip('\n\r'))

    threading.Thread(target=_stdin_reader, daemon=True).start()

    capture = io.StringIO()
    cap_console = Console(
        file=capture,
        force_terminal=False,
        width=120,
        markup=True,
        highlight=False,
    )

    runtime = PortRuntime()
    engine = _repl_engine_json_resume()
    engine.config = replace(engine.config, llm_enabled=llm_enabled)
    engine.ui_console = None

    stop_evt = threading.Event()

    def _emit(obj: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + '\n')
        sys.stdout.flush()

    def _display_model() -> str:
        raw = (engine.config.llm_model or '').strip()
        if raw:
            return raw
        try:
            from .llm_settings import read_llm_connection_settings

            return (read_llm_connection_settings().model or '').strip()
        except Exception:
            return ''

    _emit(
        {
            'type': 'ready',
            'model': _display_model(),
            'repl_team_mode': bool(engine.repl_team_mode),
            'cumulative_input_tokens': int(engine.total_usage.input_tokens),
            'cumulative_output_tokens': int(engine.total_usage.output_tokens),
        }
    )

    def _emit_state() -> None:
        _emit(
            {
                'type': 'state',
                'model': _display_model(),
                'repl_team_mode': bool(engine.repl_team_mode),
                'cumulative_input_tokens': int(engine.total_usage.input_tokens),
                'cumulative_output_tokens': int(engine.total_usage.output_tokens),
            }
        )

    while True:
        raw_line = cmd_q.get()
        if raw_line is None:
            _try_persist_repl_session(engine)
            return 0
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _emit({'type': 'error', 'message': f'invalid json: {exc}'})
            _emit({'type': 'turn_done'})
            continue

        op = req.get('op')
        if op == 'shutdown':
            _try_persist_repl_session(engine)
            _emit({'type': 'shutdown_ack'})
            return 0
        if op == 'stop':
            reset_agent_cancel()
            stop_evt.set()
            _emit(
                {
                    'type': 'system',
                    'text': '已请求中断当前工具链（agent_cancel）。',
                }
            )
            _emit({'type': 'turn_done'})
            continue

        if op != 'submit':
            _emit({'type': 'error', 'message': f'unknown op: {op!r}'})
            _emit({'type': 'turn_done'})
            continue

        text = str(req.get('text', '') or '')
        stop_evt.clear()

        if not text.strip():
            _emit({'type': 'turn_done'})
            continue

        if text.strip().lower() in ('exit', 'quit', 'q'):
            _try_persist_repl_session(engine)
            _emit({'type': 'shutdown_ack'})
            return 0

        capture.seek(0)
        capture.truncate(0)
        followup_from_slash = False
        handled, new_eng, slash_outcome = dispatch_repl_slash_command(
            text, console=cap_console, engine=engine
        )
        if new_eng is not None:
            engine = new_eng
            engine.config = replace(engine.config, llm_enabled=llm_enabled)

        if handled:
            followup_from_slash = (
                slash_outcome is not None
                and slash_outcome.trigger_llm_followup
                and llm_enabled
                and (slash_outcome.followup_prompt or '').strip()
            )
            out = capture.getvalue().strip()
            if out:
                _emit({'type': 'system', 'text': out})
            if not followup_from_slash:
                _try_persist_repl_session(engine)
                _emit_state()
                _emit({'type': 'turn_done'})
                continue

        use_team = bool(engine.repl_team_mode)
        if followup_from_slash:
            assert slash_outcome is not None
            msg = slash_outcome.followup_prompt.strip()
        else:
            msg = text
            if msg.startswith('$team'):
                msg = msg[5:].strip()
                use_team = True
        if not msg:
            _emit({'type': 'turn_done'})
            continue

        reset_agent_cancel()
        gen = engine.iter_repl_assistant_events_with_runtime(
            msg, runtime=runtime, route_limit=route_limit, team=use_team
        )

        ev_q: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def _llm_worker() -> None:
            try:
                it = iter(gen)
                while True:
                    if stop_evt.is_set():
                        _safe_close_generator(it)
                        break
                    try:
                        ev = next(it)
                    except StopIteration:
                        break
                    ev_q.put(ev)
            except BaseException as exc:
                ev_q.put({'type': 'llm_error', 'output': f'{type(exc).__name__}: {exc}'})
            finally:
                ev_q.put(None)

        threading.Thread(target=_llm_worker, daemon=True).start()

        stdin_closed = False
        while True:
            while True:
                try:
                    sneaky = cmd_q.get_nowait()
                except queue.Empty:
                    break
                if sneaky is None:
                    stop_evt.set()
                    stdin_closed = True
                    break
                try:
                    extra = json.loads(sneaky)
                except json.JSONDecodeError:
                    continue
                if extra.get('op') == 'stop':
                    reset_agent_cancel()
                    stop_evt.set()
            if stdin_closed:
                _try_persist_repl_session(engine)
                return 0
            try:
                ev = ev_q.get(timeout=0.08)
            except queue.Empty:
                continue
            if ev is None:
                break
            _emit(ev)

        _try_persist_repl_session(engine)
        _emit_state()
        _emit({'type': 'turn_done'})
