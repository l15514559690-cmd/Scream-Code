from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .bootstrap_graph import build_bootstrap_graph
from .claw_config import claw_json_path, load_project_claw_json
from .command_graph import build_command_graph
from .llm_settings import read_llm_connection_settings
from .models import UsageSummary
from .parity_audit import run_parity_audit
from .project_memory import append_long_term_memory_block, read_first_available_project_memory
from .query_engine import QueryEnginePort
from .scream_theme import ScreamTheme, skill_panel
from .session_store import list_saved_session_entries, load_session
from .setup import run_setup
from .skills.base_skill import SLASH_CATEGORY_ORDER, SLASH_CATEGORY_TITLE

_MEMO_EXTRACT_SYSTEM = """你是 Scream Code 的「长期记忆库」冷酷整理引擎。用户会提供一段冗长的对话快照。
你的任务是将其【极度压缩】为几条核心记忆，用于存入 SQLite 长期项目记忆文档中。

## 严格规则：
1. 绝对禁止复述聊天的流水账、具体的报错日志或大段具体的代码实现。
2. 只提取宏观长效信息：用户确立的技术栈、开发偏好、命名规范、以及项目级的重要架构决策。
3. 输出必须极其精简，使用 Markdown 无序列表，总字数严控在 300 字以内。
4. 如果这段对话只是日常 Debug、闲聊或临时查询，并没有沉淀出长效的项目级规则，请仅输出一行：（本轮无项目级长效要点）
"""


def flush_current_repl_session(engine: QueryEnginePort) -> str:
    engine.flush_transcript()
    engine.mutable_messages.clear()
    engine.llm_conversation_messages.clear()
    engine.transcript_store.entries.clear()
    engine.transcript_store.flushed = False
    engine.permission_denials.clear()
    engine.total_usage = UsageSummary(0, 0)
    engine.session_id = uuid4().hex
    engine.repl_team_mode = False
    return engine.persist_session()


def hard_reset_repl_session(engine: QueryEnginePort) -> str:
    try:
        from . import replLauncher

        replLauncher.clear_all_repl_token_warnings()
    except Exception:
        pass
    return flush_current_repl_session(engine)


def completion_text_no_tools(
    messages: list[dict[str, Any]],
    settings: Any,
    *,
    model: str | None = None,
) -> tuple[str, str | None]:
    from .llm_client import LlmClientError, chat_completion_stream

    parts: list[str] = []
    try:
        for chunk in chat_completion_stream(messages, settings, model=model, tools=None):
            if chunk.text_delta:
                parts.append(chunk.text_delta)
    except LlmClientError as exc:
        return '', str(exc)
    except Exception as exc:  # pragma: no cover
        return '', f'{type(exc).__name__}: {exc}'
    return ''.join(parts).strip(), None


def memo_session_excerpt(engine: QueryEnginePort, *, max_chars: int = 24_000) -> str:
    blocks: list[str] = []
    for i, m in enumerate(engine.mutable_messages):
        blocks.append(f'### 用户轮次 {i + 1}\n{m}\n')
    tail = engine.llm_conversation_messages[-24:]
    for msg in tail:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get('role', '') or '')
        content = msg.get('content', '')
        if not isinstance(content, str) or not content.strip():
            continue
        cap = 4000
        body = content if len(content) <= cap else content[:cap] + '\n…(本条已截断)…'
        blocks.append(f'### assistant/user 历史 ({role})\n{body}\n')
    blob = '\n'.join(blocks).strip()
    if len(blob) > max_chars:
        blob = blob[:max_chars] + '\n\n…(摘录已达长度上限，已截断)…'
    return blob


def memo_extract_via_llm(engine: QueryEnginePort, *, excerpt: str) -> tuple[str, str | None]:
    settings = read_llm_connection_settings()
    model = (engine.config.llm_model or '').strip() or None
    user = '请根据以下会话摘录提取长效记忆要点（仅 Markdown 输出）：\n\n' + (
        excerpt if excerpt.strip() else '（无摘录）'
    )
    messages: list[dict[str, Any]] = [
        {'role': 'system', 'content': _MEMO_EXTRACT_SYSTEM},
        {'role': 'user', 'content': user},
    ]
    return completion_text_no_tools(messages, settings, model=model)


