from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, ClassVar

from ..browser_vision import (
    BrowserVisionEngine,
    BrowserVisionError,
    BrowserVisionFatalInstallError,
)
from ..scream_theme import ScreamTheme, skill_panel
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome

_DEFAULT_FOLLOWUP = """你现在是一名精通视觉分析的前端架构师。请结合上方的截图以及我提供的页面真实 CSS 提取数据，严格按照以下 Design Tokens 规范提炼视觉要素（严禁空谈，必须给出具体的 Hex 或 px 预估值）：
1. 颜色系统：提取主色、辅色、背景色、文字颜色（使用真实的 Hex 值）。
2. 形状与阴影：提炼圆角大小（px）、投影样式。
3. 间距逻辑：分析核心控件的 Padding 规律及容器间的 Margin 间距。
4. 字体排版：识别字号层级和真实的 font-family。
注意：本轮任务绝对不要写任何前端代码！只输出这一套结构化、详尽的设计规范报告。"""

_MIME_FOR_SUFFIX: dict[str, str] = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
}

# 与 ``browser_vision._DEFAULT_MAX_CAPTURE_HEIGHT`` 对齐：仅 ``--full`` 时由底层默认裁剪高度。
_DEFAULT_MAX_CAPTURE_HEIGHT = 2400


def _look_parse_error(console: object | None, text: str) -> None:
    if console is not None:
        console.print(f'[yellow]{text}[/yellow]')
    else:
        print(text, flush=True)


def _parse_look_cmdline(args: str) -> tuple[str, str, bool, int | None]:
    """
    解析 ``/look`` 参数行。

    Returns:
        ``(url, user_prompt, full_page, max_capture_height)``。
        ``max_capture_height`` 为 ``None`` 表示未指定（``--full`` 时由底层使用默认 2400px 顶区裁剪）。
    """
    s = (args or '').strip()
    if not s:
        return '', '', False, None
    tokens = s.split()
    url = tokens[0]
    if url.startswith('--'):
        raise ValueError('URL 不能以 -- 开头；请先写目标地址。')
    rest = tokens[1:]
    full_page = False
    max_capture_height: int | None = None
    out: list[str] = []
    i = 0
    while i < len(rest):
        t = rest[i]
        if t == '--full':
            full_page = True
            i += 1
            continue
        if t == '--max-height':
            if i + 1 >= len(rest):
                raise ValueError('--max-height 需要紧跟一个正整数（像素）。')
            try:
                v = int(rest[i + 1], 10)
            except ValueError as exc:
                raise ValueError('--max-height 的值必须是整数。') from exc
            if v < 1:
                raise ValueError('--max-height 必须 ≥ 1。')
            max_capture_height = v
            i += 2
            continue
        out.append(t)
        i += 1
    user_prompt = ' '.join(out).strip()
    return url, user_prompt, full_page, max_capture_height


