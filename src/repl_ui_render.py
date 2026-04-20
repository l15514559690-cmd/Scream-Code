"""
REPL 纯展示层：工具调用面板、语法高亮、流式 Markdown 包装。
不修改事件结构、不触碰工具执行逻辑。

``ScreamMarkdown``：内联代码圆角感 + 大块 ``Syntax``；流式 ``Live`` 只用裸 Markdown（禁止外层 ``Panel``，
以免每帧重绘整张卡片）。:func:`prepare_streaming_live_buffer` 负责视口尾部裁剪 + 围栏虚拟闭合；
:func:`streaming_markdown_for_live` 供节流后的帧调用。回合间分隔 :func:`print_cyber_turn_divider`；
流式结束定稿 :func:`print_solidified_assistant_markdown` / :func:`final_assistant_markdown_panel`。
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

import rich.markdown as _rich_markdown_mod
from rich.markdown import CodeBlock, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

# TUI / 助手 Markdown 品牌与代码区（与 tui_app 靛紫系一致）
_BRAND_BORDER_HEX = '#4F46E5'
# 流式定稿与 Live 内代码块统一使用同一暗色 Pygments 主题
# one-dark: Atom One Dark — 经典极客暗黑风，代码高亮对比度高，背景与普通文字分离清晰
# 可选替代: 'dracula'（偏紫）、'github-dark'（偏灰）、'nord'（冷灰蓝）
STREAMING_CODE_THEME = 'one-dark'

# ── Live 神经帧调度：与 refresh_per_second≈30 对齐；过小会每 token 全量 Markdown 重排烧 CPU ──
STREAM_LIVE_MIN_INTERVAL_SEC = 1.0 / 30.0
STREAM_LIVE_MIN_CHAR_DELTA = 12
# 视口：按终端高度裁尾部行，把「滚动」锁在 Live 区域内，scrollback 不乱跳
STREAM_LIVE_VIEWPORT_RESERVE_LINES = 8  # 状态栏 / Rule / 系统边距
STREAM_LIVE_VIEWPORT_MIN_LINES = 12  # 再矮的 PTY 也保留可读高度
_INLINE_CODE_BG = '#2D2D39'
_INLINE_CODE_FG = '#A5B4FC'
_CODE_PANEL_BG = '#09090B'

_StockMarkdownContext = _rich_markdown_mod.MarkdownContext


# ------------------------------------------------------------
# 增量静态渲染器 (StreamChunker)
# 解决 rich.Live 全量渲染 O(N²) 卡顿 + 终端坐标失效 + 幽灵帧问题
# ------------------------------------------------------------

class StreamChunker:
    """
    增量静态渲染器：防止 Live 组件高度超限，并解决 O(N^2) 渲染卡顿。
    新增「动态思考折叠」：<thinking>...</thinking> 流式标签在 Live 内被拦截，
    仅在静态历史中留下单行耗时提示，Diff 为唯一焦点。

    算法逻辑：
    - 每次 text_delta 到来，先拼入 full_buffer。
    - 从未刷新部分（ unflushed = full_buffer[flushed_length:]）寻找最近的安全分割点
     （两个连续换行符 ``\\n\\n``，且不在代码块内 — 即 ````` 计数为偶数）。
    - 安全段落通过 console.print(Markdown(...)) 静态落盘，flushed_length 前移。
    - 返回剩下未完成的尾巴（tail）供 Live 渲染，Live 里永远只有几行字。
    - 流结束时 flush_remaining() 将最后尾巴也静态打印。
    """

    _THINKING_OPEN = '<thinking>'
    _THINKING_CLOSE = '</thinking>'
    _THINKING_TOKEN = '<THINKING_IN_PROGRESS>'

    def __init__(self, console: Any, code_theme: str = STREAMING_CODE_THEME) -> None:
        self.console = console
        self.code_theme = code_theme
        self.full_buffer = ''
        self.flushed_length = 0
        self.in_thinking = False
        self.think_start_time = 0.0
        self._thinking_depth = 0  # 支持嵌套 thinking 标签

    def process_and_flush(self, delta: str) -> str:
        """
        处理新的 delta，将已确定的安全段落静态打印，返回未完成的尾巴供 Live 渲染。
        当 in_thinking==True 时返回 _THINKING_TOKEN，调用方渲染暗色动画提示。
        """
        import time as _time

        self.full_buffer += delta
        unflushed = self.full_buffer[self.flushed_length:]

        # ── 思考链状态机 ─────────────────────────────────────────────────────
        # 检测流式 token 切割：<thin / king> 可能跨 delta 到达
        self._update_thinking_state(unflushed)
        if self.in_thinking:
            return self._THINKING_TOKEN

        # ── 正常段落刷新 ─────────────────────────────────────────────────────
        last_double_newline = unflushed.rfind('\n\n')

        if last_double_newline != -1:
            text_up_to_split = self.full_buffer[: self.flushed_length + last_double_newline]
            # 围栏计数需要排除当前 in_thinking 的 open tag
            fence_safe = text_up_to_split.count('```') % 2 == 0
            if fence_safe:
                chunk_to_flush = unflushed[:last_double_newline].strip()
                if chunk_to_flush:
                    chunk_to_flush = self._strip_thinking_blocks(chunk_to_flush)
                    if chunk_to_flush:
                        self.console.print(
                            Markdown(chunk_to_flush, code_theme=self.code_theme)
                        )
                self.flushed_length += last_double_newline + 2

        tail = self.full_buffer[self.flushed_length:]
        if self._has_open_thinking(tail):
            return self._THINKING_TOKEN
        return tail

    def _update_thinking_state(self, text: str) -> None:
        """
        扫描 text 片段，维护 in_thinking 状态和嵌套深度。
        处理 token 流式切割场景（<thin / king> 分片到达）。
        """
        import re

        if self.in_thinking:
            # 查找闭合标签（可能分片到达：</think /ing> 等）
            # 用简单字符串查找向后扫描更稳健
            close_idx = -1
            search_from = max(0, len(self.full_buffer) - len(text) - 50)
            window = self.full_buffer[search_from:]
            ci = window.find(self._THINKING_CLOSE)
            if ci != -1:
                close_idx = search_from + ci
                import time

                duration = time.time() - self.think_start_time
                self.in_thinking = False
                self._thinking_depth = 0
                flushed = self.full_buffer[max(0, self.flushed_length - 1):close_idx + len(self._THINKING_CLOSE)]
                # 从已刷新部分剥离刚才闭合的 thinking 块，不静态打印内容
                stripped = self._strip_thinking_blocks(flushed)
                if stripped.strip():
                    self.console.print(
                        Markdown(stripped, code_theme=self.code_theme)
                    )
                self.console.print(
                    f'[dim]✓ 深度推演 ({duration:.1f}s)[/dim]'
                )
        else:
            # 尚未在 thinking 中，查找 opening tag（可能分片）
            open_idx = -1
            search_from = max(0, len(self.full_buffer) - len(text) - 50)
            window = self.full_buffer[search_from:]
            oi = window.find(self._THINKING_OPEN)
            if oi != -1:
                import time

                open_idx = search_from + oi
                self.in_thinking = True
                self.think_start_time = time.time()
                self._thinking_depth = 1

    def _has_open_thinking(self, text: str) -> bool:
        """检查 text 末尾是否有未闭合的 <thinking> 标签（可能分片）。"""
        for i in range(len(text) - len(self._THINKING_OPEN), -1, -1):
            if text[i:].startswith(self._THINKING_OPEN):
                return True
        return False

    def _strip_thinking_blocks(self, text: str) -> str:
        """从 text 中移除所有完整的 <thinking>...</thinking> 块，不打印内容。"""
        import re

        pattern = re.compile(
            r'<thinking>[\s\S]*?</thinking>',
            re.IGNORECASE,
        )
        return pattern.sub('', text)

    @staticmethod
    def _render_thinking_fold(text: str) -> str:
        """
        将 <thinking>...</thinking> 标签包裹的内容替换为带左边框指示符的暗色斜体文本。

        样式: │ [dim italic]thinking 内容[/dim italic]
        这样用户在 scrollback 里一眼就能区分「中间过程」和「最终答案」。
        """
        import re

        THINKING_OPEN = '<thinking>'
        THINKING_CLOSE = '</thinking>'
        FOLD_MARKER = '│ '

        result = text

        # 策略一：处理完整闭合的 <thinking> 块（多行）
        if THINKING_OPEN in result and THINKING_CLOSE in result:
            pattern = re.compile(
                r'<thinking>\s*(.*?)\s*</thinking>',
                re.DOTALL | re.IGNORECASE,
            )
            def replacer(m: re.Match) -> str:
                inner = m.group(1).strip()
                if not inner:
                    return ''
                lines = inner.splitlines()
                folded = '\n'.join(f'{FOLD_MARKER}[dim italic]{line}[/dim italic]' for line in lines)
                return f'\n{folded}\n'
            result = pattern.sub(replacer, result)

        # 策略二：检测左对齐的「中间推算」型文字（以 │ 开头或类似思考链特征）
        # 把连续多行、每行以特定关键词开头的段落（尚未被策略一处理）做降亮处理
        # 识别特征：连续 3 行以上、以 → / => / 推断 / 分析 等开头的段落
        lines = result.splitlines()
        processed: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # 跳过已是 thinking 替换结果的行
            if line.startswith(FOLD_MARKER) or line.startswith('│'):
                processed.append(line)
                i += 1
                continue
            # 检测是否是思考链候选行（非空、以 →/=>/推/分析/拆解/逐步 等开头）
            strip = line.lstrip()
            if strip and any(strip.startswith(p) for p in ('→', '=>', '▸', '●', '◉', '推断', '分析', '拆解', '逐步', '步骤', '(', '（')):
                # 收集连续段落
                block_lines = [line]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    nstrip = nxt.lstrip()
                    # 遇到空行或非思考链特征行就停止
                    if not nstrip or not any(nstrip.startswith(p) for p in ('→', '=>', '▸', '●', '◉', '推断', '分析', '拆解', '逐步', '步骤', '(', '（')):
                        break
                    block_lines.append(nxt)
                    j += 1
                if len(block_lines) >= 2:
                    # 整体加左边框 + dim italic
                    for bl in block_lines:
                        processed.append(f'{FOLD_MARKER}[dim italic]{bl}[/dim italic]')
                    i = j
                    continue
            processed.append(line)
            i += 1

        return '\n'.join(processed)

    def flush_remaining(self) -> None:
        """流结束时，将最后剩下的尾巴打印出来。"""
        remaining = self.full_buffer[self.flushed_length:].strip()
        if remaining:
            self.console.print(Markdown(remaining, code_theme=self.code_theme))
        self.flushed_length = len(self.full_buffer)