def confirm_store_summary(console: Any | None) -> bool:
    import os

    if os.environ.get('SCREAM_REPL_JSON_STDIO', '').strip().lower() in ('1', 'true', 'yes'):
        return False
    try:
        import questionary
    except ImportError:
        questionary = None
    if console is not None and questionary is not None:
        try:
            return bool(
                questionary.confirm('是否将此摘要存入永久记忆库？', default=False).ask()
            )
        except Exception:
            pass
    try:
        ans = input('是否将此摘要存入永久记忆库？[y/N] ').strip().lower()
    except EOFError:
        return False
    return ans in ('y', 'yes')


def print_slash_help(console: Any | None, registry: Any) -> None:
    """按分类列出斜杠技能；``/look`` 等可在首次调用时自动安装 Playwright/Chromium（需网络）。补全菜单打开时 Enter 仅写入补全、不提交整行。"""
    core_static: list[tuple[str, str]] = [
        ('/help', '📖 查看所有可用指令与说明'),
        ('/clear', '🧽 清空当前屏幕显示 (保留记忆)'),
        ('/exit', '🚪 退出 Scream Code (同 /quit)'),
        ('/quit', '🚪 退出 Scream Code (同 /exit)'),
    ]
    system_tail: list[tuple[str, str]] = [
        ('$team <提示>', '仅本条走团队模式'),
    ]

    if console is not None:
        from rich.console import Group
        from rich.table import Table
        from rich.text import Text

        def block(rows: list[tuple[str, str]]) -> Table:
            t = Table(
                show_header=False,
                box=ScreamTheme.BOX_COMPACT,
                show_edge=False,
                padding=(0, 1),
                pad_edge=False,
                expand=True,
            )
            t.add_column('cmd', style=ScreamTheme.TABLE_COL_CMD, no_wrap=True, overflow='fold')
            t.add_column('说明', style=ScreamTheme.TABLE_COL_DESC, overflow='fold', ratio=1)
            for cmd, desc in rows:
                t.add_row(cmd, desc)
            return t

        parts: list[Any] = [
            Text.from_markup(f'[{ScreamTheme.TEXT_INFO}]尖叫 Code · 斜杠指令[/{ScreamTheme.TEXT_INFO}]'),
            Text(''),
        ]
        for cat in SLASH_CATEGORY_ORDER:
            title = SLASH_CATEGORY_TITLE.get(cat, cat)
            rows: list[tuple[str, str]] = []
            if cat == 'core':
                rows.extend(core_static)
            for sk in registry.skills_in_category(cat):
                label = '/' + sk.name
                al = tuple(getattr(type(sk), 'aliases', ()) or ())
                if al:
                    al_disp = '、'.join(f'/{a}' for a in al)
                    label = f'{label}（同 {al_disp}）'
                rows.append((label, sk.description))
            if cat == 'system':
                rows.extend(system_tail)
            if not rows:
                continue
            parts.append(Text.from_markup(f'[bold {ScreamTheme.BORDER_ACCENT}]{title}[/bold {ScreamTheme.BORDER_ACCENT}]'))
            parts.append(block(rows))
            parts.append(Text(''))
        console.print(
            skill_panel(
                Group(*parts),
                title=f'[{ScreamTheme.TEXT_ACCENT}]/help · 指令索引[/{ScreamTheme.TEXT_ACCENT}]',
                variant='accent',
                padding=(0, 1),
            )
        )
        console.print()
    else:
        print('\n=== 尖叫 Code · /help ===\n')
        for cat in SLASH_CATEGORY_ORDER:
            title = SLASH_CATEGORY_TITLE.get(cat, cat)
            rows: list[tuple[str, str]] = []
            if cat == 'core':
                rows.extend(core_static)
            for sk in registry.skills_in_category(cat):
                rows.append((f'/{sk.name}', sk.description))
            if cat == 'system':
                rows.extend(system_tail)
            if not rows:
                continue
            print(f'【{title}】')
            for cmd, desc in rows:
                print(f'  {cmd} — {desc}')
            print()


def print_markdown_block(console: Any | None, md: str, *, title: str) -> None:
    text = md.strip()
    if console is not None:
        from .repl_ui_render import STREAMING_CODE_THEME, ScreamMarkdown

        console.print(
            skill_panel(
                ScreamMarkdown(text, code_theme=STREAMING_CODE_THEME),
                title=title,
                variant='success',
            )
        )
    else:
        print(f'\n--- {title} ---\n{text}\n')


