from __future__ import annotations

from dataclasses import dataclass

from .models import PortingModule
from .permissions import ToolPermissionContext
from .tools import get_tools


@dataclass(frozen=True)
class ToolPool:
    tools: tuple[PortingModule, ...]
    simple_mode: bool
    include_mcp: bool

    def as_markdown(self) -> str:
        lines = [
            '# 工具池',
            '',
            f'精简模式: {"是" if self.simple_mode else "否"}',
            f'包含 MCP: {"是" if self.include_mcp else "否"}',
            f'镜像清单工具数量: {len(self.tools)}',
        ]
        lines.extend(f'- {tool.name} — {tool.source_hint}' for tool in self.tools[:15])
        lines.extend(_runtime_tools_registry_section())
        return '\n'.join(lines)


def _runtime_tools_registry_section() -> list[str]:
    """与 LLM ``tools`` 同源的 ToolsRegistry 面，挂接在 tool-pool 输出末尾。"""
    out: list[str] = [
        '',
        '## 运行时 Agent 工具（ToolsRegistry，与 claw-code 镜像 tool 路由并列展示）',
        '',
    ]
    try:
        from .tools_registry import get_tools_registry

        for row in get_tools_registry().list_tool_rows()[:40]:
            src = row.get('source') or '—'
            name = row.get('name') or ''
            desc = (row.get('description') or '')[:100]
            out.append(f'- `{name}` — {desc}')
            out.append(f'  - 来源: {src}')
    except Exception:  # pragma: no cover - 导入环或坏配置
        out.append('（运行时技能表暂不可用）')
    return out


def assemble_tool_pool(
    simple_mode: bool = False,
    include_mcp: bool = True,
    permission_context: ToolPermissionContext | None = None,
) -> ToolPool:
    return ToolPool(
        tools=get_tools(simple_mode=simple_mode, include_mcp=include_mcp, permission_context=permission_context),
        simple_mode=simple_mode,
        include_mcp=include_mcp,
    )
