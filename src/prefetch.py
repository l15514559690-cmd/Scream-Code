from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrefetchResult:
    name: str
    started: bool
    detail: str


def start_mdm_raw_read() -> PrefetchResult:
    return PrefetchResult('mdm_raw_read', True, '为工作区引导模拟 MDM 原始读取预取')


def start_keychain_prefetch() -> PrefetchResult:
    return PrefetchResult('keychain_prefetch', True, '为受信任启动路径模拟钥匙串预取')


def start_project_scan(root: Path) -> PrefetchResult:
    return PrefetchResult('project_scan', True, f'已扫描项目根目录 {root}')
