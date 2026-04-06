from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.port_manifest import build_port_manifest
from src.query_engine import QueryEngineConfig, QueryEnginePort
from src.repl_slash_commands import dispatch_repl_slash_command
from src.session_store import StoredSession, save_session


class ReplSlashCommandsTests(unittest.TestCase):
    def test_non_slash_passthrough(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        h, ne = dispatch_repl_slash_command('hello', console=None, engine=eng)
        self.assertFalse(h)
        self.assertIsNone(ne)

    def test_team_toggle_slash(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        self.assertFalse(eng.repl_team_mode)
        with patch('builtins.print'):
            h, _ = dispatch_repl_slash_command('/team', console=None, engine=eng)
        self.assertTrue(h)
        self.assertTrue(eng.repl_team_mode)
        with patch('builtins.print'):
            dispatch_repl_slash_command('/team', console=None, engine=eng)
        self.assertFalse(eng.repl_team_mode)

    def test_unknown_slash_intercepted(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        with patch('builtins.print'):
            h, ne = dispatch_repl_slash_command('/nope', console=None, engine=eng)
        self.assertTrue(h)
        self.assertIsNone(ne)

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
            h, ne = dispatch_repl_slash_command('/flush', console=None, engine=eng)
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
                    h, new_eng = dispatch_repl_slash_command(
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
                    h, ne = dispatch_repl_slash_command('/load bad', console=None, engine=eng)
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
                    h, ne = dispatch_repl_slash_command('/sessions', console=None, engine=eng)
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
                h, ne = dispatch_repl_slash_command('/new', console=None, engine=eng)
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
                os.chdir(tmp)
                eng = QueryEnginePort(build_port_manifest())
                with patch('builtins.print'):
                    with patch(
                        'src.repl_slash_commands._confirm_store_summary', return_value=False
                    ):
                        h, ne = dispatch_repl_slash_command('/summary', console=None, engine=eng)
                self.assertTrue(h)
                self.assertFalse(Path(tmp, 'SCREAM.md').exists())
        finally:
            os.chdir(old)

    def test_summary_stores_when_confirmed(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                eng = QueryEnginePort(build_port_manifest())
                with patch('builtins.print'):
                    with patch(
                        'src.repl_slash_commands._confirm_store_summary', return_value=True
                    ):
                        h, ne = dispatch_repl_slash_command('/summary', console=None, engine=eng)
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
                os.chdir(tmp)
                eng = QueryEnginePort(
                    build_port_manifest(),
                    config=QueryEngineConfig(llm_enabled=True),
                )
                eng.mutable_messages.append('用户偏好：TypeScript')
                with patch('builtins.print'):
                    with patch(
                        'src.repl_slash_commands._memo_extract_via_llm',
                        return_value=('- 偏好 TS', None),
                    ):
                        h, ne = dispatch_repl_slash_command('/memo', console=None, engine=eng)
                self.assertTrue(h)
                self.assertIsNone(ne)
                self.assertIn('偏好 TS', Path(tmp, 'SCREAM.md').read_text(encoding='utf-8'))
        finally:
            os.chdir(old)


if __name__ == '__main__':
    unittest.main()
