from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def config_file() -> Path:
    from .llm_settings import scream_user_config_dir

    return scream_user_config_dir() / 'llm_config.json'


def _migrate_legacy_repo_llm_config_if_needed() -> None:
    """若 ``~/.scream/llm_config.json`` 不存在而仓库根仍有旧文件，则迁移一次。"""
    dst = config_file()
    if dst.is_file():
        return
    legacy = Path(__file__).resolve().parent.parent / 'llm_config.json'
    if not legacy.is_file():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(legacy.read_text(encoding='utf-8'), encoding='utf-8')
    except OSError:
        pass


def empty_config_payload() -> dict[str, Any]:
    return {'active': None, 'models': [], 'allow_global_access': False}


def read_allow_global_access(raw: dict[str, Any] | None = None) -> bool:
    """
    读取 ``llm_config.json`` 根字段 ``allow_global_access``。
    缺省或非布尔可识别值时视为 ``False``（沙箱模式，仅工作区）。
    """
    if raw is None:
        raw = read_persisted_config_raw()
    if raw is None:
        return False
    v = raw.get('allow_global_access', False)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'on')
    return False


def toggle_allow_global_access() -> bool:
    """翻转 ``allow_global_access`` 并落盘；返回切换后的新值（``True`` 为全局越狱）。"""
    ensure_default_config_file()
    raw = read_persisted_config_raw()
    if raw is None:
        raw = empty_config_payload()
    nxt = not read_allow_global_access(raw)
    raw['allow_global_access'] = nxt
    raw.setdefault('models', [])
    if 'active' not in raw:
        raw['active'] = None
    save_config(raw)
    return nxt


@dataclass
class ModelProfile:
    id: str
    alias: str
    base_url: str
    model_name: str
    api_key_env_name: str
    #: ``openai`` 或 ``anthropic``。
    api_protocol: str = 'openai'


def ensure_default_config_file() -> None:
    _migrate_legacy_repo_llm_config_if_needed()
    path = config_file()
    if path.is_file():
        return
    save_config(empty_config_payload())


def read_persisted_config_raw() -> dict[str, Any] | None:
    path = config_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def save_config(data: dict[str, Any]) -> None:
    path = config_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _profiles_from_raw(raw: dict[str, Any]) -> list[ModelProfile]:
    out: list[ModelProfile] = []
    for item in raw.get('models', []):
        if not isinstance(item, dict):
            continue
        try:
            proto = str(item.get('api_protocol', 'openai')).strip().lower()
            if proto not in ('openai', 'anthropic'):
                proto = 'openai'
            out.append(
                ModelProfile(
                    id=str(item['id']).strip(),
                    alias=str(item['alias']).strip(),
                    base_url=str(item['base_url']).strip(),
                    model_name=str(item['model_name']).strip(),
                    api_key_env_name=str(item['api_key_env_name']).strip(),
                    api_protocol=proto,
                )
            )
        except KeyError:
            continue
    return out


def slug_id(alias: str) -> str:
    s = alias.strip().lower()
    s = re.sub(r'[^\w\u4e00-\u9fff]+', '-', s, flags=re.UNICODE)
    s = re.sub(r'-+', '-', s).strip('-')
    return s or 'model'


def _validate_env_key_name(name: str) -> bool:
    return bool(name) and bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name))


def api_key_env_base_from_alias(alias: str) -> str:
    """
    将别名转为大写、可用于环境变量前缀的 ASCII 片段（不含 _API_KEY 后缀）。
    纯中文等无字母数字时，使用 PROFILE_<哈希> 兜底。
    """
    s = re.sub(r'[^A-Za-z0-9]+', '_', alias.strip())
    s = re.sub(r'_+', '_', s).strip('_').upper()
    if not s:
        digest = hashlib.md5(alias.encode('utf-8')).hexdigest()[:10].upper()
        return f'PROFILE_{digest}'
    if s[0].isdigit():
        return f'P_{s}'
    return s