# ------------------------------------------------------------
# 原有工具函数
# ------------------------------------------------------------

def _get_dynamic_thinking_title() -> str:
    try:
        from .tui_app import get_current_team_agent

        agent = get_current_team_agent()
    except Exception:
        agent = None
    if agent:
        return f'[dim]🐺 {agent} 神经链路同步中...[/dim]'
    return '[dim]✨ 神经链路生成中...[/dim]'


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
        border_style='#4F46E5',
        box=box.MINIMAL,
        expand=True,
        padding=(0, 1),
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
    console.print(final_assistant_markdown_panel(stripped))


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
    """``api_tool_op`` 极简提示：仅单行状态，避免大参数 JSON 刷屏。"""
    from rich.text import Text

    name = str(ev.get('tool_name', '') or 'tool')
    return Text.from_markup(f'[dim cyan]⚙️ 准备调用工具: {name}[/dim cyan]')


def render_inline_diff(file_path: str, old_content: str, new_content: str) -> Any:
    """
    使用 unified diff 渲染文件改动（红/绿/青），供工具执行成功后快速审查。
    """
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    diff_lines = list(
        difflib.unified_diff(
            (old_content or '').splitlines(keepends=True),
            (new_content or '').splitlines(keepends=True),
            fromfile=f'a/{file_path}',
            tofile=f'b/{file_path}',
            lineterm='',
        )
    )
    if not diff_lines:
        return Panel(
            Text('（内容无变化）', style='dim'),
            title='[bold #60a5fa]🧾 Diff 预览[/bold #60a5fa]',
            border_style='#334155',
            padding=(0, 1),
            expand=True,
        )

    rows: list[Text] = []
    for raw in diff_lines[:800]:
        line = raw.rstrip('\n')
        if line.startswith('@@'):
            rows.append(Text(line, style='dim cyan'))
        elif line.startswith('+') and not line.startswith('+++'):
            rows.append(Text(line, style='green'))
        elif line.startswith('-') and not line.startswith('---'):
            rows.append(Text(line, style='red'))
        elif line.startswith('---') or line.startswith('+++'):
            rows.append(Text(line, style='bold #94a3b8'))
        else:
            rows.append(Text(line, style='white'))
    if len(diff_lines) > 800:
        rows.append(Text(f'... (其余 {len(diff_lines) - 800} 行已折叠)', style='dim'))

    return Panel(
        Group(*rows),
        title='[bold #60a5fa]🧾 Diff 预览[/bold #60a5fa]',
        border_style='#334155',
        padding=(0, 1),
        expand=True,
    )


