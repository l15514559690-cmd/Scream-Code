from __future__ import annotations

import argparse
import os
import subprocess
import sys


def check_and_install_dependencies() -> None:
    """
    启动自检：缺失的核心依赖时静默 pip 安装，避免因 ImportError 直接退出。
    自动化测试可设环境变量 ``SCREAM_SKIP_DEPS_CHECK=1`` 跳过。
    """
    if os.environ.get('SCREAM_SKIP_DEPS_CHECK', '').strip().lower() in ('1', 'true', 'yes'):
        return
    specs: tuple[tuple[str, str], ...] = (
        ('openai', 'openai'),
        ('anthropic', 'anthropic'),
        ('rich', 'rich'),
        ('questionary', 'questionary'),
        ('prompt_toolkit', 'prompt-toolkit'),
        ('dotenv', 'python-dotenv'),
    )
    missing: list[str] = []
    for mod, pip_name in specs:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return
    print('正在为您初始化环境，请稍候...', flush=True)
    cmd = [sys.executable, '-m', 'pip', 'install', '-q', *missing]
    subprocess.run(cmd, check=False)
    for mod, _ in specs:
        try:
            import importlib

            importlib.invalidate_caches()
            __import__(mod)
        except ImportError:
            pass


from .bootstrap_graph import build_bootstrap_graph
from .command_graph import build_command_graph
from .commands import execute_command, get_command, get_commands, render_command_index
from .direct_modes import run_deep_link, run_direct_connect
from .claw_config import load_project_claw_json
from .llm_settings import load_project_dotenv, reload_project_dotenv
from .model_manager import run_config_interactive_menu
from .replLauncher import (
    build_repl_banner,
    print_project_memory_loaded_notice,
    print_startup_banner,
    run_repl_interactive_loop,
)
from .parity_audit import run_parity_audit
from .permissions import ToolPermissionContext
from .port_manifest import build_port_manifest
from .query_engine import QueryEnginePort
from .remote_runtime import run_remote_mode, run_ssh_mode, run_teleport_mode
from .runtime import PortRuntime
from .session_store import load_session
from .setup import run_setup
from .tool_pool import assemble_tool_pool
from .tools import execute_tool, get_tool, get_tools, render_tool_index


class ChineseArgumentParser(argparse.ArgumentParser):
    """将 argparse 默认英文框架文案替换为中文，便于「尖叫 Code」纯中文交互。"""

    def format_help(self) -> str:
        text = super().format_help()
        replacements = (
            ('usage: ', '用法: '),
            ('positional arguments:\n', '位置参数:\n'),
            ('options:\n', '选项:\n'),
            ('optional arguments:\n', '选项:\n'),
            ('show this help message and exit', '显示此说明并退出'),
        )
        for old, new in replacements:
            text = text.replace(old, new)
        return text


