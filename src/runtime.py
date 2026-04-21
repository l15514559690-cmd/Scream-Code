from __future__ import annotations

from dataclasses import dataclass, replace

from .commands import PORTED_COMMANDS
from .context import PortContext, build_port_context, render_context
from .history import HistoryLog
from .models import PermissionDenial, PortingModule
from .query_engine import QueryEngineConfig, QueryEnginePort, TurnResult
from .setup import SetupReport, WorkspaceSetup, run_setup
from .system_init import build_system_init_message
from .tools import PORTED_TOOLS
from .execution_registry import build_execution_registry


@dataclass(frozen=True)
class RoutedMatch:
    kind: str
    name: str
    source_hint: str
    score: int


@dataclass
class RuntimeSession:
    prompt: str
    context: PortContext
    setup: WorkspaceSetup
    setup_report: SetupReport
    system_init_message: str
    history: HistoryLog
    routed_matches: list[RoutedMatch]
    turn_result: TurnResult
    command_execution_messages: tuple[str, ...]
    tool_execution_messages: tuple[str, ...]
    stream_events: tuple[dict[str, object], ...]
    persisted_session_path: str

    def as_markdown(self) -> str:
        lines = [
            '# 运行时会话',
            '',
            f'提示: {self.prompt}',
            '',
            '## 上下文',
            render_context(self.context),
            '',
            '## 环境配置',
            f'- Python: {self.setup.python_version} ({self.setup.implementation})',
            f'- 平台: {self.setup.platform_name}',
            f'- 测试命令: {self.setup.test_command}',
            '',
            '## 启动步骤',
            *(f'- {step}' for step in self.setup.startup_steps()),
            '',
            '## 系统初始化',
            self.system_init_message,
            '',
            '## 路由匹配',
        ]
        if self.routed_matches:
            lines.extend(
                f'- [{match.kind}] {match.name} ({match.score}) — {match.source_hint}'
                for match in self.routed_matches
            )
        else:
            lines.append('- 无')
        lines.extend([
            '',
            '## 命令执行',
            *(self.command_execution_messages or ('（无）',)),
            '',
            '## 工具执行',
            *(self.tool_execution_messages or ('（无）',)),
            '',
            '## 流式事件',
            *(f"- {event['type']}: {event}" for event in self.stream_events),
            '',
            '## 轮次结果',
            self.turn_result.output,
            '',
            f'持久化会话路径: {self.persisted_session_path}',
            '',
            self.history.as_markdown(),
        ])
        return '\n'.join(lines)


