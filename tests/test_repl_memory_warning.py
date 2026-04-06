"""REPL Token 水位预警：仅展示层，不改动 engine 数据。"""

from __future__ import annotations

import io
import unittest

from rich.console import Console

from src.models import UsageSummary
from src.port_manifest import build_port_manifest
from src.query_engine import QueryEngineConfig, QueryEnginePort
from src.replLauncher import (
    REPL_MEMORY_WARN_REPEAT_TOKEN_DELTA,
    REPL_MEMORY_WARN_TOTAL_TOKENS,
    REPL_MEMORY_WARN_USER_TURNS,
    _maybe_print_repl_memory_load_warning,
    _REPL_MEMORY_WARN_LAST,
)
from src.repl_ui_render import build_token_warning_panel


class ReplMemoryWarningTests(unittest.TestCase):
    def tearDown(self) -> None:
        _REPL_MEMORY_WARN_LAST.clear()

    def _engine(
        self,
        *,
        inp: int,
        outp: int,
        sid: str = 's1',
        token_warning_threshold: int | None = None,
        n_user_turns: int = 1,
    ) -> QueryEnginePort:
        eng = QueryEnginePort(build_port_manifest(), session_id=sid)
        eng.mutable_messages = ['x'] * max(0, n_user_turns)
        eng.total_usage = UsageSummary(inp, outp)
        if token_warning_threshold is not None:
            from dataclasses import replace

            eng.config = replace(
                eng.config, token_warning_threshold=token_warning_threshold
            )
        return eng

    def test_build_token_warning_panel_contains_threshold(self) -> None:
        p = build_token_warning_panel(90_000, 80_000)
        buf = io.StringIO()
        Console(file=buf, force_terminal=True, width=80).print(p)
        out = buf.getvalue()
        self.assertIn('记忆负载过高', out)
        self.assertIn('Token 水位', out)

    def test_no_warning_below_threshold(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        eng = self._engine(inp=100, outp=100)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertEqual(buf.getvalue(), '')

    def test_warns_once_per_session(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        t = REPL_MEMORY_WARN_TOTAL_TOKENS + 1
        eng = self._engine(inp=t, outp=0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertIn('记忆负载过高', buf.getvalue())
        buf.seek(0)
        buf.truncate(0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertEqual(buf.getvalue(), '')

    def test_new_session_warns_again(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        t = REPL_MEMORY_WARN_TOTAL_TOKENS + 1
        eng_a = self._engine(inp=t, outp=0, sid='a')
        _maybe_print_repl_memory_load_warning(c, eng_a, use_rich=True)
        buf.seek(0)
        buf.truncate(0)
        eng_b = self._engine(inp=t, outp=0, sid='b')
        _maybe_print_repl_memory_load_warning(c, eng_b, use_rich=True)
        self.assertIn('记忆负载过高', buf.getvalue())

    def test_falling_below_threshold_clears_flag(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        t = REPL_MEMORY_WARN_TOTAL_TOKENS + 1
        eng = self._engine(inp=t, outp=0, sid='same')
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertIn('same', _REPL_MEMORY_WARN_LAST)
        eng.total_usage = UsageSummary(100, 100)
        buf.seek(0)
        buf.truncate(0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertEqual(buf.getvalue(), '')
        self.assertNotIn('same', _REPL_MEMORY_WARN_LAST)
        eng.total_usage = UsageSummary(t, 0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertIn('记忆负载过高', buf.getvalue())

    def test_at_threshold_exactly_warns(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        eng = self._engine(inp=REPL_MEMORY_WARN_TOTAL_TOKENS, outp=0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertIn('记忆负载过高', buf.getvalue())

    def test_warns_when_user_turns_reached(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        eng = self._engine(inp=0, outp=0, n_user_turns=REPL_MEMORY_WARN_USER_TURNS)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertIn('记忆负载过高', buf.getvalue())

    def test_repeats_after_token_delta(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        base = REPL_MEMORY_WARN_TOTAL_TOKENS + 1
        eng = self._engine(inp=base, outp=0, sid='rep')
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        buf.seek(0)
        buf.truncate(0)
        eng.total_usage = UsageSummary(base + REPL_MEMORY_WARN_REPEAT_TOKEN_DELTA - 1, 0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertEqual(buf.getvalue(), '')
        buf.seek(0)
        buf.truncate(0)
        eng.total_usage = UsageSummary(base + REPL_MEMORY_WARN_REPEAT_TOKEN_DELTA, 0)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        self.assertIn('记忆负载过高', buf.getvalue())

    def test_config_override_threshold(self) -> None:
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=80)
        eng = self._engine(inp=5001, outp=0, token_warning_threshold=5000)
        _maybe_print_repl_memory_load_warning(c, eng, use_rich=True)
        out = buf.getvalue()
        self.assertIn('记忆负载过高', out)
        self.assertTrue('5000' in out.replace(',', '') or '5,000' in out)


if __name__ == '__main__':
    unittest.main()
