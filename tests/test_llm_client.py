from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.llm_client import (
    LlmClientError,
    StreamPart,
    agent_tool_iteration_cap,
    chat_completion_stream,
    max_agent_tool_rounds,
    openai_user_content_to_anthropic,
)
from src.llm_settings import LlmConnectionSettings
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
    def test_agent_tool_iteration_cap_default_100(self) -> None:
        env = {k: v for k, v in os.environ.items()}
        env.pop('SCREAM_MAX_AGENT_TOOL_ROUNDS', None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(agent_tool_iteration_cap(), 100)
            self.assertEqual(max_agent_tool_rounds(), 100)

    def test_agent_tool_iteration_cap_env(self) -> None:
        with patch.dict(os.environ, {'SCREAM_MAX_AGENT_TOOL_ROUNDS': '99'}, clear=False):
            self.assertEqual(agent_tool_iteration_cap(), 99)
            self.assertEqual(max_agent_tool_rounds(), 99)
        with patch.dict(os.environ, {'SCREAM_MAX_AGENT_TOOL_ROUNDS': '0'}, clear=False):
            self.assertIsNone(agent_tool_iteration_cap())
            self.assertEqual(max_agent_tool_rounds(), 10**9)
        with patch.dict(os.environ, {'SCREAM_MAX_AGENT_TOOL_ROUNDS': 'unlimited'}, clear=False):
            self.assertIsNone(agent_tool_iteration_cap())
        with patch.dict(os.environ, {'SCREAM_MAX_AGENT_TOOL_ROUNDS': 'not-int'}, clear=False):
            self.assertIsNone(agent_tool_iteration_cap())

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

    def test_prefix_routing_uses_anthropic_channel(self) -> None:
        settings = LlmConnectionSettings(
            base_url='https://api.anthropic.com',
            api_key='k',
            model='anthropic/claude-3-5-sonnet-20240620',
            api_protocol='openai',
            api_key_env_name='ANTHROPIC_API_KEY',
        )
        with patch('src.llm_client._chat_completion_stream_openai') as openai_stream:
            with patch(
                'src.llm_client._chat_completion_stream_anthropic',
                return_value=iter([StreamPart(text_delta='ok')]),
            ) as anth_stream:
                list(chat_completion_stream([{'role': 'user', 'content': 'hi'}], settings))
        openai_stream.assert_not_called()
        anth_stream.assert_called_once()

    def test_prefix_routing_missing_provider_key_blows_fuse(self) -> None:
        settings = LlmConnectionSettings(
            base_url='https://api.openai.com/v1',
            api_key='',
            model='openai/gpt-4o-mini',
            api_protocol='openai',
            api_key_env_name='OPENAI_API_KEY',
        )
        with self.assertRaises(LlmClientError) as ctx:
            list(chat_completion_stream([{'role': 'user', 'content': 'hi'}], settings))
        self.assertIn('OPENAI_API_KEY', str(ctx.exception))

    def test_openai_user_content_to_anthropic_data_url_image(self) -> None:
        tiny = (
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
        )
        url = f'data:image/png;base64,{tiny}'
        content = [
            {'type': 'text', 'text': 'hi'},
            {'type': 'image_url', 'image_url': {'url': url}},
        ]
        anth = openai_user_content_to_anthropic(content)
        self.assertIsInstance(anth, list)
        self.assertEqual(len(anth), 2)
        self.assertEqual(anth[0]['type'], 'text')
        self.assertEqual(anth[1]['type'], 'image')
        self.assertEqual(anth[1]['source']['type'], 'base64')
        self.assertEqual(anth[1]['source']['media_type'], 'image/png')
        self.assertEqual(anth[1]['source']['data'], tiny)


if __name__ == '__main__':
    unittest.main()
