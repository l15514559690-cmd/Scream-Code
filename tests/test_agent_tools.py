from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent_tools import (
    read_local_file,
    run_agent_tool,
    update_project_memory,
    write_local_file,
)


class AgentToolsTests(unittest.TestCase):
    def tearDown(self) -> None:
        from src.skills_registry import reset_skills_registry_for_tests

        reset_skills_registry_for_tests()

    def test_read_write_roundtrip_under_workspace(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                write_local_file('sub/hi.txt', 'hello')
                self.assertEqual(read_local_file('sub/hi.txt'), 'hello')
        finally:
            os.chdir(old)

    def test_rejects_path_outside_workspace(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                with patch('src.model_manager.read_allow_global_access', return_value=False):
                    with self.assertRaises(ValueError):
                        read_local_file('../../../etc/passwd')
        finally:
            os.chdir(old)

    def test_global_access_reads_outside_workspace(self) -> None:
        old = os.getcwd()
        outer_path = ''
        try:
            with tempfile.TemporaryDirectory() as inner:
                parent = Path(inner).resolve().parent
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    delete=False,
                    suffix='.txt',
                    encoding='utf-8',
                    dir=str(parent),
                ) as f:
                    f.write('sekret')
                    outer_path = f.name
                os.chdir(inner)
                with patch('src.model_manager.read_allow_global_access', return_value=True):
                    self.assertEqual(read_local_file(outer_path), 'sekret')
        finally:
            os.chdir(old)
            if outer_path:
                try:
                    os.unlink(outer_path)
                except OSError:
                    pass

    def test_run_agent_tool_json_error(self) -> None:
        out = run_agent_tool('read_local_file', '{not json')
        self.assertIn('无法解析', out)

    def test_run_agent_tool_unknown(self) -> None:
        out = run_agent_tool('nope', '{}')
        self.assertIn('未知工具', out)

    def test_skills_registry_includes_core_tools(self) -> None:
        from src.skills_registry import get_skills_registry, reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        rows = get_skills_registry().list_skill_rows()
        names = {r['name'] for r in rows}
        self.assertIn('read_local_file', names)
        self.assertIn('install_local_skill', names)
        self.assertIn('update_project_memory', names)

    def test_update_project_memory_append_and_overwrite(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertIn('已更新', update_project_memory('A', mode='append'))
                self.assertEqual(Path(tmp, 'SCREAM.md').read_text(encoding='utf-8'), 'A')
                self.assertIn('已更新', update_project_memory('B', mode='append'))
                self.assertIn('A', Path(tmp, 'SCREAM.md').read_text(encoding='utf-8'))
                self.assertIn('B', Path(tmp, 'SCREAM.md').read_text(encoding='utf-8'))
                self.assertIn('已更新', update_project_memory('Z', mode='overwrite'))
                self.assertEqual(Path(tmp, 'SCREAM.md').read_text(encoding='utf-8'), 'Z')
        finally:
            os.chdir(old)

    def test_run_agent_tool_update_project_memory(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                out = run_agent_tool('update_project_memory', '{"content": "mem"}')
                self.assertIn('已更新', out)
        finally:
            os.chdir(old)


if __name__ == '__main__':
    unittest.main()
