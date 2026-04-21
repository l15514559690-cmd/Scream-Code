"""
飞书侧车状态：后台 1Hz 轮询，主线程只读缓存，避免阻塞 prompt_toolkit 渲染。
"""

from __future__ import annotations

import threading
import time

_state_lock = threading.Lock()
_state_running: bool = False
_poller_started: bool = False

_ZINC_950 = '#09090b'
_INDIGO = '#4F46E5'
_DIM_ZINC = '#71717a'
_HELP_DIM = '#52525b'


def _probe_feishu_running_once() -> bool:
    try:
        from ..services.feishu_manager import feishu_manager

        return feishu_manager.is_sidecar_running()
    except Exception:
        return False


def _poll_loop() -> None:
    global _state_running
    while True:
        time.sleep(1.0)
        try:
            alive = _probe_feishu_running_once()
        except Exception:
            alive = False
        with _state_lock:
            _state_running = alive


def ensure_feishu_status_poller_started() -> None:
    """幂等启动后台轮询；首次同步探测一次再开线程。"""
    global _poller_started, _state_running
    with _state_lock:
        if _poller_started:
            return
    try:
        initial_alive = _probe_feishu_running_once()
    except Exception:
        initial_alive = False
    with _state_lock:
        if _poller_started:
            return
        _poller_started = True
        _state_running = initial_alive
    threading.Thread(target=_poll_loop, name='scream-feishu-status', daemon=True).start()


def is_feishu_running() -> bool:
    """读取缓存的侧车在线状态（由后台线程每秒更新）。"""
    ensure_feishu_status_poller_started()
    with _state_lock:
        return bool(_state_running)


def feishu_toolbar_html_fragment() -> str:
    """
    供 ``prompt_toolkit`` ``HTML()`` 使用的片段（Zinc-950 底由全局 bottom-toolbar 样式提供）。
    """
    ensure_feishu_status_poller_started()
    on = is_feishu_running()
    if on:
        return f'<style fg="{_INDIGO}"><b>[● Feishu: ON]</b></style>'
    tip = f'<style fg="{_HELP_DIM}">· /feishu start 开启侧车</style>'
    return f'<style fg="{_DIM_ZINC}"><b>[○ Feishu: OFF]</b></style>  {tip}'


def feishu_stream_rich_fragment() -> str:
    """与流式页脚 ``Rich`` 单行 markup 对齐。"""
    ensure_feishu_status_poller_started()
    on = is_feishu_running()
    if on:
        return f'  ·  [bold {_INDIGO} on {_ZINC_950}][● Feishu: ON][/bold {_INDIGO} on {_ZINC_950}]'
    return (
        f'  ·  [dim {_DIM_ZINC}][○ Feishu: OFF][/dim {_DIM_ZINC}] '
        f'[dim {_HELP_DIM}]（/feishu start）[/dim {_HELP_DIM}]'
    )
