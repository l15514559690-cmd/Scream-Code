from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.utils.workspace import get_workspace_data_root, get_workspace_id, get_workspace_root


class WorkspaceUtilsTests(unittest.TestCase):
    def test_get_workspace_root_falls_back_to_cwd_without_git(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(get_workspace_root(), Path(tmp).resolve())
        finally:
            os.chdir(old)

    def test_get_workspace_root_walks_up_to_git(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / '.git').mkdir()
                nested = root / 'a' / 'b'
                nested.mkdir(parents=True)
                os.chdir(nested)
                self.assertEqual(get_workspace_root(), root.resolve())
        finally:
            os.chdir(old)

    def test_workspace_id_length(self) -> None:
        wid = get_workspace_id(Path('/tmp/example'))
        self.assertEqual(len(wid), 12)

    def test_workspace_data_root_contains_workspace_id(self) -> None:
        root = Path('/tmp/ws-root')
        data_root = get_workspace_data_root(root)
        self.assertIn(get_workspace_id(root), str(data_root))


if __name__ == '__main__':
    unittest.main()
