from __future__ import annotations

import copy
import json
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


@dataclass(frozen=True)
class QueryEngineConfig:
    #: 用户轮次硬上限（1.0 默认 100；与工具闭环上限分轨，见 ``llm_client.agent_tool_iteration_cap``）
    max_turns: int = 100
    #: 累计 token 预算（默认 3M；产品线长上下文底线 ≥2M，勿与上游 stub 的 2k 级默认对齐）
    max_budget_tokens: int = 3_000_000
    #: 仅当 ``mutable_messages`` 条数超过此值时才做滑动裁剪；贴近 ``max_turns`` 以尽量保留原文
    compact_after_turns: int = 99
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
    #: REPL 等场景注入 Rich Console，用于 LLM 请求与工具路由时的 Status 指示器。
    ui_console: Any | None = field(default=None, repr=False)

    @classmethod
    def from_workspace(cls) -> 'QueryEnginePort':
        return cls(manifest=build_port_manifest())

    @classmethod
    def from_saved_session(cls, session_id: str) -> 'QueryEnginePort':
        """
        从 JSON 恢复 ``mutable_messages``、用量与（若存在）``llm_conversation_messages`` 快照。
        快照存在时恢复完整多轮 LLM 上下文；仅旧版文件时退化为仅用 ``mutable_messages`` 拼用户历史。
        恢复后会用当前项目记忆刷新首条 ``system``，避免 SCREAM.md 等更新后不生效。
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
        )

    def _coerce_turn_capacity_before_turn(self) -> None:
        """
        在判定轮次上限前，将 ``mutable_messages`` 压到 ``compact_after_turns`` 以内，
        并收缩过大的 ``llm_conversation_messages``，避免长会话直接 blocked。
        """
        cap = self.config.max_turns
        soft = self.config.compact_after_turns
        if len(self.mutable_messages) < cap:
            self._shrink_llm_conversation_if_huge()
            return
        keep = soft if soft < cap else max(cap - 1, 1)
        keep = max(keep, 1)
        if len(self.mutable_messages) > keep:
            self.mutable_messages[:] = self.mutable_messages[-keep:]
        self._shrink_llm_conversation_if_huge()

    def _shrink_llm_conversation_if_huge(self) -> None:
        """内存侧防止 ``llm_conversation_messages`` 无限增长；发往模型前仍会经 ``prune_historical_messages``。"""
        msgs = self.llm_conversation_messages
        max_keep = 800
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
        if len(self.mutable_messages) >= self.config.max_turns:
            output = f'在处理该提示前已达到最大对话轮次上限: {prompt}'
            return TurnResult(
                prompt=prompt,
                output=output,
                matched_commands=matched_commands,
                matched_tools=matched_tools,
                permission_denials=denied_tools,
                usage=self.total_usage,
                stop_reason='max_turns_reached',
            )

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
        return self._repl_messages_base_before_current_user() + [user_msg]

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

        messages = self._assemble_messages_for_llm_turn(
            prompt, matched_commands, matched_tools, denied_tools
        )
        settings = read_llm_connection_settings()
        raw_override = (self.config.llm_model or '').strip()
        model_override = raw_override or None

        def _call_llm():
            return chat_completion(messages, settings, model=model_override)

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
        from .llm_client import get_openai_agent_tools, iter_agent_executor_events
        from .llm_settings import read_llm_connection_settings

        self._coerce_turn_capacity_before_turn()
        if len(self.mutable_messages) >= self.config.max_turns:
            yield {
                'type': 'blocked',
                'output': f'在处理该提示前已达到最大对话轮次上限: {prompt}',
            }
            return

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

        messages: list[dict[str, Any]] = self._assemble_messages_for_llm_turn(
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

        try:
            for ev in iter_agent_executor_events(
                messages,
                settings,
                model=model_override,
                tools=get_openai_agent_tools(),
            ):
                et = ev.get('type')
                if et == 'executor_complete':
                    snap = ev.get('conversation_messages')
                    if isinstance(snap, list):
                        self.llm_conversation_messages = snap
                    in_tok = int(ev.get('input_tokens', 0))
                    out_tok = int(ev.get('output_tokens', 0))
                    llm_text = str(ev.get('assistant_text', '') or '')
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

                    stop_reason = str(ev.get('stop_reason') or 'completed')
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
        from .llm_client import iter_agent_executor_events
        from .llm_settings import read_llm_connection_settings

        self._coerce_turn_capacity_before_turn()
        if len(self.mutable_messages) >= self.config.max_turns:
            yield {
                'type': 'blocked',
                'output': f'在处理该提示前已达到最大对话轮次上限: {prompt}',
            }
            return

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

        phases: tuple[tuple[str, str, bool], ...] = (
            (
                'Planner',
                base_user
                + '\n\n【多代理·Planner】你是规划子模块：只输出简洁任务拆解（条列），不要调用任何工具。',
                False,
            ),
            (
                'Coder',
                '【多代理·Coder】你是实现子模块：结合对话中 Planner 的拆解与完整上文，给出具体实现步骤或代码；必要时可调用项目工具。',
                True,
            ),
            (
                'Reviewer',
                '【多代理·Reviewer】你是审查子模块：审查对话中的方案与输出，列出风险与改进建议；不要调用工具。',
                False,
            ),
        )

        combined_chunks: list[str] = []
        phase_in = 0
        phase_out = 0

        try:
            for agent_label, user_text, use_tools in phases:
                yield {'type': 'team_agent', 'agent': agent_label}
                msgs = self._assemble_messages_for_team_phase(user_text)
                tools_kw: list[dict[str, Any]] | None = None if use_tools else []
                for ev in iter_agent_executor_events(
                    msgs,
                    settings,
                    model=model_override,
                    tools=tools_kw,
                ):
                    et = ev.get('type')
                    if et == 'executor_complete':
                        snap = ev.get('conversation_messages')
                        if isinstance(snap, list):
                            self.llm_conversation_messages = snap
                        phase_in += int(ev.get('input_tokens', 0))
                        phase_out += int(ev.get('output_tokens', 0))
                        body = str(ev.get('assistant_text', '') or '').strip()
                        combined_chunks.append(f'[{agent_label}]\n{body}')
                        break
                    if et == 'llm_error':
                        yield ev
                        return
                    yield ev

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
