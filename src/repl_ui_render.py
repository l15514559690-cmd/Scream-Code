"""
REPL 纯展示层：工具调用面板、语法高亮、流式 Markdown 包装。
不修改事件结构、不触碰工具执行逻辑。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_token_warning_panel(current_tokens: int, threshold: int) -> Any:
    """
    Token 水位软着陆提示（仅 UI）。不读取、不修改 engine 状态。
    """
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    body = (
        f'[yellow]⚠️ 记忆负载过高：当前会话已消耗约 {current_tokens:,} tokens '
        f'(安全阈值: {threshold:,})。为防止模型响应变慢或超出最大上下文，'
        '建议输入 /summary 提取摘要，或输入 /flush 清理历史。[/yellow]'
    )
    return Panel(
        Text.from_markup(body),
        title='[bold yellow]⚠️ Token 水位[/bold yellow]',
        border_style='yellow',
        box=box.ROUNDED,
        expand=True,
        padding=(0, 1),
    )


def format_token_warning_plain(current_tokens: int, threshold: int) -> str:
    """无 Rich 时的同义纯文本一行版。"""
    return (
        f'\n⚠️ 记忆负载过高：当前会话已消耗约 {current_tokens} tokens '
        f'(安全阈值: {threshold})。建议 /summary 提取摘要或 /flush 清理历史。\n'
    )

# 与 skills / agent_tools 注册名一致（仅用于展示归类）
_FILE_WRITE_TOOLS = frozenset({'write_local_file'})
_FILE_READ_TOOLS = frozenset({'read_local_file'})
_BASH_TOOLS = frozenset({'execute_mac_bash'})
_SKILL_TOOLS = frozenset({'install_local_skill'})


def assistant_panel_title() -> Any:
    from rich.text import Text

    return Text.from_markup('[bold cyan]🤖 尖叫助理[/bold cyan]')


def assistant_panel(inner: Any) -> Any:
    from rich import box
    from rich.panel import Panel

    return Panel(
        inner,
        title=assistant_panel_title(),
        border_style='cyan',
        box=box.ROUNDED,
        expand=True,
        padding=(1, 2),
    )


def _safe_json_args(raw: str) -> dict[str, Any]:
    s = (raw or '').strip()
    if not s:
        return {}
    try:
        out = json.loads(s)
        return out if isinstance(out, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _lexer_for_path(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    return {
        '.py': 'python',
        '.rs': 'rust',
        '.toml': 'toml',
        '.json': 'json',
        '.md': 'markdown',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.sh': 'bash',
        '.bash': 'bash',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.jsx': 'jsx',
        '.html': 'html',
        '.css': 'css',
        '.sql': 'sql',
        '.go': 'go',
        '.java': 'java',
        '.kt': 'kotlin',
        '.swift': 'swift',
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.hpp': 'cpp',
        '.xml': 'xml',
    }.get(ext, 'text')


def _truncate(s: str, max_len: int = 24_000) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 80] + '\n\n… (内容过长，已截断展示；实际写入由工具层完整执行) …\n'


def build_api_tool_op_renderable(ev: dict[str, Any]) -> Any:
    """
    将 ``api_tool_op`` 事件包装为 Panel + Syntax（或摘要 Text）。
    仅消费 ev 中已有字段：tool_name, arguments。
    """
    from rich import box
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.text import Text

    name = str(ev.get('tool_name', '') or 'tool')
    raw_args = str(ev.get('arguments', '') or '')
    args = _safe_json_args(raw_args)

    fp = ''
    if isinstance(args.get('file_path'), str):
        fp = args['file_path'].strip()

    if name in _FILE_WRITE_TOOLS:
        content = args.get('content', '')
        body: Any
        if isinstance(content, str) and content.strip():
            lexer = _lexer_for_path(fp) if fp else 'text'
            body = Syntax(
                _truncate(content),
                lexer,
                theme='monokai',
                line_numbers=True,
                word_wrap=True,
            )
        else:
            body = Text('(无 content 字段或为空)', style='dim')
        title = f'[bold green]文件写入[/bold green] [cyan]{fp or name}[/cyan]'
        sub = Panel(
            body,
            box=box.ROUNDED,
            border_style='green',
            padding=(0, 1),
            expand=True,
        )
        return Panel(
            sub,
            title=title,
            box=box.ROUNDED,
            border_style='bold green',
            padding=(0, 1),
            expand=True,
        )

    if name in _FILE_READ_TOOLS:
        title = f'[bold blue]读取文件[/bold blue] [cyan]{fp or "(路径见参数)"}[/cyan]'
        meta = Text.assemble(
            ('参数 JSON\n', 'bold dim'),
            (raw_args[:8000] + ('…' if len(raw_args) > 8000 else ''), 'dim'),
        )
        return Panel(
            meta,
            title=title,
            box=box.ROUNDED,
            border_style='blue',
            padding=(0, 1),
            expand=True,
        )

    if name in _BASH_TOOLS:
        cmd = args.get('command', '')
        if not isinstance(cmd, str):
            cmd = raw_args
        body = Syntax(
            _truncate(cmd, max_len=8000),
            'bash',
            theme='monokai',
            line_numbers=False,
            word_wrap=True,
        )
        title = '[bold magenta]Shell 命令[/bold magenta]'
        return Panel(
            body,
            title=title,
            box=box.ROUNDED,
            border_style='magenta',
            padding=(0, 1),
            expand=True,
        )

    if name in _SKILL_TOOLS:
        inner = Markdown(
            f'```json\n{_truncate(raw_args, max_len=6000)}\n```',
            code_theme='monokai',
        )
        return Panel(
            inner,
            title='[bold yellow]安装技能[/bold yellow]',
            box=box.ROUNDED,
            border_style='yellow',
            padding=(0, 1),
            expand=True,
        )

    # 通用：尝试从参数里找 diff 样结构（纯展示，不假定后端会传）
    diff_text = args.get('diff') or args.get('patch') or args.get('unified_diff')
    if isinstance(diff_text, str) and diff_text.strip():
        lines = diff_text.splitlines()
        styled = Text()
        for line in lines[:500]:
            if line.startswith('+') and not line.startswith('+++'):
                styled.append(line + '\n', style='bold green')
            elif line.startswith('-') and not line.startswith('---'):
                styled.append(line + '\n', style='bold red')
            elif line.startswith('@'):
                styled.append(line + '\n', style='cyan')
            else:
                styled.append(line + '\n', style='dim')
        return Panel(
            styled,
            title=f'[bold cyan]Diff 预览[/bold cyan] · {name}',
            box=box.ROUNDED,
            border_style='cyan',
            padding=(0, 1),
            expand=True,
        )

    inner = Markdown(
        f'**工具** `{name}`\n\n```json\n{_truncate(raw_args, max_len=12000)}\n```',
        code_theme='monokai',
    )
    return Panel(
        inner,
        title='[bold yellow]🛠️ 工具调用[/bold yellow]',
        box=box.ROUNDED,
        border_style='yellow',
        padding=(0, 1),
        expand=True,
    )


def thinking_status_markup(elapsed_s: float) -> str:
    """阻塞等待下一事件时 Rich Status 的 Markup 文案（由展示层定时刷新）。"""
    return f'[cyan]🧠 大模型深度思考中... (已等待: {elapsed_s:.1f}s)[/cyan]'


# Live 内全量 Markdown 重排过频时易 CPU 顶满；超长缓冲也提高解析失败概率
_STREAMING_MARKDOWN_SOFT_CAP = 600_000


def streaming_markdown_panel_with_wait_footer(
    buffer: str, wait_elapsed_s: float | None
) -> Any:
    """
    Live 流式面板；``wait_elapsed_s`` 非空时在底部显示等待计时（主线程无 next() 阻塞时刷新）。
    渲染失败时降级为纯文本，避免未捕获异常打断 REPL（无法防御终端层原生崩溃）。
    """
    from rich.console import Group
    from rich.markdown import Markdown
    from rich.text import Text

    buf = buffer or ''
    if len(buf) > _STREAMING_MARKDOWN_SOFT_CAP:
        buf = buf[: _STREAMING_MARKDOWN_SOFT_CAP - 120] + '\n\n…(流式缓冲过长，Live 内仅展示前段；完整内容在回合结束后可见)…\n'

    try:
        panel = assistant_panel(
            Markdown(buf, code_theme='monokai', inline_code_lexer='python')
        )
    except Exception as exc:
        panel = assistant_panel(
            Text(
                f'[dim]Markdown 渲染跳过（{type(exc).__name__}），已缓冲 {len(buffer or "")} 字符。[/dim]',
                overflow='ignore',
            )
        )
    if wait_elapsed_s is None:
        return panel
    try:
        footer = Text.from_markup(
            f'[dim cyan]⏳ 等待模型响应… {wait_elapsed_s:.1f}s[/dim cyan]'
        )
    except Exception:
        footer = Text(f'⏳ 等待模型响应… {wait_elapsed_s:.1f}s', style='dim cyan')
    return Group(panel, footer)


def tool_execution_status_message(tool_name: str) -> str:
    """Rich Status 用的一行说明（Markup）。"""
    display = {
        'write_local_file': '写入文件',
        'read_local_file': '读取文件',
        'execute_mac_bash': '执行 Bash',
        'install_local_skill': '安装技能',
    }.get(tool_name, tool_name)
    return f'[bold cyan]Agent 正在执行工具[/bold cyan]: [white]{display}[/white] [dim]({tool_name})[/dim]…'


def streaming_markdown_panel(buffer: str) -> Any:
    """流式阶段 Live 用的整页渲染（与定稿面板风格一致）。"""
    from rich.markdown import Markdown

    return assistant_panel(
        Markdown(buffer, code_theme='monokai', inline_code_lexer='python')
    )
