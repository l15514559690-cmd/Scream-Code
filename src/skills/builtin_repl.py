from __future__ import annotations

import json
from dataclasses import replace
from typing import ClassVar

from ..query_engine import QueryEnginePort
from ..scream_theme import ScreamTheme, Variant, skill_panel
from ..repl_slash_helpers import (
    confirm_store_summary,
    flush_current_repl_session,
    hard_reset_repl_session,
    memo_extract_via_llm,
    memo_session_excerpt,
    msg,
    print_audit,
    print_config_panel,
    print_cost,
    print_doctor,
    print_graph,
    print_markdown_block,
    print_sessions,
    print_skills_table,
    print_slash_help,
    print_status,
    print_subsystems,
)
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class HelpSkill(BaseSkill):
    name: ClassVar[str] = 'help'
    description: ClassVar[str] = '本菜单（含 /?）'
    category: ClassVar[str] = 'core'
    aliases: ClassVar[tuple[str, ...]] = ('?',)

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from ..skills_registry import get_skills_registry

        print_slash_help(context.console, get_skills_registry())
        return SkillOutcome()


class SummarySkill(BaseSkill):
    name: ClassVar[str] = 'summary'
    description: ClassVar[str] = '📝 生成当前项目的全局摘要并归档'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from ..project_memory import append_long_term_memory_block

        body = context.engine.render_summary()
        print_markdown_block(context.console, body, title='/summary · 工作区与会话摘要')
        if confirm_store_summary(context.console):
            store_body = f'### /summary 快照\n\n```\n{body}\n```'
            result = append_long_term_memory_block(store_body, source_tag='/summary')
            msg(
                context.console,
                result,
                style='bold green' if result.startswith('已安全') else 'yellow',
            )
        return SkillOutcome()


class MemoSkill(BaseSkill):
    name: ClassVar[str] = 'memo'
    description: ClassVar[str] = '🧠 提取并保存当前对话的核心记忆'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from ..project_memory import append_long_term_memory_block

        memo_direct = (args or '').strip()
        if memo_direct:
            result = append_long_term_memory_block(memo_direct, source_tag='/memo')
            if context.console is not None:
                from rich.text import Text

                ok = result.startswith('已安全')
                st = ScreamTheme.TEXT_SUCCESS if ok else ScreamTheme.TEXT_WARNING
                memo_var: Variant = 'success' if ok else 'warning'
                context.console.print(
                    skill_panel(
                        Text.from_markup(f'[{st}]{result}[/{st}]'),
                        title=f'[{ScreamTheme.TEXT_INFO}]/memo · 长效记忆[/{ScreamTheme.TEXT_INFO}]',
                        variant=memo_var,
                    )
                )
            else:
                print(result)
            return SkillOutcome()
        if not context.engine.config.llm_enabled:
            msg(context.console, '/memo 需要已启用大模型的 REPL（勿使用 repl --no-llm）。', style='yellow')
            return SkillOutcome()
        excerpt = memo_session_excerpt(context.engine)
        if not excerpt.strip():
            msg(context.console, '当前会话尚无足够内容可供提取，可先多聊几句再试。', style='yellow')
            return SkillOutcome()
        msg(context.console, '正在调用模型整理长效要点（隐藏 Prompt，不写入当前对话历史）…', style='dim')
        text, err = memo_extract_via_llm(context.engine, excerpt=excerpt)
        if err:
            msg(context.console, f'模型调用失败: {err}', style='bold red')
            return SkillOutcome()
        if not text.strip():
            msg(context.console, '模型未返回可写入内容。', style='yellow')
            return SkillOutcome()
        result = append_long_term_memory_block(text, source_tag='/memo')
        msg(context.console, result, style='bold green' if result.startswith('已安全') else 'yellow')
        return SkillOutcome()


