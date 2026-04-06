from __future__ import annotations

from pathlib import Path

# 按优先级依次尝试（仅使用 Path.cwd() 下首个可读且非空白的文件）
PROJECT_MEMORY_FILENAMES: tuple[str, ...] = ('SCREAM.md', 'CLAUDE.md', '.cursorrules')
MAX_INJECT_CHARS = 80_000


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
    """供 ``build_system_init_message`` 追加的片段；无可用文件时为空串。"""
    name, body = read_first_available_project_memory(cwd)
    if not name or body is None:
        return ''
    return format_project_memory_system_suffix(body)