def render_approval_card(tool_name: str, arguments: dict[str, Any]) -> Any:
    """
    高危工具审批卡片：列出工具名与关键参数，提示用户 ``y/a/n`` 决策。
    """
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    kv_lines: list[Text] = []
    for key in ('command', 'file_path', 'path', 'target_file', 'source_file'):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            shown = val.strip()
            if len(shown) > 220:
                shown = shown[:220] + '…'
            kv_lines.append(
                Text.assemble(
                    Text(f'• {key}: ', style='bold #facc15'),
                    Text(shown, style='white'),
                )
            )
    if not kv_lines:
        # 回退展示：避免参数结构缺失时信息黑洞。
        raw = json.dumps(arguments, ensure_ascii=False)
        if len(raw) > 260:
            raw = raw[:260] + '…'
        kv_lines.append(
            Text.assemble(
                Text('• arguments: ', style='bold #facc15'),
                Text(raw if raw else '{}', style='white'),
            )
        )

    body = Group(
        Text.assemble(
            Text('工具: ', style='bold #facc15'),
            Text(tool_name, style='bold white'),
        ),
        Text(''),
        *kv_lines,
        Text(''),
        Text.from_markup(
            '[dim]按 [bold green]y[/bold green] 同意，按 [bold blue]a[/bold blue] 本次会话全局放行，按 [bold red]n[/bold red] 拒绝。[/dim]'
        ),
    )
    return Panel(
        body,
        title='[bold yellow]⚠️ 需要审批 (Action Required)[/bold yellow]',
        border_style='#f59e0b',
        padding=(1, 2),
        expand=True,
    )


