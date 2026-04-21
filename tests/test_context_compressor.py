"""上下文折叠：阈值、摘要组装、安全尾部与失败回退。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.context_compressor import (
    MAX_HISTORY_MSGS,
    _find_safe_tail_index,
    _suffix_coherent_for_openai,
    compress_history,
)
from src.llm_settings import LlmConnectionSettings


def _fake_settings() -> LlmConnectionSettings:
    return LlmConnectionSettings(
        base_url='https://example.invalid/v1',
        api_key='x',
        model='gpt-test',
        api_protocol='openai',
    )


class ContextCompressorTests(unittest.TestCase):
    def test_noop_when_under_threshold(self) -> None:
        sys = {'role': 'system', 'content': 'S'}
        body = [{'role': 'user', 'content': f'm{i}'} for i in range(MAX_HISTORY_MSGS)]
        messages = [sys, *body]
        out = compress_history(messages, _fake_settings())
        self.assertEqual(len(out), len(messages))
        self.assertEqual(out[0]['content'], 'S')
        self.assertEqual(out[-1]['content'], f'm{MAX_HISTORY_MSGS - 1}')

    def test_compress_returns_fresh_structure(self) -> None:
        sys = {'role': 'system', 'content': 'SYS'}
        pairs: list[dict] = []
        for i in range(8):
            pairs.append({'role': 'user', 'content': f'u{i}'})
            pairs.append({'role': 'assistant', 'content': f'a{i}'})
        messages = [sys, *pairs]

        def _fake_iter_agent(msgs, settings, **kwargs):
            assert kwargs.get('tools') == []
            yield {
                'type': 'executor_complete',
                'assistant_text': 'SUMMARY_OK',
                'input_tokens': 1,
                'output_tokens': 2,
                'conversation_messages': list(msgs),
            }

        with patch(
            'src.llm_client.iter_agent_executor_events',
            _fake_iter_agent,
        ):
            out = compress_history(messages, _fake_settings())

        self.assertLess(len(out), len(messages))
        self.assertEqual(out[0]['role'], 'system')
        self.assertEqual(out[0]['content'], 'SYS')
        self.assertEqual(out[1]['role'], 'system')
        self.assertIn('【历史记忆摘要】', out[1]['content'])
        self.assertIn('SUMMARY_OK', out[1]['content'])
        self.assertEqual(len(out), 8)
        self.assertEqual(out[2]['content'], 'u5')
        self.assertEqual(out[-1]['content'], 'a7')

    def test_failure_returns_original_shape(self) -> None:
        sys = {'role': 'system', 'content': 'S'}
        pairs = []
        for i in range(8):
            pairs.append({'role': 'user', 'content': f'u{i}'})
            pairs.append({'role': 'assistant', 'content': f'a{i}'})
        messages = [sys, *pairs]

        def _boom(*a, **k):
            if False:
                yield None
            raise OSError('network down')

        with patch('src.llm_client.iter_agent_executor_events', _boom):
            out = compress_history(messages, _fake_settings())
        self.assertEqual(len(out), len(messages))

    def test_suffix_rejects_tool_at_tail_start(self) -> None:
        work = [
            {'role': 'user', 'content': 'u'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'x', 'type': 'function', 'function': {'name': 'f', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'x', 'content': 't'},
        ]
        self.assertFalse(_suffix_coherent_for_openai(work, 2))

    def test_find_safe_tail_keeps_tool_block_intact(self) -> None:
        work = [
            {'role': 'user', 'content': 'u0'},
            {'role': 'assistant', 'content': 'a0'},
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'f', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': 'r1'},
            {'role': 'user', 'content': 'u2'},
            {'role': 'assistant', 'content': 'a2'},
            {'role': 'user', 'content': 'u3'},
            {'role': 'assistant', 'content': 'a3'},
        ]
        split = _find_safe_tail_index(work, min_tail=6)
        self.assertIsNotNone(split)
        self.assertLessEqual(split, 2)
        self.assertTrue(_suffix_coherent_for_openai(work, split))
        self.assertEqual(work[split]['role'], 'user')


if __name__ == '__main__':
    unittest.main()
