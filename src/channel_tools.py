"""
用户文件投递工具：通过 ``SCREAM_FRONTEND`` 等环境变量路由到终端提示或飞书魔法标签 stdout。

出站文件应落在项目根 ``.scream_cache/feishu_outbox/``（见工具描述）。Schema 由
``agent_tools.builtin_openai_tools_schema()`` 全局注册。
"""

from __future__ import annotations

import os
from typing import Any

from .utils.workspace import get_workspace_root

_SEND_FILE_DESC = (
    '当你需要向用户发送本地文件、生成的截图或代码压缩包时，调用此工具。\n'
    '【绝对规则】：你生成的所有临时文件（如截图、图表、zip包），必须保存在项目根目录下的 '
    '`.scream_cache/feishu_outbox/` 文件夹中，绝不允许保存在项目根目录！生成后，将绝对路径传给此工具即可。'
)

SEND_FILE_TO_USER_OPENAI_TOOL: dict[str, Any] = {
    'type': 'function',
    'function': {
        'name': 'send_file_to_user',
        'description': _SEND_FILE_DESC,
        'parameters': {
            'type': 'object',
            'properties': {
                'file_path': {
                    'type': 'string',
                    'description': (
                        '要发送文件的绝对路径；生成的新文件应位于项目根下 `.scream_cache/feishu_outbox/`。'
                    ),
                },
            },
            'required': ['file_path'],
        },
    },
}


def send_file_to_user(file_path: str) -> str:
    """飞书等侧车通过 stdout 拦截 ``[FEISHU_FILE:...]``；终端场景仅返回路径说明。"""
    try:
        os.makedirs(
            os.path.join(get_workspace_root(), '.scream_cache', 'feishu_outbox'),
            exist_ok=True,
        )
    except OSError:
        pass

    raw = (file_path or '').strip()
    if not raw:
        return 'Error: file_path 不能为空。'
    abs_path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.exists(abs_path):
        return f'Error: 文件 {abs_path} 不存在。'

    if os.getenv('SCREAM_FRONTEND') == 'feishu':
        print(f'\n[FEISHU_FILE:{abs_path}]\n', flush=True)
        return '指令已下发，文件已交由 IM 网关传输给用户。'
    return f'文件已准备就绪，存放在: {abs_path}'
