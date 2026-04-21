from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import src.claw_config as claw_config


class ClawConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        claw_config.reload_project_claw_json()

    def test_loads_when_root_has_claw_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.claw.json').write_text(
                json.dumps({'permissions': {'defaultMode': 'ask'}}),
                encoding='utf-8',
            )
            with patch.object(claw_config, 'project_root', return_value=root):
                claw_config.reload_project_claw_json()
                d = claw_config.load_project_claw_json()
            self.assertEqual(d.get('permissions', {}).get('defaultMode'), 'ask')

    def test_invalid_json_yields_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.claw.json').write_text('{', encoding='utf-8')
            with patch.object(claw_config, 'project_root', return_value=root):
                claw_config.reload_project_claw_json()
                d = claw_config.load_project_claw_json()
            self.assertEqual(d, {})


if __name__ == '__main__':
    unittest.main()
