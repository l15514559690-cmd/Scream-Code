from __future__ import annotations

import copy
import json
import shlex
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .commands import build_command_backlog
from .models import PermissionDenial, UsageSummary
from .port_manifest import PortManifest, build_port_manifest
from .session_store import StoredSession, load_session, save_session
from .tools import build_tool_backlog
from .transcript import TranscriptStore

_ONLINE_EXECUTION_PROTOCOL_NOTE = (
    '\n\n<online_execution_protocol>\n'
    '你现在处于【浏览器MCP模式】。请先确保浏览器已安装并连接 browser-mcp 插件，再执行以下思考链路：\n'
    '1. **检索优先级**：严禁直接使用训练数据回答。你必须立即调用 browser_search 或 browser_navigate。\n'
    '2. **多步规划**：如果第一步搜索结果不完整，你必须继续使用 browser_click 或 browser_scroll 进行深度挖掘。\n'
    '3. **防爆提取**：调用读取工具时，必须强制要求 Text-only 模式，禁止获取 HTML 源码。\n'
    "4. **连接性自检**：如果收到提示 'Extension not connected'，你必须停止执行，并明确指示用户："
    "'请在浏览器中点击 Browser MCP 插件的 Connect 按钮'。禁止尝试使用本地 curl 降级。\n"
    '</online_execution_protocol>'
)


@dataclass(frozen=True)
class QueryEngineConfig:
    #: 用户轮次上限：超出时滑动裁剪 ``mutable_messages``，**不**在框架层阻断发往模型的请求
    max_turns: int = 400
    #: 累计 token 预算（默认 12M；长上下文扩容后与修剪阈值配套）
    max_budget_tokens: int = 12_000_000
    #: 仅当 ``mutable_messages`` 条数超过此值时才做滑动裁剪；贴近 ``max_turns`` 以尽量保留原文
    compact_after_turns: int = 396
    structured_output: bool = False
    structured_retry_limit: int = 2
    #: 为 True 时通过 OpenAI SDK 兼容接口请求大模型（须配置 API_KEY）；默认关闭以保持离线测试稳定。
    llm_enabled: bool = False
    #: 覆盖默认模型（仅当使用环境变量直连且未写 llm_config 时参考 ``MODEL``）。
    llm_model: str | None = None
    #: REPL 展示层专用：累计 token 参与记忆水位提示；``None`` 使用 ``replLauncher.REPL_MEMORY_WARN_TOTAL_TOKENS``。不截断请求。
    token_warning_threshold: int | None = None


@dataclass(frozen=True)
class TurnResult:
    prompt: str
    output: str
    matched_commands: tuple[str, ...]
    matched_tools: tuple[str, ...]
    permission_denials: tuple[PermissionDenial, ...]
    usage: UsageSummary
    stop_reason: str


