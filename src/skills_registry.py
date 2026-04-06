from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .llm_settings import project_root


def _skills_dir() -> Path:
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


class SkillsRegistry:
    """
    **技能注册表（Agent 工具层的单一事实来源）**

    与 **claw-code 镜像工具池**（``tool_pool`` / ``main tool-pool`` 输出的清单）的关系：
    镜像侧条目来自 ``tools.py`` 归档元数据；**本注册表**提供实际可被 LLM ``function calling``
    调用的 schema 与 ``execute``，并在 ``tool_pool.ToolPool.as_markdown`` 末尾汇总展示，避免「孤岛」。

    与 ``llm_client`` / ``query_engine`` 解耦方式：

    - **Schema 侧**：``get_all_schemas()`` 产出交给大模型的 OpenAI 格式 ``tools`` 列表；
      内置条目的描述文案每次调用时与 ``agent_tools`` 同步（沙箱/越狱开关即时反映）。
    - **执行侧**：``execute_tool`` 根据工具名分发到内置实现或 ``skills/*.py`` 中加载的 ``execute``。

    动态技能约定：项目根 ``skills/`` 下每个 ``*.py``（非 ``_`` 前缀）导出
    ``TOOL_SCHEMA``（单项 ``{"type":"function","function":{...}}``）与 ``execute(**kwargs)``。
    """

    def __init__(self) -> None:
        self._schemas: list[dict[str, Any]] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], str]] = {}
        self._sources: dict[str, str] = {}

    def reload_all(self) -> None:
        """清空内存态并重新注册内置技能 + 扫描磁盘上的动态技能文件。"""
        self._schemas.clear()
        self._handlers.clear()
        self._sources.clear()
        self._register_builtin_skills()
        self._load_dynamic_skill_files()

    def _register_one(
        self,
        schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], str],
        *,
        source: str,
        allow_override: bool = False,
    ) -> None:
        """登记单条工具：写入 handler、来源标签，并更新 ``_schemas`` 中同名 schema。"""
        name = _tool_name_from_schema(schema)
        if not name:
            return
        if name in self._handlers and not allow_override:
            return
        self._handlers[name] = handler
        self._sources[name] = source
        # 刷新同名的 schema 条目
        self._schemas = [s for s in self._schemas if _tool_name_from_schema(s) != name]
        self._schemas.append(json.loads(json.dumps(schema)))

    def _register_builtin_skills(self) -> None:
        """从 ``agent_tools`` 拉取内置工具 schema 与包装后的可调用实现。"""
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

        schemas = agent_tools.builtin_openai_tools_schema()
        handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            'read_local_file': _read,
            'write_local_file': _write,
            'execute_mac_bash': _bash,
            'install_local_skill': _install,
            'update_project_memory': _memory,
        }
        for schema in schemas:
            n = _tool_name_from_schema(schema)
            if not n or n not in handlers:
                continue
            self._register_one(schema, handlers[n], source='builtin:agent_tools')

    def _load_dynamic_skill_files(self) -> None:
        """按文件名排序加载 ``skills/*.py``，失败模块打印到 stderr 并跳过。"""
        root = _skills_dir()
        for path in sorted(root.glob('*.py')):
            if path.name.startswith('_'):
                continue
            self._load_skill_module(path)

    def _load_skill_module(self, path: Path) -> None:
        """对单个文件 ``importlib`` 执行模块，校验 ``TOOL_SCHEMA`` + ``execute`` 后注册；禁止覆盖内置名。"""
        mod_name = f'_scream_skill_{path.stem}'
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # pragma: no cover - 坏技能跳过
            print(f'[skills] 跳过 {path.name}: {exc}', file=sys.stderr)
            return
        schema = getattr(mod, 'TOOL_SCHEMA', None)
        execute_fn = getattr(mod, 'execute', None)
        if not isinstance(schema, dict) or not callable(execute_fn):
            print(
                f'[skills] 跳过 {path.name}: 缺少 TOOL_SCHEMA 或 execute',
                file=sys.stderr,
            )
            return
        name = _tool_name_from_schema(schema)
        if not name:
            print(f'[skills] 跳过 {path.name}: 无法解析工具名', file=sys.stderr)
            return
        if name in self._handlers and self._sources.get(name, '').startswith('builtin:'):
            print(f'[skills] 跳过 {path.name}: 与内置工具重名 {name}', file=sys.stderr)
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
        """
        返回当前应下发给模型的完整 ``tools`` 列表（深拷贝）。

        内置部分每次重新从 ``agent_tools.builtin_openai_tools_schema()`` 生成，保证
        ``allow_global_access`` 等配置变更在下一轮请求前生效；动态部分来自上次 ``reload_all``。
        """
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
        """
        执行名为 ``name`` 的工具；``arguments`` 可为已解析的 ``dict`` 或 JSON 字符串。
        任意异常均转为可读错误串，供多轮对话中的 ``tool`` 消息使用，不向模型抛栈。
        """
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

    def list_skill_rows(self) -> list[dict[str, str]]:
        """返回 ``[{"name","description","source"}, ...]``，供 CLI ``findskills`` 表格渲染。"""
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


_registry: SkillsRegistry | None = None


def get_skills_registry() -> SkillsRegistry:
    """进程内单例；首次访问时 ``reload_all()``。"""
    global _registry
    if _registry is None:
        _registry = SkillsRegistry()
        _registry.reload_all()
    return _registry


def reset_skills_registry_for_tests() -> None:
    """测试用：强制下次 ``get_skills_registry`` 重新加载。"""
    global _registry
    _registry = None
