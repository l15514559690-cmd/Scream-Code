"""
跨线程的「中断当前 Agent 工具链」信号。

供 REPL ``/stop``、长时间 bash 等轮询检查；与 ``llm_client`` 的闭环配合。
"""

from __future__ import annotations

import threading

# 写入 tool 角色消息内容，供大模型识别为用户侧中断（与需求文案一致）
INTERRUPT_TOOL_MESSAGE = '[User Interrupted Task]'

_cancel_event = threading.Event()


def reset_agent_cancel() -> None:
    """新一轮用户输入开始时清除信号。"""
    _cancel_event.clear()


def request_agent_cancel() -> None:
    """请求尽快结束当前工具执行与后续同轮 tool 调用（如 ``/stop``）。"""
    _cancel_event.set()


def agent_cancel_requested() -> bool:
    return _cancel_event.is_set()
