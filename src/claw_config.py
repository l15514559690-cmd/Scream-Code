from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm_settings import project_root

_claw_cache: dict[str, Any] | None = None


def claw_json_path() -> Path:
    """项目根目录下的 ``.claw.json``（与 claw-code / 原版配置对齐）。"""
    return project_root() / '.claw.json'


def load_project_claw_json(*, force_reload: bool = False) -> dict[str, Any]:
    """
    读取并解析项目根 ``.claw.json``；缺失或损坏时返回空 dict。
    结果进程内缓存，直至 ``force_reload=True``。
    """
    global _claw_cache
    if not force_reload and _claw_cache is not None:
        return _claw_cache
    path = claw_json_path()
    if not path.is_file():
        _claw_cache = {}
        return _claw_cache
    try:
        raw = path.read_text(encoding='utf-8')
        data = json.loads(raw)
        _claw_cache = data if isinstance(data, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _claw_cache = {}
    return _claw_cache


def reload_project_claw_json() -> dict[str, Any]:
    """强制重新从磁盘加载 ``.claw.json``。"""
    return load_project_claw_json(force_reload=True)


def is_product_session_ready() -> bool:
    """
    产品入口用：大模型侧（API Key 等）是否已就绪。
    项目根 ``.claw.json`` 为可选增强配置，不阻断启动。
    """
    from .llm_onboarding import is_llm_runtime_configured

    return is_llm_runtime_configured()
