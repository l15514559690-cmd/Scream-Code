from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .llm_settings import project_root


def _project_tool_plugins_dir() -> Path:
    """项目根 ``skills/*.py``：LLM ``function calling`` 动态插件（非 REPL 斜杠技能）。"""
    d = project_root() / 'skills'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tool_name_from_schema(schema: dict[str, Any]) -> str | None:
    try:
        fn = schema.get('function')
        if isinstance(fn, dict):
            name = str(fn.get('name', '')).strip()
            return name or None
    except (TypeError, AttributeError):
        pass
    return None


class ToolsRegistry:
    """
    **Agent 工具注册表（LLM function calling 单一事实来源）**

    与 **claw-code 镜像工具池**（``tool_pool``）的关系：镜像侧条目来自归档元数据；本注册表提供
    实际可调用的 schema 与 ``execute_tool``，并在 ``tool_pool`` 附录中汇总展示。

    动态插件：项目根 ``skills/*.py`` 导出 ``TOOL_SCHEMA`` + ``execute(**kwargs)``。
    """

    def __init__(self) -> None:
        self._schemas: list[dict[str, Any]] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], str]] = {}
        self._sources: dict[str, str] = {}

    def reload_all(self) -> None:
        self._schemas.clear()
        self._handlers.clear()
        self._sources.clear()
        self._register_builtin_tools()
        self._load_dynamic_tool_modules()

    def _register_one(
        self,
        schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], str],
        *,
        source: str,
        allow_override: bool = False,
    ) -> None:
        name = _tool_name_from_schema(schema)
        if not name:
            return
        if name in self._handlers and not allow_override:
            return
        self._handlers[name] = handler
        self._sources[name] = source
        self._schemas = [s for s in self._schemas if _tool_name_from_schema(s) != name]
        self._schemas.append(json.loads(json.dumps(schema)))

    def _register_builtin_tools(self) -> None:
        from . import agent_tools

        def _read(a: dict[str, Any]) -> str:
            p = a.get('file_path')
            if not isinstance(p, str) or not p.strip():
                return '[工具参数错误] 缺少有效字段 file_path（字符串）。'
            try:
                return agent_tools.read_local_file(p.strip())
            except (OSError, ValueError) as exc:
                return f'[执行失败] {type(exc).__name__}: {exc}'

        def _write(a: dict[str, Any]) -> str:
            p = a.get('file_path')
            c = a.get('content')
            if not isinstance(p, str) or not p.strip():
                return '[工具参数错误] 缺少有效字段 file_path（字符串）。'
            if not isinstance(c, str):
                return '[工具参数错误] content 必须为字符串。'
            try:
                return agent_tools.write_local_file(p.strip(), c)
            except (OSError, ValueError) as exc:
                return f'[执行失败] {type(exc).__name__}: {exc}'

        def _bash(a: dict[str, Any]) -> str:
            cmd = a.get('command')
            if not isinstance(cmd, str) or not cmd.strip():
                return '[工具参数错误] 缺少有效字段 command（字符串）。'
            try:
                return agent_tools.execute_mac_bash(cmd.strip())
            except (OSError, subprocess.TimeoutExpired) as exc:
                return f'[执行失败] {type(exc).__name__}: {exc}'

        def _install(a: dict[str, Any]) -> str:
            p = a.get('file_path')
            if not isinstance(p, str) or not p.strip():
                return '[工具参数错误] 缺少有效字段 file_path（字符串）。'
            return agent_tools.install_local_skill(p.strip())

        def _memory(a: dict[str, Any]) -> str:
            c = a.get('content')
            if not isinstance(c, str):
                return '[工具参数错误] 缺少有效字段 content（字符串）。'
            m = a.get('mode', 'append')
            if m is not None and not isinstance(m, str):
                return '[工具参数错误] mode 须为字符串。'
            return agent_tools.update_project_memory(c, mode=m if isinstance(m, str) else 'append')

        def _memorize_rule(a: dict[str, Any]) -> str:
            k = a.get('key_name')
            c = a.get('content')
            if not isinstance(k, str) or not k.strip():
                return '[工具参数错误] key_name 须为非空字符串。'
            if not isinstance(c, str):
                return '[工具参数错误] content 必须为字符串。'
            return agent_tools.memorize_project_rule(k.strip(), c)

        def _forget_rule(a: dict[str, Any]) -> str:
            k = a.get('key_name')
            if not isinstance(k, str) or not k.strip():
                return '[工具参数错误] key_name 须为非空字符串。'
            return agent_tools.forget_project_rule(k.strip())

        schemas = agent_tools.builtin_openai_tools_schema()
        handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            'read_local_file': _read,
            'write_local_file': _write,
            'execute_mac_bash': _bash,
            'install_local_skill': _install,
            'update_project_memory': _memory,
            'memorize_project_rule': _memorize_rule,
            'forget_project_rule': _forget_rule,
        }
        for schema in schemas:
            n = _tool_name_from_schema(schema)
            if not n or n not in handlers:
                continue
            self._register_one(schema, handlers[n], source='builtin:agent_tools')

    def _load_dynamic_tool_modules(self) -> None:
        root = _project_tool_plugins_dir()
        for path in sorted(root.glob('*.py')):
            if path.name.startswith('_'):
                continue
            self._load_tool_module(path)

    def _load_tool_module(self, path: Path) -> None:
        mod_name = f'_scream_tool_plugin_{path.stem}'
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # pragma: no cover
            print(f'[tools] 跳过 {path.name}: {exc}', file=sys.stderr)
            return
        schema = getattr(mod, 'TOOL_SCHEMA', None)
        execute_fn = getattr(mod, 'execute', None)
        if not isinstance(schema, dict) or not callable(execute_fn):
            print(f'[tools] 跳过 {path.name}: 缺少 TOOL_SCHEMA 或 execute', file=sys.stderr)
            return
        name = _tool_name_from_schema(schema)
        if not name:
            print(f'[tools] 跳过 {path.name}: 无法解析工具名', file=sys.stderr)
            return
        if name in self._handlers and self._sources.get(name, '').startswith('builtin:'):
            print(f'[tools] 跳过 {path.name}: 与内置工具重名 {name}', file=sys.stderr)
            return

        def _handler(args: dict[str, Any], fn: Any = execute_fn) -> str:
            try:
                return str(fn(**args))
            except TypeError as exc:
                return f'[执行失败] 参数不匹配: {exc}'
            except Exception as exc:  # pragma: no cover
                return f'[执行失败] {type(exc).__name__}: {exc}'

        self._register_one(
            schema,
            _handler,
            source=str(path.resolve()),
            allow_override=True,
        )

    def get_all_schemas(self) -> list[dict[str, Any]]:
        if not self._handlers:
            self.reload_all()
        from . import agent_tools

        fresh_builtin = agent_tools.builtin_openai_tools_schema()
        dyn = [
            s
            for s in self._schemas
            if not str(self._sources.get(_tool_name_from_schema(s) or '', '')).startswith(
                'builtin:'
            )
        ]
        return json.loads(json.dumps([*fresh_builtin, *dyn]))

    def execute_tool(self, name: str, arguments: dict[str, Any] | str) -> str:
        if not self._handlers:
            self.reload_all()
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or '{}')
            except json.JSONDecodeError as exc:
                return f'[工具参数错误] 无法解析 JSON 参数: {exc}'
        if not isinstance(arguments, dict):
            return '[工具参数错误] 参数必须为 JSON 对象。'
        handler = self._handlers.get(name)
        if handler is None:
            return f'[错误] 未知工具: {name}'
        try:
            return handler(arguments)
        except Exception as exc:  # pragma: no cover
            return f'[执行失败] {type(exc).__name__}: {exc}'

    def list_tool_rows(self) -> list[dict[str, str]]:
        """``[{"name","description","source"}, ...]``，供 CLI / tool-pool 表格。"""
        if not self._handlers:
            self.reload_all()
        rows: list[dict[str, str]] = []
        for schema in self.get_all_schemas():
            fn = schema.get('function') if isinstance(schema, dict) else None
            if not isinstance(fn, dict):
                continue
            name = str(fn.get('name', '') or '')
            desc = str(fn.get('description', '') or '')
            src = self._sources.get(name, '')
            rows.append({'name': name, 'description': desc, 'source': src})
        rows.sort(key=lambda r: r['name'])
        return rows


_registry: ToolsRegistry | None = None


def get_tools_registry() -> ToolsRegistry:
    global _registry
    if _registry is None:
        _registry = ToolsRegistry()
        _registry.reload_all()
    return _registry


def reset_tools_registry_for_tests() -> None:
    global _registry
    _registry = None
