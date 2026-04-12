"""
REPL 纯展示层：工具调用面板、语法高亮、流式 Markdown 包装。
不修改事件结构、不触碰工具执行逻辑。

``ScreamMarkdown``：内联代码圆角感 + 大块 ``Syntax``；流式 ``Live`` 仅用裸 Markdown；
回合间分隔用 :func:`print_cyber_turn_divider`；流式结束定稿用 :func:`print_solidified_assistant_markdown`；
其它定稿仍可用 :func:`final_assistant_markdown_panel`（靛紫 ``Panel``）。工具事件等仍用 ``Panel``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import rich.markdown as _rich_markdown_mod
from rich.markdown import CodeBlock, Markdown
from rich.syntax import Syntax
from rich.text import Text

# TUI / 助手 Markdown 品牌与代码区（与 tui_app 靛紫系一致）
_BRAND_BORDER_HEX = '#4F46E5'
# 流式定稿与 Live 内代码块统一使用同一暗色 Pygments 主题（可改为 "dracula" 等）
STREAMING_CODE_THEME = 'monokai'
_INLINE_CODE_BG = '#2D2D39'
_INLINE_CODE_FG = '#A5B4FC'
_CODE_PANEL_BG = '#09090B'

_StockMarkdownContext = _rich_markdown_mod.MarkdownContext


def wrap_syntax_in_styled_panel(syntax: Syntax, lexer_name: str) -> Any:
    """
    将 ``Syntax`` 包进圆角 ``Panel``：极深底、靛紫边框、左上角语言标题（大写）。
    """
    from rich import box
    from rich.panel import Panel

    label = (lexer_name or 'text').strip().upper() or 'TEXT'
    title = f'[bold {_BRAND_BORDER_HEX}]{label}[/bold {_BRAND_BORDER_HEX}]'
    return Panel(
        syntax,
        title=title,
        title_align='left',
        border_style=_BRAND_BORDER_HEX,
        box=box.ROUNDED,
        style=f'on {_CODE_PANEL_BG}',
        padding=(0, 1),
        expand=True,
    )


class ScreamCodeBlock(CodeBlock):
    """围栏代码块：``Syntax`` + ``wrap_syntax_in_styled_panel``。"""

    def __rich_console__(self, console: Any, options: Any):
        code = str(self.text).rstrip()
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=(0, 1),
            background_color=_CODE_PANEL_BG,
        )
        yield wrap_syntax_in_styled_panel(syntax, self.lexer_name)


class ScreamMarkdownContext(_StockMarkdownContext):
    """
    内联 ``code_inline``：深紫灰底 + 淡紫字，两侧用 box 字符做微型「圆角」感。
    """

    def on_text(self, text: str, node_type: str) -> None:
        if node_type == 'code_inline':
            corner = f'bold {_BRAND_BORDER_HEX} on {_INLINE_CODE_BG}'
            if self._syntax is not None:
                highlight_text = self._syntax.highlight(text)
                highlight_text.rstrip()
                boxed = Text.assemble(
                    Text('╭ ', style=corner),
                    highlight_text,
                    Text(' ╮', style=corner),
                )
                self.stack.top.on_text(self, boxed)
                return
            boxed = Text.assemble(
                Text('╭ ', style=corner),
                Text(text, style=f'on {_INLINE_CODE_BG} {_INLINE_CODE_FG}'),
                Text(' ╮', style=corner),
            )
            self.stack.top.on_text(self, boxed)
            return
        super().on_text(text, node_type)


_SCREAM_MD_DEPTH = 0


class ScreamMarkdown(Markdown):
    """
    使用 ``ScreamMarkdownContext`` 与 ``ScreamCodeBlock``；嵌套渲染时重入安全地切换 Context。
    """

    elements = {
        **Markdown.elements,
        'fence': ScreamCodeBlock,
        'code_block': ScreamCodeBlock,
    }

    def __init__(
        self,
        markup: str,
        code_theme: str = STREAMING_CODE_THEME,
        **kwargs: Any,
    ) -> None:
        # 默认关闭内联 Pygments，便于统一「药丸」底色与淡紫字；需要时可显式传入 lexer
        kwargs.setdefault('inline_code_lexer', None)
        super().__init__(markup, code_theme, **kwargs)

    def __rich_console__(self, console: Any, options: Any):
        global _SCREAM_MD_DEPTH
        if _SCREAM_MD_DEPTH == 0:
            _rich_markdown_mod.MarkdownContext = ScreamMarkdownContext
        _SCREAM_MD_DEPTH += 1
        try:
            yield from Markdown.__rich_console__(self, console, options)
        finally:
            _SCREAM_MD_DEPTH -= 1
            if _SCREAM_MD_DEPTH == 0:
                _rich_markdown_mod.MarkdownContext = _StockMarkdownContext


def build_token_warning_panel(current_tokens: int, threshold: int) -> Any:
    """
    上下文压力软警告（仅 UI）：不拦截请求，由调用方在发往模型前按需触发。
    """
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    body = (
        '[bold yellow][警告][/bold yellow] [yellow]当前会话 Token 已接近模型极限，'
        'AI 回答可能会变慢或出现截断。建议任务完成后使用斜杠压缩类指令或清理上下文。[/yellow]\n'
        f'[dim]（累计约 {current_tokens:,} tokens · 提示阈值 {threshold:,}）[/dim]'
    )
    return Panel(
        Text.from_markup(body),
        title='[bold yellow]上下文压力[/bold yellow]',
        border_style='yellow',
        box=box.ROUNDED,
        expand=True,
        padding=(0, 1),
    )


def format_token_warning_plain(current_tokens: int, threshold: int) -> str:
    """无 Rich 时的同义纯文本版。"""
    return (
        '\n[警告] 当前会话 Token 已接近模型极限，AI 回答可能会变慢或出现截断。'
        '建议任务完成后使用斜杠压缩类指令或清理上下文。\n'
        f'（累计约 {current_tokens} tokens · 提示阈值 {threshold}）\n'
    )

# 与 skills / agent_tools 注册名一致（仅用于展示归类）
_FILE_WRITE_TOOLS = frozenset({'write_local_file'})
_FILE_READ_TOOLS = frozenset({'read_local_file'})
_BASH_TOOLS = frozenset({'execute_mac_bash'})
_SKILL_TOOLS = frozenset({'install_local_skill'})


def assistant_panel_title() -> Any:
    from rich.text import Text

    return Text.from_markup('[bold cyan]🚀scream code🚀[/bold cyan]')


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


def final_assistant_markdown_panel(markdown: str) -> Any:
    """
    Live（``transient=True``）停止后写入 scrollback 的**唯一**定稿：靛紫圆角卡片，不经过
    ``assistant_panel`` monkeypatch，样式固定以免与流式阶段混淆。
    调用方须保证 ``markdown.strip()`` 非空。
    """
    from rich import box
    from rich.panel import Panel

    stripped = (markdown or '').strip()
    return Panel(
        ScreamMarkdown(stripped, code_theme=STREAMING_CODE_THEME),
        title='◆ ASSISTANT',
        border_style='#4F46E5',
        box=box.ROUNDED,
        expand=True,
        padding=(1, 2),
    )


def print_cyber_turn_divider(console: Any) -> None:
    """用户轮与助手流式输出之间的低调分隔（scrollback 层次）。"""
    from rich.rule import Rule

    console.print(Rule(style='dim #334155'))


def tool_params_stream_collapsed_panel(raw_fragment: str | None = None) -> Any:
    """
    流式工具 JSON 结束后写入 scrollback 的坍缩提示：尝试解析参数，给出单行摘要
    （写文件行数 / bash 命令预览等），避免重复冗长 JSON。
    """
    from rich import box
    from rich.markup import escape
    from rich.panel import Panel

    tool_summary = '工具参数构建完毕'
    raw = (raw_fragment or '').strip()
    if raw:
        try:
            tool_data = json.loads(raw)
            if isinstance(tool_data, dict):
                fp = tool_data.get('filepath') or tool_data.get('file_path')
                content = tool_data.get('content')
                if fp and isinstance(content, str):
                    lines_count = len(content.splitlines())
                    tool_summary = (
                        f'已生成/修改文件: [cyan]{escape(str(fp))}[/] '
                        f'([green]+{lines_count} 行[/])'
                    )
                elif 'command' in tool_data:
                    cmd = str(tool_data['command'] or '')
                    cmd = (cmd[:40] + '…') if len(cmd) > 40 else cmd
                    tool_summary = f'即将执行命令: [yellow]{escape(cmd)}[/]'
                elif fp:
                    tool_summary = f'工具路径: [cyan]{escape(str(fp))}[/]'
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            pass

    collapse_msg = (
        f'[bold green]✓[/] [dim]{tool_summary} (详情已折叠)[/]'
    )
    return Panel(collapse_msg, border_style='dim', box=box.ROUNDED)


def print_solidified_assistant_markdown(console: Any, markdown: str) -> None:
    """
    ``Live(transient=True)`` 停止后的静态定稿：裸 ``ScreamMarkdown`` 写入终端历史，
    避免与流式瞬态重复堆叠。
    """
    stripped = (markdown or '').strip()
    if not stripped:
        return
    console.print(ScreamMarkdown(stripped, code_theme=STREAMING_CODE_THEME))


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
                theme=STREAMING_CODE_THEME,
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
            theme=STREAMING_CODE_THEME,
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
        inner = ScreamMarkdown(
            f'```json\n{_truncate(raw_args, max_len=6000)}\n```',
            code_theme=STREAMING_CODE_THEME,
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
        # 使用 Rich 原生 diff lexer 渲染，避免手写拼接；超出 2000 行则截断
        diff_body = Syntax(
            diff_text[:400_000],
            lexer='diff',
            theme=STREAMING_CODE_THEME,
            background_color='#09090B',
            word_wrap=True,
        )
        return Panel(
            diff_body,
            title=f'[bold cyan]Diff 预览[/bold cyan] · {name}',
            box=box.ROUNDED,
            border_style='cyan',
            padding=(0, 1),
            expand=True,
        )

    inner = ScreamMarkdown(
        f'**工具** `{name}`\n\n```json\n{_truncate(raw_args, max_len=12000)}\n```',
        code_theme=STREAMING_CODE_THEME,
    )
    return Panel(
        inner,
        title='[bold yellow]🛠️ 工具调用[/bold yellow]',
        box=box.ROUNDED,
        border_style='yellow',
        padding=(0, 1),
        expand=True,
    )


# Live 内全量 Markdown 重排过频时易 CPU 顶满；超长缓冲也提高解析失败概率
_STREAMING_MARKDOWN_SOFT_CAP = 600_000


def streaming_markdown_for_live(buffer: str) -> Any:
    """
    **仅**供 ``rich.Live`` 使用：裸 ``ScreamMarkdown``，禁止 ``Panel``。
    定稿请用 :func:`final_assistant_markdown_panel`。
    """
    from rich.text import Text

    buf = buffer or ''
    if len(buf) > _STREAMING_MARKDOWN_SOFT_CAP:
        buf = buf[: _STREAMING_MARKDOWN_SOFT_CAP - 120] + '\n\n…(流式缓冲过长，Live 内仅展示前段；完整内容在回合结束后可见)…\n'

    try:
        return ScreamMarkdown(buf, code_theme=STREAMING_CODE_THEME)
    except Exception as exc:
        return Text(
            f'[dim]Markdown 渲染跳过（{type(exc).__name__}），已缓冲 {len(buffer or "")} 字符。[/dim]',
            overflow='ignore',
        )


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
    """兼容旧名：同 :func:`streaming_markdown_for_live`。"""
    return streaming_markdown_for_live(buffer)
