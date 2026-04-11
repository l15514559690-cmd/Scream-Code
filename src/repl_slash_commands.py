from __future__ import annotations

import json
import subprocess
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
from .session_store import list_saved_session_entries, load_session
from .setup import run_setup

_MEMO_EXTRACT_SYSTEM = """你是「长效记忆库」整理助手。下面是一段 REPL 对话摘录（仅作依据，勿外传语气）。
请只输出 Markdown（可用 `###` 小标题与 `-` 列表），归纳：
1. 用户的技术偏好（语言、框架、工具、代码风格）
2. 已确定的架构或设计决策
3. 关键项目背景与约束

要求：不要寒暄；不要重复摘录全文；禁止臆造摘录中不存在的内容；每条尽量具体可执行。
若几乎无可保存信息，只输出一行：（本轮无可提取的长效要点）"""


def _flush_current_repl_session(engine: QueryEnginePort) -> str:
    """清空当前 REPL 对话与累计用量，分配新 session_id 并落盘。"""
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


def _hard_reset_repl_session(engine: QueryEnginePort) -> str:
    """
    比 ``/flush`` 更彻底：在同等清空与会话落盘基础上，额外清空 REPL 展示层 token 水位缓存，
    使新会话与「刚打开窗口」一致。
    """
    try:
        from . import replLauncher

        replLauncher.clear_all_repl_token_warnings()
    except Exception:
        pass
    return _flush_current_repl_session(engine)


def _completion_text_no_tools(
    messages: list[dict[str, Any]],
    settings: Any,
    *,
    model: str | None = None,
) -> tuple[str, str | None]:
    """单次补全（不注册工具），供 ``/memo`` 隐藏 Prompt。"""
    from .llm_client import LlmClientError, chat_completion_stream

    parts: list[str] = []
    try:
        for chunk in chat_completion_stream(messages, settings, model=model, tools=None):
            if chunk.text_delta:
                parts.append(chunk.text_delta)
    except LlmClientError as exc:
        return '', str(exc)
    except Exception as exc:  # pragma: no cover - 网络/供应商异常
        return '', f'{type(exc).__name__}: {exc}'
    return ''.join(parts).strip(), None


def _memo_session_excerpt(engine: QueryEnginePort, *, max_chars: int = 48_000) -> str:
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
        cap = 12_000
        body = content if len(content) <= cap else content[:cap] + '\n…(本条已截断)…'
        blocks.append(f'### assistant/user 历史 ({role})\n{body}\n')
    blob = '\n'.join(blocks).strip()
    if len(blob) > max_chars:
        blob = blob[:max_chars] + '\n\n…(摘录已达长度上限，已截断)…'
    return blob


def _memo_extract_via_llm(engine: QueryEnginePort, *, excerpt: str) -> tuple[str, str | None]:
    from .llm_settings import read_llm_connection_settings

    settings = read_llm_connection_settings()
    model = (engine.config.llm_model or '').strip() or None
    user = '请根据以下会话摘录提取长效记忆要点（仅 Markdown 输出）：\n\n' + (
        excerpt if excerpt.strip() else '（无摘录）'
    )
    messages: list[dict[str, Any]] = [
        {'role': 'system', 'content': _MEMO_EXTRACT_SYSTEM},
        {'role': 'user', 'content': user},
    ]
    return _completion_text_no_tools(messages, settings, model=model)


def _confirm_store_summary(console: Any | None) -> bool:
    import os

    # Rust TUI 经 JSON stdio 驱动时 stdin 专用于协议行，不能阻塞在 questionary/input。
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