def allocate_api_key_env_name(
    alias: str,
    raw: dict[str, Any],
    *,
    ignore_profile_id: str | None = None,
) -> str:
    """生成 ``{别名衍生}_API_KEY``，与同配置内其它条目不冲突。"""
    stem = api_key_env_base_from_alias(alias)
    used = {
        p.api_key_env_name
        for p in _profiles_from_raw(raw)
        if ignore_profile_id is None or p.id != ignore_profile_id
    }
    base_key = f'{stem}_API_KEY'
    if base_key not in used:
        return base_key
    for n in range(2, 10_000):
        cand = f'{stem}_{n}_API_KEY'
        if cand not in used:
            return cand
    digest = hashlib.md5(alias.encode('utf-8')).hexdigest()[:8].upper()
    return f'{stem}_{digest}_API_KEY'


def get_active_profile(raw: dict[str, Any]) -> ModelProfile | None:
    profiles = _profiles_from_raw(raw)
    if not profiles:
        return None
    active = raw.get('active', None)
    if active is None or (isinstance(active, str) and not active.strip()):
        return None
    active_id = str(active).strip()
    for p in profiles:
        if p.id == active_id:
            return p
    return None


def set_active(profile_id: str | None) -> bool:
    raw = read_persisted_config_raw()
    if raw is None:
        return False
    if profile_id is None:
        raw['active'] = None
        save_config(raw)
        return True
    ids = {p.id for p in _profiles_from_raw(raw)}
    if profile_id not in ids:
        return False
    raw['active'] = profile_id
    save_config(raw)
    return True


def add_model(profile: ModelProfile) -> None:
    raw = read_persisted_config_raw()
    if raw is None:
        raw = empty_config_payload()
    models = _profiles_from_raw(raw)
    existing_ids = {m.id for m in models}
    pid = profile.id
    n = 2
    while pid in existing_ids:
        pid = f'{profile.id}-{n}'
        n += 1
    profile = ModelProfile(
        id=pid,
        alias=profile.alias,
        base_url=profile.base_url,
        model_name=profile.model_name,
        api_key_env_name=profile.api_key_env_name,
        api_protocol=profile.api_protocol,
    )
    raw.setdefault('models', [])
    raw['models'].append(asdict(profile))
    raw['active'] = profile.id
    save_config(raw)


def replace_profile_by_id(profile_id: str, new_profile: ModelProfile) -> None:
    raw = read_persisted_config_raw()
    if raw is None:
        raise ValueError('无配置')
    items = raw.get('models', [])
    new_list = []
    found = False
    for item in items:
        if isinstance(item, dict) and str(item.get('id', '')).strip() == profile_id:
            new_list.append(
                asdict(
                    ModelProfile(
                        id=profile_id,
                        alias=new_profile.alias,
                        base_url=new_profile.base_url,
                        model_name=new_profile.model_name,
                        api_key_env_name=new_profile.api_key_env_name,
                        api_protocol=new_profile.api_protocol,
                    )
                )
            )
            found = True
        else:
            new_list.append(item)
    if not found:
        raise ValueError('未找到模型')
    raw['models'] = new_list
    save_config(raw)


def delete_profile(profile_id: str) -> ModelProfile | None:
    """从配置中移除模型；若删除的是 active，将 active 置空。返回被删条目（若存在）。"""
    raw = read_persisted_config_raw()
    if raw is None:
        return None
    removed: ModelProfile | None = None
    new_models: list[dict[str, Any]] = []
    for item in raw.get('models', []):
        if not isinstance(item, dict):
            continue
        try:
            proto = str(item.get('api_protocol', 'openai')).strip().lower()
            if proto not in ('openai', 'anthropic'):
                proto = 'openai'
            p = ModelProfile(
                id=str(item['id']).strip(),
                alias=str(item['alias']).strip(),
                base_url=str(item['base_url']).strip(),
                model_name=str(item['model_name']).strip(),
                api_key_env_name=str(item['api_key_env_name']).strip(),
                api_protocol=proto,
            )
        except KeyError:
            continue
        if p.id == profile_id:
            removed = p
            continue
        new_models.append(item)
    raw['models'] = new_models
    if raw.get('active') == profile_id:
        raw['active'] = None
    save_config(raw)
    return removed


