"""REPL / 会话恢复：发往 LLM 的 messages 须带上落盘的用户历史。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.query_engine import QueryEnginePort
from src.session_store import StoredSession


class QueryEngineReplHistoryTests(unittest.TestCase):
    def test_fresh_session_first_turn_only_system_and_user(self) -> None:
        eng = QueryEnginePort.from_workspace()
        with patch('src.system_init.build_system_init_message', return_value='SYS'):
            msgs = eng._assemble_messages_for_llm_turn('hi', (), (), ())
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0], {'role': 'system', 'content': 'SYS'})
        self.assertEqual(msgs[1]['role'], 'user')
        self.assertIn('hi', str(msgs[1]['content']))

    def test_restored_mutable_messages_injected_when_llm_empty(self) -> None:
        stored = StoredSession(
            session_id='sid',
            messages=('first question', 'second question'),
            input_tokens=0,
            output_tokens=0,
        )
        with patch('src.query_engine.load_session', return_value=stored):
            eng = QueryEnginePort.from_saved_session('sid')
        self.assertEqual(eng.llm_conversation_messages, [])
        self.assertEqual(eng.mutable_messages, ['first question', 'second question'])

        with patch('src.system_init.build_system_init_message', return_value='SYS'):
            msgs = eng._assemble_messages_for_llm_turn('third', (), (), ())
        self.assertEqual(msgs[0], {'role': 'system', 'content': 'SYS'})
        self.assertEqual(msgs[1]['role'], 'user')
        self.assertEqual(msgs[1]['content'], 'first question')
        self.assertEqual(msgs[2]['role'], 'user')
        self.assertEqual(msgs[2]['content'], 'second question')
        self.assertEqual(msgs[3]['role'], 'user')
        self.assertIn('third', str(msgs[3]['content']))

    def test_restored_llm_snapshot_used_when_present(self) -> None:
        stored = StoredSession(
            session_id='sid2',
            messages=('u1',),
            input_tokens=0,
            output_tokens=0,
            llm_conversation_messages=(
                {'role': 'system', 'content': 'OLD_SYS'},
                {'role': 'user', 'content': 'prior'},
                {'role': 'assistant', 'content': 'prior reply'},
            ),
        )
        with patch('src.system_init.build_system_init_message', return_value='FRESH_SYS'):
            with patch('src.query_engine.load_session', return_value=stored):
                eng = QueryEnginePort.from_saved_session('sid2')
            self.assertEqual(len(eng.llm_conversation_messages), 3)
            self.assertEqual(eng.llm_conversation_messages[1]['role'], 'user')
            self.assertEqual(eng.llm_conversation_messages[2]['content'], 'prior reply')
            msgs = eng._assemble_messages_for_llm_turn('next', (), (), ())
        self.assertEqual(msgs[0], {'role': 'system', 'content': 'FRESH_SYS'})
        self.assertEqual(len(msgs), 4)
        self.assertIn('next', str(msgs[-1]['content']))


if __name__ == '__main__':
    unittest.main()
