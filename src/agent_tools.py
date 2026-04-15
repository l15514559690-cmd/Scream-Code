from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from .constants.messages import AGENT_EXEC_TIMEOUT_SEC, MSG_TIMEOUT_FUSE, MSG_TOOL_EXCEPTION
from .llm_settings import project_root

_log = logging.getLogger(__name__)


def _allow_global_access() -> bool:
    from . import model_manager

    return model_manager.read_allow_global_access()


def _workspace_root() -> Path:
    """允许通过环境变量限定工作区根目录，默认可用进程当前工作目录。"""
    raw = os.environ.get('SCREAM_WORKSPACE_ROOT', '').strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def _safe_file_path(file_path: str) -> Path:
    """
    将 file_path 解析为绝对路径，并确保解析结果落在工作区根目录之下，
    防止通过 ``..`` 等方式读出工作区外敏感文件。
    """
    base = _workspace_root()
    p = Path(file_path).expanduser()
    if not p.is_absolute():
        p = (base / p).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f'拒绝访问工作区外的路径。工作区根: {base}，请求路径: {p}'
        ) from exc
    return p


def _resolved_file_path(file_path: str) -> Path:
    """沙箱模式限制在工作区内；越狱模式放行任意路径并展开 ``~``。"""
    s = (file_path or '').strip()
    if _allow_global_access():
        p = Path(os.path.expanduser(s))
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
        return p
    return _safe_file_path(file_path)


def read_local_file(file_path: str) -> str:
    """
    读取工作区内的本地文本文件并返回其 UTF-8 解码后的内容。

    用于让大模型查看项目源码、配置或日志。
    沙箱模式下路径相对于工作区根解析且不得越界；全局模式下任意路径并支持 ``~`` 展开。
    大文件可能导致响应体过大，请优先读取必要片段。

    Args:
        file_path: 沙箱下为工作区内路径；全局模式下可为任意可读路径。

    Returns:
        文件全文字符串；若文件为空则返回空字符串。

    Raises:
        OSError: 读文件失败（权限、不是文件等）。
        ValueError: 路径逃出工作区（沙箱模式）。
        ValueError: 非 UTF-8 文本或其它无效内容。
    """
    path = _resolved_file_path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f'不是文件或不存在: {path}')
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f'文件非 UTF-8 文本，无法读取: {path}') from exc


def write_local_file(file_path: str, content: str) -> str:
    """
    将 ``content`` 以 UTF-8 **覆盖写入**指定路径。若父目录不存在会自动创建。

    用于让大模型创建或修改本地文件。沙箱模式下路径受工作区根约束；全局模式下任意可写路径。

    Args:
        file_path: 目标文件路径（沙箱下须在工作区内；全局模式下任意，支持 ``~``）。
        content: 要写入的完整文本内容。

    Returns:
        简短成功说明（含解析后的绝对路径），便于作为工具结果反馈给模型。

    Raises:
        ValueError: 路径逃出工作区（沙箱模式）。
        OSError: 创建目录或写入失败。
    """
    path = _resolved_file_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return f'已写入 {path}（{len(content)} 字符）。'


