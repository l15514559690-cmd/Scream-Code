from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DOTENV_LOADED = False

# LLM 网络超时防护（秒）：连接建立上限 + 流式读取上限
LLM_CONNECT_TIMEOUT = 15.0
LLM_READ_TIMEOUT = 90.0
MCP_SERVER_COMMAND: str | None = None
"""可选 MCP server 启动命令（例如 ``npx -y @browsermcp/mcp``）；None 表示禁用。"""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def scream_user_config_dir() -> Path:
    """用户级配置目录（``~/.scream``），与代码仓库解耦。"""
    d = Path.home() / '.scream'
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _migrate_legacy_repo_dotenv_if_needed() -> None:
    """首次使用时将仓库根 ``.env`` 复制到 ``~/.scream/.env``（若后者尚不存在）。"""
    dst = scream_user_config_dir() / '.env'
    if dst.is_file():
        return
    leg = project_root() / '.env'
    if not leg.is_file():
        return
    try:
        dst.write_text(leg.read_text(encoding='utf-8'), encoding='utf-8')
    except OSError:
        pass


def load_project_dotenv() -> None:
    """先加载 ``~/.scream/.env``，再加载项目根 ``.env``（后者不覆盖已有键）。"""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _DOTENV_LOADED = True
        return
    _migrate_legacy_repo_dotenv_if_needed()
    user_env = scream_user_config_dir() / '.env'
    if user_env.is_file():
        load_dotenv(user_env)
    proj = project_root() / '.env'
    if proj.is_file():
        load_dotenv(proj, override=False)
    _DOTENV_LOADED = True


def reload_project_dotenv() -> None:
    """写入 `.env` 后重新加载到当前进程。"""
    global _DOTENV_LOADED
    _DOTENV_LOADED = False
    load_project_dotenv()


def upsert_project_dotenv_var(key: str, value: str) -> None:
    """
    在 ``~/.scream/.env`` 中新增或覆盖 ``KEY=value``，并同步更新 ``os.environ``。
    值中的换行会被替换为空格，避免破坏 .env 格式。
    """
    path = scream_user_config_dir() / '.env'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
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


def _read_dotenv_file_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ''
    prefix_eq = f'{key}='
    prefix_sp = f'{key} ='
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return ''
    for line in lines:
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


def read_project_dotenv_value(key: str) -> str:
    """优先环境变量，其次 ``~/.scream/.env``，再次项目根 ``.env``。"""
    v = os.environ.get(key, '').strip()
    if v:
        return v
    u = _read_dotenv_file_value(scream_user_config_dir() / '.env', key)
    if u:
        return u
    return _read_dotenv_file_value(project_root() / '.env', key)


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
    """从 ``~/.scream/.env``（及兼容性的项目根 ``.env``）中移除指定键。"""
    os.environ.pop(key, None)
    prefix = f'{key}='

    def _strip(path: Path) -> None:
        if not path.is_file():
            return
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(prefix) or stripped.startswith(f'{key} ='):
                continue
            out.append(line)
        body = '\n'.join(out).rstrip() + ('\n' if out else '')
        path.write_text(body, encoding='utf-8')

    _strip(scream_user_config_dir() / '.env')
    _strip(project_root() / '.env')


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


def read_mcp_server_command() -> str | None:
    """
    读取 MCP server 启动命令：
    - 优先 ``MCP_SERVER_COMMAND`` 环境变量 / .env
    - 无值时回退模块常量 ``MCP_SERVER_COMMAND``（默认 None）
    """
    load_project_dotenv()
    raw = read_project_dotenv_value('MCP_SERVER_COMMAND').strip()
    if raw:
        return raw
    fallback = (MCP_SERVER_COMMAND or '').strip()
    return fallback or None