def print_audit(console: Any | None) -> None:
    result = run_parity_audit()
    if console is not None:
        from rich.table import Table

        t = Table(title='parity-audit · 摘要', show_lines=True, expand=True)
        t.add_column('指标', style=ScreamTheme.TABLE_COL_KEY, no_wrap=True, overflow='fold')
        t.add_column('值', style=ScreamTheme.TABLE_COL_VAL, overflow='fold')
        t.add_row('归档可用', '是' if result.archive_present else '否')
        t.add_row('根文件覆盖', f'{result.root_file_coverage[0]}/{result.root_file_coverage[1]}')
        t.add_row('目录覆盖', f'{result.directory_coverage[0]}/{result.directory_coverage[1]}')
        t.add_row('Python/TS 文件', f'{result.total_file_ratio[0]}/{result.total_file_ratio[1]}')
        t.add_row('命令条目', f'{result.command_entry_ratio[0]}/{result.command_entry_ratio[1]}')
        t.add_row('工具条目', f'{result.tool_entry_ratio[0]}/{result.tool_entry_ratio[1]}')
        console.print(skill_panel(t, title='[/audit] · 摘要', variant='warning'))

        n_root = len(result.missing_root_targets)
        n_dir = len(result.missing_directory_targets)
        if n_root or n_dir:
            miss = Table(title='缺失项（节选）', show_lines=True, expand=True)
            miss.add_column('类型', style=ScreamTheme.TEXT_MUTED, no_wrap=True, overflow='fold')
            miss.add_column('名称', style=ScreamTheme.TEXT_ERROR, overflow='fold')
            for x in result.missing_root_targets[:16]:
                miss.add_row('根文件', x)
            for x in result.missing_directory_targets[:16]:
                miss.add_row('目录', x)
            if n_root > 16 or n_dir > 16:
                miss.add_row('…', f'另有 {max(0, n_root - 16) + max(0, n_dir - 16)} 条，见下方 Markdown')
            console.print(skill_panel(miss, title='[/audit] · 缺失项', variant='error'))
        print_markdown_block(console, result.to_markdown(), title='[/audit] · 完整报告 (Markdown)')
    else:
        print(result.to_markdown())


def print_subsystems(console: Any | None, engine: QueryEnginePort) -> None:
    modules = engine.manifest.top_level_modules[:64]
    if console is not None:
        from rich.table import Table

        t = Table(title='subsystems · 顶层 Python 模块', show_lines=True, expand=True)
        t.add_column('模块', style=ScreamTheme.TABLE_COL_KEY, no_wrap=True, overflow='fold')
        t.add_column('文件数', justify='right', style=ScreamTheme.TABLE_COL_VAL)
        t.add_column('备注', style=ScreamTheme.TABLE_COL_DESC, overflow='fold')
        for m in modules:
            t.add_row(m.name, str(m.file_count), (m.notes or '—')[:80])
        console.print(skill_panel(t, title='[/subsystems]', variant='info'))
    else:
        for m in modules:
            print(f'{m.name}\t{m.file_count}\t{m.notes}')


def print_graph(console: Any | None) -> None:
    from rich.markup import escape

    bg = build_bootstrap_graph()
    cg = build_command_graph()
    if console is not None:
        from rich.console import Group
        from rich.text import Text
        from rich.tree import Tree

        r1 = Tree(f'[{ScreamTheme.TEXT_ACCENT}]bootstrap-graph · 引导/运行流[/{ScreamTheme.TEXT_ACCENT}]')
        for st in bg.stages:
            r1.add(escape(st))

        r2 = Tree(f'[{ScreamTheme.TEXT_ACCENT}]command-graph · 命令路由面[/{ScreamTheme.TEXT_ACCENT}]')
        b = r2.add(f'内建命令 ({len(cg.builtins)})')
        for m in cg.builtins[:30]:
            b.add(escape(m.name))
        if len(cg.builtins) > 30:
            b.add(f'… 其余 {len(cg.builtins) - 30} 条')

        pl = r2.add(f'插件类 ({len(cg.plugin_like)})')
        for m in cg.plugin_like[:20]:
            pl.add(escape(m.name))
        if len(cg.plugin_like) > 20:
            pl.add('…')

        sk = r2.add(f'技能类 ({len(cg.skill_like)})')
        for m in cg.skill_like[:20]:
            sk.add(escape(m.name))
        if len(cg.skill_like) > 20:
            sk.add('…')
        console.print(
            skill_panel(
                Group(r1, Text(''), r2),
                title=f'[{ScreamTheme.TEXT_ACCENT}]/graph · 拓扑[/{ScreamTheme.TEXT_ACCENT}]',
                variant='accent',
            )
        )
    else:
        print('=== bootstrap-graph ===')
        for st in bg.stages:
            print(f'  · {st}')
        print('=== command-graph ===')
        print(f'  内建 ({len(cg.builtins)}): ' + ', '.join(m.name for m in cg.builtins[:12]) + ' …')
        print(f'  插件类 ({len(cg.plugin_like)}): ' + ', '.join(m.name for m in cg.plugin_like[:8]) + ' …')
        print(f'  技能类 ({len(cg.skill_like)}): ' + ', '.join(m.name for m in cg.skill_like[:8]) + ' …')