def _print_help(console: Any | None) -> None:
    sections: list[tuple[str, list[str]]] = [
        (
            '时光机与记忆',
            [
                '/summary — 项目与会话摘要；可确认后写入长效记忆（SCREAM.md / CLAUDE.md）',
                '/memo [要点] — 带文字时直接追加到 SCREAM.md；不带参数时用模型从会话提取要点',
                '/new — 硬重置：清空对话、新 session_id、重置计数与展示层缓存（较 /flush 更彻底）',
                '/flush — 清空本轮对话、重置 token 累计并落盘新会话',
                '/sessions — 扫描 .port_sessions 下列出历史会话',
                '/load <id> — 恢复指定会话 id（原生 load-session）',
                '/stop — 中断当前轮工具链（长 bash、后续 tool 调用会收到 [User Interrupted Task]）',
            ],
        ),
        (
            '系统体检',
            [
                '/audit — 原生 parity-audit（与 TS 归档一致性）',
                '/report — 原生 setup-report（环境与启动体检）',
            ],
        ),
        (
            '深度引擎',
            [
                '/subsystems — 原生 subsystems（顶层 Python 子系统模块）',
                '/graph — bootstrap-graph + command-graph 树状总览',
            ],
        ),
        (
            '日常利器',
            [
                '/doctor — Python/依赖/路径/权限快速体检（绿通过/红建议）',
                '/cost — 本会话 Token 与粗略费用账单',
                '/diff — 当前 Git 工作区改动（git diff --stat）',
                '/status — 沙箱权限、工具数、模型、.claw.json、项目记忆',
            ],
        ),
        (
            '多代理团队',
            [
                '/team — 开关多代理编排（Planner→Coder→Reviewer）',
                '$team <提示> — 仅本条以团队模式处理（不改变开关）',
            ],
        ),
    ]
    if console is not None:
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        blocks: list[Any] = [Text.from_markup('[bold cyan]尖叫 Code · 原生能力（斜杠指令）[/bold cyan]')]
        for title, lines in sections:
            t = Table(show_header=False, box=None, padding=(0, 1))
            t.add_column('cmd', style='bold green', no_wrap=True)
            t.add_column('说明', style='dim')
            for line in lines:
                seg = line.split(' — ', 1)
                t.add_row(seg[0], seg[1] if len(seg) > 1 else '')
            blocks.append(Panel(t, title=title, border_style='blue'))
        console.print(Panel(Group(*blocks), border_style='cyan', title='[bold]/help[/bold]'))
    else:
        print('\n=== 尖叫 Code · 斜杠指令 (/help) ===')
        for title, lines in sections:
            print(f'\n【{title}】')
            for ln in lines:
                print(f'  {ln}')
        print()


def _print_markdown_block(console: Any | None, md: str, *, title: str) -> None:
    text = md.strip()
    if console is not None:
        from rich.panel import Panel

        from .repl_ui_render import ScreamMarkdown

        console.print(
            Panel(
                ScreamMarkdown(text, code_theme='monokai'),
                title=title,
                border_style='green',
            )
        )
    else:
        print(f'\n--- {title} ---\n{text}\n')


def _print_audit(console: Any | None) -> None:
    result = run_parity_audit()
    if console is not None:
        from rich.panel import Panel
        from rich.table import Table

        t = Table(title='parity-audit · 摘要', show_lines=True)
        t.add_column('指标', style='cyan', no_wrap=True)
        t.add_column('值', style='white')
        t.add_row('归档可用', '是' if result.archive_present else '否')
        t.add_row('根文件覆盖', f'{result.root_file_coverage[0]}/{result.root_file_coverage[1]}')
        t.add_row('目录覆盖', f'{result.directory_coverage[0]}/{result.directory_coverage[1]}')
        t.add_row('Python/TS 文件', f'{result.total_file_ratio[0]}/{result.total_file_ratio[1]}')
        t.add_row('命令条目', f'{result.command_entry_ratio[0]}/{result.command_entry_ratio[1]}')
        t.add_row('工具条目', f'{result.tool_entry_ratio[0]}/{result.tool_entry_ratio[1]}')
        console.print(Panel(t, border_style='yellow', title='[/audit]'))

        n_root = len(result.missing_root_targets)
        n_dir = len(result.missing_directory_targets)
        if n_root or n_dir:
            miss = Table(title='缺失项（节选）', show_lines=True)
            miss.add_column('类型', style='dim', no_wrap=True)
            miss.add_column('名称', style='red')
            for x in result.missing_root_targets[:16]:
                miss.add_row('根文件', x)
            for x in result.missing_directory_targets[:16]:
                miss.add_row('目录', x)
            if n_root > 16 or n_dir > 16:
                miss.add_row('…', f'另有 {max(0, n_root - 16) + max(0, n_dir - 16)} 条，见下方 Markdown')
            console.print(miss)
        _print_markdown_block(console, result.to_markdown(), title='完整报告 (Markdown)')
    else:
        print(result.to_markdown())


