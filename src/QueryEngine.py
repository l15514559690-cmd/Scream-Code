from __future__ import annotations

from .query_engine import QueryEnginePort
from .runtime import PortRuntime


class QueryEngineRuntime(QueryEnginePort):
    def route(self, prompt: str, limit: int = 5) -> str:
        matches = PortRuntime().route_prompt(prompt, limit=limit)
        lines = ['# 查询引擎路由', '', f'提示: {prompt}', '']
        if not matches:
            lines.append('未发现镜像的命令/工具匹配项。')
            return '\n'.join(lines)
        lines.append('匹配结果:')
        lines.extend(f'- [{match.kind}] {match.name} ({match.score}) — {match.source_hint}' for match in matches)
        return '\n'.join(lines)


__all__ = ['QueryEnginePort', 'QueryEngineRuntime']