def build_parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(description='尖叫 Code：Python 移植工作区命令行（原 Claude Code 重写工程的镜像实现）')
    subparsers = parser.add_subparsers(dest='command', required=True, parser_class=ChineseArgumentParser)
    repl_parser = subparsers.add_parser(
        'repl',
        help='进入交互式 REPL（默认启用大模型；可用 --no-llm 仅显示 Logo 与说明）',
    )
    repl_parser.add_argument(
        '--llm',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='启用大模型（默认开启；密钥见 llm_config.json 或 .env；--no-llm 仅打印说明后退出）',
    )
    repl_parser.add_argument(
        '--json-stdio',
        action='store_true',
        help='行协议 JSON stdio：供 Rust 全屏 TUI 等前端驱动；stdout 仅输出 JSON 行，stdin 每行一条 JSON 指令',
    )
    repl_parser.add_argument(
        '--python-tui',
        action='store_true',
        help='纯 Python 终端 UI（prompt_toolkit + rich 流式 Markdown），规避 macOS PTY/crossterm EOF 问题',
    )
    subparsers.add_parser('config', help='交互式管理多模型配置（llm_config.json）')
    subparsers.add_parser('summary', help='以 Markdown 渲染 Python 移植工作区摘要')
    subparsers.add_parser('manifest', help='打印当前 Python 工作区清单')
    subparsers.add_parser('parity-audit', help='在本地归档可用时，将 Python 工作区与已忽略的 TypeScript 归档对照审计')
    subparsers.add_parser('setup-report', help='渲染启动与预取相关的环境报告')
    subparsers.add_parser('command-graph', help='展示命令图谱分段统计')
    subparsers.add_parser('tool-pool', help='按默认设置展示已组装的工具池')
    subparsers.add_parser('bootstrap-graph', help='展示镜像的引导/运行时分阶段流程')
    list_parser = subparsers.add_parser('subsystems', help='列出工作区内的顶层 Python 模块')
    list_parser.add_argument('--limit', type=int, default=32, help='最多列出多少个模块')

    commands_parser = subparsers.add_parser('commands', help='列出归档快照中的镜像命令条目')
    commands_parser.add_argument('--limit', type=int, default=20, help='最多列出多少条')
    commands_parser.add_argument('--query', help='按关键词筛选')
    commands_parser.add_argument('--no-plugin-commands', action='store_true', help='排除插件类命令')
    commands_parser.add_argument('--no-skill-commands', action='store_true', help='排除技能类命令')

    tools_parser = subparsers.add_parser('tools', help='列出归档快照中的镜像工具条目')
    tools_parser.add_argument('--limit', type=int, default=20, help='最多列出多少条')
    tools_parser.add_argument('--query', help='按关键词筛选')
    tools_parser.add_argument('--simple-mode', action='store_true', help='仅保留精简工具集')
    tools_parser.add_argument('--no-mcp', action='store_true', help='排除 MCP 相关工具')
    tools_parser.add_argument('--deny-tool', action='append', default=[], help='按名称拒绝指定工具（可重复）')
    tools_parser.add_argument('--deny-prefix', action='append', default=[], help='按名称前缀拒绝工具（可重复）')

    route_parser = subparsers.add_parser('route', help='在镜像命令/工具清单中为用户提示做路由匹配')
    route_parser.add_argument('prompt', help='用户提示文本')
    route_parser.add_argument('--limit', type=int, default=5, help='最多返回多少条匹配')

    bootstrap_parser = subparsers.add_parser('bootstrap', help='基于镜像清单生成运行时会话式 Markdown 报告')
    bootstrap_parser.add_argument('prompt', help='用户提示文本')
    bootstrap_parser.add_argument('--limit', type=int, default=5, help='路由匹配条数上限')
    bootstrap_parser.add_argument(
        '--llm',
        action='store_true',
        help='调用大模型（密钥见 llm_config.json 对应变量，或 .env 的 API_KEY；可用 config 子命令配置）',
    )

    loop_parser = subparsers.add_parser('turn-loop', help='在镜像运行时上执行小型有状态多轮循环')
    loop_parser.add_argument('prompt', help='用户提示文本')
    loop_parser.add_argument('--limit', type=int, default=5, help='路由匹配条数上限')
    loop_parser.add_argument('--max-turns', type=int, default=3, help='最大轮次数')
    loop_parser.add_argument('--structured-output', action='store_true', help='使用结构化（JSON）输出')
    loop_parser.add_argument(
        '--llm',
        action='store_true',
        help='调用大模型（密钥见 llm_config.json 对应变量，或 .env 的 API_KEY；可用 config 子命令配置）',
    )

    flush_parser = subparsers.add_parser('flush-transcript', help='持久化并清空临时会话记录')
    flush_parser.add_argument('prompt', help='用于提交一轮对话的提示文本')

    load_session_parser = subparsers.add_parser('load-session', help='加载此前持久化的会话')
    load_session_parser.add_argument('session_id', help='会话标识符')

    remote_parser = subparsers.add_parser('remote-mode', help='模拟远程控制运行时分支')
    remote_parser.add_argument('target', help='目标标识')
    ssh_parser = subparsers.add_parser('ssh-mode', help='模拟 SSH 运行时分支')
    ssh_parser.add_argument('target', help='目标标识')
    teleport_parser = subparsers.add_parser('teleport-mode', help='模拟 Teleport 运行时分支')
    teleport_parser.add_argument('target', help='目标标识')
    direct_parser = subparsers.add_parser('direct-connect-mode', help='模拟直连运行时分支')
    direct_parser.add_argument('target', help='目标标识')
    deep_link_parser = subparsers.add_parser('deep-link-mode', help='模拟深度链接运行时分支')
    deep_link_parser.add_argument('target', help='目标标识')

    show_command = subparsers.add_parser('show-command', help='按精确名称展示一条镜像命令')
    show_command.add_argument('name', help='命令名称')
    show_tool = subparsers.add_parser('show-tool', help='按精确名称展示一条镜像工具')
    show_tool.add_argument('name', help='工具名称')

    exec_command_parser = subparsers.add_parser('exec-command', help='按精确名称执行镜像命令垫片')
    exec_command_parser.add_argument('name', help='命令名称')
    exec_command_parser.add_argument('prompt', help='传给命令的提示文本')

    exec_tool_parser = subparsers.add_parser('exec-tool', help='按精确名称执行镜像工具垫片')
    exec_tool_parser.add_argument('name', help='工具名称')
    exec_tool_parser.add_argument('payload', help='传给工具的负载文本')

    subparsers.add_parser('findskills', help='列出已注册的技能（内置核心 + skills/ 动态扩展）')
    return parser