def print_doctor(console: Any | None) -> None:
    rows: list[tuple[str, str, str]] = []
    try:
        rep = run_setup(trusted=True)
        rows.append(('启动报告', '已生成', 'green'))
        py = rep.setup.python_version
        rows.append(('Python', py, 'green'))
    except OSError as exc:
        rows.append(('启动报告', f'失败: {exc}', 'red'))

    for mod in ('openai', 'anthropic', 'rich', 'dotenv', 'prompt_toolkit', 'questionary'):
        try:
            __import__(mod)
            rows.append((f'import {mod}', 'OK', 'green'))
        except ImportError:
            rows.append((f'import {mod}', '缺失 pip install', 'red'))

    cw = Path.cwd()
    try:
        p = cw / '.__scream_write_test__'
        p.write_text('x', encoding='utf-8')
        p.unlink(missing_ok=True)
        rows.append(('工作目录可写', str(cw), 'green'))
    except OSError as exc:
        rows.append(('工作目录可写', str(exc), 'red'))

    claw = load_project_claw_json()
    if claw:
        rows.append(('.claw.json', f'已加载 {len(claw)} 个顶层键', 'green'))
    else:
        cpath = claw_json_path()
        rows.append(
            (
                '.claw.json',
                '未找到或为空' if not cpath.is_file() else '解析失败或空对象',
                'dim',
            )
        )

    if console is not None:
        from rich.table import Table

        t = Table(title='/doctor · 系统体检', show_lines=True, expand=True)
        t.add_column('检查项', style=ScreamTheme.TABLE_COL_KEY, overflow='fold')
        t.add_column('结果', overflow='fold')
        for name, val, st in rows:
            t.add_row(name, f'[{st}]{val}[/{st}]')
        console.print(skill_panel(t, title='[/doctor]', variant='success'))
    else:
        for name, val, st in rows:
            print(f'{name}: {val}')


def print_cost(console: Any | None, engine: QueryEnginePort) -> None:
    u = engine.total_usage
    rate_in = 5.0 / 1_000_000
    rate_out = 15.0 / 1_000_000
    est = u.input_tokens * rate_in + u.output_tokens * rate_out
    entries = list_saved_session_entries(limit=5)
    extra_in = sum(x[2] for x in entries)
    extra_out = sum(x[3] for x in entries)

    if console is not None:
        from rich.table import Table

        t = Table(title='/cost · Token 与粗略费用（USD 估算）', show_lines=True, expand=True)
        t.add_column('项', style=ScreamTheme.TABLE_COL_KEY, overflow='fold')
        t.add_column('值', justify='right', overflow='fold')
        t.add_row('本会话 input_tokens', str(u.input_tokens))
        t.add_row('本会话 output_tokens', str(u.output_tokens))
        t.add_row('估算费用（示意）', f'~${est:.6f}')
        t.add_row('最近落盘会话(前5) in 合计', str(extra_in))
        t.add_row('最近落盘会话(前5) out 合计', str(extra_out))
        console.print(skill_panel(t, title='[/cost]', variant='accent'))
        console.print('[dim]费率仅为示意；以厂商账单为准。[/dim]')
    else:
        print(f'input={u.input_tokens} output={u.output_tokens} ~${est:.6f} (示意)')