def render_and_print_file_diff(
    console: Any,
    file_path: str,
    new_content: str,
    *,
    theme: str = 'ansi_dark',
) -> None:
    """
    读取原文件，与新内容比对，打印高级 Git Unified Diff 视图。
    使用 Rich Syntax + diff lexer，自动红绿背景高亮。
    """
    path = Path(file_path)
    old_content = ''
    if path.exists():
        try:
            old_content = path.read_text(encoding='utf-8')
        except OSError:
            old_content = ''

    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f'a/{file_path} (Original)',
            tofile=f'b/{file_path} (Modified)',
            n=3,
        )
    )

    if not diff_lines:
        console.print(
            Panel(
                '[dim]AI 尝试覆写文件，但内容与硬盘上完全一致，无实质性代码变更。[/dim]',
                title=f'📝 [bold yellow]No Changes: {file_path}[/]',
                border_style='yellow',
            )
        )
        return

    diff_str = ''.join(diff_lines)
    diff_syntax = Syntax(
        diff_str,
        lexer='diff',
        theme=theme,
        background_color='default',
        word_wrap=True,
    )
    console.print(
        Panel(
            diff_syntax,
            title=f'📝 [bold cyan]Pending Changes: {file_path}[/]',
            border_style='cyan',
        )
    )


# Live 内全量 Markdown 重排过频时易 CPU 顶满；超长缓冲也提高解析失败概率
_STREAMING_MARKDOWN_SOFT_CAP = 600_000


def _fence_language_if_open_at_end(text: str) -> str | None:
    """
    扫描至 ``text`` 末尾：若停在未闭合的围栏代码块内，返回该块声明的语言标识（无则 ``text``）。
    """
    in_fence = False
    lang = 'text'
    for line in text.split('\n'):
        s = line.lstrip()
        if not s.startswith('```'):
            continue
        rest = s[3:].strip()
        if not in_fence:
            in_fence = True
            lang = rest if rest else 'text'
        else:
            in_fence = False
    return lang if in_fence else None


def stabilize_streaming_markdown_fences(buf: str) -> str:
    """
    流式中途围栏 `` ``` `` 常不成对，CommonMark 会把后续全文当代码吃掉。
    在缓冲末尾**虚拟闭合**一层围栏，让 Pygments 与段落结构保持稳定；定稿打印仍用原始全文。
    """
    if not buf:
        return buf
    in_fence = False
    for line in buf.split('\n'):
        s = line.lstrip()
        if s.startswith('```'):
            in_fence = not in_fence
    if in_fence:
        return buf + '\n```\n'
    return buf


