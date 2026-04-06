from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeModeReport:
    mode: str
    connected: bool
    detail: str

    def as_text(self) -> str:
        connected_zh = '是' if self.connected else '否'
        return f'模式={self.mode}\n已连接={connected_zh}\n详情={self.detail}'


def run_remote_mode(target: str) -> RuntimeModeReport:
    return RuntimeModeReport('remote', True, f'已为「{target}」准备远程控制占位实现')


def run_ssh_mode(target: str) -> RuntimeModeReport:
    return RuntimeModeReport('ssh', True, f'已为「{target}」准备 SSH 代理占位实现')


def run_teleport_mode(target: str) -> RuntimeModeReport:
    return RuntimeModeReport('teleport', True, f'已为「{target}」准备 Teleport 恢复/创建占位实现')