def _run_findskills_cli() -> None:
    from rich.console import Console
    from rich.table import Table

    from .tools_registry import get_tools_registry

    rows = get_tools_registry().list_tool_rows()
    table = Table(title='已加载技能（内置 + skills/）', show_lines=True)
    table.add_column('名称', style='cyan', no_wrap=True)
    table.add_column('描述')
    table.add_column('来源', style='dim')
    for r in rows:
        desc = r['description']
        if len(desc) > 160:
            desc = desc[:157] + '...'
        table.add_row(r['name'], desc, r['source'] or '—')
    Console().print(table)


def main(argv: list[str] | None = None) -> int:
    check_and_install_dependencies()
    load_project_dotenv()
    load_project_claw_json()
    # 无子命令时（仅可执行文件名）直接进入带大模型的 REPL（repl 默认 --llm）
    if argv is None and len(sys.argv) == 1:
        argv = ['repl']
    parser = build_parser()
    args = parser.parse_args(argv)
    manifest = build_port_manifest()
    if args.command == 'repl':
        if getattr(args, 'json_stdio', False):
            from .replLauncher import run_repl_json_stdio_loop

            if args.llm:
                from .llm_onboarding import ensure_llm_ready_interactive

                if not ensure_llm_ready_interactive():
                    return 1
            try:
                return run_repl_json_stdio_loop(llm_enabled=args.llm, route_limit=5)
            except KeyboardInterrupt:
                return 130
            except Exception as exc:
                print(
                    f'[REPL json-stdio] {type(exc).__name__}: {exc}',
                    flush=True,
                    file=sys.stderr,
                )
                return 1
        if getattr(args, 'python_tui', False):
            from .tui_app import run_python_tui_repl

            if args.llm:
                from .llm_onboarding import ensure_llm_ready_interactive

                if not ensure_llm_ready_interactive():
                    return 1
            try:
                return run_python_tui_repl(llm_enabled=args.llm, route_limit=5)
            except KeyboardInterrupt:
                print('\n已中断。', flush=True)
                return 130
            except Exception as exc:
                print(
                    f'[REPL python-tui] {type(exc).__name__}: {exc}',
                    flush=True,
                    file=sys.stderr,
                )
                return 1
        if args.llm:
            from .llm_onboarding import ensure_llm_ready_interactive

            if not ensure_llm_ready_interactive():
                return 1
            try:
                return run_repl_interactive_loop(llm_enabled=True)
            except KeyboardInterrupt:
                print('\n已中断。', flush=True)
                return 130
            except Exception as exc:
                print(
                    f'[REPL] 未捕获异常（进程仍保持退出码非零）: {type(exc).__name__}: {exc}',
                    flush=True,
                )
                return 1
        print_startup_banner()
        print_project_memory_loaded_notice()
        print(build_repl_banner())
        return 0
    if args.command == 'config':
        return run_config_interactive_menu()
    if args.command == 'findskills':
        _run_findskills_cli()
        return 0
    if args.command == 'summary':
        print(QueryEnginePort(manifest).render_summary())
        return 0
    if args.command == 'manifest':
        print(manifest.to_markdown())
        return 0
    if args.command == 'parity-audit':
        print(run_parity_audit().to_markdown())
        return 0
    if args.command == 'setup-report':
        print(run_setup().as_markdown())
        return 0
    if args.command == 'command-graph':
        print(build_command_graph().as_markdown())
        return 0
    if args.command == 'tool-pool':
        print(assemble_tool_pool().as_markdown())
        return 0
    if args.command == 'bootstrap-graph':
        print(build_bootstrap_graph().as_markdown())
        return 0
    if args.command == 'subsystems':
        for subsystem in manifest.top_level_modules[: args.limit]:
            print(f'{subsystem.name}\t{subsystem.file_count}\t{subsystem.notes}')
        return 0
    if args.command == 'commands':
        if args.query:
            print(render_command_index(limit=args.limit, query=args.query))
        else:
            commands = get_commands(include_plugin_commands=not args.no_plugin_commands, include_skill_commands=not args.no_skill_commands)
            output_lines = [f'命令条目: {len(commands)}', '']
            output_lines.extend(f'- {module.name} — {module.source_hint}' for module in commands[: args.limit])
            print('\n'.join(output_lines))
        return 0
    if args.command == 'tools':
        if args.query:
            print(render_tool_index(limit=args.limit, query=args.query))
        else:
            permission_context = ToolPermissionContext.from_iterables(args.deny_tool, args.deny_prefix)
            tools = get_tools(simple_mode=args.simple_mode, include_mcp=not args.no_mcp, permission_context=permission_context)
            output_lines = [f'工具条目: {len(tools)}', '']
            output_lines.extend(f'- {module.name} — {module.source_hint}' for module in tools[: args.limit])
            print('\n'.join(output_lines))
        return 0
    if args.command == 'route':
        matches = PortRuntime().route_prompt(args.prompt, limit=args.limit)
        if not matches:
            print('未发现镜像的命令或工具匹配项。')
            return 0
        for match in matches:
            print(f'{match.kind}\t{match.name}\t{match.score}\t{match.source_hint}')
        return 0
    if args.command == 'bootstrap':
        if args.llm:
            from .llm_onboarding import ensure_llm_ready_interactive

            if not ensure_llm_ready_interactive():
                return 1
        print(PortRuntime().bootstrap_session(args.prompt, limit=args.limit, llm_enabled=args.llm).as_markdown())
        return 0
    if args.command == 'turn-loop':
        if args.llm:
            from .llm_onboarding import ensure_llm_ready_interactive

            if not ensure_llm_ready_interactive():
                return 1
        results = PortRuntime().run_turn_loop(
            args.prompt,
            limit=args.limit,
            max_turns=args.max_turns,
            structured_output=args.structured_output,
            llm_enabled=args.llm,
        )
        for idx, result in enumerate(results, start=1):
            print(f'## 第 {idx} 轮')
            print(result.output)
            print(f'停止原因={result.stop_reason}')
        return 0
    if args.command == 'flush-transcript':
        engine = QueryEnginePort.from_workspace()
        engine.submit_message(args.prompt)
        path = engine.persist_session()
        print(path)
        print(f'已落盘={"是" if engine.transcript_store.flushed else "否"}')
        return 0
    if args.command == 'load-session':
        session = load_session(args.session_id)
        print(
            f'{session.session_id}\n'
            f'消息条数={len(session.messages)}\n'
            f'LLM 快照条数={len(session.llm_conversation_messages)}\n'
            f'入站 token={session.input_tokens} 出站 token={session.output_tokens}',
        )
        return 0
    if args.command == 'remote-mode':
        print(run_remote_mode(args.target).as_text())
        return 0
    if args.command == 'ssh-mode':
        print(run_ssh_mode(args.target).as_text())
        return 0
    if args.command == 'teleport-mode':
        print(run_teleport_mode(args.target).as_text())
        return 0
    if args.command == 'direct-connect-mode':
        print(run_direct_connect(args.target).as_text())
        return 0
    if args.command == 'deep-link-mode':
        print(run_deep_link(args.target).as_text())
        return 0
    if args.command == 'show-command':
        module = get_command(args.name)
        if module is None:
            print(f'未找到命令: {args.name}')
            return 1
        print('\n'.join([module.name, module.source_hint, module.responsibility]))
        return 0
    if args.command == 'show-tool':
        module = get_tool(args.name)
        if module is None:
            print(f'未找到工具: {args.name}')
            return 1
        print('\n'.join([module.name, module.source_hint, module.responsibility]))
        return 0
    if args.command == 'exec-command':
        result = execute_command(args.name, args.prompt)
        print(result.message)
        return 0 if result.handled else 1
    if args.command == 'exec-tool':
        result = execute_tool(args.name, args.payload)
        print(result.message)
        return 0 if result.handled else 1
    parser.error(f'未知子命令: {args.command}')
    return 2


