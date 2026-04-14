from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src import llm_settings


class LlmSettingsTests(unittest.TestCase):
    def test_upsert_dotenv_creates_and_updates(self) -> None:
        root = Path(__file__).resolve().parent / '_tmp_env_test'
        root.mkdir(exist_ok=True)
        env_path = root / '.env'
        try:
            if env_path.is_file():
                env_path.unlink()
            with patch.object(llm_settings, 'project_root', return_value=root):
                with patch.object(llm_settings, 'scream_user_config_dir', return_value=root):
                    llm_settings.upsert_project_dotenv_var('TEST_KEY_A', 'first')
                    self.assertTrue(env_path.is_file())
                    self.assertEqual(os.environ.get('TEST_KEY_A'), 'first')
                    llm_settings.upsert_project_dotenv_var('TEST_KEY_A', 'second')
                    text = env_path.read_text(encoding='utf-8')
                    self.assertEqual(text.count('TEST_KEY_A='), 1)
                    self.assertIn('TEST_KEY_A=second', text)
                    self.assertEqual(os.environ.get('TEST_KEY_A'), 'second')
        finally:
            if env_path.is_file():
                env_path.unlink()
            try:
                root.rmdir()
            except OSError:
                pass
            os.environ.pop('TEST_KEY_A', None)

    def test_remove_dotenv_var_keeps_other_lines(self) -> None:
        root = Path(__file__).resolve().parent / '_tmp_env_test_rm'
        root.mkdir(exist_ok=True)
        env_path = root / '.env'
        try:
            env_path.write_text('KEEP=1\nDROP=bye\nOTHER=2\n', encoding='utf-8')
            with patch.object(llm_settings, 'project_root', return_value=root):
                with patch.object(llm_settings, 'scream_user_config_dir', return_value=root):
                    llm_settings.remove_project_dotenv_var('DROP')
            text = env_path.read_text(encoding='utf-8')
            self.assertNotIn('DROP', text)
            self.assertIn('KEEP=1', text)
            self.assertIn('OTHER=2', text)
        finally:
            if env_path.is_file():
                env_path.unlink()
            try:
                root.rmdir()
            except OSError:
                pass

    def test_parse_model_route_with_prefix(self) -> None:
        route = llm_settings.parse_model_route('openai/gpt-4o')
        self.assertEqual(route.provider, 'openai')
        self.assertEqual(route.model_id, 'gpt-4o')
        self.assertEqual(route.routed_model, 'openai/gpt-4o')

    def test_parse_model_route_infer_provider(self) -> None:
        r1 = llm_settings.parse_model_route('gpt-4o')
        r2 = llm_settings.parse_model_route('claude-3-5-sonnet')
        self.assertEqual(r1.provider, 'openai')
        self.assertEqual(r2.provider, 'anthropic')

    def test_parse_model_route_fallback_default_provider(self) -> None:
        route = llm_settings.parse_model_route(
            'custom-model-x',
            default_provider='deepseek',
        )
        self.assertEqual(route.provider, 'deepseek')
        self.assertEqual(route.model_id, 'custom-model-x')


if __name__ == '__main__':
    unittest.main()