def execute_mac_bash(command: str) -> str:
    """
    在本地通过 ``/bin/bash -lc`` 执行一条 shell 命令，合并 stdout/stderr 后返回文本。

    需要系统存在 ``/bin/bash``；用于让大模型运行构建、测试、git 等命令。
    若 ``SandboxManager.is_sandbox_enabled`` 为 True，则改为在 Docker 容器内执行（挂载工作区根到 ``/workspace``）。
    否则：沙箱路径策略下在工作区根目录执行；全局越狱模式下在用户主目录下执行。超时 60 秒。
    请勿用于交互式或长期驻留进程。

    Args:
        command: 传给 bash 的完整命令字符串（可含管道与重定向，仍需谨慎）。

    Returns:
        进程退出码与输出摘要；若退出码非 0，返回内容中仍会包含 stderr 以便排错。

    Raises:
        subprocess.TimeoutExpired: 超时（仅宿主机 bash 分支；Docker 分支在内部吞掉并返回字符串）。
        OSError: 无法启动子进程（仅宿主机 bash 分支）。
    """
    from .sandbox_env import SandboxManager

    if SandboxManager.instance().is_sandbox_enabled:
        return SandboxManager.instance().execute_in_sandbox(command, str(_workspace_root()))

    bash = Path('/bin/bash')
    if not bash.is_file():
        return f'[错误] 未找到 /bin/bash（当前平台 {sys.platform}）。'
    if _allow_global_access():
        cwd = os.path.expanduser('~')
    else:
        cwd = str(_workspace_root())
    env = {
        **os.environ,
        'LC_ALL': 'C.UTF-8',
        'LANG': 'C.UTF-8',
        'PYTHONIOENCODING': 'utf-8',
    }
    proc = subprocess.Popen(
        [str(bash), '-lc', command],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
    )
    out_box: list[tuple[str, str] | BaseException] = []

    def _drain() -> None:
        try:
            out_box.append(proc.communicate())
        except Exception as exc:  # pragma: no cover - 极少
            out_box.append(exc)

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    try:
        from . import agent_cancel

        deadline = time.monotonic() + AGENT_EXEC_TIMEOUT_SEC
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
    if len(out) > 32_000:
        out = out[:32_000] + '\n…(输出已截断)…'
    status = '成功' if proc.returncode == 0 else f'失败(退出码 {proc.returncode})'
    return f'[{status}]\n{out}' if out else f'[{status}]（无输出）'


def update_project_memory(content: str, mode: str = 'append') -> str:
    """
    将内容写入当前工作目录下的 ``SCREAM.md``，用于项目级持久记忆。

    当用户要求记住偏好、全局规则或长期上下文时，应调用本工具而非仅口头答应。

    Args:
        content: 要写入的文本（UTF-8）。
        mode: ``append``（默认，追加到文件末尾）或 ``overwrite``（整文件覆盖）。

    Returns:
        简短结果说明；失败时返回带前缀的可读错误信息，不抛异常。
    """
    if not isinstance(content, str):
        return '[工具参数错误] content 必须为字符串。'
    raw_mode = (mode or 'append').strip().lower()
    if raw_mode not in ('append', 'overwrite'):
        return '[工具参数错误] mode 须为 append 或 overwrite。'
    path = (Path.cwd() / 'SCREAM.md').resolve()
    try:
        if raw_mode == 'overwrite':
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        else:
            existing = ''
            if path.is_file():
                try:
                    existing = path.read_text(encoding='utf-8')
                except (OSError, UnicodeDecodeError) as exc:
                    return f'[执行失败] 无法读取现有 SCREAM.md: {exc}'
            sep = '\n\n' if existing and not existing.endswith('\n') else ''
            new_body = f'{existing}{sep}{content}' if existing else content
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_body, encoding='utf-8')
        size = path.stat().st_size
        return f'已更新项目记忆文件 {path}（模式: {raw_mode}，约 {size} 字节）。'
    except OSError as exc:
        return f'[执行失败] {type(exc).__name__}: {exc}'


