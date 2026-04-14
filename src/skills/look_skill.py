from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import ClassVar

from ..browser_vision import (
    BrowserVisionEngine,
    BrowserVisionError,
    BrowserVisionFatalInstallError,
)
from ..scream_theme import ScreamTheme, skill_panel
from .base_skill import BaseSkill, ReplSkillContext, SkillOutcome

_DEFAULT_FOLLOWUP = (
    '请结合上方截图分析该页面的视觉与布局（对齐、间距、层次、可读性、对比度等），'
    '若涉及前端实现请给出可落地的修改建议。'
)

_MIME_FOR_SUFFIX: dict[str, str] = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
}


class LookSkill(BaseSkill):
    name: ClassVar[str] = 'look'
    category: ClassVar[str] = 'vision'
    description: ClassVar[str] = '👁️ 获取指定网页或 UI 的视觉快照'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        console = context.console
        raw = (args or '').strip()
        if not raw:
            self._print_usage(console)
            return SkillOutcome()

        parts = raw.split(None, 1)
        url = parts[0].strip()
        user_prompt = parts[1].strip() if len(parts) > 1 else ''

        json_stdio = os.environ.get('SCREAM_REPL_JSON_STDIO', '').strip().lower() in (
            '1',
            'true',
            'yes',
        )
        llm_on = bool(context.engine.config.llm_enabled)

        try:
            if console is not None:
                result = BrowserVisionEngine().capture_page(url, console=console)
            else:
                result = BrowserVisionEngine().capture_page(url)
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

        shot_path = Path(result)
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

        ctx_text = (
            f'[/look 网页快照]\n'
            f'URL: {url}\n'
            + (
                f'用户说明: {user_prompt}\n'
                if user_prompt
                else '用户未追加文字说明；请主动审视页面 UI 与可访问性。\n'
            )
            + f'本地文件: {abs_path}'
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
            '[bold white]/look[/bold white] [cyan]<url>[/cyan] [dim][可选说明][/dim]\n\n'
            '[dim]示例:[/dim]\n'
            '  [grey62]/look https://example.com[/grey62]\n'
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
                '用法: /look <url> [说明…]\n'
                '示例: /look http://localhost:3000 帮我看按钮为何未居中'
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
