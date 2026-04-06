#!/usr/bin/env python3
"""
一键将 ``scream`` 注册为 Zsh 全局命令（macOS）。

**推荐**：跨平台一键安装请优先使用仓库根目录的 ``install.sh``（含 venv、pip、zsh/bash 注册）。

本脚本适合仅需写入 ``~/.zshrc``、且已手动装好依赖的场景。在项目根目录执行::

    python3 install_mac.py

依赖 ``rich``（已在项目 requirements.txt 中）。
"""
from __future__ import annotations

import os
import sys


def _bash_double_quote_escape(path: str) -> str:
    """将路径安全嵌入 Bash 双引号字符串内。"""
    return path.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')


def main() -> int:
    try:
        from rich.console import Console
        from rich.panel import Panel
    except ImportError:
        print('请先安装 rich：python3 -m pip install rich', file=sys.stderr)
        return 1

    console = Console()
    project_root = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
    scream_path = _bash_double_quote_escape(project_root)

    zshrc_path = os.path.expanduser('~/.zshrc')
    marker = '# ====== Scream Code 全局命令 ======'

    block = f'''{marker}
scream() {{
    local SCREAM_PATH="{scream_path}"
    if [[ -x "$SCREAM_PATH/venv/bin/python3" ]]; then
        PYTHONPATH="$SCREAM_PATH" "$SCREAM_PATH/venv/bin/python3" -m src.main "$@"
    else
        PYTHONPATH="$SCREAM_PATH" python3 -m src.main "$@"
    fi
}}
'''

    try:
        if os.path.isfile(zshrc_path):
            with open(zshrc_path, encoding='utf-8') as f:
                existing = f.read()
        else:
            existing = ''
    except OSError as exc:
        console.print(f'[bold red]无法读取 ~/.zshrc：{exc}[/bold red]')
        return 1

    if marker in existing:
        console.print(
            Panel.fit(
                '[yellow]已存在 Scream Code 配置块，未重复写入。[/yellow]\n\n'
                '如需重装，请手动删除 ``~/.zshrc`` 中以该标记开头至 ``scream`` 函数结束的整段后再运行本脚本。',
                title='提示',
                border_style='yellow',
            )
        )
        return 0

    try:
        with open(zshrc_path, 'a', encoding='utf-8') as f:
            if existing and not existing.endswith('\n'):
                f.write('\n')
            f.write('\n')
            f.write(block)
            if not block.endswith('\n'):
                f.write('\n')
    except OSError as exc:
        console.print(f'[bold red]无法写入 ~/.zshrc：{exc}[/bold red]')
        return 1

    console.print(
        Panel.fit(
            '[bold green]安装成功！[/bold green]\n\n'
            '请在终端中执行 [bold cyan]source ~/.zshrc[/bold cyan] 让配置立刻生效。\n\n'
            '之后可在任意目录使用 [bold]scream[/bold]，例如：[bold]scream summary[/bold]、[bold]scream repl[/bold]（默认进入大模型对话）。\n\n'
            '[dim]若已创建项目内 venv，将优先使用 [bold]venv/bin/python3[/bold]；否则使用当前 PATH 中的 python3。[/dim]',
            title='Scream Code',
            border_style='green',
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