def install_local_skill(file_path: str) -> str:
    """
    将本地 Python 技能文件复制到项目 ``skills/`` 目录并热重载注册表。
    仅接受 ``.py`` 文件名安全的源路径（使用源文件 basename 作为目标名）。
    """
    raw = (file_path or '').strip()
    if not raw:
        return '[工具参数错误] file_path 不能为空。'
    src = Path(os.path.expanduser(raw)).resolve()
    if not src.is_file():
        return f'[错误] 源文件不存在: {src}'
    if src.suffix.lower() != '.py':
        return '[错误] 仅支持安装 .py 技能文件。'
    name = src.name
    if not name or name.startswith('.') or not re.fullmatch(r'[A-Za-z0-9_.-]+\.py', name):
        return '[错误] 技能文件名仅允许字母、数字、._- 且须为 .py 结尾。'
    dest_dir = project_root() / 'skills'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / name).resolve()
    try:
        dest.relative_to(dest_dir.resolve())
    except ValueError:
        return '[错误] 目标路径非法。'
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        return f'[错误] 复制失败: {exc}'
    from .tools_registry import get_tools_registry

    get_tools_registry().reload_all()
    return f'已安装技能 {name} 至 {dest}，并已热重载 ToolsRegistry。'


def memorize_project_rule(key_name: str, content: str) -> str:
    """
    将架构决策、开发规范、用户代码习惯等写入本机长期记忆库（SQLite，``~/.scream/memory.db``）。

    与 ``update_project_memory``（SCREAM.md）互补：本工具按 **键** 结构化存储，便于后续注入系统提示词。
    """
    from .memory_store import memorize_core_rule

    return memorize_core_rule(key_name, content)


def forget_project_rule(key_name: str) -> str:
    """从长期记忆库删除指定键；过时规则应主动清理。"""
    from .memory_store import forget_core_rule

    return forget_core_rule(key_name)


def run_agent_tool(function_name: str, arguments_json: str) -> str:
    """调度技能注册表；兼容测试与旧调用点。"""
    from .tools_registry import get_tools_registry

    try:
        return get_tools_registry().execute_tool(function_name, arguments_json)
    except Exception as exc:  # pragma: no cover - 兜底防御
        err = f'{type(exc).__name__}: {exc}'
        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip().splitlines()
        tb_short = '\n'.join(tb[:6]) if tb else ''
        _log.warning('run_agent_tool crashed: %s', err)
        msg = MSG_TOOL_EXCEPTION.format(error_trace=err)
        return f'{msg}\n{tb_short}' if tb_short else msg


