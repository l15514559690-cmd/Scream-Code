"""Tests for send_file_to_user and global tools registry wiring."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import channel_tools
from src.query_engine import QueryEnginePort
from src.tools_registry import get_tools_registry, reset_tools_registry_for_tests


class TestSendFileToUser(unittest.TestCase):
    def test_missing_file_returns_error(self) -> None:
        err = channel_tools.send_file_to_user('/nonexistent/path/feishu_test_abc123.bin')
        self.assertIn('不存在', err)
        self.assertNotIn('[FEISHU_FILE:', err)

    def test_feishu_frontend_prints_tag(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            path = f.name
            f.write(b'x')
        try:
            buf = io.StringIO()
            with patch.object(sys, 'stdout', buf):
                with patch.dict(os.environ, {'SCREAM_FRONTEND': 'feishu'}, clear=False):
                    out = channel_tools.send_file_to_user(path)
            self.assertIn('IM 网关', out)
            printed = buf.getvalue()
            self.assertIn('[FEISHU_FILE:', printed)
            self.assertIn(os.path.abspath(path), printed)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_terminal_frontend_returns_path_only(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            path = f.name
            f.write(b'y')
        try:
            buf = io.StringIO()
            with patch.object(sys, 'stdout', buf):
                with patch.dict(os.environ, {'SCREAM_FRONTEND': 'tui'}, clear=False):
                    out = channel_tools.send_file_to_user(path)
            self.assertIn('文件已准备就绪', out)
            self.assertIn(os.path.abspath(path), out)
            self.assertEqual(buf.getvalue(), '')
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class TestToolsRegistrySendFileToUser(unittest.TestCase):
    def tearDown(self) -> None:
        reset_tools_registry_for_tests()

    def test_schema_in_global_agent_tools_list(self) -> None:
        reg = get_tools_registry()
        reg.reload_all()
        names: set[str] = set()
        for schema in reg.get_all_schemas():
            fn = schema.get('function')
            if isinstance(fn, dict):
                n = str(fn.get('name') or '').strip()
                if n:
                    names.add(n)
        self.assertIn('send_file_to_user', names)

    def test_execute_tool_feishu_prints_tag(self) -> None:
        reg = get_tools_registry()
        reg.reload_all()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            path = f.name
            f.write(b'z')
        try:
            buf = io.StringIO()
            with patch.object(sys, 'stdout', buf):
                with patch.dict(os.environ, {'SCREAM_FRONTEND': 'feishu'}, clear=False):
                    out = reg.execute_tool('send_file_to_user', {'file_path': path})
            self.assertIn('网关', out)
            self.assertIn('[FEISHU_FILE:', buf.getvalue())
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class TestQueryEngineMergedTools(unittest.TestCase):
    def test_merged_tools_include_send_file_to_user(self) -> None:
        eng = QueryEnginePort.from_workspace()
        merged = eng._merged_openai_tools()
        names = {
            str(item.get('function', {}).get('name', ''))
            for item in merged
            if isinstance(item, dict) and isinstance(item.get('function'), dict)
        }
        self.assertIn('send_file_to_user', names)


if __name__ == '__main__':
    unittest.main()
