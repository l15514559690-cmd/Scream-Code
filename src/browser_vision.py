from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_DEFAULT_NAV_TIMEOUT_MS = 15_000
_POST_DOM_LOAD_PAUSE_SEC = 0.35
_VIEWPORT = {'width': 1280, 'height': 720}

# 唯一允许的截图根目录（绝对路径，禁止写入桌面或其它任意路径）
def _screenshots_root() -> Path:
    return (Path.home() / '.scream' / 'screenshots').expanduser()


class BrowserVisionError(Exception):
    """
    网页视觉失败（仅 Playwright 对 **DOM** 截图）。

    本模块绝不调用 screencapture / ImageGrab / pyautogui 等系统截屏。
    """

    pass


class BrowserVisionFatalInstallError(BrowserVisionError):
    """自动安装 playwright/chromium 失败，且已在终端绘制 Fatal Panel。"""

    panel_emitted: bool = True


def _normalize_url(url: str) -> str:
    """规范化 URL；非法则抛 ``BrowserVisionError``。"""
    raw = (url or '').strip()
    if not raw:
        raise BrowserVisionError('[BrowserVision] 错误: URL 不能为空。')
    if len(raw) > 8_192:
        raise BrowserVisionError('[BrowserVision] 错误: URL 过长。')
    if '://' not in raw:
        raw = f'https://{raw}'
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise BrowserVisionError(f'[BrowserVision] 错误: URL 无法解析（{exc}）。') from exc
    if parsed.scheme not in ('http', 'https'):
        raise BrowserVisionError(
            f'[BrowserVision] 错误: 不支持的协议 {parsed.scheme!r}，仅支持 http/https。'
        )
    if not parsed.netloc:
        raise BrowserVisionError('[BrowserVision] 错误: URL 缺少主机名。')
    return raw


def _allocate_capture_path() -> Path:
    """
    在 ``~/.scream/screenshots/`` 下生成唯一文件名（仅 ``.png``）。

    始终返回已 ``resolve()`` 的绝对路径；目录不存在则创建。
    """
    root = _screenshots_root()
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    out = (root / f'capture_{ts}.png').resolve()
    try:
        out.relative_to(root)
    except ValueError as exc:
        raise BrowserVisionError('[BrowserVision] 内部错误: 截图路径越界。') from exc
    return out


@contextmanager
def _rich_status(console: Any | None, message: str):
    """Rich ``console.status``；无终端或非 Rich 时退回 stderr 一行提示。"""
    if console is not None:
        try:
            with console.status(f'[bold #22d3ee]{message}[/bold #22d3ee]', spinner='dots12'):
                yield
            return
        except Exception:
            pass
    print(message, file=sys.stderr, flush=True)
    yield


def _run_subprocess(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=None,
        )
    except OSError as exc:
        return 127, f'{type(exc).__name__}: {exc}'
    parts = [x for x in (proc.stdout, proc.stderr) if x]
    merged = '\n'.join(parts).strip()
    return proc.returncode, merged


def _invalidate_playwright_modules() -> None:
    for key in list(sys.modules):
        if key == 'playwright' or key.startswith('playwright.'):
            del sys.modules[key]


def _try_import_sync_playwright() -> Any | None:
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError:
        return None


def _pip_install_playwright(console: Any | None) -> tuple[int, str]:
    cmd = [sys.executable, '-m', 'pip', 'install', 'playwright']
    with _rich_status(
        console,
        '🚀 首次激活视觉引擎：正在自动下载依赖 (1/2)…',
    ):
        return _run_subprocess(cmd)


def _playwright_install_chromium(console: Any | None) -> tuple[int, str]:
    cmd = [sys.executable, '-m', 'playwright', 'install', 'chromium']
    with _rich_status(
        console,
        '🌐 正在拉取无头浏览器内核，这可能需要几分钟 (2/2)…',
    ):
        return _run_subprocess(cmd)