def _print_geek_help() -> None:
    print(
        """
╔════════════════════════════════════════════════════════════╗
║  SCREAM // neural.cli  ·  single entry · ~/.scream state  ║
╚════════════════════════════════════════════════════════════╝

  scream              启动 TUI；若无 API Key，会先跑交互引导
  scream config       模型 / 密钥完整菜单（写入 ~/.scream/）
  scream help         本页

  配置目录            ~/.scream/llm_config.json  +  ~/.scream/.env
"""
    )


def _offer_launch_tui_after_config() -> int:
    if not sys.stdin.isatty():
        return 0
    try:
        import questionary
        from questionary import Style
    except ImportError:
        return 0
    style = Style([('selected', 'fg:ansicyan bold')])
    try:
        go = questionary.confirm('是否进入主界面（TUI）？', default=True, style=style).ask()
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。', flush=True)
        return 130
    if go is True:
        reload_project_dotenv()
        return _run_product_tui(llm_enabled=True, skip_ready_check=True)
    return 0


def _run_product_tui(*, llm_enabled: bool, skip_ready_check: bool = False) -> int:
    from .llm_onboarding import ensure_llm_ready_interactive
    from .tui_app import run_python_tui_repl

    if llm_enabled and not skip_ready_check:
        if not ensure_llm_ready_interactive():
            print(
                'scream: 未完成模型配置。运行 scream config 后再试。',
                file=sys.stderr,
                flush=True,
            )
            return 1
    try:
        return run_python_tui_repl(llm_enabled=llm_enabled, route_limit=5)
    except KeyboardInterrupt:
        print('\n已中断。', flush=True)
        return 130
    except Exception as exc:
        print(f'scream: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        return 1


class _ScreamProductParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f'scream: {message}', file=sys.stderr)
        print('提示：运行「scream help」查看用法。', file=sys.stderr)
        self.exit(2)