class LookSkill(BaseSkill):
    name: ClassVar[str] = 'look'
    category: ClassVar[str] = 'vision'
    description: ClassVar[str] = (
        '👁️ 网页视觉快照；可选 ``--full``（顶区长图）、``--max-height <px>``（默认 '
        f'{_DEFAULT_MAX_CAPTURE_HEIGHT}，仅与 ``--full`` 联用）；无参 ``/look`` 看用法'
    )

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        console = context.console
        raw = (args or '').strip()
        if not raw:
            self._print_usage(console)
            return SkillOutcome()

        try:
            url, user_prompt, full_page, max_capture_height = _parse_look_cmdline(raw)
        except ValueError as exc:
            _look_parse_error(console, str(exc))
            self._print_usage(console)
            return SkillOutcome()

        if not url:
            self._print_usage(console)
            return SkillOutcome()

        json_stdio = os.environ.get('SCREAM_REPL_JSON_STDIO', '').strip().lower() in (
            '1',
            'true',
            'yes',
        )
        llm_on = bool(context.engine.config.llm_enabled)

        cap_kw: dict[str, Any] = {'full_page': full_page}
        if full_page and max_capture_height is not None:
            cap_kw['max_capture_height'] = max_capture_height

        try:
            if console is not None:
                result = BrowserVisionEngine().capture_page(url, console=console, **cap_kw)
            else:
                result = BrowserVisionEngine().capture_page(url, **cap_kw)
        except BrowserVisionFatalInstallError:
            return SkillOutcome()
        except BrowserVisionError as exc:
            self._print_web_access_failed(console, str(exc))
            return SkillOutcome()
        except Exception as exc:  # pragma: no cover
            self._print_web_access_failed(
                console, f'{type(exc).__name__}: {exc}'
            )
            return SkillOutcome()

        screenshot_path = ''
        css_tokens: dict[str, Any] = {}
        if isinstance(result, dict):
            raw_path = result.get('screenshot_path')
            raw_tokens = result.get('css_tokens')
            if isinstance(raw_path, str):
                screenshot_path = raw_path
            if isinstance(raw_tokens, dict):
                css_tokens = raw_tokens
        elif isinstance(result, str):
            # 兼容旧返回：仅路径字符串
            screenshot_path = result
        else:
            self._print_web_access_failed(console, '视觉模块返回了无法识别的数据结构。')
            return SkillOutcome()

        shot_path = Path(screenshot_path)
        try:
            image_bytes = shot_path.read_bytes()
        except OSError as exc:
            self._print_web_access_failed(
                console, f'无法读取截图文件: {type(exc).__name__}: {exc}'
            )
            return SkillOutcome()

        mime = _MIME_FOR_SUFFIX.get(shot_path.suffix.lower(), 'image/png')
        b64 = base64.standard_b64encode(image_bytes).decode('ascii')
        data_url = f'data:{mime};base64,{b64}'

        abs_path = str(shot_path.resolve())
        self._print_ready(console, abs_path)

        capture_note = (
            f'截图模式: 视口（默认）\n'
            if not full_page
            else (
                f'截图模式: 自顶向下裁剪（full_page 语义）；max_capture_height='
                f'{max_capture_height if max_capture_height is not None else _DEFAULT_MAX_CAPTURE_HEIGHT}px\n'
            )
        )
        ctx_text = (
            f'[/look 网页快照]\n'
            f'URL: {url}\n'
            + capture_note
            + (
                f'用户说明: {user_prompt}\n'
                if user_prompt
                else '用户未追加文字说明；请主动审视页面 UI 与可访问性。\n'
            )
            + f'本地文件: {abs_path}\n'
            + '--- 页面真实 CSS 提取数据（Design Tokens，JSON）---\n'
            + json.dumps(css_tokens, ensure_ascii=False, indent=2)
            + '\n--- 以上数据与截图为同一页面同一时刻 ---'
        )
        user_msg: dict[str, object] = {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': ctx_text},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ],
        }

        follow = (user_prompt or _DEFAULT_FOLLOWUP).strip()
        trigger = llm_on and not json_stdio and bool(follow)

        append = (user_msg,)
        if json_stdio and llm_on and not trigger and console is not None:
            console.print(
                '[dim grey39]多模态消息已写入会话；JSON stdio 模式下请再发送一条 submit 以触发模型。[/dim grey39]'
            )

        return SkillOutcome(
            append_llm_messages=append,
            trigger_llm_followup=trigger,
            followup_prompt=follow,
        )

    def _print_usage(self, console: object | None) -> None:
        body = (
            '[bold white]/look[/bold white] [cyan]<url>[/cyan] '
            '[dim][--full] [--max-height N] [可选说明…]][/dim]\n\n'
            '[dim]选项：[/dim]\n'
            '  [cyan]--full[/cyan]  自页面顶部向下截取较长区域（非整页拼接；避免超长图被压缩）\n'
            f'  [cyan]--max-height N[/cyan]  与 [cyan]--full[/cyan] 联用，裁剪最大高度（像素）；'
            f'省略时底层默认 [bold]{_DEFAULT_MAX_CAPTURE_HEIGHT}[/bold]\n\n'
            '[dim]示例:[/dim]\n'
            '  [grey62]/look https://example.com[/grey62]\n'
            '  [grey62]/look https://example.com --full --max-height 4000[/grey62]\n'
            '  [grey62]/look localhost:3000 按钮没有垂直居中，请结合截图分析原因[/grey62]'
        )
        title = f'[{ScreamTheme.TEXT_ACCENT}]/look · VISION[/{ScreamTheme.TEXT_ACCENT}]'
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(body),
                    title=title,
                    variant='accent',
                )
            )
        else:
            print(
                '用法: /look <url> [--full] [--max-height N] [说明…]\n'
                '  --full           顶区长图模式（省略 --max-height 时默认高度 2400px）\n'
                '  --max-height N   与 --full 联用，最大裁剪高度（像素）\n'
                '示例:\n'
                '  /look https://example.com\n'
                '  /look https://example.com --full --max-height 4000\n'
                '  /look http://localhost:3000 帮我看按钮为何未居中'
            )

    def _print_ready(self, console: object | None, path: str) -> None:
        if console is not None:
            console.print(
                f'[bold green]👁️ 视觉数据已就绪：[/bold green][bold cyan]{path}[/bold cyan]'
            )
        else:
            print(f'👁️ 视觉数据已就绪：{path}')

    def _print_web_access_failed(self, console: object | None, message: str) -> None:
        """网页导航/截图失败（仅 Playwright）；深色面板，禁止与系统截屏混淆。"""
        body = (
            f'[bold #f87171]网页访问失败（Playwright DOM 截图）[/bold #f87171]\n\n'
            f'[dim]{message}[/dim]\n\n'
            f'[dim]说明：/look 仅截取远程网页，不会使用 screencapture 或桌面截屏。[/dim]'
        )
        title = f'[{ScreamTheme.TEXT_ERROR}]/look · WEB · FAIL[/{ScreamTheme.TEXT_ERROR}]'
        if console is not None:
            from rich.text import Text

            console.print(
                skill_panel(
                    Text.from_markup(body),
                    title=title,
                    variant='error',
                )
            )
        else:
            print(message, flush=True)
