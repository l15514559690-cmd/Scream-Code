from __future__ import annotations

import atexit
from collections import deque
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


class MCPClientError(Exception):
    """MCP 子进程或 JSON-RPC 层异常。"""


@dataclass(frozen=True)
class MCPTool:
    """MCP tools/list 返回的标准化工具。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    raw: dict[str, Any]

    def as_openai_tool(self) -> dict[str, Any]:
        schema = self.input_schema if isinstance(self.input_schema, dict) else {}
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': schema,
            },
        }


class MCPClient:
    """
    最小可用 MCP stdio 客户端（JSON-RPC 2.0）。

    - 通过 subprocess 启动外部 MCP server（例如: ``npx -y @browsermcp/mcp``）。
    - 支持 request/response 相关匹配与超时。
    - 启动后可调用 ``tools/list`` 并转换到 OpenAI tools schema。
    - 支持 ``tools/call``。
    """

    def __init__(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        startup_timeout_sec: float = 15.0,
        request_timeout_sec: float = 45.0,
        tool_call_timeout_sec: float = 30.0,
    ) -> None:
        if not command:
            raise ValueError('MCP command 不能为空')
        self.command = list(command)
        self.cwd = cwd
        self.env = env
        self.startup_timeout_sec = max(1.0, float(startup_timeout_sec))
        self.request_timeout_sec = max(1.0, float(request_timeout_sec))
        self.tool_call_timeout_sec = max(1.0, float(tool_call_timeout_sec))

        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._running = False
        self._id_lock = threading.Lock()
        self._next_id = 1
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._last_stderr_lines: queue.Queue[str] = queue.Queue(maxsize=40)
        self._recent_errors = deque(maxlen=20)
        self._tools_cache: list[MCPTool] = []
        # 生命周期状态：idle -> starting -> ready / error
        self.status: str = 'idle'

    @property
    def is_running(self) -> bool:
        return bool(self._running and self._proc is not None and self._proc.poll() is None)

    @property
    def tools_cache(self) -> tuple[MCPTool, ...]:
        return tuple(self._tools_cache)

    def start(self) -> None:
        if self.is_running:
            return
        self.status = 'starting'
        try:
            self._proc = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.status = 'error'
            raise MCPClientError(f'启动 MCP server 失败: {exc}') from exc

        if self._proc.stdin is None or self._proc.stdout is None or self._proc.stderr is None:
            self.stop()
            self.status = 'error'
            raise MCPClientError('MCP server stdio 管道不可用')

        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()
        atexit.register(self.stop)

        deadline = time.time() + self.startup_timeout_sec
        while time.time() < deadline:
            if not self.is_running:
                break
            # 给子进程一点时间进入事件循环；无握手协议时只做 liveness 检查。
            time.sleep(0.03)
            return
        self.stop()
        self.status = 'error'
        raise MCPClientError('MCP server 启动超时')

    def stop(self) -> None:
        self._running = False
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
        except OSError:
            pass
        finally:
            with self._pending_lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for q in pending:
                q.put({'jsonrpc': '2.0', 'error': {'message': 'MCP server stopped'}})
        self.status = 'idle'

    def refresh_tools(self) -> list[MCPTool]:
        try:
            payload = self.request('tools/list', params={})
        except Exception:
            self.status = 'error'
            raise
        result = payload.get('result')
        items: list[dict[str, Any]]
        if isinstance(result, dict) and isinstance(result.get('tools'), list):
            items = [x for x in result['tools'] if isinstance(x, dict)]
        elif isinstance(result, list):
            items = [x for x in result if isinstance(x, dict)]
        else:
            items = []
        _WEB_MODE_TOOL_DESC_SUFFIX = (
            '[强制] 如果当前处于浏览器MCP模式，请务必先以此工具获取最新信息。'
            '使用前请先在浏览器安装并连接 browser-mcp 插件。'
        )
        _BROWSER_ENTRY_TOOL_NAMES = {
            'browser_search',
            'browser_navigate',
            'browser_go_back',
            'browser_go_forward',
            'browser_tabs',
            'browser_snapshot',
        }

        tools: list[MCPTool] = []
        for row in items:
            name = str(row.get('name') or '').strip()
            if not name:
                continue
            desc = str(row.get('description') or '').strip()
            if name in _BROWSER_ENTRY_TOOL_NAMES or name.startswith('browser_'):
                if _WEB_MODE_TOOL_DESC_SUFFIX not in desc:
                    desc = (desc + '\n\n' if desc else '') + _WEB_MODE_TOOL_DESC_SUFFIX
            schema = row.get('inputSchema') or row.get('input_schema') or {'type': 'object', 'properties': {}}
            if not isinstance(schema, dict):
                schema = {'type': 'object', 'properties': {}}
            tools.append(
                MCPTool(
                    name=name,
                    description=desc,
                    input_schema=schema,
                    raw=row,
                )
            )
        self._tools_cache = tools
        self.status = 'ready'
        return list(tools)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.as_openai_tool() for t in self._tools_cache]

    def get_recent_errors(self) -> list[str]:
        return list(self._recent_errors)

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        n = (name or '').strip()
        if not n:
            raise MCPClientError('tool name 不能为空')
        params = {'name': n, 'arguments': arguments or {}}
        wait = self.tool_call_timeout_sec if timeout_sec is None else max(0.1, float(timeout_sec))
        return self.request(
            'tools/call',
            params=params,
            timeout_sec=wait,
        )

    def request(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        if not self.is_running:
            raise MCPClientError('MCP server 未运行')
        req_id = self._alloc_id()
        payload = {
            'jsonrpc': '2.0',
            'id': req_id,
            'method': method,
            'params': params or {},
        }
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[req_id] = q
        try:
            self._write_json(payload)
            wait_for = self.request_timeout_sec if timeout_sec is None else max(0.1, float(timeout_sec))
            try:
                resp = q.get(timeout=wait_for)
            except queue.Empty as exc:
                raise MCPClientError(f'MCP request 超时: method={method}') from exc
            if 'error' in resp and resp['error'] is not None:
                msg = str(resp['error'].get('message') or resp['error'])
                raise MCPClientError(f'MCP error: {msg}')
            return resp
        finally:
            with self._pending_lock:
                self._pending.pop(req_id, None)

    def _alloc_id(self) -> int:
        with self._id_lock:
            i = self._next_id
            self._next_id += 1
            return i

    def _write_json(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPClientError('MCP server stdin 不可用')
        line = json.dumps(payload, ensure_ascii=False)
        with self._write_lock:
            try:
                proc.stdin.write(line + '\n')
                proc.stdin.flush()
            except OSError as exc:
                raise MCPClientError(f'写入 MCP server 失败: {exc}') from exc

    def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while self._running:
                raw = proc.stdout.readline()
                if raw == '':
                    break
                msg = self._safe_json_load(raw)
                if msg is None:
                    continue
                msg_id = msg.get('id')
                if isinstance(msg_id, int):
                    with self._pending_lock:
                        q = self._pending.get(msg_id)
                    if q is not None:
                        q.put(msg)
                        continue
                self._event_queue.put(msg)
        finally:
            self._running = False

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while self._running:
                line = proc.stderr.readline()
                if line == '':
                    break
                s = line.rstrip('\n')
                if not s:
                    continue
                self._recent_errors.append(s)
                try:
                    self._last_stderr_lines.put_nowait(s)
                except queue.Full:
                    try:
                        self._last_stderr_lines.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._last_stderr_lines.put_nowait(s)
                    except queue.Full:
                        pass
        finally:
            self._running = False

    @staticmethod
    def _safe_json_load(line: str) -> dict[str, Any] | None:
        t = (line or '').strip()
        if not t:
            return None
        try:
            obj = json.loads(t)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return obj

