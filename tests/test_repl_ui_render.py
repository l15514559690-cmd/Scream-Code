"""展示层 repl_ui_render：无后端依赖的轻量断言。"""

from __future__ import annotations

import io
import unittest

from rich.console import Console

from src.repl_ui_render import build_api_tool_op_renderable, tool_execution_status_message


class ReplUiRenderTests(unittest.TestCase):
    def test_tool_status_message(self) -> None:
        s = tool_execution_status_message('write_local_file')
        self.assertIn('write_local_file', s)
        self.assertIn('写入文件', s)

    def test_write_file_panel_renders(self) -> None:
        ev = {
            'type': 'api_tool_op',
            'tool_name': 'write_local_file',
            'arguments': '{"file_path":"x.py","content":"a = 1\\n"}',
        }
        r = build_api_tool_op_renderable(ev)
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80, record=True)
        c.print(r)
        out = c.export_text(clear=False)
        self.assertIn('x.py', out)
        self.assertIn('a = 1', out)

    def test_bash_panel_renders(self) -> None:
        ev = {
            'type': 'api_tool_op',
            'tool_name': 'execute_mac_bash',
            'arguments': '{"command":"echo hi"}',
        }
        r = build_api_tool_op_renderable(ev)
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=60, record=True)
        c.print(r)
        self.assertIn('echo hi', c.export_text(clear=False))


if __name__ == '__main__':
    unittest.main()
