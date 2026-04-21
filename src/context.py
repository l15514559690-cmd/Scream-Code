from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .utils.workspace import get_workspace_root


@dataclass(frozen=True)
class PortContext:
    source_root: Path
    tests_root: Path
    assets_root: Path
    archive_root: Path
    python_file_count: int
    test_file_count: int
    asset_file_count: int
    archive_available: bool


def build_port_context(base: Path | None = None) -> PortContext:
    root = base or get_workspace_root()
    source_root = root / 'src'
    tests_root = root / 'tests'
    assets_root = root / 'assets'
    archive_root = root / 'archive' / 'claude_code_ts_snapshot' / 'src'
    return PortContext(
        source_root=source_root,
        tests_root=tests_root,
        assets_root=assets_root,
        archive_root=archive_root,
        python_file_count=sum(1 for path in source_root.rglob('*.py') if path.is_file()),
        test_file_count=sum(1 for path in tests_root.rglob('*.py') if path.is_file()),
        asset_file_count=sum(1 for path in assets_root.rglob('*') if path.is_file()),
        archive_available=archive_root.exists(),
    )


def render_context(context: PortContext) -> str:
    return '\n'.join([
        f'源码根目录: {context.source_root}',
        f'测试根目录: {context.tests_root}',
        f'资源根目录: {context.assets_root}',
        f'归档根目录: {context.archive_root}',
        f'Python 文件数: {context.python_file_count}',
        f'测试文件数: {context.test_file_count}',
        f'资源文件数: {context.asset_file_count}',
        f'归档可用: {"是" if context.archive_available else "否"}',
    ])