def _print_subsystems(console: Any | None, engine: QueryEnginePort) -> None:
    modules = engine.manifest.top_level_modules[:64]
    if console is not None:
        from rich.table import Table

        t = Table(title='subsystems · 顶层 Python 模块', show_lines=True)
        t.add_column('模块', style='cyan', no_wrap=True)
        t.add_column('文件数', justify='right', style='white')
        t.add_column('备注', style='dim')
        for m in modules:
            t.add_row(m.name, str(m.file_count), (m.notes or '—')[:80])
        console.print(t)
    else:
        for m in modules:
            print(f'{m.name}\t{m.file_count}\t{m.notes}')


def _print_graph(console: Any | None) -> None:
    from rich.markup import escape

    bg = build_bootstrap_graph()
    cg = build_command_graph()
    if console is not None:
        from rich.tree import Tree

        r1 = Tree('[bold magenta]bootstrap-graph · 引导/运行流[/bold magenta]')
        for st in bg.stages:
            r1.add(escape(st))
        console.print(r1)

        r2 = Tree('[bold magenta]command-graph · 命令路由面[/bold magenta]')
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
        console.print(r2)
    else:
        print('=== bootstrap-graph ===')
        for st in bg.stages:
            print(f'  · {st}')
        print('=== command-graph ===')
        print(f'  内建 ({len(cg.builtins)}): ' + ', '.join(m.name for m in cg.builtins[:12]) + ' …')
        print(f'  插件类 ({len(cg.plugin_like)}): ' + ', '.join(m.name for m in cg.plugin_like[:8]) + ' …')
        print(f'  技能类 ({len(cg.skill_like)}): ' + ', '.join(m.name for m in cg.skill_like[:8]) + ' …')


def _print_doctor(console: Any | None) -> None:
    """原生 setup + 依赖探测 + 路径权限，绿/红分行。"""
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
        from rich.panel import Panel
        from rich.table import Table

        t = Table(title='/doctor · 系统体检', show_lines=True)
        t.add_column('检查项', style='cyan')
        t.add_column('结果')
        for name, val, st in rows:
            t.add_row(name, f'[{st}]{val}[/{st}]')
        console.print(Panel(t, border_style='green'))
    else:
        for name, val, st in rows:
            print(f'{name}: {val}')


def _print_cost(console: Any | None, engine: QueryEnginePort) -> None:
    """本会话累计 Token + 粗算费用（通用参考价，非账单）。"""
    u = engine.total_usage
    # 参考：约 $5/M input, $15/M output（仅示意）
    rate_in = 5.0 / 1_000_000
    rate_out = 15.0 / 1_000_000
    est = u.input_tokens * rate_in + u.output_tokens * rate_out
    entries = list_saved_session_entries(limit=5)
    extra_in = sum(x[2] for x in entries)
    extra_out = sum(x[3] for x in entries)

    if console is not None:
        from rich.panel import Panel
        from rich.table import Table

        t = Table(title='/cost · Token 与粗略费用（USD 估算）', show_lines=True)
        t.add_column('项', style='cyan')
        t.add_column('值', justify='right')
        t.add_row('本会话 input_tokens', str(u.input_tokens))
        t.add_row('本会话 output_tokens', str(u.output_tokens))
        t.add_row('估算费用（示意）', f'~${est:.6f}')
        t.add_row('最近落盘会话(前5) in 合计', str(extra_in))
        t.add_row('最近落盘会话(前5) out 合计', str(extra_out))
        console.print(Panel(t, border_style='magenta'))
        console.print('[dim]费率仅为示意；以厂商账单为准。[/dim]')
    else:
        print(f'input={u.input_tokens} output={u.output_tokens} ~${est:.6f} (示意)')