def print_status(console: Any | None, engine: QueryEnginePort) -> None:
    from . import model_manager

    model_manager.ensure_default_config_file()
    raw = model_manager.read_persisted_config_raw()
    aga = model_manager.read_allow_global_access(raw)
    prof = model_manager.get_active_profile(raw) if raw else None
    mem_name, _ = read_first_available_project_memory(Path.cwd())
    claw = load_project_claw_json()
    try:
        from .llm_client import get_openai_agent_tools

        n_tools = len(get_openai_agent_tools())
    except Exception:
        n_tools = -1
    try:
        settings = read_llm_connection_settings()
        has_key = bool((settings.api_key or '').strip())
    except Exception:
        has_key = False

    rows = [
        ('沙箱/越狱', '全局越狱' if aga else '沙箱模式'),
        ('已加载工具数', str(n_tools)),
        ('API 密钥可读', '是' if has_key else '否'),
        ('激活模型', prof.alias if prof else '（无）'),
        ('项目记忆文件', mem_name or '（无）'),
        ('.claw.json', '有' if claw else '无'),
        ('LLM 消息缓存条数', str(len(engine.llm_conversation_messages))),
        ('团队模式', '开' if engine.repl_team_mode else '关'),
    ]
    if console is not None:
        from rich.table import Table

        t = Table(title='/status · Agent 与配置', show_lines=True, expand=True)
        t.add_column('项', style=ScreamTheme.TABLE_COL_KEY, no_wrap=True, overflow='fold')
        t.add_column('值', style=ScreamTheme.TABLE_COL_VAL, overflow='fold')
        for k, v in rows:
            t.add_row(k, v)
        console.print(skill_panel(t, title='[/status]', variant='accent'))
    else:
        for k, v in rows:
            print(f'{k}: {v}')


def print_sessions(console: Any | None) -> None:
    entries = list_saved_session_entries(limit=80)
    if console is not None:
        from rich.table import Table

        if not entries:
            console.print('[dim]尚无已落盘会话（.port_sessions/）。[/dim]')
            return
        t = Table(
            title='/sessions · 本地会话历史',
            box=ScreamTheme.BOX,
            show_lines=True,
            expand=True,
        )
        t.add_column('会话 ID', style=ScreamTheme.TEXT_INFO, no_wrap=True, overflow='fold')
        t.add_column('消息数', justify='right', style=ScreamTheme.TABLE_COL_VAL)
        t.add_column('↑入 / ↓出', justify='right', style=ScreamTheme.TEXT_MUTED)
        t.add_column('更新时间', style=ScreamTheme.TEXT_MUTED, overflow='fold')
        for sid, n, it, ot, path in entries:
            ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(path.stat().st_mtime))
            t.add_row(sid, str(n), f'{it}/{ot}', ts)
        console.print(skill_panel(t, title='[/sessions]', variant='info'))
        console.print('[dim]恢复上下文: [bold]/load <session_id>[/bold][/dim]')
    else:
        if not entries:
            print('（无已保存会话）')
        for sid, n, it, ot, path in entries:
            ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(path.stat().st_mtime))
            print(f'{sid}\t{n}\t{it}/{ot}\t{ts}')
        print('使用: /load <session_id>')


def msg(console: Any | None, text: str, *, style: str = 'dim') -> None:
    if console is not None:
        console.print(f'[{style}]{text}[/{style}]')
    else:
        print(text)


def print_skills_table(console: Any | None) -> None:
    from rich.table import Table

    cg = build_command_graph()
    table = Table(
        title=f'[{ScreamTheme.TEXT_ACCENT}]/skills · 已加载的扩展能力[/{ScreamTheme.TEXT_ACCENT}]',
        box=ScreamTheme.BOX,
        show_lines=True,
        expand=True,
    )
    table.add_column('名称', style=ScreamTheme.TEXT_SUCCESS, overflow='fold')
    table.add_column('类型', style=ScreamTheme.TABLE_COL_KEY, overflow='fold')
    for m in cg.skill_like:
        table.add_row(m.name, 'Skill (技能)')
    for m in cg.plugin_like:
        table.add_row(m.name, 'Plugin (插件)')
    if console is not None:
        console.print(skill_panel(table, variant='success'))
    else:
        print('/skills · 已加载的扩展能力')
        for m in cg.skill_like:
            print(f'  {m.name}\tSkill (技能)')
        for m in cg.plugin_like:
            print(f'  {m.name}\tPlugin (插件)')


