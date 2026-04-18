from __future__ import annotations

import hashlib
import os
from pathlib import Path

# ------------------------------------------------------------
# 轻量级代码地图生成器 (Repo Map Generator)
# ------------------------------------------------------------

# 目录遍历黑名单：防止 Token 爆炸
_REPO_MAP_EXCLUDE_DIRS = frozenset({
    '.git',
    'node_modules',
    '__pycache__',
    'venv',
    '.venv',
    'target',
    'dist',
    'build',
    '.scream_cache',
    '.idea',
    '.vscode',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    '.tox',
    '.nox',
    'site-packages',
    'eggs',
    '*.egg-info',
})

# 项目根目录可保留的配置文件（即使以 . 开头）
_REPO_MAP_ALLOW_ROOT_DOTFILES = frozenset({
    '.env.example',
    '.env.local',
    '.claw.json',
    '.editorconfig',
    '.gitignore',
    '.gitattributes',
})

_MAX_REPO_MAP_CHARS = 8000


def generate_lightweight_repo_map(workspace_root: Path, max_depth: int = 3) -> str:
    """
    生成类似 ``tree`` 命令的轻量级目录树字符串，用于注入 System Prompt。

    - 递归遍历目录，最大深度 ``max_depth``。
    - 跳过黑名单目录和所有以 ``.`` 开头的目录（项目根下白名单配置文件除外）。
    - 若输出超过约 8000 字符则强制截断并追加提示。

    Args:
        workspace_root: 工作区根目录。
        max_depth: 最大递归深度，默认 3 层。

    Returns:
        树状目录结构字符串。
    """
    root = workspace_root.expanduser().resolve()
    if not root.is_dir():
        return f'（工作区根目录不存在或不是文件夹: {root}）'

    lines: list[str] = []
    indent_str = '│   '
    bullet_char = '├── '
    last_char = '└── '

    def _format_entry(name: str, is_last: bool) -> str:
        return (last_char if is_last else bullet_char) + name

    def _walk(
        dir_path: Path,
        depth: int,
        prefix: str,
        allow_root_dotfiles: bool,
    ) -> None:
        try:
            entries = list(dir_path.iterdir())
        except PermissionError:
            lines.append(prefix + '[权限拒绝]')
            return
        except OSError as exc:
            lines.append(prefix + f'[读取失败: {exc}]')
            return

        # 过滤黑名单目录和隐藏目录
        filtered: list[tuple[Path, bool, bool]] = []
        for p in entries:
            name = p.name
            is_dir = p.is_dir()
            is_dotfile = name.startswith('.') and name not in _REPO_MAP_ALLOW_ROOT_DOTFILES

            if is_dotfile and depth > 0:
                continue
            if name in _REPO_MAP_EXCLUDE_DIRS:
                continue
            filtered.append((p, is_dir, is_dotfile and depth == 0))

        filtered.sort(key=lambda x: (not x[1], x[0].name.lower()))

        for idx, (path, is_dir, _) in enumerate(filtered):
            is_last = idx == len(filtered) - 1
            lines.append(prefix + _format_entry(path.name + ('/' if is_dir else ''), is_last))
            if is_dir and depth < max_depth:
                extension = indent_str if not is_last else '    '
                _walk(path, depth + 1, prefix + extension, allow_root_dotfiles=False)

    lines.append(root.name + '/')
    _walk(root, depth=0, prefix='', allow_root_dotfiles=True)

    result = '\n'.join(lines)
    if len(result) > _MAX_REPO_MAP_CHARS:
        result = result[:_MAX_REPO_MAP_CHARS] + f'\n… [目录树过长已截断，原始长度 {len(result)} 字符] …'
    return result


# ------------------------------------------------------------
# 原有的工作区工具函数
# ------------------------------------------------------------

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