def _force_soft_close_fence_if_unbalanced(buf: str) -> str:
    """
    末端保险：若整段 ````` `` 出现次数为奇数，追加一段虚拟闭合围栏。
    与 :func:`stabilize_streaming_markdown_fences` 叠加使用，避免极端增量片段导致代码块渲染抖动。
    """
    if not buf:
        return buf
    if buf.count('```') % 2 == 1:
        return buf + '\n```\n'
    return buf


def _live_viewport_tail(text: str, *, console: Any) -> str:
    """
    只把尾部若干行送进 Live：视口高度跟终端走，旧行在缓冲区里退场而不是顶爆 scrollback。
    若裁剪点落在围栏内，在片段首补一行 `` ```lang`` 续写语义，再经 :func:`stabilize_streaming_markdown_fences` 闭合。
    """
    try:
        height = int(getattr(getattr(console, 'size', None), 'height', 0) or 0)
    except (TypeError, ValueError):
        height = 0
    if height <= 0:
        height = 24
    max_lines = max(
        STREAM_LIVE_VIEWPORT_MIN_LINES, height - STREAM_LIVE_VIEWPORT_RESERVE_LINES
    )
    lines = text.split('\n')
    if len(lines) <= max_lines:
        return text
    dropped = len(lines) - max_lines
    head = '\n'.join(lines[:-max_lines])
    tail = '\n'.join(lines[-max_lines:])
    lang = _fence_language_if_open_at_end(head)
    if lang is not None:
        tail = f'```{lang}\n' + tail
    ribbon = (
        f'\n\n> ‥ *{dropped} lines above live fold* · *full transcript on freeze* ‥\n\n'
    )
    return ribbon + tail


def prepare_streaming_live_buffer(buffer: str, *, console: Any | None = None) -> str:
    """
    Live 专用：软上限 → 视口尾部 → 围栏闭合。返回可直接喂给 ``ScreamMarkdown`` 的字符串。
    """
    buf = buffer or ''
    if len(buf) > _STREAMING_MARKDOWN_SOFT_CAP:
        buf = (
            buf[: _STREAMING_MARKDOWN_SOFT_CAP - 120]
            + '\n\n…(流式缓冲过长，Live 内仅展示前段；完整内容在回合结束后可见)…\n'
        )
    if console is not None:
        buf = _live_viewport_tail(buf, console=console)
    buf = stabilize_streaming_markdown_fences(buf)
    return _force_soft_close_fence_if_unbalanced(buf)


def streaming_markdown_for_live(buffer: str, *, console: Any | None = None) -> Any:
    """
    **仅**供 ``rich.Live`` 使用：轻量左边框 ``Panel`` + ``ScreamMarkdown``，强化流式区与历史区的视觉隔离。
    传入 ``console`` 时启用视口尾部裁剪，缓和全屏模式下终端滚动条抽搐。
    定稿请用 :func:`final_assistant_markdown_panel` / :func:`print_solidified_assistant_markdown`。
    """
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    buf = prepare_streaming_live_buffer(buffer, console=console)
    # 渲染前最后一道保险：确保流式中代码围栏始终闭合，避免纯文本塌陷到回合末才恢复高亮。
    buf = _force_soft_close_fence_if_unbalanced(buf)
    try:
        md = ScreamMarkdown(buf, code_theme=STREAMING_CODE_THEME)
        return Panel(
            md,
            box=box.MINIMAL,
            border_style='dim #A5B4FC',
            title=_get_dynamic_thinking_title(),
            title_align='left',
            padding=(0, 1),
            expand=True,
        )
    except Exception as exc:
        return Text(
            f'[dim]Markdown 渲染跳过（{type(exc).__name__}），已缓冲 {len(buffer or "")} 字符。[/dim]',
            overflow='ignore',
        )


def tool_execution_status_message(tool_name: str) -> str:
    """Rich Status 用的一行紧凑说明（Markup）。"""
    return f'[dim cyan]运行中: {tool_name}...[/dim cyan]'


def streaming_markdown_panel(buffer: str, *, console: Any | None = None) -> Any:
    """兼容旧名：同 :func:`streaming_markdown_for_live`。"""
    return streaming_markdown_for_live(buffer, console=console)
