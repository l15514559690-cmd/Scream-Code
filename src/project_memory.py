from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# 按优先级依次尝试（仅使用 Path.cwd() 下首个可读且非空白的文件）
PROJECT_MEMORY_FILENAMES: tuple[str, ...] = ('SCREAM.md', 'CLAUDE.md', '.cursorrules')
MAX_INJECT_CHARS = 320_000


def project_memory_workspace_root() -> Path:
    """
    查找项目记忆文件时使用的根目录：与会话落盘、文件类工具一致，
    优先 ``SCREAM_WORKSPACE_ROOT``，否则为进程当前工作目录。
    """
    raw = os.environ.get('SCREAM_WORKSPACE_ROOT', '').strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def read_first_available_project_memory(cwd: Path | None = None) -> tuple[str | None, str | None]:
    """
    在当前工作目录下按优先级查找项目记忆文件。

    Returns:
        (文件名, 正文)；若均不存在、不可读或正文去空白后为空则返回 (None, None)。
    """
    base = (cwd if cwd is not None else Path.cwd()).resolve()
    for name in PROJECT_MEMORY_FILENAMES:
        path = base / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        if len(text) > MAX_INJECT_CHARS:
            text = text[:MAX_INJECT_CHARS] + '\n\n…(项目记忆文件过长，已截断)…'
        return name, text
    return None, None


def format_project_memory_system_suffix(body: str) -> str:
    """拼接到系统提示词末尾的固定格式。"""
    return (
        f'\n\n<project_memory>\n{body}\n</project_memory>\n'
        '请在接下来的对话中严格遵守以上项目记忆与规则。'
    )


def project_memory_system_suffix(cwd: Path | None = None) -> str:
    """
    供 ``build_system_init_message`` 追加的片段；无可用文件时为空串。

    ``cwd`` 为 ``None`` 时使用 :func:`project_memory_workspace_root`（尊重
    ``SCREAM_WORKSPACE_ROOT``），避免在安装目录启动时读不到项目下 SCREAM.md。
    """
    base = project_memory_workspace_root() if cwd is None else cwd
    name, body = read_first_available_project_memory(base)
    if not name or body is None:
        return ''
    return format_project_memory_system_suffix(body)


# REPL ``/memo``、``/summary`` 追加块使用的稳定小节锚点（便于人工检索，不替换整文件）
LONG_TERM_MEMORY_SECTION_HEADING = '## 长效记忆库 · 尖叫 REPL'


def long_term_memory_target_path(cwd: Path | None = None) -> Path:
    """
    写入长效记忆时的目标文件：优先已有 ``SCREAM.md``，否则已有 ``CLAUDE.md``，否则新建 ``SCREAM.md``。
    仅追加，不覆盖用户原有正文结构。
    """
    base = (cwd if cwd is not None else project_memory_workspace_root()).resolve()
    scream = base / 'SCREAM.md'
    claude = base / 'CLAUDE.md'
    if scream.is_file():
        return scream
    if claude.is_file():
        return claude
    return scream


def append_long_term_memory_block(
    body: str,
    *,
    cwd: Path | None = None,
    source_tag: str = '/memo',
) -> str:
    """
    将 ``body`` 以独立小节追加到项目记忆文件（Markdown）。

    Returns:
        成功时为简短说明；失败时为可读错误信息（不抛异常）。
    """
    raw = (body or '').strip()
    if not raw:
        return '无内容可写入。'
    path = long_term_memory_target_path(cwd)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    block = (
        f'\n\n---\n\n{LONG_TERM_MEMORY_SECTION_HEADING}（`{source_tag}` · {stamp}）\n\n{raw}\n'
    )
    try:
        existing = path.read_text(encoding='utf-8') if path.is_file() else ''
    except (OSError, UnicodeDecodeError) as exc:
        return f'读取现有文件失败: {exc}'
    sep = '\n\n' if existing and not existing.endswith('\n') else ''
    new_text = f'{existing}{sep}{block.lstrip()}' if existing else block.lstrip()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding='utf-8')
    except OSError as exc:
        return f'写入失败: {exc}'
    return f'已安全追加至 {path.name}（{path}）。'