class NewSkill(BaseSkill):
    name: ClassVar[str] = 'new'
    description: ClassVar[str] = '✨ 开启全新会话 (清空当前上下文)'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        try:
            path = hard_reset_repl_session(context.engine)
            msg(
                context.console,
                f'已硬重置：全新 session、对话与计数器已清空，并已落盘 {path}。'
                ' 长效记忆文件未改动。',
                style='bold green',
            )
        except OSError as exc:
            msg(context.console, f'/new 落盘失败: {exc}', style='bold red')
        return SkillOutcome()


class FlushSkill(BaseSkill):
    name: ClassVar[str] = 'flush'
    description: ClassVar[str] = '💾 保存并结束当前对话 (重置 Token)'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        try:
            path = flush_current_repl_session(context.engine)
            msg(context.console, f'已清空对话并落盘新会话: {path}', style='bold green')
        except OSError as exc:
            msg(context.console, f'flush 失败: {exc}', style='bold red')
        return SkillOutcome()


class StopSkill(BaseSkill):
    name: ClassVar[str] = 'stop'
    description: ClassVar[str] = '🛑 强制中断 AI 当前的思考与执行'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        context.engine.request_stream_abort()
        msg(
            context.console,
            '已请求中断当前生成与工具链（流式输出将尽快结束；bash 子进程将尽快结束；未执行的 tool 将收到 [User Interrupted Task]）。',
            style='bold yellow',
        )
        return SkillOutcome()


class SessionsSkill(BaseSkill):
    name: ClassVar[str] = 'sessions'
    description: ClassVar[str] = '📂 查看本地历史会话记录'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_sessions(context.console)
        return SkillOutcome()


class LoadSkill(BaseSkill):
    name: ClassVar[str] = 'load'
    description: ClassVar[str] = '🔄 恢复指定的历史会话 (需加 ID)'
    category: ClassVar[str] = 'memory'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from ..session_store import (
            BLOCKED_CROSS_WORKSPACE_LOAD_MSG,
            CrossWorkspaceSessionLoadBlockedError,
            load_session,
        )

        sid = (args or '').split()[0] if (args or '').strip() else ''
        if not sid:
            msg(context.console, '用法: /load <session_id>', style='yellow')
            return SkillOutcome()
        try:
            load_session(sid)
        except CrossWorkspaceSessionLoadBlockedError:
            msg(context.console, BLOCKED_CROSS_WORKSPACE_LOAD_MSG, style='bold red')
            return SkillOutcome()
        except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            msg(context.console, f'无法加载会话 {sid!r}: {exc}', style='bold red')
            return SkillOutcome()

        new_eng = QueryEnginePort.from_saved_session(sid)
        new_eng.config = replace(context.engine.config)
        new_eng.ui_console = context.engine.ui_console
        new_eng.repl_team_mode = context.engine.repl_team_mode
        n = len(new_eng.mutable_messages)
        if context.console is not None:
            context.console.print(
                f'[bold green]已加载会话[/bold green] [cyan]{sid}[/cyan] [dim]（消息 {n} 条）[/dim]'
            )
        else:
            print(f'已加载会话 {sid}（消息 {n} 条）。')
        return SkillOutcome(new_engine=new_eng)


class AuditSkill(BaseSkill):
    name: ClassVar[str] = 'audit'
    description: ClassVar[str] = '🛠️ [诊断] 审查工作区架构对齐度'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_audit(context.console)
        return SkillOutcome()


class ReportSkill(BaseSkill):
    name: ClassVar[str] = 'report'
    description: ClassVar[str] = '🛠️ [诊断] 生成深度环境启动报告'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from ..setup import run_setup

        try:
            rep = run_setup(trusted=True).as_markdown()
        except OSError as exc:
            msg(context.console, f'setup-report 失败: {exc}', style='red')
            return SkillOutcome()
        print_markdown_block(context.console, rep, title='/report · setup-report')
        return SkillOutcome()


class SubsystemsSkill(BaseSkill):
    name: ClassVar[str] = 'subsystems'
    description: ClassVar[str] = '🛠️ [诊断] 列出顶层 Python 模块'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_subsystems(context.console, context.engine)
        return SkillOutcome()