def print_config_panel(console: Any | None) -> None:
    from . import model_manager

    raw = model_manager.read_persisted_config_raw()
    if raw is None:
        msg(
            console,
            '未找到有效的 ~/.scream/llm_config.json（文件不存在或 JSON 无法解析）。',
            style='yellow',
        )
        return
    if console is not None:
        from rich.json import JSON

        console.print(
            skill_panel(
                JSON(json.dumps(raw, ensure_ascii=False, indent=2)),
                title=f'[{ScreamTheme.TEXT_ACCENT}]/config · ~/.scream[/{ScreamTheme.TEXT_ACCENT}]',
                variant='accent',
                padding=(1, 1),
            )
        )
    else:
        print(json.dumps(raw, ensure_ascii=False, indent=2))
    msg(
        console,
        '💡 提示：若需交互式修改配置，请在新终端运行 `scream config`。',
        style='dim',
    )


def prompt_toolkit_scream_slash_style() -> Any:
    """
    ``prompt_toolkit`` 斜杠补全悬浮菜单 + 底栏：与 ``tui_app`` 靛紫深色一致。
    """
    from prompt_toolkit.styles import Style

    brand = '#4F46E5'
    surface = '#161622'
    return Style.from_dict(
        {
            'completion-menu': f'bg:{surface}',
            'completion-menu.completion': f'bg:{surface} fg:#e2e8f0',
            'completion-menu.completion.current': f'bg:{brand} fg:#ffffff bold',
            'completion-menu.meta.completion': 'fg:#64748b',
            'completion-menu.meta.completion.current': f'bg:{brand} fg:#a5b4fc',
            '': 'fg:#e2e8f0',
            # 神经底栏：近黑底 + 默认灰字；高亮由 HTML 内 ansicyan / ansigreen 控制
            'bottom-toolbar': 'bg:#020617 fg:#64748b noreverse',
        }
    )


def prompt_toolkit_slash_completion_enter_bindings() -> Any:
    """
    补全菜单可见时：``Enter`` / ``Ctrl-M`` 只应用当前（或首个）补全项并追加空格，
    不调用 ``validate_and_handle``，避免未输完参数就提交整行。

    绑定置于 ``PromptSession`` 的 ``key_bindings`` 中，由 ``merge_key_bindings`` 排在默认
    ``accept-line`` 之后且 ``eager=True``，以便优先于提交。
    """
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.enums import DEFAULT_BUFFER
    from prompt_toolkit.filters import Condition, has_focus
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @Condition
    def completion_menu_open() -> bool:
        return get_app().current_buffer.complete_state is not None

    @kb.add(
        'enter',
        'c-m',
        filter=completion_menu_open & has_focus(DEFAULT_BUFFER),
        eager=True,
    )
    def _enter_apply_completion_only(event: Any) -> None:
        b = event.app.current_buffer
        cs = b.complete_state
        if cs is None:
            return
        comp = cs.current_completion
        if comp is None and cs.completions:
            comp = cs.completions[0]
        if comp is not None:
            b.apply_completion(comp)
            b.insert_text(' ')
        else:
            b.cancel_completion()

    return kb


class SlashCommandCompleter:
    """
    当光标前文本从某处起以 ``/`` 为前缀时，按前缀过滤
    :meth:`SkillsRegistry.iter_slash_completion_items` 的结果。

    实现 ``prompt_toolkit.completion.Completer`` 协议，供 ``ThreadedCompleter`` 包装。
    """

    def get_completions(self, document: Any, complete_event: Any):
        from prompt_toolkit.completion import Completion

        from .skills_registry import get_skills_registry

        text = document.text_before_cursor
        slash = text.rfind('/')
        if slash < 0:
            return
        fragment = text[slash:]
        if not fragment.startswith('/'):
            return
        base_commands: list[tuple[str, str]] = [
            ('/help', '📖 查看所有可用指令与说明'),
            ('/clear', '🧽 清空当前屏幕显示 (保留记忆)'),
            ('/exit', '🚪 退出 Scream Code (同 /quit)'),
            ('/quit', '🚪 退出 Scream Code (同 /exit)'),
        ]
        seen: set[str] = set()
        for cmd, meta in base_commands:
            if cmd in seen:
                continue
            seen.add(cmd)
            if cmd.startswith(fragment):
                yield Completion(
                    cmd,
                    start_position=-len(fragment),
                    display_meta=meta,
                )
        for cmd, meta in get_skills_registry().iter_slash_completion_items():
            if cmd in seen:
                continue
            seen.add(cmd)
            if cmd.startswith(fragment):
                yield Completion(
                    cmd,
                    start_position=-len(fragment),
                    display_meta=meta,
                )
