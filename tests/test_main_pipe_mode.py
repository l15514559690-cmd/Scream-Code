from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src import direct_modes, main


class _FakeIn:
    def __init__(self, *, is_tty: bool, body: str = '') -> None:
        self._is_tty = is_tty
        self._body = body

    def isatty(self) -> bool:
        return self._is_tty

    def read(self) -> str:
        return self._body


class MainPipeModeTests(unittest.TestCase):
    def test_detect_piped_stdin(self) -> None:
        self.assertTrue(direct_modes.detect_piped_stdin(_FakeIn(is_tty=False)))
        self.assertFalse(direct_modes.detect_piped_stdin(_FakeIn(is_tty=True)))

    def test_read_piped_stdin_text(self) -> None:
        body = direct_modes.read_piped_stdin_text(_FakeIn(is_tty=False, body='abc\n'))
        self.assertEqual(body, 'abc\n')

    def test_compose_headless_query_with_cli_and_pipe(self) -> None:
        text = main._compose_headless_query('重构这段代码', 'print("x")')
        self.assertIn('重构这段代码', text)
        self.assertIn('[管道输入内容]:', text)
        self.assertIn('print("x")', text)

    def test_main_repl_routes_to_pipe_mode_when_stdin_not_tty(self) -> None:
        with patch('src.main.check_and_install_dependencies'):
            with patch('src.main.load_project_dotenv'):
                with patch('src.main.load_project_claw_json'):
                    with patch('src.main.detect_piped_stdin', return_value=True):
                        with patch('src.main.read_piped_stdin_text', return_value='abc'):
                            with patch('src.main.run_headless_query', return_value=7) as run_pipe:
                                code = main.main(['repl', '请解释'])
        self.assertEqual(code, 7)
        run_pipe.assert_called_once()
        call_args, call_kwargs = run_pipe.call_args
        self.assertIn('请解释', call_args[0])
        self.assertIn('abc', call_args[0])
        self.assertEqual(call_kwargs, {'llm_enabled': True})

    def test_run_headless_query_error_returns_nonzero(self) -> None:
        with patch('src.query_engine.QueryEnginePort.from_workspace', side_effect=RuntimeError('boom')):
            code = direct_modes.run_headless_query('hello', llm_enabled=True)
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
