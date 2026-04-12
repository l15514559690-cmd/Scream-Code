from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from xml.sax.saxutils import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_MAX_KEY_LEN = 128
_MAX_CONTENT_LEN = 500_000


def memory_db_path() -> Path:
    """``~/.scream/memory.db``；测试可设环境变量 ``SCREAM_MEMORY_DB`` 覆盖。"""
    raw = os.environ.get('SCREAM_MEMORY_DB', '').strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / '.scream' / 'memory.db'


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_key(key_name: str) -> tuple[str | None, str | None]:
    s = (key_name or '').strip()
    if not s:
        return None, 'key_name 不能为空。'
    if len(s) > _MAX_KEY_LEN:
        return None, f'key_name 长度不得超过 {_MAX_KEY_LEN}。'
    if '\x00' in s:
        return None, 'key_name 含非法字符。'
    return s, None


def _validate_content(content: str) -> tuple[str | None, str | None]:
    if not isinstance(content, str):
        return None, 'content 必须为字符串。'
    s = content.strip()
    if not s:
        return None, 'content 不能为空（去空白后）。'
    if len(content) > _MAX_CONTENT_LEN:
        return None, f'content 长度不得超过 {_MAX_CONTENT_LEN}。'
    return content, None


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = memory_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS core_memory (
                key_name TEXT PRIMARY KEY NOT NULL,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        yield conn
    finally:
        conn.close()


def memorize_core_rule(key_name: str, content: str) -> str:
    """
    写入或覆盖一条核心长期记忆（架构决策、开发规范、用户偏好等）。

    Returns:
        成功说明；参数非法时返回 ``[错误]`` 前缀的短句。
    """
    k, err = _validate_key(key_name)
    if err:
        return f'[错误] {err}'
    c, err = _validate_content(content)
    if err:
        return f'[错误] {err}'
    ts = _utc_now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO core_memory (key_name, content, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key_name) DO UPDATE SET
                content = excluded.content,
                updated_at = excluded.updated_at
            """,
            (k, c, ts),
        )
        conn.commit()
    return f'已记入长期记忆库 [{k}]（{memory_db_path()}）。'


def forget_core_rule(key_name: str) -> str:
    """按 key 删除一条规则；不存在则返回提示。"""
    k, err = _validate_key(key_name)
    if err:
        return f'[错误] {err}'
    with _connect() as conn:
        cur = conn.execute('DELETE FROM core_memory WHERE key_name = ?', (k,))
        conn.commit()
        if cur.rowcount == 0:
            return f'[提示] 未找到键 {k!r}，无需删除。'
    return f'已从长期记忆库删除 [{k}]。'


def get_core_rule(key_name: str) -> str | None:
    """按 key 读取正文；不存在返回 ``None``。"""
    k, err = _validate_key(key_name)
    if err:
        return None
    with _connect() as conn:
        row = conn.execute(
            'SELECT content FROM core_memory WHERE key_name = ?', (k,)
        ).fetchone()
    if row is None:
        return None
    return str(row['content'])


def list_core_rules() -> list[dict[str, str]]:
    """列出全部键、更新时间（供系统提示词注入等）。"""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT key_name, content, updated_at FROM core_memory ORDER BY key_name'
        ).fetchall()
    return [
        {'key_name': str(r['key_name']), 'content': str(r['content']), 'updated_at': str(r['updated_at'])}
        for r in rows
    ]


def format_project_long_term_memory_xml_block() -> str:
    """
    将 ``core_memory`` 全量格式化为 ``<Project_LongTerm_Memory>`` XML 块，供拼入系统提示词末尾。
    无记录或读库失败时返回空串。
    """
    try:
        rows = list_core_rules()
    except (OSError, sqlite3.Error):
        return ''
    if not rows:
        return ''

    def _attr(s: str) -> str:
        return escape(s, {'"': '&quot;', "'": '&apos;'})

    lines = [
        '<Project_LongTerm_Memory>',
        '<!-- 长期项目记忆（SQLite ~/.scream/memory.db）；由 memorize_project_rule / REPL /memory 维护 -->',
        '',
    ]
    for r in rows:
        k = _attr(r['key_name'])
        ts = _attr(r['updated_at'])
        body = escape(r['content'])
        lines.append(f'<entry key="{k}" updated_at="{ts}">')
        lines.append(body)
        lines.append('</entry>')
        lines.append('')
    lines.append('</Project_LongTerm_Memory>')
    return '\n'.join(lines)