def format_status_lines(raw: dict[str, Any]) -> list[str]:
    perm = '全局越狱' if read_allow_global_access(raw) else '沙箱模式'
    lines = [f'系统操作权限：{perm}（allow_global_access）']
    p = get_active_profile(raw)
    if p is None:
        lines.append('（当前无激活模型）')
        return lines
    lines.extend(
        [
            f'当前：{p.alias}（{p.id}）',
            f'协议：{"Anthropic 兼容" if p.api_protocol == "anthropic" else "OpenAI 兼容"}（{p.api_protocol}）',
            f'Base URL：{p.base_url}',
            f'模型：{p.model_name}',
            f'密钥变量：{p.api_key_env_name}（从 .env 读取）',
        ]
    )
    return lines


# 二级菜单统一「返回」值（与 questionary 选项 value 对应）
_MENU_BACK = '__menu_back__'


def _norm_protocol(p: str | None) -> str:
    return 'anthropic' if (p or '').strip().lower() == 'anthropic' else 'openai'


def _choice_back(title: str = '« 返回上一级') -> Any:
    import questionary

    return questionary.Choice(title=title, value=_MENU_BACK)


def _prompt_text(
    style: Any,
    message: str,
    *,
    default: str = '',
    required: bool = True,
) -> str | None:
    """
    文本输入；Ctrl+C / 输入 q 视为取消（返回 None）。
    ``required`` 为 True 时，除使用 default 直接回车外，不得提交空串。
    """
    import questionary

    hint = f'{message}\n（输入 q 放弃并返回主菜单）'
    raw = questionary.text(hint, default=default, style=style).ask()
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() == 'q':
        return None
    if not s:
        if default and not required:
            return default
        if required and default:
            return default.strip() or None
        if required:
            return None
        return ''
    return s


def _prompt_api_protocol(style: Any, *, default: str = 'openai') -> str | None:
    """返回 ``openai`` / ``anthropic``，或 ``None``（返回上一级 / 取消）。"""
    import questionary

    d = _norm_protocol(default)
    choice = questionary.select(
        '接口协议',
        choices=[
            questionary.Choice(title='OpenAI 兼容', value='openai'),
            questionary.Choice(title='Anthropic 兼容', value='anthropic'),
            _choice_back(),
        ],
        default=d,
        style=style,
    ).ask()
    if choice is None or choice == _MENU_BACK:
        return None
    return _norm_protocol(str(choice))


def _prompt_connection_fields(
    style: Any,
    *,
    defaults: ModelProfile | None = None,
) -> tuple[str, str, str] | None:
    """别名、Base URL、模型名；任一步取消则返回 None。"""
    alias_d = defaults.alias if defaults else ''
    url_d = defaults.base_url if defaults else ''
    model_d = defaults.model_name if defaults else ''

    alias = _prompt_text(style, '配置别名：', default=alias_d, required=True)
    if alias is None:
        return None
    base_url = _prompt_text(style, 'Base URL：', default=url_d, required=True)
    if base_url is None:
        return None
    model_name = _prompt_text(style, '模型名称：', default=model_d, required=True)
    if model_name is None:
        return None
    return (
        alias.strip(),
        base_url.strip().rstrip('/'),
        model_name.strip(),
    )


def _prompt_api_key_required(style: Any) -> str | None:
    import questionary

    while True:
        hint = 'API Key：\n（不可为空；输入 q 放弃并返回主菜单）'
        raw = questionary.text(hint, default='', style=style).ask()
        if raw is None:
            return None
        s = str(raw).strip()
        if s.lower() == 'q':
            return None
        if s:
            return s
        print('API Key 不能为空，请重新输入。', file=sys.stderr)