def builtin_openai_tools_schema() -> list[dict[str, object]]:
    """OpenAI Chat Completions ``tools`` 参数所需的 JSON Schema 列表（随沙箱/越狱配置变化）。"""
    from .sandbox_env import SandboxManager

    jail = _allow_global_access()
    docker_sandbox = SandboxManager.instance().is_sandbox_enabled
    if jail:
        read_desc = (
            '读取本地文本文件（UTF-8）。当前为全局模式：可使用任意绝对路径或相对路径，'
            '路径中的 ~ 会按用户主目录展开。'
        )
        read_fp = '文件路径（绝对路径、相对路径或含 ~ 的路径）。'
        write_desc = (
            '将内容覆盖写入本地文件；若目录不存在会自动创建。'
            '当前为全局模式：可写入任意允许的路径。'
        )
        write_fp = '目标文件路径（绝对、相对或含 ~）。'
        bash_desc = (
            '在 macOS 上通过 bash 执行一条命令（在用户主目录下启动 shell，超时 120s）。'
            '可组合命令完成系统级任务（如截图、系统工具等）。'
        )
        if docker_sandbox:
            bash_desc = (
                '在 Docker 容器内通过 bash 执行命令（工作区根挂载为 /workspace，超时 120s）。'
                '需要本机已安装 Docker；适合隔离执行构建/脚本。'
            )
    else:
        read_desc = (
            '读取工作区内的文本文件（UTF-8）。路径相对于工作区根；'
            '不可访问工作区外的路径。'
        )
        read_fp = '相对于工作区根的文件路径，或工作区内的绝对路径。'
        write_desc = (
            '将内容覆盖写入工作区内的文件；若目录不存在会自动创建。'
            '不可写入工作区外。'
        )
        write_fp = '目标文件路径（相对工作区根或工作区内绝对路径）。'
        bash_desc = (
            '在 macOS 上通过 bash 执行一条命令（工作区根为 cwd，超时 120s）。'
            '适合运行测试、构建、git 等非交互命令；无法用于工作区外的系统级操作。'
        )
        if docker_sandbox:
            bash_desc = (
                '在 Docker 容器内通过 bash 执行命令（工作区根挂载为 /workspace，超时 120s）。'
                '需要本机已安装 Docker；命令仅在容器环境内生效。'
            )
    from . import channel_tools

    return [
        {
            'type': 'function',
            'function': {
                'name': 'read_local_file',
                'description': read_desc,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'file_path': {
                            'type': 'string',
                            'description': read_fp,
                        },
                    },
                    'required': ['file_path'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'write_local_file',
                'description': write_desc,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'file_path': {
                            'type': 'string',
                            'description': write_fp,
                        },
                        'content': {
                            'type': 'string',
                            'description': '要写入的完整文件内容。',
                        },
                    },
                    'required': ['file_path', 'content'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'execute_mac_bash',
                'description': bash_desc,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {
                            'type': 'string',
                            'description': '完整的 shell 命令字符串，将传给 bash -lc。',
                        },
                    },
                    'required': ['command'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'install_local_skill',
                'description': (
                    '将指定路径的 Python 技能文件安全复制到项目 ./skills/ 目录，'
                    '并热重载动态技能注册表；用于扩展助理能力。源文件须为 .py，目标使用源文件名。'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'file_path': {
                            'type': 'string',
                            'description': '源 .py 文件路径（可含 ~，相对路径相对当前工作目录）。',
                        },
                    },
                    'required': ['file_path'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'update_project_memory',
                'description': (
                    '当用户要求你记住某事、设定全局规则、偏好或长期项目约定时，调用此工具将内容写入'
                    '当前工作目录的 SCREAM.md，从而在后续会话中通过项目记忆机制持久生效。'
                    '不要仅在回复中承诺「已记住」而不写入文件。'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'content': {
                            'type': 'string',
                            'description': '要保存的记忆或规则全文（建议分条、简洁）。',
                        },
                        'mode': {
                            'type': 'string',
                            'description': 'append=追加到 SCREAM.md 末尾（默认）；overwrite=整文件覆盖。',
                            'enum': ['append', 'overwrite'],
                            'default': 'append',
                        },
                    },
                    'required': ['content'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'memorize_project_rule',
                'description': (
                    '**强烈建议**：在对话中一旦发现用户有稳定的代码风格、命名习惯、技术栈偏好、'
                    '或项目级架构/目录/测试/发布等**长期有效**的约定，应主动调用本工具写入长期记忆库（按 key 存储，'
                    '后续会自动进入系统上下文）。不要等到用户说「请记住」才写入；对重复出现或明确拍板的规则尤应记录。'
                    '与 update_project_memory（SCREAM.md 叙述型记忆）可同时使用；本工具适合可检索的短键值规则。'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'key_name': {
                            'type': 'string',
                            'description': (
                                '唯一键，建议点分或 snake_case，例如 rust.edition、api.base_url、'
                                'style.no_any。同一键再次写入会覆盖更新。'
                            ),
                        },
                        'content': {
                            'type': 'string',
                            'description': '该规则下的完整说明（可含多行），应具体可执行、避免空泛套话。',
                        },
                    },
                    'required': ['key_name', 'content'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'forget_project_rule',
                'description': (
                    '当某条长期规则已被用户否定、架构已迁移或内容已过时，调用本工具按 key 从长期记忆库删除，'
                    '避免错误信息持续注入上下文。删除前请确认用户意图或对话中已明确废弃该规则。'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'key_name': {
                            'type': 'string',
                            'description': '要删除的规则键名，须与当初 memorize_project_rule 使用的 key_name 一致。',
                        },
                    },
                    'required': ['key_name'],
                },
            },
        },
        channel_tools.SEND_FILE_TO_USER_OPENAI_TOOL,
    ]