def cli_main(argv: list[str]) -> int:
    """产品 CLI：``scream`` / ``scream config`` / ``scream help``。"""
    from .claw_config import is_product_session_ready
    from .llm_onboarding import ensure_llm_ready_interactive, run_product_config_menu

    check_and_install_dependencies()
    load_project_dotenv()
    load_project_claw_json()

    parser = _ScreamProductParser(prog='scream', add_help=False)
    parser.add_argument('-h', '--help', action='store_true', help='显示帮助')
    parser.add_argument(
        'command',
        nargs='?',
        default=None,
        choices=(None, 'config', 'help'),
        metavar='子命令',
    )
    args = parser.parse_args(argv)

    if args.help:
        _print_geek_help()
        return 0
    if args.command == 'help':
        _print_geek_help()
        return 0
    if args.command == 'config':
        code = run_product_config_menu()
        if code != 0:
            return code
        reload_project_dotenv()
        return _offer_launch_tui_after_config()
    if not is_product_session_ready():
        if not sys.stdin.isatty():
            print(
                'scream: 未检测到 API Key，且当前为非交互环境。'
                '请配置 ~/.scream/ 或设置环境变量。',
                file=sys.stderr,
                flush=True,
            )
            return 1
        if not ensure_llm_ready_interactive():
            print(
                'scream: 未完成配置。可运行 scream config 稍后再试。',
                file=sys.stderr,
                flush=True,
            )
            return 1
        reload_project_dotenv()

    return _run_product_tui(llm_enabled=True, skip_ready_check=True)


def cli_entry() -> int:
    """setuptools ``console_scripts`` 入口：``scream=src.main:cli_entry``。"""
    try:
        return cli_main(sys.argv[1:])
    except KeyboardInterrupt:
        print('\n已中断。', flush=True)
        return 130
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except Exception as exc:
        print(f'scream: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
