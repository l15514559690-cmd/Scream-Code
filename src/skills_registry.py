from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path

from .skills.base_skill import SLASH_CATEGORY_ORDER, BaseSkill

_PACKAGE_SKILLS_DIR = Path(__file__).resolve().parent / 'skills'
_PACKAGE_SKILLS_PREFIX = 'src.skills'

# 补全菜单：排除单字符/占位别名（如 help 的 ``?``），避免无说明的 ``/?`` 噪声
_MIN_SLASH_COMPLETION_LEN = 2
_SLASH_COMPLETION_BLOCKLIST = frozenset({'?'})


def _valid_slash_completion_keyword(raw: str) -> bool:
    """主名或别名（不含前导 ``/``）是否应出现在终端补全列表中。"""
    t = (raw or '').strip().lstrip('/').lower()
    if not t or t in _SLASH_COMPLETION_BLOCKLIST:
        return False
    if len(t) < _MIN_SLASH_COMPLETION_LEN:
        return False
    return True


def _user_skills_dir() -> Path:
    """存在则扫描；不自动建目录（避免无写权限环境报错）。"""
    return Path.home() / '.scream' / 'skills'


def _skip_skill_file(name: str) -> bool:
    if name.startswith('_'):
        return True
    return name in {'__init__.py', 'base_skill.py'}


def _load_skill_module(path: Path) -> object | None:
    """包内模块用 importlib 包路径加载（保留相对导入）；用户目录仍按文件加载。"""
    try:
        path.resolve().relative_to(_PACKAGE_SKILLS_DIR.resolve())
    except ValueError:
        return _load_skill_module_from_file(path)
    qual = f'{_PACKAGE_SKILLS_PREFIX}.{path.stem}'
    if qual in sys.modules:
        return importlib.reload(sys.modules[qual])
    return importlib.import_module(qual)


def _load_skill_module_from_file(path: Path) -> object | None:
    mod_name = f'_scream_user_skill_{hash(path.resolve()) & 0xFFFF_FFFF:x}_{path.stem}'
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SkillsRegistry:
    """
    REPL 斜杠技能注册表：扫描 ``src/skills/*.py`` 与 ``~/.scream/skills/*.py``，
    收集 ``BaseSkill`` 子类实例。与 ``tools_registry.ToolsRegistry``（LLM 工具）正交。
    """

    def __init__(self) -> None:
        self._by_name: dict[str, BaseSkill] = {}
        self._alias: dict[str, str] = {}

    def reload_all(self) -> None:
        self._by_name.clear()
        self._alias.clear()
        i = 0
        user_root = _user_skills_dir()
        for root in (_PACKAGE_SKILLS_DIR, user_root):
            if not root.is_dir():
                continue
            override = root == user_root
            for path in sorted(root.glob('*.py')):
                if _skip_skill_file(path.name):
                    continue
                i = self._load_py(path, i, override=override)
        self._rebuild_aliases()

    def _rebuild_aliases(self) -> None:
        self._alias.clear()
        for sk in self._by_name.values():
            cls = type(sk)
            for a in cls.aliases:
                self._alias[a.lower().lstrip('/')] = sk.name

    def _load_py(self, path: Path, i: int, *, override: bool) -> int:
        i += 1
        try:
            mod = _load_skill_module(path)
        except Exception as exc:  # pragma: no cover
            print(f'[repl-skills] 跳过 {path}: {exc}', file=sys.stderr)
            return i
        if mod is None:
            return i
        for cls in _skill_classes_from_module(mod):
            try:
                inst = cls()
            except TypeError:
                continue
            n = (inst.name or '').strip().lower()
            if not n:
                print(f'[repl-skills] 跳过 {path}: 空 name', file=sys.stderr)
                continue
            if n in self._by_name and not override:
                continue
            self._by_name[n] = inst
        return i

    def get(self, key: str) -> BaseSkill | None:
        k = key.strip().lower().lstrip('/')
        if k in self._by_name:
            return self._by_name[k]
        primary = self._alias.get(k)
        return self._by_name.get(primary) if primary else None

    def skills_in_category(self, category: str) -> list[BaseSkill]:
        out = [s for s in self._by_name.values() if type(s).category == category]
        out.sort(key=lambda s: s.name)
        return out

    def all_skill_names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def list_skills(self) -> list[dict[str, str]]:
        """已注册斜杠技能（主名 + 说明），供补全/外部 UI 使用。"""
        out: list[dict[str, str]] = []
        for sk in sorted(self._by_name.values(), key=lambda s: s.name):
            out.append(
                {
                    'name': sk.name,
                    'description': (getattr(sk, 'description', None) or '').strip(),
                }
            )
        return out

    def iter_slash_completion_items(self) -> list[tuple[str, str]]:
        """
        终端 ``/`` 补全菜单：``('/cmd', '右侧 meta 说明')``。

        顺序与 ``/help`` 分类一致；含各技能 ``aliases``（过滤单字符与块名单如 ``?``）；
        无有效说明的技能不进入补全；末尾附加非 skill 桥接项（如 ``/clear``）。
        """
        items: list[tuple[str, str]] = []
        seen: set[str] = set()
        for cat in SLASH_CATEGORY_ORDER:
            for sk in self.skills_in_category(cat):
                desc_raw = (getattr(sk, 'description', None) or '').strip()
                if not desc_raw:
                    continue
                desc = desc_raw
                cls = type(sk)
                name_key = sk.name.strip().lower()
                if _valid_slash_completion_keyword(name_key):
                    primary = '/' + name_key
                    if primary not in seen:
                        seen.add(primary)
                        items.append((primary, desc))
                for raw_al in getattr(cls, 'aliases', ()) or ():
                    al = (raw_al or '').strip().lstrip('/').lower()
                    if not _valid_slash_completion_keyword(al):
                        continue
                    cmd = '/' + al
                    if cmd in seen:
                        continue
                    seen.add(cmd)
                    items.append((cmd, desc))
        for cmd, meta in (('/clear', '清屏（TUI 补全可用）'),):
            if cmd not in seen:
                seen.add(cmd)
                items.append((cmd, meta))
        return items


def _skill_classes_from_module(mod: object) -> list[type[BaseSkill]]:
    out: list[type[BaseSkill]] = []
    mod_name = getattr(mod, '__name__', '')
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if not issubclass(obj, BaseSkill) or obj is BaseSkill:
            continue
        if getattr(obj, '__module__', '') != mod_name:
            continue
        out.append(obj)
    return out


_registry: SkillsRegistry | None = None


def get_skills_registry() -> SkillsRegistry:
    global _registry
    if _registry is None:
        _registry = SkillsRegistry()
        _registry.reload_all()
    return _registry


def reset_skills_registry_for_tests() -> None:
    global _registry
    _registry = None


__all__ = [
    'SkillsRegistry',
    'get_skills_registry',
    'reset_skills_registry_for_tests',
]
