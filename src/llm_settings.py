from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DOTENV_LOADED = False


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_project_dotenv() -> None:
    """从项目根目录加载 `.env` 到进程环境（幂等）。"""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _DOTENV_LOADED = True
        return
    load_dotenv(project_root() / '.env')
    _DOTENV_LOADED = True


def reload_project_dotenv() -> None:
    """写入 `.env` 后重新加载到当前进程。"""
    global _DOTENV_LOADED
    _DOTENV_LOADED = False
    load_project_dotenv()


def upsert_project_dotenv_var(key: str, value: str) -> None:
    """
    在项目根 `.env` 中新增或覆盖一行 ``KEY=value``，并同步更新 ``os.environ``。
    值中的换行会被替换为空格，避免破坏 .env 格式。
    """
    path = project_root() / '.env'
    safe_value = value.replace('\n', ' ').replace('\r', '')
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding='utf-8').splitlines()
    out: list[str] = []
    prefix = f'{key}='
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) or stripped.startswith(f'{key} ='):
            out.append(f'{key}={safe_value}')
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append('')
        out.append(f'{key}={safe_value}')
    path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
    os.environ[key] = safe_value


def read_project_dotenv_value(key: str) -> str:
    """从当前环境或项目根 ``.env`` 文件中读取某键的值（不含引号包裹处理外的转义）。"""
    v = os.environ.get(key, '').strip()
    if v:
        return v
    path = project_root() / '.env'
    if not path.is_file():
        return ''
    prefix_eq = f'{key}='
    prefix_sp = f'{key} ='
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if s.startswith(prefix_eq):
            raw = s[len(prefix_eq) :].strip()
        elif s.startswith(prefix_sp):
            raw = s[len(prefix_sp) :].strip()
        else:
            continue
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        return raw.strip()
    return ''


def migrate_project_dotenv_key(old_key: str, new_key: str) -> None:
    """
    将 ``old_key`` 的值迁移到 ``new_key`` 后删除旧行，避免别名变更后 .env 残留无效键。
    若旧键无值，则仅删除旧行（不写入新键）。
    """
    if old_key == new_key:
        return
    val = read_project_dotenv_value(old_key)
    remove_project_dotenv_var(old_key)
    if val:
        upsert_project_dotenv_var(new_key, val)


def remove_project_dotenv_var(key: str) -> None:
    """从项目根 ``.env`` 中移除指定键的行（若存在），不影响其它变量。"""
    path = project_root() / '.env'
    os.environ.pop(key, None)
    if not path.is_file():
        return
    lines = path.read_text(encoding='utf-8').splitlines()
    prefix = f'{key}='
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) or stripped.startswith(f'{key} ='):
            continue
        out.append(line)
    body = '\n'.join(out).rstrip() + ('\n' if out else '')
    path.write_text(body, encoding='utf-8')


@dataclass(frozen=True)
class LlmConnectionSettings:
    """OpenAI / Anthropic 兼容连接参数；优先来自 llm_config.json 当前激活项。"""

    base_url: str
    api_key: str
    model: str
    #: ``openai`` 或 ``anthropic``，决定 SDK 与请求格式。
    api_protocol: str = 'openai'
    #: 密钥所在环境变量名（用于报错指引）；旧版直连为 API_KEY。
    api_key_env_name: str | None = None
    profile_alias: str | None = None


def _legacy_env_settings() -> LlmConnectionSettings:
    """无 ``llm_config.json`` 激活项时，仅依赖环境变量；不设厂商写死的默认 Base URL / 型号。"""
    raw_base = os.environ.get('BASE_URL', '').strip()
    base_url = raw_base.rstrip('/') if raw_base else ''
    if not base_url:
        base_url = 'https://api.openai.com/v1'
    api_key = os.environ.get('API_KEY', '').strip()
    model = os.environ.get('MODEL', '').strip() or 'gpt-4o-mini'
    return LlmConnectionSettings(
        base_url=base_url,
        api_key=api_key,
        model=model,
        api_protocol='openai',
        api_key_env_name='API_KEY',
        profile_alias=None,
    )


def read_llm_connection_settings() -> LlmConnectionSettings:
    """优先使用 llm_config.json 中 active 模型；否则回退 BASE_URL / API_KEY / MODEL。"""
    load_project_dotenv()
    from . import model_manager

    model_manager.ensure_default_config_file()
    raw = model_manager.read_persisted_config_raw()
    if raw is None:
        return _legacy_env_settings()
    profile = model_manager.get_active_profile(raw)
    if profile is None:
        return _legacy_env_settings()
    api_key = os.environ.get(profile.api_key_env_name, '').strip()
    return LlmConnectionSettings(
        base_url=profile.base_url.rstrip('/'),
        api_key=api_key,
        model=profile.model_name,
        api_protocol=profile.api_protocol,
        api_key_env_name=profile.api_key_env_name,
        profile_alias=profile.alias,
    )
