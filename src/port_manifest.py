from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .models import Subsystem

DEFAULT_SRC_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class PortManifest:
    src_root: Path
    total_python_files: int
    top_level_modules: tuple[Subsystem, ...]

    def to_markdown(self) -> str:
        lines = [
            f'移植根目录: `{self.src_root}`',
            f'Python 文件总数: **{self.total_python_files}**',
            '',
            '顶层 Python 模块:',
        ]
        for module in self.top_level_modules:
            lines.append(f'- `{module.name}` ({module.file_count} 个文件) — {module.notes}')
        return '\n'.join(lines)


def build_port_manifest(src_root: Path | None = None) -> PortManifest:
    root = src_root or DEFAULT_SRC_ROOT
    files = [path for path in root.rglob('*.py') if path.is_file()]
    counter = Counter(
        path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else path.name
        for path in files
        if path.name != '__pycache__'
    )
    notes = {
        '__init__.py': '包导出面',
        'main.py': 'CLI 入口',
        'port_manifest.py': '工作区清单生成',
        'query_engine.py': '移植编排摘要层',
        'commands.py': '命令积压元数据',
        'tools.py': '工具积压元数据',
        'models.py': '共享数据类',
        'task.py': '任务级规划结构',
    }
    modules = tuple(
        Subsystem(name=name, path=f'src/{name}', file_count=count, notes=notes.get(name, 'Python 移植支撑模块'))
        for name, count in counter.most_common()
    )
    return PortManifest(src_root=root, total_python_files=len(files), top_level_modules=modules)
