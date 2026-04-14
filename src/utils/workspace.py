from __future__ import annotations

import hashlib
import os
from pathlib import Path


def get_workspace_root() -> Path:
    """
    以当前运行目录为起点向上回溯，寻找包含 ``.git`` 的工作区根目录。
    若未找到，则回退为当前目录。
    """
    current = Path(os.getcwd()).expanduser().resolve()
    probe = current
    while True:
        if (probe / '.git').exists():
            return probe
        parent = probe.parent
        if parent == probe:
            return current
        probe = parent


def get_workspace_id(root: Path | None = None) -> str:
    """
    根据工作区绝对路径计算稳定 ID（MD5 前 12 位）。
    """
    ws_root = (root or get_workspace_root()).expanduser().resolve()
    digest = hashlib.md5(str(ws_root).encode('utf-8')).hexdigest()
    return digest[:12]


def get_workspace_data_root(root: Path | None = None) -> Path:
    """
    返回当前工作区隔离数据根目录：``~/.screamcode/workspaces/{workspace_id}``。
    """
    ws_root = root or get_workspace_root()
    return Path.home() / '.screamcode' / 'workspaces' / get_workspace_id(ws_root)