def _prompt_api_key_optional(style: Any) -> str | None:
    """
    返回 ``None`` 表示取消；空串表示不修改密钥；非空表示新密钥。
    """
    import questionary

    hint = (
        'API Key（留空不修改；输入新值写入 .env；输入 q 放弃并返回主菜单）：'
    )
    raw = questionary.text(hint, default='', style=style).ask()
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() == 'q':
        return None
    return s


def run_add_model_interactive(style: Any, *, announce_done: bool = True) -> bool:
    """添加模型：子菜单 → 协议 → 手动 URL/型号/Key；成功返回 True。"""
    from .llm_settings import reload_project_dotenv, upsert_project_dotenv_var

    import questionary

    step = questionary.select(
        '添加新模型',
        choices=[
            questionary.Choice(title='开始填写', value='go'),
            _choice_back('返回上一级（主菜单）'),
        ],
        style=style,
    ).ask()
    if step is None or step != 'go':
        return False

    ensure_default_config_file()
    raw = read_persisted_config_raw()
    if raw is None:
        raw = empty_config_payload()
        save_config(raw)
        raw = read_persisted_config_raw()
    assert raw is not None

    proto = _prompt_api_protocol(style, default='openai')
    if proto is None:
        print('已返回。', file=sys.stderr)
        return False
    fields = _prompt_connection_fields(style, defaults=None)
    if fields is None:
        print('已取消。', file=sys.stderr)
        return False
    alias, base_url, model_name = fields
    env_name = allocate_api_key_env_name(alias, raw)
    if not _validate_env_key_name(env_name):
        print('无法生成合法的环境变量名', file=sys.stderr)
        return False

    api_key = _prompt_api_key_required(style)
    if api_key is None:
        print('已取消。', file=sys.stderr)
        return False

    upsert_project_dotenv_var(env_name, api_key)
    reload_project_dotenv()

    pid = slug_id(alias)
    add_model(
        ModelProfile(
            id=pid,
            alias=alias,
            base_url=base_url,
            model_name=model_name,
            api_key_env_name=env_name,
            api_protocol=proto,
        )
    )
    if announce_done:
        print('已添加并设为当前')
    return True


def run_switch_model_interactive(style: Any, raw: dict[str, Any]) -> None:
    import questionary

    profiles = _profiles_from_raw(raw)
    if not profiles:
        print('暂无模型', file=sys.stderr)
        return
    choices: list[Any] = [_choice_back()]
    choices.extend(
        questionary.Choice(title=f'{p.alias}（{p.id}）', value=p.id) for p in profiles
    )
    choice = questionary.select('切换当前模型', choices=choices, style=style).ask()
    if choice is None or choice == _MENU_BACK:
        return
    set_active(str(choice))
    print('已切换')


