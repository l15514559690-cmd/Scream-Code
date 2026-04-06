from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.port_manifest import build_port_manifest
from src.query_engine import QueryEngineConfig, QueryEnginePort


def _chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: MagicMock | None = None,
    tool_calls: list | None = None,
) -> MagicMock:
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


class LlmClientTests(unittest.TestCase):
    def test_submit_message_calls_openai_sdk_when_llm_enabled(self) -> None:
        manifest = build_port_manifest()
        fake_stream = iter(
            [
                _chunk(content='模'),
                _chunk(content='型'),
                _chunk(content='回复'),
                _chunk(
                    content=None,
                    finish_reason='stop',
                    usage=MagicMock(prompt_tokens=3, completion_tokens=5),
                ),
            ]
        )
        fake_create = MagicMock(return_value=fake_stream)
        fake_client_instance = MagicMock()
        fake_client_instance.chat.completions.create = fake_create

        env = {
            'API_KEY': 'test-key',
            'BASE_URL': 'https://api.deepseek.com/v1',
            'MODEL': 'deepseek-chat',
        }
        with patch('src.model_manager.ensure_default_config_file'):
            with patch('src.model_manager.read_persisted_config_raw', return_value=None):
                with patch.dict(os.environ, env, clear=False):
                    with patch('src.llm_client.OpenAI', return_value=fake_client_instance):
                        engine = QueryEnginePort(
                            manifest,
                            config=QueryEngineConfig(llm_enabled=True, max_budget_tokens=100_000),
                        )
                        result = engine.submit_message('hello', ('review',), ('BashTool',), ())

        fake_create.assert_called_once()
        call_kw = fake_create.call_args.kwargs
        self.assertTrue(call_kw.get('stream'), '必须使用流式 API')
        self.assertIn('tools', call_kw)
        self.assertEqual(call_kw['tool_choice'], 'auto')
        self.assertEqual(call_kw['model'], 'deepseek-chat')
        self.assertEqual(call_kw['messages'][0]['role'], 'system')
        self.assertEqual(call_kw['messages'][1]['role'], 'user')
        self.assertIn('hello', call_kw['messages'][1]['content'])
        self.assertEqual(result.output, '模型回复')
        self.assertGreaterEqual(result.usage.input_tokens, 3)
        self.assertGreaterEqual(result.usage.output_tokens, 5)

    def test_llm_missing_api_key_does_not_call_network(self) -> None:
        manifest = build_port_manifest()
        fake_openai = MagicMock()
        with patch('src.model_manager.ensure_default_config_file'):
            with patch('src.model_manager.read_persisted_config_raw', return_value=None):
                with patch.dict(os.environ, {'API_KEY': ''}, clear=False):
                    with patch('src.llm_client.OpenAI', fake_openai):
                        engine = QueryEnginePort(manifest, config=QueryEngineConfig(llm_enabled=True))
                        result = engine.submit_message('x')
        fake_openai.assert_not_called()
        self.assertIn('[LLM]', result.output)
        self.assertIn('API_KEY', result.output)


if __name__ == '__main__':
    unittest.main()
