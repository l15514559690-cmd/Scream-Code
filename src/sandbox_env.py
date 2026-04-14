from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

from .constants.messages import AGENT_EXEC_TIMEOUT_SEC, MSG_TIMEOUT_FUSE

# 默认镜像；可用环境变量覆盖：`export SCREAM_SANDBOX_IMAGE=node:18-alpine`
SANDBOX_DOCKER_IMAGE_DEFAULT = 'python:3.11-slim'

SANDBOX_COMMAND_TIMEOUT_SEC = AGENT_EXEC_TIMEOUT_SEC
_OUTPUT_CAP = 32_000


def _sandbox_image() -> str:
    return os.environ.get('SCREAM_SANDBOX_IMAGE', '').strip() or SANDBOX_DOCKER_IMAGE_DEFAULT


class SandboxManager:
    """
    Docker 容器内执行 shell（工作区目录 rw 挂载到容器内 ``/workspace``，便于构建与测试）。
    ``is_sandbox_enabled`` 为 True 时，``agent_tools.execute_mac_bash`` 走容器而非宿主机 bash。
    TUI 神经底栏通过单例读取该开关，与 ``/sandbox`` 技能同步。
    """

    _instance: ClassVar[SandboxManager | None] = None

    is_sandbox_enabled: bool = False

    def __new__(cls) -> SandboxManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> SandboxManager:
        return cls()

    def execute_in_sandbox(self, command: str, workspace_dir: str) -> str:
        """
        ``docker run --rm -v {workspace}:/workspace -w /workspace <image> bash -lc <command>``

        Returns:
            与 ``execute_mac_bash`` 风格一致的可读串（含退出码摘要）；不抛异常到调用方边界外。
        """
        ws = Path(workspace_dir).expanduser().resolve()
        if not ws.is_dir():
            return f'[sandbox] 工作区目录无效或不存在: {ws}'

        image = _sandbox_image()
        docker_args = [
            'docker',
            'run',
            '--rm',
            '-v',
            f'{ws}:/workspace',
            '-w',
            '/workspace',
            image,
            'bash',
            '-lc',
            command,
        ]

        try:
            proc = subprocess.Popen(
                docker_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
        except FileNotFoundError:
            return (
                '[sandbox] 未找到 docker 可执行文件，请安装 Docker 并确保在 PATH 中。'
                f'（平台 {sys.platform}）'
            )
        except OSError as exc:
            return f'[sandbox] 无法启动 docker: {type(exc).__name__}: {exc}'

        out_box: list[tuple[str, str] | BaseException] = []

        def _drain() -> None:
            try:
                out_box.append(proc.communicate())
            except Exception as exc:  # pragma: no cover
                out_box.append(exc)

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()

        try:
            from . import agent_cancel

            deadline = time.monotonic() + SANDBOX_COMMAND_TIMEOUT_SEC
            while reader.is_alive():
                if agent_cancel.agent_cancel_requested():
                    proc.terminate()
                    try:
                        proc.wait(timeout=4.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=3.0)
                        except subprocess.TimeoutExpired:
                            pass
                    reader.join(timeout=8.0)
                    return agent_cancel.INTERRUPT_TOOL_MESSAGE
                if time.monotonic() > deadline:
                    proc.kill()
                    try:
                        proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        pass
                    reader.join(timeout=8.0)
                    return MSG_TIMEOUT_FUSE
                time.sleep(0.12)
            reader.join(timeout=1.0)
        except OSError as exc:
            return f'[执行失败] {type(exc).__name__}: {exc}'

        if not out_box:
            return '[执行失败] 子进程无输出'
        got = out_box[0]
        if isinstance(got, BaseException):
            return f'[执行失败] {type(got).__name__}: {got}'
        stdout, stderr = got
        out = (stdout or '') + (stderr or '')
        out = out.strip()
        if len(out) > _OUTPUT_CAP:
            out = out[:_OUTPUT_CAP] + '\n…(输出已截断)…'
        status = '成功' if proc.returncode == 0 else f'失败(退出码 {proc.returncode})'
        prefix = '[docker 沙箱]'
        if out:
            return f'{prefix} [{status}]\n{out}'
        return f'{prefix} [{status}]（无输出）'