def run_edit_model_interactive(style: Any, raw: dict[str, Any]) -> None:
    import questionary

    from .llm_settings import (
        migrate_project_dotenv_key,
        reload_project_dotenv,
        upsert_project_dotenv_var,
    )

    profiles = _profiles_from_raw(raw)
    if not profiles:
        print('暂无模型', file=sys.stderr)
        return
    choices: list[Any] = [_choice_back()]
    choices.extend(
        questionary.Choice(title=f'{p.alias}（{p.id}）', value=p.id) for p in profiles
    )
    choice = questionary.select('修改已有模型', choices=choices, style=style).ask()
    if choice is None or choice == _MENU_BACK:
        return
    target = next(p for p in profiles if p.id == choice)

    proto = _prompt_api_protocol(style, default=target.api_protocol)
    if proto is None:
        print('已取消。', file=sys.stderr)
        return
    fields = _prompt_connection_fields(style, defaults=target)
    if fields is None:
        print('已取消。', file=sys.stderr)
        return
    alias, base_url, model_name = fields
    env_name = allocate_api_key_env_name(alias, raw, ignore_profile_id=target.id)
    if not _validate_env_key_name(env_name):
        print('无法生成合法的环境变量名', file=sys.stderr)
        return

    new_key_reply = _prompt_api_key_optional(style)
    if new_key_reply is None:
        print('已取消。', file=sys.stderr)
        return

    old_env = target.api_key_env_name

    if env_name != old_env:
        if new_key_reply:
            migrate_project_dotenv_key(old_env, env_name)
            upsert_project_dotenv_var(env_name, new_key_reply)
        else:
            migrate_project_dotenv_key(old_env, env_name)
    elif new_key_reply:
        upsert_project_dotenv_var(env_name, new_key_reply)

    reload_project_dotenv()

    replace_profile_by_id(
        target.id,
        ModelProfile(
            id=target.id,
            alias=alias,
            base_url=base_url,
            model_name=model_name,
            api_key_env_name=env_name,
            api_protocol=proto,
        ),
    )
    print('已更新')


def run_delete_model_interactive(style: Any, raw: dict[str, Any]) -> None:
    import questionary

    from .llm_settings import reload_project_dotenv, remove_project_dotenv_var

    profiles = _profiles_from_raw(raw)
    if not profiles:
        print('暂无模型', file=sys.stderr)
        return
    choices: list[Any] = [_choice_back()]
    choices.extend(
        questionary.Choice(title=f'{p.alias}（{p.id}）', value=p.id) for p in profiles
    )
    choice = questionary.select('删除已有模型', choices=choices, style=style).ask()
    if choice is None or choice == _MENU_BACK:
        return
    if not questionary.confirm('确定删除该模型配置？', default=False, style=style).ask():
        return
    if not questionary.confirm('此操作不可恢复，再次确认删除？', default=False, style=style).ask():
        return
    removed = delete_profile(str(choice))
    if removed:
        remove_project_dotenv_var(removed.api_key_env_name)
        reload_project_dotenv()
        print('已删除')
    else:
        print('删除失败', file=sys.stderr)


def run_config_interactive_menu() -> int:
    from .replLauncher import print_project_memory_loaded_notice, print_startup_banner

    import questionary
    from questionary import Style

    style = Style([('selected', 'fg:ansicyan bold')])
    print_startup_banner(compact=True)
    print_project_memory_loaded_notice()
    ensure_default_config_file()
    while True:
        raw = read_persisted_config_raw()
        if raw is None:
            print('无法读取 llm_config.json', file=sys.stderr)
            return 1
        aga = read_allow_global_access(raw)
        toggle_label = (
            f'🔓 切换系统操作权限 (当前: {"全局越狱" if aga else "沙箱模式"})'
        )
        action = questionary.select(
            '模型配置（主菜单）',
            choices=[
                toggle_label,
                '切换当前模型',
                '添加新模型',
                '修改已有模型',
                '删除已有模型',
                '查看当前状态',
                '退出',
            ],
            style=style,
        ).ask()
        if action is None or action == '退出':
            return 0
        if action == toggle_label:
            new_val = toggle_allow_global_access()
            if new_val:
                print(
                    '已开启【全局越狱】：工具可访问任意路径，bash 在用户主目录下执行。'
                    '请谨慎使用，勿执行不可信指令。'
                )
            else:
                print(
                    '已恢复【沙箱模式】：文件读写与 bash 均限制在当前工作区，更安全。'
                )
            continue
        if action == '查看当前状态':
            print('\n'.join(format_status_lines(raw)))
            continue
        if action == '切换当前模型':
            run_switch_model_interactive(style, raw)
            continue
        if action == '添加新模型':
            run_add_model_interactive(style, announce_done=True)
            continue
        if action == '修改已有模型':
            run_edit_model_interactive(style, raw)
            continue
        if action == '删除已有模型':
            run_delete_model_interactive(style, raw)
            continue
