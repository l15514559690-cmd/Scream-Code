from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from .deferred_init import DeferredInitResult, run_deferred_init
from .prefetch import PrefetchResult, start_keychain_prefetch, start_mdm_raw_read, start_project_scan


@dataclass(frozen=True)
class WorkspaceSetup:
    python_version: str
    implementation: str
    platform_name: str
    test_command: str = 'python3 -m unittest discover -s tests -v'

    def startup_steps(self) -> tuple[str, ...]:
        return (
            '启动顶层预取副作用',
            '构建工作区上下文',
            '加载镜像命令快照',
            '加载镜像工具快照',
            '准备一致性审计钩子',
            '在受信任门控下应用延迟初始化',
        )


@dataclass(frozen=True)
class SetupReport:
    setup: WorkspaceSetup
    prefetches: tuple[PrefetchResult, ...]
    deferred_init: DeferredInitResult
    trusted: bool
    cwd: Path

    def as_markdown(self) -> str:
        lines = [
            '# 启动报告',
            '',
            f'- Python: {self.setup.python_version} ({self.setup.implementation})',
            f'- 平台: {self.setup.platform_name}',
            f'- 受信任模式: {"是" if self.trusted else "否"}',
            f'- 工作目录: {self.cwd}',
            '',
            '预取:',
            *(f'- {prefetch.name}: {prefetch.detail}' for prefetch in self.prefetches),
            '',
            '延迟初始化:',
            *self.deferred_init.as_lines(),
        ]
        return '\n'.join(lines)


def build_workspace_setup() -> WorkspaceSetup:
    return WorkspaceSetup(
        python_version='.'.join(str(part) for part in sys.version_info[:3]),
        implementation=platform.python_implementation(),
        platform_name=platform.platform(),
    )


def run_setup(cwd: Path | None = None, trusted: bool = True) -> SetupReport:
    root = cwd or Path(__file__).resolve().parent.parent
    prefetches = [
        start_mdm_raw_read(),
        start_keychain_prefetch(),
        start_project_scan(root),
    ]
    return SetupReport(
        setup=build_workspace_setup(),
        prefetches=tuple(prefetches),
        deferred_init=run_deferred_init(trusted=trusted),
        trusted=trusted,
        cwd=root,
    )