@dataclass
class QueryEnginePort:
    manifest: PortManifest
    config: QueryEngineConfig = field(default_factory=QueryEngineConfig)
    session_id: str = field(default_factory=lambda: uuid4().hex)
    mutable_messages: list[str] = field(default_factory=list)
    permission_denials: list[PermissionDenial] = field(default_factory=list)
    total_usage: UsageSummary = field(default_factory=UsageSummary)
    transcript_store: TranscriptStore = field(default_factory=TranscriptStore)
    #: REPL 多轮 LLM：OpenAI 格式的完整历史（system 仅在首条构建一次，含项目记忆）。
    llm_conversation_messages: list[dict[str, Any]] = field(default_factory=list, repr=False)
    #: REPL 多代理团队模式（/team 切换）；与 ``$team`` 单行前缀可叠加触发编排。
    repl_team_mode: bool = field(default=False, repr=False)
    #: 浏览器MCP模式：开启时，给 API 的 user 内容隐式追加「优先调用 Browser MCP 浏览器/搜索工具」指令。
    mcp_online_mode: bool = field(default=False, repr=False)
    #: REPL 等场景注入 Rich Console，用于 LLM 请求与工具路由时的 Status 指示器。
    ui_console: Any | None = field(default=None, repr=False)
    #: 与 REPL/TUI 流式回合配合：是否处于 ``iter_repl_assistant_events*`` 消费中（跨线程读须加锁）。
    _stream_state_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )
    _stream_generating: bool = field(default=False, repr=False, compare=False)
    #: 本轮在 ``check_and_compress_history`` 中已成功折叠 ``llm_conversation_messages``，待 UI 打一行提示后清零。
    _just_compressed: bool = field(default=False, repr=False, compare=False)
    _mcp_client: Any | None = field(default=None, repr=False, compare=False)
    _mcp_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )
    _mcp_init_thread: threading.Thread | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_workspace(cls) -> 'QueryEnginePort':
        return cls(manifest=build_port_manifest())

    @classmethod
    def from_saved_session(cls, session_id: str) -> 'QueryEnginePort':
        """
        从 JSON 恢复 ``mutable_messages``、用量与（若存在）``llm_conversation_messages`` 快照。
        快照存在时恢复完整多轮 LLM 上下文；仅旧版文件时退化为仅用 ``mutable_messages`` 拼用户历史。
        恢复后会用当前项目记忆刷新首条 ``system``，避免 SCREAM.md 等更新后不生效。

        **不**会发起任何 LLM 请求；REPL/TUI 须在用户显式提交新输入后才可调用
        ``iter_repl_assistant_events*`` / ``submit_message`` 等推理入口。
        """
        stored = load_session(session_id)
        transcript = TranscriptStore(entries=list(stored.messages), flushed=True)
        llm_list: list[dict[str, Any]] = []
        if stored.llm_conversation_messages:
            llm_list = [copy.deepcopy(m) for m in stored.llm_conversation_messages]
            from .system_init import build_system_init_message

            sys_msg: dict[str, Any] = {
                'role': 'system',
                'content': build_system_init_message(trusted=True),
            }
            if llm_list and llm_list[0].get('role') == 'system':
                llm_list[0] = sys_msg
            else:
                llm_list.insert(0, sys_msg)
        return cls(
            manifest=build_port_manifest(),
            session_id=stored.session_id,
            mutable_messages=list(stored.messages),
            total_usage=UsageSummary(stored.input_tokens, stored.output_tokens),
            transcript_store=transcript,
            llm_conversation_messages=llm_list,
            repl_team_mode=False,
            mcp_online_mode=bool(getattr(stored, 'mcp_online_mode', False)),
        )

    def __post_init__(self) -> None:
        self._spawn_mcp_init_thread()

    def _spawn_mcp_init_thread(self) -> bool:
        with self._mcp_lock:
            t = self._mcp_init_thread
            if t is not None and t.is_alive():
                return True
            t = threading.Thread(target=self._try_init_mcp_client, daemon=True)
            self._mcp_init_thread = t
            t.start()
        return True

    def _try_init_mcp_client(self) -> bool:
        from .llm_settings import read_mcp_server_command
        from .mcp_manager import MCPClient, MCPClientError

        cmd_raw = (read_mcp_server_command() or '').strip()
        if not cmd_raw:
            return False
        try:
            cmd = shlex.split(cmd_raw)
        except ValueError:
            return False
        if not cmd:
            return False
        client = MCPClient(command=cmd)
        with self._mcp_lock:
            old = self._mcp_client
            self._mcp_client = client
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        try:
            client.start()
            client.refresh_tools()
        except MCPClientError:
            # 启动失败保留 client.status=error 供 UI 观测；不抛到主线程。
            return False
        except Exception:
            try:
                client.status = 'error'
            except Exception:
                pass
            return False
        return True

    def _merged_openai_tools(self) -> list[dict[str, Any]]:
        from .llm_client import get_openai_agent_tools

        local = get_openai_agent_tools()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []

        def _append_unique(rows: list[dict[str, Any]]) -> None:
            for item in rows:
                fn = item.get('function') if isinstance(item, dict) else None
                if not isinstance(fn, dict):
                    continue
                name = str(fn.get('name') or '').strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(item)

        _append_unique(local)
        with self._mcp_lock:
            mcp = self._mcp_client
        if mcp is not None and getattr(mcp, 'is_running', False):
            try:
                _append_unique(mcp.openai_tools())
            except Exception:
                pass
        return out

    def _has_running_mcp_tools(self) -> bool:
        with self._mcp_lock:
            mcp = self._mcp_client
        if mcp is None or not getattr(mcp, 'is_running', False):
            return False
        try:
            return len(list(getattr(mcp, 'tools_cache', ()) or ())) > 0
        except Exception:
            return False

    def get_mcp_client(self) -> Any | None:
        with self._mcp_lock:
            return self._mcp_client

    def mcp_status_snapshot(self) -> dict[str, Any]:
        from .llm_settings import read_mcp_server_command

        cmd = (read_mcp_server_command() or '').strip()
        with self._mcp_lock:
            mcp = self._mcp_client
        running = bool(mcp is not None and getattr(mcp, 'is_running', False))
        status = str(getattr(mcp, 'status', 'idle') or 'idle') if mcp is not None else 'idle'
        tools_count = 0
        tools: list[dict[str, Any]] = []
        if mcp is not None:
            try:
                cache = list(getattr(mcp, 'tools_cache', ()) or ())
                tools_count = len(cache)
                tools = [
                    {
                        'name': str(getattr(t, 'name', '') or ''),
                        'description': str(getattr(t, 'description', '') or ''),
                    }
                    for t in cache
                ]
            except Exception:
                tools = []
        return {
            'enabled': bool(cmd),
            'running': running,
            'command': cmd,
            'tools_count': tools_count,
            'tools': tools,
            'web_mode': bool(self.mcp_online_mode),
            'status': status,
        }

    def set_mcp_online_mode(self, enabled: bool) -> None:
        self.mcp_online_mode = bool(enabled)

    def toggle_mcp_online_mode(self) -> bool:
        self.mcp_online_mode = not self.mcp_online_mode
        return self.mcp_online_mode

    def restart_mcp_client(self) -> bool:
        with self._mcp_lock:
            old = self._mcp_client
            self._mcp_client = None
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        return self._spawn_mcp_init_thread()

    def close(self) -> None:
        with self._mcp_lock:
            mcp = self._mcp_client
            self._mcp_client = None
        if mcp is None:
            return
        try:
            mcp.stop()
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover - GC 时机不可预测
        self.close()

    def _coerce_turn_capacity_before_turn(self) -> None:
        """
        在追加本轮 user 前压缩 ``mutable_messages``（``compact_after_turns`` / ``max_turns``），
        并收缩过大的 ``llm_conversation_messages``。仅滑动裁剪，**不**因轮次触达上限而阻断请求。
        """
        cap = self.config.max_turns
        soft = self.config.compact_after_turns
        if len(self.mutable_messages) < cap:
            self._shrink_llm_conversation_if_huge()
        else:
            keep = soft if soft < cap else max(cap - 1, 1)
            keep = max(keep, 1)
            if len(self.mutable_messages) > keep:
                self.mutable_messages[:] = self.mutable_messages[-keep:]
            self._shrink_llm_conversation_if_huge()

        # ``max_turns==1`` 等边界下上一轮可能仍占满额度；为本轮 user 腾出空位，避免框架硬停。
        if cap > 0 and len(self.mutable_messages) >= cap:
            free = max(cap - 1, 0)
            self.mutable_messages[:] = (
                self.mutable_messages[-free:] if free > 0 else []
            )

    def check_and_compress_history(
        self, settings: Any, model_override: str | None
    ) -> None:
        """
        仅压缩 ``self.llm_conversation_messages`` 中**已落盘的历史**（尚未把本轮 user 拼进列表），
        成功则更新实例、``persist_session``，并置 ``_just_compressed`` 供 UI 提示。
        """
        from .context_compressor import compress_history, should_compress_messages

        raw = self.llm_conversation_messages
        if not raw or not should_compress_messages(raw):
            return
        before_len = len(raw)
        try:
            compressed = compress_history(raw, settings, model=model_override)
        except Exception:
            return
        if len(compressed) >= before_len:
            return
        self.llm_conversation_messages = compressed
        try:
            self.persist_session()
        except Exception:
            pass
        self._just_compressed = True

    def _emit_pre_llm_context_soft_warning(self) -> None:
        """
        在**发往模型前**打印记忆水位软警告（Rich 或纯文本），不修改会话、不拦截请求。
        去重与重复节奏与 ``replLauncher._maybe_print_repl_memory_load_warning`` 一致。
        """
        from .replLauncher import _maybe_print_repl_memory_load_warning

        console = self.ui_console
        use_rich = bool(
            console is not None
            and getattr(console, 'is_terminal', False)
            and bool(console.is_terminal)
        )
        _maybe_print_repl_memory_load_warning(console, self, use_rich=use_rich)

    def _shrink_llm_conversation_if_huge(self) -> None:
        """内存侧防止 ``llm_conversation_messages`` 无限增长；发往模型前仍会经 ``prune_historical_messages``。"""
        msgs = self.llm_conversation_messages
        max_keep = 3200
        if len(msgs) <= max_keep:
            return
        head_end = 0
        for m in msgs:
            if (m.get('role') or '').strip().lower() == 'system':
                head_end += 1
            else:
                break
        if head_end >= len(msgs):
            return
        body_keep = max(max_keep - head_end, 1)
        tail = msgs[-body_keep:]
        self.llm_conversation_messages = msgs[:head_end] + tail

    def submit_message(
        self,
        prompt: str,
        matched_commands: tuple[str, ...] = (),
        matched_tools: tuple[str, ...] = (),
        denied_tools: tuple[PermissionDenial, ...] = (),
    ) -> TurnResult:
        self._coerce_turn_capacity_before_turn()

        summary_lines = self._router_summary_lines(
            prompt, matched_commands, matched_tools, denied_tools
        )
        if self.config.llm_enabled:
            llm_text, in_tok, out_tok = self._complete_with_openai_llm(
                prompt,
                matched_commands,
                matched_tools,
                denied_tools,
            )
            output = self._finalize_llm_assistant_text(
                llm_text,
                summary_lines,
                matched_commands,
                matched_tools,
                denied_tools,
            )
            if in_tok > 0 or out_tok > 0:
                self.total_usage = UsageSummary(
                    input_tokens=self.total_usage.input_tokens + in_tok,
                    output_tokens=self.total_usage.output_tokens + out_tok,
                )
            else:
                self.total_usage = self.total_usage.add_turn(prompt, output)
        else:
            output = self._format_output(summary_lines)
            self.total_usage = self.total_usage.add_turn(prompt, output)

        stop_reason = 'completed'
        if self.total_usage.input_tokens + self.total_usage.output_tokens > self.config.max_budget_tokens:
            stop_reason = 'max_budget_reached'
        self.mutable_messages.append(prompt)
        self.transcript_store.append(prompt)
        self.permission_denials.extend(denied_tools)
        self.compact_messages_if_needed()
        return TurnResult(
            prompt=prompt,
            output=output,
            matched_commands=matched_commands,
            matched_tools=matched_tools,
            permission_denials=denied_tools,
            usage=self.total_usage,
            stop_reason=stop_reason,
        )

    @staticmethod
    def _router_summary_lines(
        prompt: str,
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...],
    ) -> list[str]:
        return [
            f'提示: {prompt}',
            f'匹配的命令: {", ".join(matched_commands) if matched_commands else "无"}',
            f'匹配的工具: {", ".join(matched_tools) if matched_tools else "无"}',
            f'权限拒绝次数: {len(denied_tools)}',
        ]

    def _format_turn_user_content(
        self,
        prompt: str,
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...],
    ) -> str:
        summary = self._router_summary_lines(
            prompt, matched_commands, matched_tools, denied_tools
        )
        user_lines = [
            '以下为当前轮次的路由与权限上下文（技术标识与数据字段保持英文原样）：',
            *summary,
        ]
        if denied_tools:
            user_lines.extend(f'- {d.tool_name}: {d.reason}' for d in denied_tools)
        return '\n'.join(user_lines)

    def mark_stream_generation_start(self) -> None:
        """新一轮 LLM 流式编排开始（在 ``reset_agent_cancel`` 之后调用）。"""
        with self._stream_state_lock:
            self._stream_generating = True

    def mark_stream_generation_end(self) -> None:
        with self._stream_state_lock:
            self._stream_generating = False

    def request_stream_abort(self) -> None:
        """
        用户请求终止当前生成/工具链：与 ``agent_cancel`` 同源信号，供 TUI 侧 ``/stop``、Ctrl+C 等触发。
        """
        from . import agent_cancel

        agent_cancel.request_agent_cancel()

    @property
    def is_generating(self) -> bool:
        with self._stream_state_lock:
            return self._stream_generating

    @property
    def is_aborted(self) -> bool:
        """是否与 ``/stop``、Ctrl+C 等一致处于「取消已请求」状态（由 ``agent_cancel`` 承载）。"""
        from . import agent_cancel

        return agent_cancel.agent_cancel_requested()

    def _repl_messages_base_before_current_user(self) -> list[dict[str, Any]]:
        """
        构造「当前 user 条」之前的消息前缀。

        - 若已有 ``llm_conversation_messages``（含多轮工具闭环快照），则深拷贝后**重写首条
          system**，使 ``SCREAM.md`` 等与 :func:`build_system_init_message` 同步注入（不修改
          磁盘上的会话 JSON，仅影响当次 API 请求）。
        - 若为空，则用 ``system`` + 逐条历史用户原文补全。
        """
        from .system_init import build_system_init_message

        sys_content = build_system_init_message(trusted=True)
        if self.llm_conversation_messages:
            out = copy.deepcopy(self.llm_conversation_messages)
            if out and (out[0].get('role') or '').strip().lower() == 'system':
                merged = dict(out[0])
                merged['role'] = 'system'
                merged['content'] = sys_content
                out[0] = merged
            else:
                out.insert(0, {'role': 'system', 'content': sys_content})
            return out

        out = [{'role': 'system', 'content': sys_content}]
        for raw in self.mutable_messages:
            out.append({'role': 'user', 'content': str(raw)})
        return out

    def _assemble_messages_for_llm_turn(
        self,
        prompt: str,
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...],
    ) -> list[dict[str, Any]]:
        """
        组装发往 API 的 messages：首轮含 system（含项目记忆，仅一次）；后续轮在深拷贝历史上追加本轮 user。
        """
        user_msg: dict[str, Any] = {
            'role': 'user',
            'content': self._format_turn_user_content(
                prompt, matched_commands, matched_tools, denied_tools
            ),
        }
        messages = self._repl_messages_base_before_current_user() + [user_msg]
        if self.mcp_online_mode and self._has_running_mcp_tools():
            for m in reversed(messages):
                if str(m.get('role') or '').strip().lower() != 'user':
                    continue
                raw = m.get('content')
                content = raw if isinstance(raw, str) else str(raw or '')
                m['content'] = content + _ONLINE_EXECUTION_PROTOCOL_NOTE
                break
        return messages

    def _assemble_messages_for_team_phase(self, user_content: str) -> list[dict[str, Any]]:
        """团队编排单阶段：在已有 ``llm_conversation_messages`` 上追加一条 user。"""
        user_msg: dict[str, Any] = {'role': 'user', 'content': user_content}
        return self._repl_messages_base_before_current_user() + [user_msg]

    def _finalize_llm_assistant_text(
        self,
        llm_text: str,
        summary_lines: list[str],
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...],
    ) -> str:
        if self.config.structured_output:
            payload: dict[str, object] = {
                'assistant': llm_text,
                'session_id': self.session_id,
                'matched_commands': list(matched_commands),
                'matched_tools': list(matched_tools),
                'permission_denials': [
                    {'tool': d.tool_name, 'reason': d.reason} for d in denied_tools
                ],
            }
            return self._render_structured_output(payload)
        return llm_text if llm_text.strip() else '\n'.join(summary_lines)

    def _complete_with_openai_llm(
        self,
        prompt: str,
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...],
    ) -> tuple[str, int, int]:
        from .llm_client import LlmClientError, chat_completion
        from .llm_settings import read_llm_connection_settings

        self._emit_pre_llm_context_soft_warning()
        settings = read_llm_connection_settings()
        raw_override = (self.config.llm_model or '').strip()
        model_override = raw_override or None
        self.check_and_compress_history(settings, model_override)
        if self._just_compressed:
            msg = '\n[🧠 历史记忆已折叠，释放上下文空间...]\n'
            if self.ui_console is not None:
                try:
                    self.ui_console.print(msg)
                except Exception:
                    pass
            self._just_compressed = False
        messages = self._assemble_messages_for_llm_turn(
            prompt, matched_commands, matched_tools, denied_tools
        )

        def _call_llm():
            return chat_completion(
                messages,
                settings,
                model=model_override,
                tools=self._merged_openai_tools(),
                mcp_client=self._mcp_client,
            )

        console = self.ui_console
        use_status = (
            console is not None
            and getattr(console, 'is_terminal', False)
            and bool(console.is_terminal)
        )
        try:
            if use_status:
                if matched_tools:
                    tool_label = ', '.join(matched_tools)
                    with console.status(
                        f'[bold yellow]🛠️ 调用工具中: {tool_label}[/bold yellow]',
                        spinner='dots',
                    ):
                        time.sleep(0.06)
                with console.status('[bold cyan]🤔 思考中...[/bold cyan]', spinner='dots'):
                    result = _call_llm()
            else:
                result = _call_llm()
            if result.conversation_messages is not None:
                self.llm_conversation_messages = result.conversation_messages
            return result.text, result.input_tokens, result.output_tokens
        except LlmClientError as exc:
            return f'[LLM] {exc}', 0, 0
        except Exception as exc:  # pragma: no cover - 网络/供应商错误
            return f'[LLM] 请求异常: {exc}', 0, 0

    def iter_repl_assistant_events(
        self,
        prompt: str,
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...] = (),
    ):
        """
        会话编排层：拼装路由上下文与 transcript，**不实现多轮 tool 循环**（该闭环仅在
        ``llm_client.iter_agent_executor_events``）。产出供 REPL/通道消费的 UI 事件。
        若生成器被 close()（如 Ctrl+C），不提交本轮。
        """
        from .llm_client import iter_agent_executor_events
        from .llm_settings import read_llm_connection_settings

        self._coerce_turn_capacity_before_turn()

        summary_lines = self._router_summary_lines(
            prompt, matched_commands, matched_tools, denied_tools
        )

        if not self.config.llm_enabled:
            output = self._format_output(summary_lines)
            self.total_usage = self.total_usage.add_turn(prompt, output)
            stop_reason = 'completed'
            if (
                self.total_usage.input_tokens + self.total_usage.output_tokens
                > self.config.max_budget_tokens
            ):
                stop_reason = 'max_budget_reached'
            self.mutable_messages.append(prompt)
            self.transcript_store.append(prompt)
            self.permission_denials.extend(denied_tools)
            self.compact_messages_if_needed()
            yield {'type': 'non_llm', 'output': output, 'stop_reason': stop_reason}
            return

        self._emit_pre_llm_context_soft_warning()
        try:
            settings = read_llm_connection_settings()
        except Exception as exc:
            yield {
                'type': 'llm_error',
                'output': f'[LLM] 无法读取模型连接配置: {exc}',
            }
            return
        raw_override = (self.config.llm_model or '').strip()
        model_override = raw_override or None
        self.check_and_compress_history(settings, model_override)

        self.mark_stream_generation_start()
        try:
            try:
                if self._just_compressed:
                    yield {
                        'type': 'text_delta',
                        'text': (
                            '\n[🧠 历史记忆已折叠，释放上下文空间...]\n'
                        ),
                    }
                    self._just_compressed = False
                messages: list[dict[str, Any]] = self._assemble_messages_for_llm_turn(
                    prompt, matched_commands, matched_tools, denied_tools
                )
                for ev in iter_agent_executor_events(
                    messages,
                    settings,
                    model=model_override,
                    tools=self._merged_openai_tools(),
                    mcp_client=self._mcp_client,
                ):
                    et = ev.get('type')
                    if et == 'executor_complete':
                        snap = ev.get('conversation_messages')
                        if isinstance(snap, list):
                            self.llm_conversation_messages = snap
                        in_tok = int(ev.get('input_tokens', 0))
                        out_tok = int(ev.get('output_tokens', 0))
                        llm_text = str(ev.get('assistant_text', '') or '')
                        stop_reason = str(ev.get('stop_reason') or 'completed')
                        if (
                            stop_reason == 'user_interrupt'
                            and '[🛑 任务已被用户手动终止]' not in llm_text
                        ):
                            llm_text = (
                                llm_text.rstrip() + '\n\n[🛑 任务已被用户手动终止]'
                            )
                        output = self._finalize_llm_assistant_text(
                            llm_text,
                            summary_lines,
                            matched_commands,
                            matched_tools,
                            denied_tools,
                        )
                        if in_tok > 0 or out_tok > 0:
                            self.total_usage = UsageSummary(
                                input_tokens=self.total_usage.input_tokens + in_tok,
                                output_tokens=self.total_usage.output_tokens + out_tok,
                            )
                        else:
                            self.total_usage = self.total_usage.add_turn(prompt, output)

                        if (
                            self.total_usage.input_tokens + self.total_usage.output_tokens
                            > self.config.max_budget_tokens
                        ):
                            stop_reason = 'max_budget_reached'
                        self.mutable_messages.append(prompt)
                        self.transcript_store.append(prompt)
                        self.permission_denials.extend(denied_tools)
                        self.compact_messages_if_needed()
                        yield {
                            'type': 'finished',
                            'output': output,
                            'stop_reason': stop_reason,
                            'turn_input_tokens': in_tok,
                            'turn_output_tokens': out_tok,
                            'cumulative_input_tokens': self.total_usage.input_tokens,
                            'cumulative_output_tokens': self.total_usage.output_tokens,
                        }
                        return
                    if et == 'llm_error':
                        yield ev
                        return
                    yield ev
            except GeneratorExit:
                raise
            except Exception as exc:
                yield {
                    'type': 'llm_error',
                    'output': f'[LLM] 会话编排异常: {exc}',
                }
                return
        finally:
            self.mark_stream_generation_end()

    def iter_team_repl_assistant_events(
        self,
        prompt: str,
        matched_commands: tuple[str, ...],
        matched_tools: tuple[str, ...],
        denied_tools: tuple[PermissionDenial, ...] = (),
    ):
        """
        多代理编排：Planner（无工具）→ Coder（全量工具）→ Reviewer（无工具），
        顺序调用 ``iter_agent_executor_events``，共享 ``llm_conversation_messages``。
        """
        import re

        from .coordinator.team_roles import TeamRole, get_team_role_prompt
        from .llm_client import iter_agent_executor_events
        from .llm_settings import read_llm_connection_settings

        self._coerce_turn_capacity_before_turn()

        if not self.config.llm_enabled:
            yield from self.iter_repl_assistant_events(
                prompt, matched_commands, matched_tools, denied_tools
            )
            return

        summary_lines = self._router_summary_lines(
            prompt, matched_commands, matched_tools, denied_tools
        )
        base_user = self._format_turn_user_content(
            prompt, matched_commands, matched_tools, denied_tools
        )
        try:
            settings = read_llm_connection_settings()
        except Exception as exc:
            yield {
                'type': 'llm_error',
                'output': f'[LLM] 无法读取模型连接配置: {exc}',
            }
            return
        raw_override = (self.config.llm_model or '').strip()
        model_override = raw_override or None

        self.check_and_compress_history(settings, model_override)
        self._emit_pre_llm_context_soft_warning()

        combined_chunks: list[str] = []
        analyst_delta_chunks: list[str] = []
        analyst_full_text = ''
        planner_seed = ''
        planner_plan = ''
        phase_in = 0
        phase_out = 0
        max_iterations = 3

        def _extract_analyst_deliverable(full_text: str) -> str:
            raw = str(full_text or '').strip()
            if not raw:
                return ''
            m = re.search(
                r'<deliverable>\s*(.*?)\s*</deliverable>', raw, flags=re.I | re.S
            )
            if m:
                body = (m.group(1) or '').strip()
                if body:
                    return body
            return raw

        self.mark_stream_generation_start()
        try:
            try:
                if self._just_compressed:
                    yield {
                        'type': 'text_delta',
                        'text': (
                            '\n[🧠 历史记忆已折叠，释放上下文空间...]\n'
                        ),
                    }
                    self._just_compressed = False
                # Phase 1: Analyst -> Planner (线性前置)
                analyst_delta_chunks = []
                yield {'type': 'team_agent', 'agent': 'Analyst'}
                analyst_msgs = self._assemble_messages_for_team_phase(base_user)
                analyst_system = get_team_role_prompt(TeamRole.ANALYST)
                analyst_msgs.insert(
                    max(len(analyst_msgs) - 1, 0),
                    {'role': 'system', 'content': analyst_system},
                )
                for ev in iter_agent_executor_events(
                    analyst_msgs,
                    settings,
                    model=model_override,
                    tools=[],
                    mcp_client=self._mcp_client,
                ):
                    et = ev.get('type')
                    if et == 'executor_complete':
                        snap = ev.get('conversation_messages')
                        if isinstance(snap, list):
                            self.llm_conversation_messages = snap
                        phase_in += int(ev.get('input_tokens', 0))
                        phase_out += int(ev.get('output_tokens', 0))
                        body = str(ev.get('assistant_text', '') or '').strip()
                        if analyst_delta_chunks and not body:
                            body = ''.join(analyst_delta_chunks).strip()
                        analyst_full_text = body
                        planner_seed = _extract_analyst_deliverable(analyst_full_text)
                        analyst_note = (
                            '【来自 Analyst 的需求拆解】\n'
                            + (planner_seed or '（Analyst 未给出有效 deliverable）')
                        )
                        self.llm_conversation_messages.append(
                            {'role': 'system', 'content': analyst_note}
                        )
                        combined_chunks.append(f'[Analyst]\n{body}')
                        break
                    if et == 'llm_error':
                        yield ev
                        return
                    if et == 'text_delta':
                        analyst_delta_chunks.append(str(ev.get('text', '') or ''))
                    yield ev

                yield {'type': 'team_agent', 'agent': 'Planner'}
                planner_user = (
                    f'{base_user}\n\n【来自 Analyst 的需求拆解】\n{planner_seed or "（无）"}'
                )
                planner_msgs = self._assemble_messages_for_team_phase(planner_user)
                planner_system = get_team_role_prompt(TeamRole.PLANNER)
                planner_msgs.insert(
                    max(len(planner_msgs) - 1, 0),
                    {'role': 'system', 'content': planner_system},
                )
                for ev in iter_agent_executor_events(
                    planner_msgs,
                    settings,
                    model=model_override,
                    tools=[],
                    mcp_client=self._mcp_client,
                ):
                    et = ev.get('type')
                    if et == 'executor_complete':
                        snap = ev.get('conversation_messages')
                        if isinstance(snap, list):
                            self.llm_conversation_messages = snap
                        phase_in += int(ev.get('input_tokens', 0))
                        phase_out += int(ev.get('output_tokens', 0))
                        planner_plan = str(ev.get('assistant_text', '') or '').strip()
                        combined_chunks.append(f'[Planner]\n{planner_plan}')
                        break
                    if et == 'llm_error':
                        yield ev
                        return
                    yield ev

                # Phase 2: Coder <-> Reviewer feedback loop (最多 3 轮)
                merged_tools = self._merged_openai_tools()
                coder_instruction = (
                    '【来自 Planner 的执行计划，请严格执行】\n'
                    + (planner_plan or '（无）')
                )
                approved = False
                for attempt in range(1, max_iterations + 1):
                    yield {
                        'type': 'team_agent',
                        'agent': 'Coder',
                        'round': attempt,
                        'max_rounds': max_iterations,
                    }
                    coder_user = (
                        f'{coder_instruction}\n\n【执行要求】\n'
                        f'当前是第 {attempt} 轮，请严格按计划与修复意见落地执行并给出结果。'
                    )
                    coder_msgs = self._assemble_messages_for_team_phase(coder_user)
                    coder_system = get_team_role_prompt(TeamRole.CODER)
                    coder_msgs.insert(
                        max(len(coder_msgs) - 1, 0),
                        {'role': 'system', 'content': coder_system},
                    )
                    coder_report = ''
                    for ev in iter_agent_executor_events(
                        coder_msgs,
                        settings,
                        model=model_override,
                        tools=merged_tools,
                        mcp_client=self._mcp_client,
                    ):
                        et = ev.get('type')
                        if et == 'executor_complete':
                            snap = ev.get('conversation_messages')
                            if isinstance(snap, list):
                                self.llm_conversation_messages = snap
                            phase_in += int(ev.get('input_tokens', 0))
                            phase_out += int(ev.get('output_tokens', 0))
                            coder_report = str(ev.get('assistant_text', '') or '').strip()
                            combined_chunks.append(f'[Coder#{attempt}]\n{coder_report}')
                            break
                        if et == 'llm_error':
                            yield ev
                            return
                        yield ev

                    yield {
                        'type': 'team_agent',
                        'agent': 'Reviewer',
                        'round': attempt,
                        'max_rounds': max_iterations,
                    }
                    reviewer_user = (
                        f'【Coder 第 {attempt} 轮的执行报告，请审查】\n'
                        f'{coder_report or "（无）"}\n\n'
                        '请给出明确裁决：[APPROVE] 或 [REJECT: ...]。'
                    )
                    reviewer_msgs = self._assemble_messages_for_team_phase(reviewer_user)
                    reviewer_system = get_team_role_prompt(TeamRole.REVIEWER)
                    reviewer_msgs.insert(
                        max(len(reviewer_msgs) - 1, 0),
                        {'role': 'system', 'content': reviewer_system},
                    )
                    reviewer_report = ''
                    for ev in iter_agent_executor_events(
                        reviewer_msgs,
                        settings,
                        model=model_override,
                        tools=merged_tools,
                        mcp_client=self._mcp_client,
                    ):
                        et = ev.get('type')
                        if et == 'executor_complete':
                            snap = ev.get('conversation_messages')
                            if isinstance(snap, list):
                                self.llm_conversation_messages = snap
                            phase_in += int(ev.get('input_tokens', 0))
                            phase_out += int(ev.get('output_tokens', 0))
                            reviewer_report = str(ev.get('assistant_text', '') or '').strip()
                            combined_chunks.append(
                                f'[Reviewer#{attempt}]\n{reviewer_report}'
                            )
                            break
                        if et == 'llm_error':
                            yield ev
                            return
                        yield ev

                    reviewer_lower = reviewer_report.lower()
                    if '[approve]' in reviewer_lower:
                        approved = True
                        break
                    coder_instruction = (
                        '【来自 Reviewer 的打回意见，请务必修复以下问题】\n'
                        + (reviewer_report or '（Reviewer 未给出有效建议）')
                    )

                if not approved:
                    warn = (
                        '⚠️ 团队模式达到最大迭代次数，未获得 Reviewer 最终批准，流程强制终止，请人类介入。'
                    )
                    combined_chunks.append(f'[System]\n{warn}')
                    yield {'type': 'text_delta', 'text': f'\n[bold red]{warn}[/bold red]\n'}

                if phase_in > 0 or phase_out > 0:
                    self.total_usage = UsageSummary(
                        input_tokens=self.total_usage.input_tokens + phase_in,
                        output_tokens=self.total_usage.output_tokens + phase_out,
                    )
                else:
                    out_all = '\n\n'.join(combined_chunks)
                    self.total_usage = self.total_usage.add_turn(prompt, out_all)

                stop_reason = 'completed'
                if (
                    self.total_usage.input_tokens + self.total_usage.output_tokens
                    > self.config.max_budget_tokens
                ):
                    stop_reason = 'max_budget_reached'

                full_out = '\n\n---\n\n'.join(combined_chunks)
                if self.is_aborted and '[🛑 任务已被用户手动终止]' not in full_out:
                    full_out = full_out.rstrip() + '\n\n[🛑 任务已被用户手动终止]'
                    if stop_reason == 'completed':
                        stop_reason = 'user_interrupt'
                output = self._finalize_llm_assistant_text(
                    full_out,
                    summary_lines,
                    matched_commands,
                    matched_tools,
                    denied_tools,
                )
                self.mutable_messages.append(prompt)
                self.transcript_store.append(prompt)
                self.permission_denials.extend(denied_tools)
                self.compact_messages_if_needed()
                yield {
                    'type': 'finished',
                    'output': output,
                    'stop_reason': stop_reason,
                    'turn_input_tokens': phase_in,
                    'turn_output_tokens': phase_out,
                    'cumulative_input_tokens': self.total_usage.input_tokens,
                    'cumulative_output_tokens': self.total_usage.output_tokens,
                }
            except GeneratorExit:
                raise
            except Exception as exc:
                yield {
                    'type': 'llm_error',
                    'output': f'[LLM] 团队编排异常: {exc}',
                }
                return
        finally:
            self.mark_stream_generation_end()

    def iter_repl_assistant_events_with_runtime(
        self,
        prompt: str,
        *,
        runtime: Any,
        route_limit: int = 5,
        team: bool = False,
    ):
        """
        先经 **PortRuntime**（claw-code 镜像侧 ``route_prompt`` / 权限推断）得到
        ``matched_commands`` / ``matched_tools`` / ``denied_tools``，再进入
        ``iter_repl_assistant_events`` 或团队编排。REPL 应优先使用本入口。
        """
        matches = runtime.route_prompt(prompt, limit=route_limit)
        command_names = tuple(m.name for m in matches if m.kind == 'command')
        tool_names = tuple(m.name for m in matches if m.kind == 'tool')
        denials = tuple(runtime._infer_permission_denials(matches))
        if team:
            yield from self.iter_team_repl_assistant_events(
                prompt, command_names, tool_names, denials
            )
            return
        yield from self.iter_repl_assistant_events(
            prompt, command_names, tool_names, denials
        )

    def run_headless_turn(
        self,
        prompt: str,
        matched_commands: tuple[str, ...] = (),
        matched_tools: tuple[str, ...] = (),
        denied_tools: tuple[PermissionDenial, ...] = (),
    ) -> str:
        """
        无头消费 ``iter_repl_assistant_events``（**多轮工具闭环在** ``llm_client.iter_agent_executor_events`` **内**）。

        适用于已显式给出路由元组的调用方（如测试）；生产通道请用
        :meth:`run_headless_turn_with_runtime`。
        """
        self.ui_console = None
        buf: list[str] = []
        try:
            for ev in self.iter_repl_assistant_events(
                prompt, matched_commands, matched_tools, denied_tools
            ):
                et = ev.get('type')
                if et == 'text_delta':
                    buf.append(str(ev.get('text', '')))
                elif et in ('finished', 'non_llm', 'blocked', 'llm_error'):
                    out = str(ev.get('output', '') or '').strip()
                    return out if out else ''.join(buf).strip()
            return ''.join(buf).strip()
        except Exception as exc:  # pragma: no cover
            return f'[headless] {type(exc).__name__}: {exc}'

    def run_headless_turn_with_runtime(
        self,
        runtime: Any,
        prompt: str,
        *,
        route_limit: int = 5,
    ) -> str:
        """与 :meth:`iter_repl_assistant_events_with_runtime` 配套的无头文本收集。"""
        self.ui_console = None
        buf: list[str] = []
        try:
            for ev in self.iter_repl_assistant_events_with_runtime(
                prompt, runtime=runtime, route_limit=route_limit
            ):
                et = ev.get('type')
                if et == 'text_delta':
                    buf.append(str(ev.get('text', '')))
                elif et in ('finished', 'non_llm', 'blocked', 'llm_error'):
                    out = str(ev.get('output', '') or '').strip()
                    return out if out else ''.join(buf).strip()
            return ''.join(buf).strip()
        except Exception as exc:  # pragma: no cover
            return f'[headless] {type(exc).__name__}: {exc}'

    def stream_submit_message(
        self,
        prompt: str,
        matched_commands: tuple[str, ...] = (),
        matched_tools: tuple[str, ...] = (),
        denied_tools: tuple[PermissionDenial, ...] = (),
    ):
        yield {'type': 'message_start', 'session_id': self.session_id, 'prompt': prompt}
        if matched_commands:
            yield {'type': 'command_match', 'commands': matched_commands}
        if matched_tools:
            yield {'type': 'tool_match', 'tools': matched_tools}
        if denied_tools:
            yield {'type': 'permission_denial', 'denials': [denial.tool_name for denial in denied_tools]}
        result = self.submit_message(prompt, matched_commands, matched_tools, denied_tools)
        yield {'type': 'message_delta', 'text': result.output}
        yield {
            'type': 'message_stop',
            'usage': {'input_tokens': result.usage.input_tokens, 'output_tokens': result.usage.output_tokens},
            'stop_reason': result.stop_reason,
            'transcript_size': len(self.transcript_store.entries),
        }

    def compact_messages_if_needed(self) -> None:
        if len(self.mutable_messages) > self.config.compact_after_turns:
            self.mutable_messages[:] = self.mutable_messages[-self.config.compact_after_turns :]
        self.transcript_store.compact(self.config.compact_after_turns)
        self._shrink_llm_conversation_if_huge()

    def replay_user_messages(self) -> tuple[str, ...]:
        return self.transcript_store.replay()

    def flush_transcript(self) -> None:
        self.transcript_store.flush()

    def persist_session(self) -> str:
        self.flush_transcript()
        conv_tuple: tuple[dict[str, Any], ...] = tuple(
            copy.deepcopy(m) for m in self.llm_conversation_messages
        )
        path = save_session(
            StoredSession(
                session_id=self.session_id,
                messages=tuple(self.mutable_messages),
                input_tokens=self.total_usage.input_tokens,
                output_tokens=self.total_usage.output_tokens,
                llm_conversation_messages=conv_tuple,
                mcp_online_mode=bool(self.mcp_online_mode),
            )
        )
        return str(path)

    def _format_output(self, summary_lines: list[str]) -> str:
        if self.config.structured_output:
            payload = {
                'summary': summary_lines,
                'session_id': self.session_id,
            }
            return self._render_structured_output(payload)
        return '\n'.join(summary_lines)

    def _render_structured_output(self, payload: dict[str, object]) -> str:
        last_error: Exception | None = None
        for _ in range(self.config.structured_retry_limit):
            try:
                return json.dumps(payload, indent=2)
            except (TypeError, ValueError) as exc:  # pragma: no cover - defensive branch
                last_error = exc
                payload = {'summary': ['结构化输出重试'], 'session_id': self.session_id}
        raise RuntimeError('structured output rendering failed') from last_error

    def render_summary(self) -> str:
        command_backlog = build_command_backlog()
        tool_backlog = build_tool_backlog()
        sections = [
            '# Python 移植工作区摘要',
            '',
            self.manifest.to_markdown(),
            '',
            f'命令面: {len(command_backlog.modules)} 个镜像条目',
            *command_backlog.summary_lines()[:10],
            '',
            f'工具面: {len(tool_backlog.modules)} 个镜像条目',
            *tool_backlog.summary_lines()[:10],
            '',
            f'会话 id: {self.session_id}',
            f'已存储对话轮次: {len(self.mutable_messages)}',
            f'已记录权限拒绝: {len(self.permission_denials)}',
            f'用量累计: 入站={self.total_usage.input_tokens} 出站={self.total_usage.output_tokens}',
            f'最大轮次: {self.config.max_turns}',
            f'最大预算 token: {self.config.max_budget_tokens}',
            f'会话记录已落盘: {"是" if self.transcript_store.flushed else "否"}',
        ]
        return '\n'.join(sections)
