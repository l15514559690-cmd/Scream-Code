"""TUI 神经底栏：``neural_status_fields`` 纯数据逻辑（无 prompt_toolkit）。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from src.models import UsageSummary
from src.port_manifest import build_port_manifest
from src.query_engine import QueryEnginePort
from src.tui_app import neural_status_fields


class NeuralStatusFieldsTests(unittest.TestCase):
    def test_token_pct_against_max_budget(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        eng.config = replace(eng.config, max_budget_tokens=1000)
        eng.total_usage = UsageSummary(400, 100)
        f = neural_status_fields(eng)
        self.assertEqual(f['total_tokens'], 500)
        self.assertEqual(f['token_pct'], 50)

    def test_token_pct_caps_at_100(self) -> None:
        eng = QueryEnginePort(build_port_manifest())
        eng.config = replace(eng.config, max_budget_tokens=100)
        eng.total_usage = UsageSummary(900, 200)
        f = neural_status_fields(eng)
        self.assertEqual(f['token_pct'], 100)


if __name__ == '__main__':
    unittest.main()
