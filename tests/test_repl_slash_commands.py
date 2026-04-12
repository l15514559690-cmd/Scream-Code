from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.command_graph import CommandGraph
from src.models import PortingModule
from src.port_manifest import build_port_manifest
from src.query_engine import QueryEngineConfig, QueryEnginePort
from src.repl_slash_commands import dispatch_repl_slash_command
from src.session_store import StoredSession, save_session
from src.skills_registry import get_skills_registry, reset_skills_registry_for_tests


class ReplSlashCommandsTests(unittest.TestCase):
    def test_slash_completion_includes_look_from_registry(self) -> None:
        reset_skills_registry_for_tests()
        reg = get_skills_registry()
        cmds = [c for c, _ in reg.iter_slash_completion_items()]
        self.assertIn('/look', cmds)
        names = {d['name'] for d in reg.list_skills()}
        self.assertIn('look', names)

    def test_slash_completion_excludes_question_mark_alias(self) -> None:
        """help 的 ``?`` 别名不应出现在补全中（避免出现无规范说明的 ``/?``）。"""
        reset_skills_registry_for_tests()
        reg = get_skills_registry()
        cmds = [c for c, _ in reg.iter_slash_completion_items()]
        self.assertNotIn('/?', cmds)
        self.assertIn('/help', cmds)

    def test_non_slash_passthrough(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        h, ne, out = dispatch_repl_slash_command('hello', console=None, engine=eng)
        self.assertFalse(h)
        self.assertIsNone(ne)
        self.assertIsNone(out)

    def test_team_toggle_slash(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        self.assertFalse(eng.repl_team_mode)
        with patch('builtins.print'):
            h, _, _ = dispatch_repl_slash_command('/team', console=None, engine=eng)
        self.assertTrue(h)
        self.assertTrue(eng.repl_team_mode)
        with patch('builtins.print'):
            _, _, _ = dispatch_repl_slash_command('/team', console=None, engine=eng)
        self.assertFalse(eng.repl_team_mode)

    def test_unknown_slash_intercepted(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        with patch('builtins.print'):
            h, ne, _ = dispatch_repl_slash_command('/nope', console=None, engine=eng)
        self.assertTrue(h)
        self.assertIsNone(ne)

    def test_memo_inline_appends_without_llm(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                os.chdir(tmp)
                eng = QueryEnginePort(
                    build_port_manifest(),
                    config=QueryEngineConfig(llm_enabled=False),
                )
                with patch('builtins.print'):
                    with patch(
                        'src.project_memory.project_memory_workspace_root',
                        return_value=tmp_path,
                    ):
                        h, ne, _ = dispatch_repl_slash_command(
                            '/memo 记住当前使用 Rust 2021 edition',
                            console=None,
                            engine=eng,
                        )
                self.assertTrue(h)
                self.assertIsNone(ne)
                text = Path(tmp, 'SCREAM.md').read_text(encoding='utf-8')
                self.assertIn('Rust 2021 edition', text)
                self.assertIn('/memo', text)
        finally:
            os.chdir(old)

    def test_flush_clears_engine(self) -> None:
        eng = QueryEnginePort(
            build_port_manifest(),
            config=QueryEngineConfig(llm_enabled=True, max_budget_tokens=99_999),
        )
        eng.mutable_messages.append('u1')
        eng.repl_team_mode = True
        eng.total_usage = eng.total_usage.add_turn('a', 'b')
        old_sid = eng.session_id
        with patch('builtins.print'):
            h, ne, _ = dispatch_repl_slash_command('/flush', console=None, engine=eng)
        self.assertTrue(h)
        self.assertIsNone(ne)
        self.assertEqual(eng.mutable_messages, [])
        self.assertEqual(eng.llm_conversation_messages, [])
        self.assertFalse(eng.repl_team_mode)
        self.assertEqual(eng.total_usage.input_tokens, 0)
        self.assertEqual(eng.total_usage.output_tokens, 0)
        self.assertNotEqual(eng.session_id, old_sid)

    def test_load_swaps_engine_preserving_config(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                sid = 'test-sid-abc'
                save_session(
                    StoredSession(
                        session_id=sid,
                        messages=('m1', 'm2'),
                        input_tokens=3,
                        output_tokens=4,
                    )
                )
                eng = QueryEnginePort(
                    build_port_manifest(),
                    config=QueryEngineConfig(llm_enabled=True, max_turns=99),
                )
                eng.repl_team_mode = True
                with patch('builtins.print'):
                    h, new_eng, _ = dispatch_repl_slash_command(
                        f'/load {sid}',
                        console=None,
                        engine=eng,
                    )
                self.assertTrue(h)
                assert new_eng is not None
                self.assertEqual(new_eng.session_id, sid)
                self.assertEqual(new_eng.mutable_messages, ['m1', 'm2'])
                self.assertTrue(new_eng.config.llm_enabled)
                self.assertEqual(new_eng.config.max_turns, 99)
                self.assertTrue(new_eng.repl_team_mode)
        finally:
            os.chdir(old)

    def test_load_invalid_json(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, '.port_sessions').mkdir(parents=True)
                Path(tmp, '.port_sessions', 'bad.json').write_text('{', encoding='utf-8')
                eng = QueryEnginePort(build_port_manifest())
                with patch('builtins.print'):
                    h, ne, _ = dispatch_repl_slash_command('/load bad', console=None, engine=eng)
                self.assertTrue(h)
                self.assertIsNone(ne)
        finally:
            os.chdir(old)

    def test_sessions_lists_files(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(session_id='s1', messages=(), input_tokens=0, output_tokens=0)
                )
                eng = QueryEnginePort(build_port_manifest())
                with patch('builtins.print'):
                    h, ne, _ = dispatch_repl_slash_command('/sessions', console=None, engine=eng)
                self.assertTrue(h)
                self.assertIsNone(ne)
        finally:
            os.chdir(old)

    def test_new_hard_reset_like_flush(self) -> None:
        eng = QueryEnginePort(
            build_port_manifest(),
            config=QueryEngineConfig(llm_enabled=True, max_budget_tokens=99_999),
        )
        eng.mutable_messages.append('u1')
        eng.repl_team_mode = True
        eng.total_usage = eng.total_usage.add_turn('a', 'b')
        old_sid = eng.session_id
        with patch('builtins.print'):
            with patch('src.replLauncher.clear_all_repl_token_warnings') as clr:
                h, ne, _ = dispatch_repl_slash_command('/new', console=None, engine=eng)
        self.assertTrue(h)
        self.assertIsNone(ne)
        clr.assert_called_once()
        self.assertEqual(eng.mutable_messages, [])
        self.assertEqual(eng.llm_conversation_messages, [])
        self.assertFalse(eng.repl_team_mode)
        self.assertEqual(eng.total_usage.input_tokens, 0)
        self.assertEqual(eng.total_usage.output_tokens, 0)
        self.assertNotEqual(eng.session_id, old_sid)

    def test_summary_skips_store_when_declined(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                os.chdir(tmp)
                eng = QueryEnginePort(build_port_manifest())
                with patch('builtins.print'):
                    with patch(
                        'src.project_memory.project_memory_workspace_root',
                        return_value=tmp_path,
                    ):
                        with patch(
                            'src.skills.builtin_repl.confirm_store_summary', return_value=False
                        ):
                            h, ne, _ = dispatch_repl_slash_command('/summary', console=None, engine=eng)
                self.assertTrue(h)
                self.assertFalse(Path(tmp, 'SCREAM.md').exists())
        finally:
            os.chdir(old)

    def test_summary_stores_when_confirmed(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                os.chdir(tmp)
                eng = QueryEnginePort(build_port_manifest())
                with patch('builtins.print'):
                    with patch(
                        'src.project_memory.project_memory_workspace_root',
                        return_value=tmp_path,
                    ):
                        with patch(
                            'src.skills.builtin_repl.confirm_store_summary', return_value=True
                        ):
                            h, ne, _ = dispatch_repl_slash_command('/summary', console=None, engine=eng)
                self.assertTrue(h)
                text = Path(tmp, 'SCREAM.md').read_text(encoding='utf-8')
                self.assertIn('/summary', text)
                self.assertIn('会话 id', text)
        finally:
            os.chdir(old)

    def test_memo_writes_scream_when_llm_returns(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                os.chdir(tmp)
                eng = QueryEnginePort(
                    build_port_manifest(),
                    config=QueryEngineConfig(llm_enabled=True),
                )
                eng.mutable_messages.append('用户偏好：TypeScript')
                with patch('builtins.print'):
                    with patch(
                        'src.project_memory.project_memory_workspace_root',
                        return_value=tmp_path,
                    ):
                        with patch(
                            'src.skills.builtin_repl.memo_extract_via_llm',
                            return_value=('- 偏好 TS', None),
                        ):
                            h, ne, _ = dispatch_repl_slash_command('/memo', console=None, engine=eng)
                self.assertTrue(h)
                self.assertIsNone(ne)
                self.assertIn('偏好 TS', Path(tmp, 'SCREAM.md').read_text(encoding='utf-8'))
        finally:
            os.chdir(old)

    def test_memory_slash_set_list_drop(self) -> None:
        from src import memory_store
        from src.skills_registry import reset_skills_registry_for_tests

        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        old_env = os.environ.get('SCREAM_MEMORY_DB')
        eng = QueryEnginePort(build_port_manifest())
        try:
            os.environ['SCREAM_MEMORY_DB'] = path
            reset_skills_registry_for_tests()
            with patch('builtins.print'):
                h, ne, _ = dispatch_repl_slash_command(
                    '/memory set cli.demo hello world',
                    console=None,
                    engine=eng,
                )
            self.assertTrue(h)
            self.assertIsNone(ne)
            rows = memory_store.list_core_rules()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['key_name'], 'cli.demo')
            self.assertEqual(rows[0]['content'], 'hello world')
            with patch('builtins.print'):
                h2, ne2, _ = dispatch_repl_slash_command(
                    '/memory drop cli.demo',
                    console=None,
                    engine=eng,
                )
            self.assertTrue(h2)
            self.assertIsNone(ne2)
            self.assertEqual(memory_store.list_core_rules(), [])
        finally:
            if old_env is None:
                os.environ.pop('SCREAM_MEMORY_DB', None)
            else:
                os.environ['SCREAM_MEMORY_DB'] = old_env
            Path(path).unlink(missing_ok=True)
            reset_skills_registry_for_tests()

    def test_look_appends_multimodal_user_message(self) -> None:
        from src.skills_registry import reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        raw_png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
        )
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            png_path = str(Path(tmp) / 'cap.png')
            Path(png_path).write_bytes(raw_png)
            eng = QueryEnginePort(
                build_port_manifest(),
                config=QueryEngineConfig(llm_enabled=True),
            )
            with patch('builtins.print'):
                # reload_all 会 importlib.reload look_skill，勿 patch 该模块内的别名。
                with patch('src.browser_vision.BrowserVisionEngine') as mock_cls:
                    mock_cls.return_value.capture_page.return_value = png_path
                    h, ne, out = dispatch_repl_slash_command(
                        '/look https://example.com 看看布局',
                        console=None,
                        engine=eng,
                    )
            self.assertTrue(h)
            self.assertIsNone(ne)
            self.assertIsNotNone(out)
            self.assertTrue(out.trigger_llm_followup)
            self.assertEqual(out.followup_prompt.strip(), '看看布局')
            llm_msgs = eng.llm_conversation_messages
            self.assertEqual(len(llm_msgs), 1)
            self.assertEqual(llm_msgs[0].get('role'), 'user')
            content = llm_msgs[0].get('content')
            self.assertIsInstance(content, list)
            kinds = {p.get('type') for p in content if isinstance(p, dict)}
            self.assertIn('text', kinds)
            self.assertIn('image_url', kinds)
        reset_skills_registry_for_tests()

    def test_look_suppresses_followup_when_llm_disabled(self) -> None:
        from src.skills_registry import reset_skills_registry_for_tests

        reset_skills_registry_for_tests()
        raw_png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
        )
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            png_path = str(Path(tmp) / 'cap.png')
            Path(png_path).write_bytes(raw_png)
            eng = QueryEnginePort(
                build_port_manifest(),
                config=QueryEngineConfig(llm_enabled=False),
            )
            with patch('builtins.print'):
                # reload_all 会 importlib.reload look_skill，勿 patch 该模块内的别名。
                with patch('src.browser_vision.BrowserVisionEngine') as mock_cls:
                    mock_cls.return_value.capture_page.return_value = png_path
                    h, ne, out = dispatch_repl_slash_command(
                        '/look https://example.com',
                        console=None,
                        engine=eng,
                    )
            self.assertTrue(h)
            self.assertFalse(out.trigger_llm_followup)
            self.assertEqual(len(eng.llm_conversation_messages), 1)
        reset_skills_registry_for_tests()


def test_dispatch_config_no_console(
    capsys: pytest.CaptureFixture[str],
    mocker: Any,
) -> None:
    mocker.patch('src.model_manager.read_persisted_config_raw', return_value={'active': 'test-model'})
    eng = QueryEnginePort(build_port_manifest())
    h, ne, _ = dispatch_repl_slash_command('/config', console=None, engine=eng)
    assert h is True
    assert ne is None
    out = capsys.readouterr().out
    assert 'test-model' in out
    assert 'scream config' in out


def test_dispatch_skills_no_console(
    capsys: pytest.CaptureFixture[str],
    mocker: Any,
) -> None:
    fake_graph = CommandGraph(
        builtins=(),
        skill_like=(
            PortingModule(
                name='MockSkill',
                responsibility='',
                source_hint='skills',
                status='planned',
            ),
        ),
        plugin_like=(
            PortingModule(
                name='MockPlugin',
                responsibility='',
                source_hint='plugin',
                status='planned',
            ),
        ),
    )
    mocker.patch('src.repl_slash_helpers.build_command_graph', return_value=fake_graph)
    eng = QueryEnginePort(build_port_manifest())
    h, ne, _ = dispatch_repl_slash_command('/skills', console=None, engine=eng)
    assert h is True
    assert ne is None
    out = capsys.readouterr().out
    assert 'MockSkill' in out
    assert 'MockPlugin' in out
    assert 'Skill (技能)' in out
    assert 'Plugin (插件)' in out


if __name__ == '__main__':
    unittest.main()