def _print_git_diff(console: Any | None) -> None:
    root = Path.cwd()
    try:
        st = subprocess.run(
            ['git', 'status', '--short'],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        df = subprocess.run(
            ['git', 'diff', '--stat'],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _msg(console, f'git 调用失败: {exc}', style='red')
        return

    out_status = (st.stdout or '').strip() or '（无改动或未跟踪文件）'
    out_diff = (df.stdout or '').strip() or '（无 diff）'
    if st.returncode != 0 and st.stderr:
        _msg(console, st.stderr.strip(), style='yellow')
    if df.returncode != 0 and df.stderr:
        _msg(console, df.stderr.strip(), style='yellow')

    block = f'## git status --short\n```\n{out_status}\n```\n\n## git diff --stat\n```\n{out_diff}\n```'
    _print_markdown_block(console, block, title='/diff · 工作区')


def _print_status(console: Any | None, engine: QueryEnginePort) -> None:
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
        from rich.panel import Panel
        from rich.table import Table

        t = Table(title='/status · Agent 与配置', show_lines=True)
        t.add_column('项', style='cyan', no_wrap=True)
        t.add_column('值', style='white')
        for k, v in rows:
            t.add_row(k, v)
        console.print(Panel(t, border_style='blue'))
    else:
        for k, v in rows:
            print(f'{k}: {v}')


def _print_sessions(console: Any | None) -> None:
    entries = list_saved_session_entries(limit=80)
    if console is not None:
        from rich.table import Table

        if not entries:
            console.print('[dim]尚无已落盘会话（.port_sessions/）。[/dim]')
        else:
            t = Table(title='本地会话历史', show_lines=True)
            t.add_column('session_id', style='green', no_wrap=True, overflow='fold')
            t.add_column('消息数', justify='right')
            t.add_column('in/out', justify='right', style='dim')
            t.add_column('更新时间', style='dim')
            for sid, n, it, ot, path in entries:
                ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(path.stat().st_mtime))
                t.add_row(sid, str(n), f'{it}/{ot}', ts)
            console.print(t)
        console.print('[dim]恢复上下文: [bold]/load <session_id>[/bold][/dim]')
    else:
        if not entries:
            print('（无已保存会话）')
        for sid, n, it, ot, path in entries:
            ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(path.stat().st_mtime))
            print(f'{sid}\t{n}\t{it}/{ot}\t{ts}')
        print('使用: /load <session_id>')


def _msg(console: Any | None, text: str, *, style: str = 'dim') -> None:
    if console is not None:
        console.print(f'[{style}]{text}[/{style}]')
    else:
        print(text)


