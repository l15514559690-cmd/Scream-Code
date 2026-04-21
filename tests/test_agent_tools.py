from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent_tools import (
    execute_mac_bash,
    read_local_file,
    run_agent_tool,
    update_project_memory,
    write_local_file,
)


class AgentToolsTests(unittest.TestCase):
    def tearDown(self) -> None:
        from src.skills_registry import reset_skills_registry_for_tests
        from src.tools_registry import reset_tools_registry_for_tests

        reset_tools_registry_for_tests()
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

    def test_tools_registry_includes_core_tools(self) -> None:
        from src.tools_registry import get_tools_registry, reset_tools_registry_for_tests

        reset_tools_registry_for_tests()
        rows = get_tools_registry().list_tool_rows()
        names = {r['name'] for r in rows}
        self.assertIn('read_local_file', names)
        self.assertIn('install_local_skill', names)
        self.assertIn('update_project_memory', names)
        self.assertIn('memorize_project_rule', names)
        self.assertIn('forget_project_rule', names)

    def test_repl_skills_registry_routes_help(self) -> None:
        from src.skills_registry import get_skills_registry, reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        self.assertIsNotNone(get_skills_registry().get('help'))
        self.assertIsNotNone(get_skills_registry().get('?'))

    def test_diff_skill_loaded_from_standalone_module(self) -> None:
        from src.skills_registry import get_skills_registry, reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        sk = get_skills_registry().get('diff')
        self.assertIsNotNone(sk)
        self.assertEqual(sk.__class__.__name__, 'DiffSkill')
        self.assertEqual(sk.__class__.__module__, 'src.skills.diff_skill')

    def test_memory_slash_skill_registered(self) -> None:
        from src.skills_registry import get_skills_registry, reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        self.assertEqual(get_skills_registry().get('memory').__class__.__module__, 'src.skills.memory_skill')

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

    def test_run_agent_tool_long_term_memory_roundtrip(self) -> None:
        from src.tools_registry import reset_tools_registry_for_tests

        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        old_env = os.environ.get('SCREAM_MEMORY_DB')
        try:
            os.environ['SCREAM_MEMORY_DB'] = path
            reset_tools_registry_for_tests()
            out = run_agent_tool(
                'memorize_project_rule',
                '{"key_name": "lint.ruff", "content": "Use ruff for Python lint."}',
            )
            self.assertIn('已记入', out)
            out_del = run_agent_tool('forget_project_rule', '{"key_name": "lint.ruff"}')
            self.assertIn('删除', out_del)
        finally:
            if old_env is None:
                os.environ.pop('SCREAM_MEMORY_DB', None)
            else:
                os.environ['SCREAM_MEMORY_DB'] = old_env
            Path(path).unlink(missing_ok=True)
            reset_tools_registry_for_tests()

    def test_execute_mac_bash_routes_to_docker_sandbox_when_enabled(self) -> None:
        from src.sandbox_env import SandboxManager

        mgr = SandboxManager.instance()
        prev = mgr.is_sandbox_enabled
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_res = Path(tmp).resolve()
                os.chdir(tmp)
                mgr.is_sandbox_enabled = True
                with patch('src.agent_tools._workspace_root', return_value=tmp_res):
                    with patch.object(mgr, 'execute_in_sandbox', return_value='DOCKER_OK') as m:
                        self.assertEqual(execute_mac_bash('echo 1'), 'DOCKER_OK')
                        m.assert_called_once()
                        cmd, ws = m.call_args[0]
                        self.assertEqual(cmd, 'echo 1')
                        self.assertEqual(Path(ws).resolve(), tmp_res)
        finally:
            mgr.is_sandbox_enabled = prev
            os.chdir(old)

    def test_sandbox_execute_rejects_missing_workspace_dir(self) -> None:
        from src.sandbox_env import SandboxManager

        out = SandboxManager.instance().execute_in_sandbox('true', '/no/such/dir/scream_sandbox_test')
        self.assertIn('无效', out)

    def test_sandbox_slash_skill_toggles_manager(self) -> None:
        from src.port_manifest import build_port_manifest
        from src.query_engine import QueryEnginePort
        from src.repl_slash_commands import dispatch_repl_slash_command
        from src.sandbox_env import SandboxManager
        from src.skills_registry import reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        mgr = SandboxManager.instance()
        prev = mgr.is_sandbox_enabled
        eng = QueryEnginePort(build_port_manifest())
        try:
            mgr.is_sandbox_enabled = False
            with patch('builtins.print'):
                h, ne, _ = dispatch_repl_slash_command('/sandbox on', console=None, engine=eng)
            self.assertTrue(h)
            self.assertIsNone(ne)
            self.assertTrue(mgr.is_sandbox_enabled)
            with patch('builtins.print'):
                _, _, _ = dispatch_repl_slash_command('/sandbox off', console=None, engine=eng)
            self.assertFalse(mgr.is_sandbox_enabled)
        finally:
            mgr.is_sandbox_enabled = prev


if __name__ == '__main__':
    unittest.main()