class PortRuntime:
    def route_prompt(self, prompt: str, limit: int = 5) -> list[RoutedMatch]:
        tokens = {token.lower() for token in prompt.replace('/', ' ').replace('-', ' ').split() if token}
        by_kind = {
            'command': self._collect_matches(tokens, PORTED_COMMANDS, 'command'),
            'tool': self._collect_matches(tokens, PORTED_TOOLS, 'tool'),
        }

        selected: list[RoutedMatch] = []
        for kind in ('command', 'tool'):
            if by_kind[kind]:
                selected.append(by_kind[kind].pop(0))

        leftovers = sorted(
            [match for matches in by_kind.values() for match in matches],
            key=lambda item: (-item.score, item.kind, item.name),
        )
        selected.extend(leftovers[: max(0, limit - len(selected))])
        return selected[:limit]

    def bootstrap_session(self, prompt: str, limit: int = 5, *, llm_enabled: bool = False) -> RuntimeSession:
        context = build_port_context()
        setup_report = run_setup(trusted=True)
        setup = setup_report.setup
        history = HistoryLog()
        engine = QueryEnginePort.from_workspace()
        if llm_enabled:
            engine.config = replace(engine.config, llm_enabled=True)
        history.add('上下文', f'python 文件数={context.python_file_count}, 归档可用={context.archive_available}')
        history.add('注册表', f'命令数={len(PORTED_COMMANDS)}, 工具数={len(PORTED_TOOLS)}')
        matches = self.route_prompt(prompt, limit=limit)
        registry = build_execution_registry()
        command_execs = tuple(registry.command(match.name).execute(prompt) for match in matches if match.kind == 'command' and registry.command(match.name))
        tool_execs = tuple(registry.tool(match.name).execute(prompt) for match in matches if match.kind == 'tool' and registry.tool(match.name))
        denials = tuple(self._infer_permission_denials(matches))
        stream_events = tuple(engine.stream_submit_message(
            prompt,
            matched_commands=tuple(match.name for match in matches if match.kind == 'command'),
            matched_tools=tuple(match.name for match in matches if match.kind == 'tool'),
            denied_tools=denials,
        ))
        turn_result = engine.submit_message(
            prompt,
            matched_commands=tuple(match.name for match in matches if match.kind == 'command'),
            matched_tools=tuple(match.name for match in matches if match.kind == 'tool'),
            denied_tools=denials,
        )
        persisted_session_path = engine.persist_session()
        history.add('路由', f'匹配数={len(matches)}，提示={prompt!r}')
        history.add('执行', f'命令执行数={len(command_execs)} 工具执行数={len(tool_execs)}')
        history.add(
            '轮次',
            f'命令={len(turn_result.matched_commands)} 工具={len(turn_result.matched_tools)} '
            f'拒绝={len(turn_result.permission_denials)} 停止原因={turn_result.stop_reason}',
        )
        history.add('会话存储', persisted_session_path)
        return RuntimeSession(
            prompt=prompt,
            context=context,
            setup=setup,
            setup_report=setup_report,
            system_init_message=build_system_init_message(trusted=True),
            history=history,
            routed_matches=matches,
            turn_result=turn_result,
            command_execution_messages=command_execs,
            tool_execution_messages=tool_execs,
            stream_events=stream_events,
            persisted_session_path=persisted_session_path,
        )

    def run_turn_loop(
        self,
        prompt: str,
        limit: int = 5,
        max_turns: int = 3,
        structured_output: bool = False,
        *,
        llm_enabled: bool = False,
    ) -> list[TurnResult]:
        engine = QueryEnginePort.from_workspace()
        engine.config = replace(
            QueryEngineConfig(max_turns=max_turns, structured_output=structured_output),
            llm_enabled=llm_enabled,
        )
        matches = self.route_prompt(prompt, limit=limit)
        command_names = tuple(match.name for match in matches if match.kind == 'command')
        tool_names = tuple(match.name for match in matches if match.kind == 'tool')
        results: list[TurnResult] = []
        for turn in range(max_turns):
            turn_prompt = prompt if turn == 0 else f'{prompt} [第 {turn + 1} 轮]'
            result = engine.submit_message(turn_prompt, command_names, tool_names, ())
            results.append(result)
            if result.stop_reason != 'completed':
                break
        return results

    def _infer_permission_denials(self, matches: list[RoutedMatch]) -> list[PermissionDenial]:
        denials: list[PermissionDenial] = []
        for match in matches:
            if match.kind == 'tool' and 'bash' in match.name.lower():
                denials.append(
                    PermissionDenial(tool_name=match.name, reason='在 Python 移植版中，破坏性 Shell 执行仍受门控限制'),
                )
        return denials

    def _collect_matches(self, tokens: set[str], modules: tuple[PortingModule, ...], kind: str) -> list[RoutedMatch]:
        matches: list[RoutedMatch] = []
        for module in modules:
            score = self._score(tokens, module)
            if score > 0:
                matches.append(RoutedMatch(kind=kind, name=module.name, source_hint=module.source_hint, score=score))
        matches.sort(key=lambda item: (-item.score, item.name))
        return matches

    @staticmethod
    def _score(tokens: set[str], module: PortingModule) -> int:
        haystacks = [module.name.lower(), module.source_hint.lower(), module.responsibility.lower()]
        score = 0
        for token in tokens:
            if any(token in haystack for haystack in haystacks):
                score += 1
        return score