class GraphSkill(BaseSkill):
    name: ClassVar[str] = 'graph'
    description: ClassVar[str] = '🛠️ [诊断] 查看引擎路由与命令图谱'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_graph(context.console)
        return SkillOutcome()


class ConfigSkill(BaseSkill):
    name: ClassVar[str] = 'config'
    description: ClassVar[str] = '⚙️ 查看当前模型与 API 密钥配置'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_config_panel(context.console)
        return SkillOutcome()


class SkillsCommandSkill(BaseSkill):
    name: ClassVar[str] = 'skills'
    description: ClassVar[str] = '🧩 查看已加载的扩展技能与插件'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_skills_table(context.console)
        return SkillOutcome()


class DoctorSkill(BaseSkill):
    name: ClassVar[str] = 'doctor'
    description: ClassVar[str] = '🏥 检查系统环境与依赖是否健康'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_doctor(context.console)
        return SkillOutcome()


class CostSkill(BaseSkill):
    name: ClassVar[str] = 'cost'
    description: ClassVar[str] = '💰 查看 Token 消耗与账单估算'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_cost(context.console, context.engine)
        return SkillOutcome()


class StatusSkill(BaseSkill):
    name: ClassVar[str] = 'status'
    description: ClassVar[str] = '📊 查看 AI 引擎与系统运行状态'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        print_status(context.console, context.engine)
        return SkillOutcome()


class TeamSkill(BaseSkill):
    name: ClassVar[str] = 'team'
    description: ClassVar[str] = '🐺 切换多智能体团队协作模式'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        context.engine.repl_team_mode = not context.engine.repl_team_mode
        state = '开启' if context.engine.repl_team_mode else '关闭'
        msg(context.console, f'多代理团队模式已{state}（Planner → Coder → Reviewer）。', style='bold green')
        return SkillOutcome()


class UndoSkill(BaseSkill):
    """
    /undo — 一键撤销：恢复上轮 Agent 所做文件修改，并裁剪 LLM 对话上下文。

    1. 调用 SnapshotManager.restore_last_snapshot() 恢复/删除文件。
    2. 将 engine.llm_conversation_messages 裁剪到用户上一次输入之前的状态
       （剔除最后一条 role=user 的消息及其后续产生的所有消息）。
    """

    name: ClassVar[str] = 'undo'
    description: ClassVar[str] = '↩️ 撤销上一次执行所做的全部文件修改，并回滚大模型对话上下文'
    category: ClassVar[str] = 'core'
    aliases: ClassVar[tuple[str, ...]] = ()

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        from ..project_memory import project_memory_workspace_root
        from ..utils.snapshot_manager import restore_last_snapshot

        ws_root = project_memory_workspace_root()
        restored = restore_last_snapshot(ws_root)

        # ── 裁剪 LLM 对话上下文 ─────────────────────────────────────────────
        # 找到 llm_conversation_messages 中最后一条 role=user 的消息位置，
        # 及其后续所有消息一并剔除（包括 assistant 响应、tool 调用记录）。
        llm_msgs = context.engine.llm_conversation_messages
        last_user_idx = -1
        for i in range(len(llm_msgs) - 1, -1, -1):
            if llm_msgs[i].get('role', '') == 'user':
                last_user_idx = i
                break
        if last_user_idx >= 0:
            del llm_msgs[last_user_idx:]
            trimmed = True
        else:
            trimmed = False
        # ── /裁剪 LLM 对话上下文 ────────────────────────────────────────────

        if not restored and not trimmed:
            msg(context.console, '/undo：无内容可撤销（本轮未修改任何文件）。', style='yellow')
            return SkillOutcome()

        if restored:
            paths_str = ', '.join(restored) if len(restored) <= 5 else ', '.join(restored[:5]) + f'…（共 {len(restored)} 个）'
            msg(
                context.console,
                f'[bold green]↩️ 已撤销上一次执行。恢复了以下文件：{paths_str}[/bold green]',
                style='bold green',
            )
        else:
            msg(context.console, '↩️ 已回滚对话上下文（无文件需恢复）。', style='bold green')

        return SkillOutcome()