def _emit_fatal_panel(console: Any | None, body_markup: str) -> None:
    title = '[bold #64748b]BROWSER · VISION · FATAL[/bold #64748b]'
    if console is None:
        print(
            body_markup.replace('[bold #f87171]', '').replace('[/bold #f87171]', ''),
            file=sys.stderr,
            flush=True,
        )
        return
    try:
        from rich import box
        from rich.panel import Panel
        from rich.text import Text

        console.print(
            Panel(
                Text.from_markup(body_markup),
                title=title,
                border_style='red',
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    except Exception:
        print(body_markup, file=sys.stderr, flush=True)


def _fatal_install_raise(
    console: Any | None,
    summary: str,
    detail: str,
    *,
    prior: str = '',
) -> None:
    detail_esc = (detail or '(无输出)').strip()
    if len(detail_esc) > 12_000:
        detail_esc = detail_esc[:12_000] + '\n… (已截断)'
    prior_block = f'\n\n[dim]此前截图阶段: {prior}[/dim]' if prior else ''
    body = (
        f'[bold #f87171]{summary}[/bold #f87171]\n\n'
        f'[dim]{detail_esc}[/dim]'
        f'{prior_block}'
    )
    _emit_fatal_panel(console, body)
    raise BrowserVisionFatalInstallError(f'[BrowserVision] {summary}')


def _is_chromium_launch_failure(exc: BrowserVisionError) -> bool:
    return '无法启动 Chromium' in str(exc)


def _format_nav_error(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc).strip() or '(无详情)'
    if 'Timeout' in name or 'timeout' in msg.lower():
        return (
            f'[BrowserVision] 页面加载超时（{_DEFAULT_NAV_TIMEOUT_MS // 1000}s，wait_until=domcontentloaded）: {msg}'
        )
    if 'net::' in msg.lower() or 'navigation' in name.lower():
        return f'[BrowserVision] 导航失败（URL 不可达或证书等问题）: {msg}'
    return f'[BrowserVision] 打开页面失败: {name}: {msg}'


def _capture_with_playwright_impl(
    sync_playwright: Any,
    normalized: str,
    out_file: Path,
    console: Any | None,
) -> Path:
    """Playwright 无头 Chromium 仅截取 **网页 DOM**；成功返回绝对路径。"""
    try:
        with _rich_status(console, '📸 正在捕获网页快照…'):
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as exc:
                    raise BrowserVisionError(
                        f'[BrowserVision] 无法启动 Chromium: {type(exc).__name__}: {exc}'
                    ) from exc

                try:
                    page = browser.new_page(viewport=_VIEWPORT)
                    page.set_default_navigation_timeout(_DEFAULT_NAV_TIMEOUT_MS)
                    page.set_default_timeout(_DEFAULT_NAV_TIMEOUT_MS)
                    try:
                        page.goto(
                            normalized,
                            wait_until='domcontentloaded',
                            timeout=_DEFAULT_NAV_TIMEOUT_MS,
                        )
                    except Exception as exc:
                        raise BrowserVisionError(_format_nav_error(exc)) from exc

                    time.sleep(_POST_DOM_LOAD_PAUSE_SEC)

                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        page.screenshot(
                            path=str(out_file),
                            full_page=True,
                            type='png',
                        )
                    except OSError as exc:
                        raise BrowserVisionError(
                            f'[BrowserVision] 无法写入截图文件: {type(exc).__name__}: {exc}'
                        ) from exc
                    except Exception as exc:
                        raise BrowserVisionError(
                            f'[BrowserVision] 截图失败: {type(exc).__name__}: {exc}'
                        ) from exc
                finally:
                    browser.close()
    except BrowserVisionError:
        raise
    except Exception as exc:
        raise BrowserVisionError(
            f'[BrowserVision] Playwright 异常: {type(exc).__name__}: {exc}'
        ) from exc

    resolved = out_file.resolve()
    if not resolved.is_file():
        raise BrowserVisionError(
            '[BrowserVision] 截图文件未生成，请检查磁盘权限与 ~/.scream/screenshots 目录。'
        )
    root = _screenshots_root().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrowserVisionError('[BrowserVision] 内部错误: 截图未写入受控目录。') from exc
    return resolved


class BrowserVisionEngine:
    """
    基于 Playwright Chromium（**无头**）的整页 **网页 DOM** 截图。

    - **绝不**使用系统原生截屏（screencapture / ImageGrab / pyautogui 等）。
    - 输出 **仅** 写入 ``~/.scream/screenshots/``。
    """

    def capture_page(
        self,
        url: str,
        *,
        console: Any | None = None,
    ) -> str:
        """
        打开 ``url`` 并保存整页截图。

        Returns:
            成功时为 ``~/.scream/screenshots/`` 下文件的绝对路径字符串。

        Raises:
            BrowserVisionFatalInstallError: 自动安装失败（已绘制 Fatal Panel）。
            BrowserVisionError: URL 非法、导航失败、截图失败等。
        """
        normalized = _normalize_url(url)
        out_file = _allocate_capture_path()

        sync_pw = _try_import_sync_playwright()
        if sync_pw is None:
            code, detail = _pip_install_playwright(console)
            if code != 0:
                _fatal_install_raise(
                    console,
                    '自动安装 playwright（pip）失败',
                    detail or f'退出码 {code}',
                )
            _invalidate_playwright_modules()
            sync_pw = _try_import_sync_playwright()
            if sync_pw is None:
                _fatal_install_raise(
                    console,
                    'playwright 已安装但仍无法导入 sync_playwright',
                    '请确认当前进程使用的 Python 与 pip 目标环境一致。',
                )

        try:
            path = _capture_with_playwright_impl(
                sync_pw, normalized, out_file, console
            )
        except BrowserVisionError as first:
            if not _is_chromium_launch_failure(first):
                raise
            code, detail = _playwright_install_chromium(console)
            if code != 0:
                _fatal_install_raise(
                    console,
                    '自动安装 Chromium 内核失败',
                    detail or f'退出码 {code}',
                    prior=str(first),
                )
            path = _capture_with_playwright_impl(
                sync_pw, normalized, out_file, console
            )
        return str(path)


__all__ = [
    'BrowserVisionEngine',
    'BrowserVisionError',
    'BrowserVisionFatalInstallError',
    '_normalize_url',
    '_allocate_capture_path',
]
