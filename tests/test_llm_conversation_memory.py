from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.port_manifest import build_port_manifest
from src.query_engine import QueryEngineConfig, QueryEnginePort


class LlmConversationMemoryTests(unittest.TestCase):
    def test_first_turn_includes_single_system(self) -> None:
        eng = QueryEnginePort(build_port_manifest(), config=QueryEngineConfig(llm_enabled=True))
        self.assertEqual(eng.llm_conversation_messages, [])
        msgs = eng._assemble_messages_for_llm_turn('你好', (), (), ())
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertEqual(msgs[1]['role'], 'user')
        self.assertIn('你好', msgs[1]['content'])

    def test_second_turn_prepends_history_deep_copy(self) -> None:
        eng = QueryEnginePort(build_port_manifest(), config=QueryEngineConfig(llm_enabled=True))
        eng.llm_conversation_messages = [
            {'role': 'system', 'content': 'SYS'},
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': 'a1'},
        ]
        msgs = eng._assemble_messages_for_llm_turn('第二句', (), (), ())
        self.assertEqual(len(msgs), 4)
        self.assertEqual(msgs[-1]['role'], 'user')
        self.assertIn('第二句', msgs[-1]['content'])
        msgs[0]['content'] = 'MUTATED'
        self.assertEqual(eng.llm_conversation_messages[0]['content'], 'SYS')

    def test_submit_message_second_call_sends_longer_messages(self) -> None:
        manifest = build_port_manifest()

        def _chunk(**kw):
            c = MagicMock()
            c.content = kw.get('content')
            c.tool_calls = kw.get('tool_calls') or []
            ch = MagicMock()
            ch.delta = c
            ch.finish_reason = kw.get('finish_reason')
            chunk = MagicMock()
            chunk.choices = [ch]
            chunk.usage = kw.get('usage')
            return chunk

        stream1 = iter(
            [
                _chunk(content='一'),
                _chunk(content=None, finish_reason='stop', usage=MagicMock(prompt_tokens=1, completion_tokens=2)),
            ]
        )
        stream2 = iter(
            [
                _chunk(content='二'),
                _chunk(content=None, finish_reason='stop', usage=MagicMock(prompt_tokens=10, completion_tokens=20)),
            ]
        )
        fake_create = MagicMock(side_effect=[stream1, stream2])
        fake_client = MagicMock()
        fake_client.chat.completions.create = fake_create

        env = {
            'API_KEY': 'k',
            'BASE_URL': 'https://api.openai.com/v1',
            'MODEL': 'gpt-4o-mini',
        }
        with patch('src.model_manager.ensure_default_config_file'):
            with patch('src.model_manager.read_persisted_config_raw', return_value=None):
                with patch.dict(os.environ, env, clear=False):
                    with patch('src.llm_client.OpenAI', return_value=fake_client):
                        eng = QueryEnginePort(
                            manifest,
                            config=QueryEngineConfig(llm_enabled=True, max_budget_tokens=1_000_000),
                        )
                        eng.submit_message('第一轮', (), (), ())
                        eng.submit_message('第二轮', (), (), ())

        self.assertEqual(fake_create.call_count, 2)
        m1 = fake_create.call_args_list[0].kwargs['messages']
        m2 = fake_create.call_args_list[1].kwargs['messages']
        self.assertEqual(len(m1), 2)
        self.assertGreater(len(m2), len(m1))
        self.assertEqual(m2[0]['role'], 'system')
        self.assertIn('第二轮', m2[-1]['content'])


if __name__ == '__main__':
    unittest.main()
