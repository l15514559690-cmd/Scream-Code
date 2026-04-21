from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

# ------------------------------------------------------------
# 快照管理器 (Snapshot Manager)
# 提供文件修改前的备份与一键回滚能力，支持 /undo 斜杠命令。
# ------------------------------------------------------------

# 快照存储根目录（位于工作区 .scream_cache/undo_snapshots/ 下）
UNDO_SNAPSHOTS_DIR = '.scream_cache/undo_snapshots'
MANIFEST_NAME = 'manifest.json'


def _snapshot_root(workspace_root: Path) -> Path:
    return (workspace_root / UNDO_SNAPSHOTS_DIR).resolve()


def _manifest_path(workspace_root: Path) -> Path:
    return _snapshot_root(workspace_root) / MANIFEST_NAME


def _backup_name(original_path: Path, workspace_root: Path) -> str:
    """
    根据原始文件的相对路径生成备份文件名。
    使用完整绝对路径的 MD5 前 16 位做散列，避免路径冲突且保证确定性。
    """
    key = original_path.resolve().as_posix()
    digest = hashlib.md5(key.encode('utf-8')).hexdigest()[:16]
    return f'{digest}_{original_path.name}'


# ------------------------------------------------------------
# 公开 API
# ------------------------------------------------------------


def backup_file_before_edit(file_path: Path, workspace_root: Path) -> None:
    """
    在文件被修改前调用：将目标文件拷贝到快照目录。

    - 若文件存在 → 拷贝到 undo_snapshots/ 下（同名 MD5 哈希文件名）。
    - 若文件不存在 → 在 manifest 中记录为一个 "marker"（待创建文件）。

    manifest 格式（列表，每项一个 JSON 对象）:
        {
          "original": "/abs/path/to/file.txt",
          "backup": "/abs/path/to/backup/file.txt",   # 或 null（marker）
          "existed": true,
          "backup_name": "xxxx_filename"
        }
    """
    root = workspace_root.resolve()
    snap_root = _snapshot_root(root)
    snap_root.mkdir(parents=True, exist_ok=True)

    manifest_path = _manifest_path(root)
    manifest: list[dict[str, Any]] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            manifest = []

    abs_path = file_path.resolve()
    backup_name = _backup_name(abs_path, root)
    backup_path = snap_root / backup_name

    entry: dict[str, Any] = {
        'original': abs_path.as_posix(),
        'backup': None,
        'existed': False,
        'backup_name': backup_name,
    }

    if abs_path.is_file():
        shutil.copy2(abs_path, backup_path)
        entry['backup'] = backup_path.as_posix()
        entry['existed'] = True

    # 去重（同一文件多次写入只保留最新备份）
    manifest = [e for e in manifest if e.get('original') != abs_path.as_posix()]
    manifest.append(entry)

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def restore_last_snapshot(workspace_root: Path) -> list[str]:
    """
    读取 manifest，将所有备份文件覆盖回原始路径，
    并删除 manifest 记录中"待创建"的新文件 marker，
    最后清空快照目录。

    Returns:
        被恢复/删除的文件路径列表（字符串）。
    """
    root = workspace_root.resolve()
    manifest_path = _manifest_path(root)

    if not manifest_path.exists():
        return []

    try:
        manifest: list[dict[str, Any]] = json.loads(
            manifest_path.read_text(encoding='utf-8')
        )
    except (OSError, json.JSONDecodeError):
        return []

    restored: list[str] = []

    for entry in manifest:
        orig = entry.get('original', '')
        backup = entry.get('backup')
        existed = entry.get('existed', False)

        if not orig:
            continue

        orig_p = Path(orig)
        if existed and backup:
            bp = Path(backup)
            if bp.is_file():
                try:
                    shutil.copy2(bp, orig_p)
                    restored.append(orig)
                except OSError:
                    pass
        else:
            # Agent 新建的文件（marker），撤销时删除
            if orig_p.is_file():
                try:
                    orig_p.unlink()
                    restored.append(orig)
                except OSError:
                    pass

    # 清空快照目录
    snap_root = _snapshot_root(root)
    if snap_root.is_dir():
        try:
            shutil.rmtree(snap_root)
        except OSError:
            pass

    return restored


def clear_snapshot(workspace_root: Path) -> None:
    """
    仅清空快照目录（不清除 manifest），在每轮开始时调用，
    保证 /undo 总是只撤销"最近一次"的修改。
    """
    snap_root = _snapshot_root(workspace_root)
    if snap_root.is_dir():
        try:
            shutil.rmtree(snap_root)
        except OSError:
            pass
    elif snap_root.is_file():
        try:
            snap_root.unlink()
        except OSError:
            pass
