from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def workspace_root_for_sessions() -> Path:
    """与 ``agent_tools`` 工作区一致：用于 ``.scream/`` 索引路径。"""
    raw = os.environ.get('SCREAM_WORKSPACE_ROOT', '').strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def _write_scream_sessions_index(session_id: str, session_path: Path) -> None:
    """在工作区根写入 ``.scream/sessions.json``，便于发现最近会话（与 ``.port_sessions`` 并存）。"""
    root = workspace_root_for_sessions()
    scream = root / '.scream'
    try:
        scream.mkdir(parents=True, exist_ok=True)
        rows = list_saved_session_entries(limit=48)
        payload = {
            'version': 1,
            'latest_session_id': session_id,
            'latest_session_path': str(session_path.resolve()),
            'sessions': [
                {
                    'id': sid,
                    'user_messages': n,
                    'input_tokens': it,
                    'output_tokens': ot,
                    'path': str(p.resolve()),
                }
                for sid, n, it, ot, p in rows
            ],
        }
        (scream / 'sessions.json').write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8',
        )
    except OSError:
        pass


@dataclass(frozen=True)
class StoredSession:
    session_id: str
    messages: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    #: 发往 LLM 的完整消息快照（含 assistant / tool）；可能经上下文折叠缩短；旧版 JSON 无此字段则为空。
    llm_conversation_messages: tuple[dict[str, Any], ...] = ()
    #: 全局浏览器MCP模式：开启后优先要求模型调用 Browser MCP 浏览器/搜索工具。
    mcp_online_mode: bool = False


def resolve_session_dir(explicit: Path | None = None) -> Path:
    """
    会话目录：显式参数优先；否则若设置 ``SCREAM_WORKSPACE_ROOT`` 则使用该路径下的
    ``.port_sessions``（与读写文件类工具的工作区一致）；否则为当前工作目录下的
    ``.port_sessions``。
    """
    if explicit is not None:
        return explicit
    raw = os.environ.get('SCREAM_WORKSPACE_ROOT', '').strip()
    if raw:
        return Path(raw).expanduser().resolve() / '.port_sessions'
    return Path.cwd() / '.port_sessions'


def save_session(session: StoredSession, directory: Path | None = None) -> Path:
    target_dir = directory or resolve_session_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'{session.session_id}.json'
    path.write_text(
        json.dumps(asdict(session), indent=2, ensure_ascii=False, default=str),
        encoding='utf-8',
    )
    _write_scream_sessions_index(session.session_id, path)
    return path


def load_session(session_id: str, directory: Path | None = None) -> StoredSession:
    """读取会话 JSON；纯 I/O + 反序列化，不触发大模型或 REPL 回合。"""
    target_dir = directory or resolve_session_dir()
    data = json.loads((target_dir / f'{session_id}.json').read_text(encoding='utf-8'))
    raw_llm = data.get('llm_conversation_messages')
    llm_conv: tuple[dict[str, Any], ...] = ()
    if isinstance(raw_llm, list):
        llm_conv = tuple(m for m in raw_llm if isinstance(m, dict))
    return StoredSession(
        session_id=data['session_id'],
        messages=tuple(data['messages']),
        input_tokens=data['input_tokens'],
        output_tokens=data['output_tokens'],
        llm_conversation_messages=llm_conv,
        mcp_online_mode=bool(data.get('mcp_online_mode', False)),
    )


def session_exists(session_id: str, directory: Path | None = None) -> bool:
    """会话文件是否存在（仅文件层检查，不触发反序列化）。"""
    target_dir = directory or resolve_session_dir()
    return (target_dir / f'{session_id}.json').is_file()


def list_saved_session_entries(
    directory: Path | None = None,
    *,
    limit: int = 64,
) -> list[tuple[str, int, int, int, Path]]:
    """
    扫描本地会话目录，按修改时间新到旧排序。

    Returns:
        ``(session_id, message_count, input_tokens, output_tokens, path)`` 列表。
    """
    target_dir = directory or resolve_session_dir()
    if not target_dir.is_dir():
        return []
    rows: list[tuple[str, int, int, int, Path]] = []
    for path in sorted(target_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[
        :limit
    ]:
        sid = path.stem
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            msgs = data.get('messages', [])
            n = len(msgs) if isinstance(msgs, list) else 0
            it = int(data.get('input_tokens', 0) or 0)
            ot = int(data.get('output_tokens', 0) or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            n, it, ot = -1, 0, 0
        rows.append((sid, n, it, ot, path))
    return rows


def most_recent_saved_session_id(directory: Path | None = None) -> str | None:
    """
    返回最近会话 ``session_id``：优先 ``.port_sessions/*.json`` 按 mtime；
    若目录为空则回读工作区 ``.scream/sessions.json`` 中的 ``latest_session_id``（文件仍存在时）。
    """
    entries = list_saved_session_entries(directory=directory, limit=1)
    if entries:
        sid, n, _, _, _ = entries[0]
        if n >= 0:
            return sid
    target_dir = directory or resolve_session_dir()
    idx = workspace_root_for_sessions() / '.scream' / 'sessions.json'
    if not idx.is_file():
        return None
    try:
        data = json.loads(idx.read_text(encoding='utf-8'))
        sid = str(data.get('latest_session_id') or '').strip()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not sid or not (target_dir / f'{sid}.json').is_file():
        return None
    return sid
