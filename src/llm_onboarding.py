from __future__ import annotations

import sys

from . import model_manager
from .llm_settings import read_llm_connection_settings


def ensure_llm_ready_interactive() -> bool:
    """
    若当前激活模型在环境中没有可用 API Key，则进入 questionary 引导；
    成功写入 llm_config.json 与 .env 后返回 True；用户拒绝或失败返回 False。
    """
    model_manager.ensure_default_config_file()
    if read_llm_connection_settings().api_key.strip():
        return True

    # 管道/自动化场景无法完成 questionary 引导：不拦截启动，首次 LLM 调用时再报错。
    if not sys.stdin.isatty():
        return True

    try:
        from rich.console import Console

        console = Console()
    except ImportError:
        console = None

    try:
        import questionary
        from questionary import Style
    except ImportError:
        if console:
            console.print('[red]未安装 questionary，无法进入引导。请 pip install questionary 后重试。[/red]')
        else:
            print('未安装 questionary，无法进入引导。', file=sys.stderr)
        return False

    style = Style([('selected', 'fg:ansicyan bold')])

    if console:
        console.print(
            '[bold yellow]检测到您尚未配置大模型，是否现在开始快速设置？[/bold yellow]'
        )
    else:
        print('检测到您尚未配置大模型，是否现在开始快速设置？')

    start = questionary.confirm('开始快速设置？', default=True, style=style).ask()
    if start is not True:
        if console:
            console.print(
                '[dim]已跳过。可稍后运行 `python3 -m src.main config` 或手动编辑 .env。[/dim]'
            )
        else:
            print('已跳过配置。')
        return False

    if not model_manager.run_add_model_interactive(style, announce_done=False):
        return False

    if not read_llm_connection_settings().api_key.strip():
        if console:
            console.print(
                '[red]配置已写入，但当前进程仍无法读取密钥，请检查 llm_config.json 与 .env。[/red]'
            )
        return False

    if console:
        console.print('[bold green]✅ 配置成功！正在为您连接...[/bold green]')
    else:
        print('配置成功！正在为您连接...')
    return True