def dispatch_repl_slash_command(
    line: str,
    *,
    console: Any | None,
    engine: QueryEnginePort,
) -> tuple[bool, QueryEnginePort | None]:
    """
    若本行是已注册的斜杠指令则处理并返回 ``(True, 可选的新 engine)``；
    否则 ``(False, None)``。未知 ``/`` 开头指令也会拦截并提示，避免误送大模型。
    """
    raw = (line or '').strip()
    if not raw.startswith('/'):
        return False, None

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ''

    if cmd in ('/help', '/?'):
        _print_help(console)
        return True, None

    if cmd == '/summary':
        body = engine.render_summary()
        _print_markdown_block(console, body, title='/summary · 工作区与会话摘要')
        if _confirm_store_summary(console):
            store_body = f'### /summary 快照\n\n```\n{body}\n```'
            result = append_long_term_memory_block(store_body, source_tag='/summary')
            _msg(console, result, style='bold green' if result.startswith('已安全') else 'yellow')
        return True, None

    if cmd == '/memo':
        memo_direct = rest.strip()
        if memo_direct:
            result = append_long_term_memory_block(memo_direct, source_tag='/memo')
            if console is not None:
                from rich.panel import Panel
                from rich.text import Text

                ok = result.startswith('已安全')
                st = 'bold green' if ok else 'yellow'
                br = 'green' if ok else 'yellow'
                console.print(
                    Panel(
                        Text.from_markup(f'[{st}]{result}[/{st}]'),
                        title='[bold]/memo · 长效记忆[/bold]',
                        border_style=br,
                    )
                )
            else:
                print(result)
            return True, None
        if not engine.config.llm_enabled:
            _msg(console, '/memo 需要已启用大模型的 REPL（勿使用 repl --no-llm）。', style='yellow')
            return True, None
        excerpt = _memo_session_excerpt(engine)
        if not excerpt.strip():
            _msg(console, '当前会话尚无足够内容可供提取，可先多聊几句再试。', style='yellow')
            return True, None
        _msg(console, '正在调用模型整理长效要点（隐藏 Prompt，不写入当前对话历史）…', style='dim')
        text, err = _memo_extract_via_llm(engine, excerpt=excerpt)
        if err:
            _msg(console, f'模型调用失败: {err}', style='bold red')
            return True, None
        if not text.strip():
            _msg(console, '模型未返回可写入内容。', style='yellow')
            return True, None
        result = append_long_term_memory_block(text, source_tag='/memo')
        _msg(console, result, style='bold green' if result.startswith('已安全') else 'yellow')
        return True, None

    if cmd == '/new':
        try:
            path = _hard_reset_repl_session(engine)
            _msg(
                console,
                f'已硬重置：全新 session、对话与计数器已清空，并已落盘 {path}。'
                ' 长效记忆文件未改动。',
                style='bold green',
            )
        except OSError as exc:
            _msg(console, f'/new 落盘失败: {exc}', style='bold red')
        return True, None

    if cmd == '/flush':
        try:
            path = _flush_current_repl_session(engine)
            _msg(console, f'已清空对话并落盘新会话: {path}', style='bold green')
        except OSError as exc:
            _msg(console, f'flush 失败: {exc}', style='bold red')
        return True, None

    if cmd == '/stop':
        from . import agent_cancel

        agent_cancel.request_agent_cancel()
        _msg(
            console,
            '已请求中断当前工具链（bash 子进程将尽快结束；未执行的 tool 将收到 [User Interrupted Task]）。',
            style='bold yellow',
        )
        return True, None

    if cmd == '/sessions':
        _print_sessions(console)
        return True, None

    if cmd == '/load':
        sid = rest.split()[0] if rest else ''
        if not sid:
            _msg(console, '用法: /load <session_id>', style='yellow')
            return True, None
        try:
            load_session(sid)
        except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            _msg(console, f'无法加载会话 {sid!r}: {exc}', style='bold red')
            return True, None

        new_eng = QueryEnginePort.from_saved_session(sid)
        new_eng.config = replace(engine.config)
        new_eng.ui_console = engine.ui_console
        new_eng.repl_team_mode = engine.repl_team_mode
        n = len(new_eng.mutable_messages)
        if console is not None:
            console.print(f'[bold green]已加载会话[/bold green] [cyan]{sid}[/cyan] [dim]（消息 {n} 条）[/dim]')
        else:
            print(f'已加载会话 {sid}（消息 {n} 条）。')
        return True, new_eng

    if cmd == '/audit':
        _print_audit(console)
        return True, None

    if cmd == '/report':
        try:
            rep = run_setup(trusted=True).as_markdown()
        except OSError as exc:
            _msg(console, f'setup-report 失败: {exc}', style='red')
            return True, None
        _print_markdown_block(console, rep, title='/report · setup-report')
        return True, None

    if cmd == '/subsystems':
        _print_subsystems(console, engine)
        return True, None

    if cmd == '/graph':
        _print_graph(console)
        return True, None

    if cmd == '/doctor':
        _print_doctor(console)
        return True, None

    if cmd == '/cost':
        _print_cost(console, engine)
        return True, None

    if cmd == '/diff':
        _print_git_diff(console)
        return True, None

    if cmd == '/status':
        _print_status(console, engine)
        return True, None

    if cmd == '/team':
        engine.repl_team_mode = not engine.repl_team_mode
        state = '开启' if engine.repl_team_mode else '关闭'
        _msg(console, f'多代理团队模式已{state}（Planner → Coder → Reviewer）。', style='bold green')
        return True, None

    _msg(
        console,
        f'未知斜杠指令 {cmd!r}。输入 /help 查看原生桥接命令。',
        style='yellow',
    )
    return True, None
