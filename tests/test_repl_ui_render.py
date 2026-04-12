"""展示层 repl_ui_render：无后端依赖的轻量断言。"""

from __future__ import annotations

import io
import unittest

from rich.console import Console

from src.repl_ui_render import (
    build_api_tool_op_renderable,
    prepare_streaming_live_buffer,
    stabilize_streaming_markdown_fences,
    tool_execution_status_message,
)
from src.scream_theme import skill_panel


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

    def test_stabilize_closes_trailing_fence(self) -> None:
        raw = '前言\n```python\nx = 1 +'
        out = stabilize_streaming_markdown_fences(raw)
        self.assertTrue(out.rstrip().endswith('```'))

    def test_stabilize_balanced_fence_noop(self) -> None:
        raw = '```python\npass\n```\nok'
        self.assertEqual(stabilize_streaming_markdown_fences(raw), raw)

    def test_prepare_viewport_shortens_tall_buffer(self) -> None:
        lines = [f'L{i:04d}' for i in range(200)]
        buf = '\n'.join(lines)
        c = Console(force_terminal=True, width=100, height=24)
        out = prepare_streaming_live_buffer(buf, console=c)
        self.assertIn('live fold', out)
        self.assertLess(out.count('\n'), buf.count('\n'))

    def test_skill_panel_slash_command_title_no_markup_error(self) -> None:
        """``[/cost]`` 等标题若以 str 传入 Panel，Rich 会误解析为闭合标签。"""
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80, record=True)
        c.print(skill_panel('ok', title='[/cost]', variant='accent'))
        self.assertIn('/cost', c.export_text(clear=False))


if __name__ == '__main__':
    unittest.main()
