from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredSession:
    session_id: str
    messages: tuple[str, ...]
    input_tokens: int
    output_tokens: int


DEFAULT_SESSION_DIR = Path('.port_sessions')


def save_session(session: StoredSession, directory: Path | None = None) -> Path:
    target_dir = directory or DEFAULT_SESSION_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'{session.session_id}.json'
    path.write_text(json.dumps(asdict(session), indent=2))
    return path


def load_session(session_id: str, directory: Path | None = None) -> StoredSession:
    target_dir = directory or DEFAULT_SESSION_DIR
    data = json.loads((target_dir / f'{session_id}.json').read_text())
    return StoredSession(
        session_id=data['session_id'],
        messages=tuple(data['messages']),
        input_tokens=data['input_tokens'],
        output_tokens=data['output_tokens'],
    )


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
    target_dir = directory or DEFAULT_SESSION_DIR
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
