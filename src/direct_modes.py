from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectModeReport:
    mode: str
    target: str
    active: bool

    def as_text(self) -> str:
        active_zh = '是' if self.active else '否'
        return f'模式={self.mode}\n目标={self.target}\n已激活={active_zh}'


def run_direct_connect(target: str) -> DirectModeReport:
    return DirectModeReport(mode='direct-connect', target=target, active=True)


def run_deep_link(target: str) -> DirectModeReport:
    return DirectModeReport(mode='deep-link', target=target, active=True)
