from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapGraph:
    stages: tuple[str, ...]

    def as_markdown(self) -> str:
        lines = ['# 引导流程图', '']
        lines.extend(f'- {stage}' for stage in self.stages)
        return '\n'.join(lines)


def build_bootstrap_graph() -> BootstrapGraph:
    return BootstrapGraph(
        stages=(
            '顶层预取副作用',
            '警告处理与环境防护',
            'CLI 解析与执行前受信任门控',
            'setup() 与命令/智能体并行加载',
            '受信任通过后的延迟初始化',
            '模式路由：本地 / 远程 / SSH / Teleport / 直连 / 深度链接',
            '查询引擎提交循环',
        )
    )
