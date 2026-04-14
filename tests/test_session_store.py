from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src.session_store import (
    BLOCKED_CROSS_WORKSPACE_LOAD_MSG,
    CrossWorkspaceSessionLoadBlockedError,
    StoredSession,
    load_session,
    most_recent_saved_session_id,
    save_session,
)
from src.utils.workspace import get_workspace_data_root


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get('HOME')
        self._home_tmp = tempfile.TemporaryDirectory()
        os.environ['HOME'] = self._home_tmp.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop('HOME', None)
        else:
            os.environ['HOME'] = self._old_home
        self._home_tmp.cleanup()

    def test_most_recent_saved_session_id_by_mtime(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(
                        session_id='older',
                        messages=('a',),
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                time.sleep(0.02)
                save_session(
                    StoredSession(
                        session_id='newer',
                        messages=('b',),
                        input_tokens=1,
                        output_tokens=2,
                    )
                )
                self.assertEqual(most_recent_saved_session_id(), 'newer')
        finally:
            os.chdir(old)

    def test_save_session_writes_scream_index(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(
                        session_id='idx_sid',
                        messages=('a',),
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                idx = get_workspace_data_root() / 'sessions.json'
                self.assertTrue(idx.is_file())
                loaded = json.loads(idx.read_text(encoding='utf-8'))
                self.assertEqual(loaded.get('latest_session_id'), 'idx_sid')
        finally:
            os.chdir(old)

    def test_roundtrip_llm_conversation_messages(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                snap = ({'role': 'assistant', 'content': '你好'},)
                save_session(
                    StoredSession(
                        session_id='snap1',
                        messages=('u1',),
                        input_tokens=1,
                        output_tokens=2,
                        llm_conversation_messages=snap,
                    )
                )
                loaded = load_session('snap1')
                self.assertEqual(loaded.llm_conversation_messages, snap)
        finally:
            os.chdir(old)

    def test_most_recent_none_when_empty(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertIsNone(most_recent_saved_session_id())
        finally:
            os.chdir(old)

    def test_cross_workspace_load_is_blocked(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as ws_a, tempfile.TemporaryDirectory() as ws_b:
                os.chdir(ws_a)
                save_session(
                    StoredSession(
                        session_id='shared-sid',
                        messages=('a',),
                        input_tokens=1,
                        output_tokens=1,
                    )
                )
                os.chdir(ws_b)
                with self.assertRaises(CrossWorkspaceSessionLoadBlockedError) as ctx:
                    load_session('shared-sid')
                self.assertIn(BLOCKED_CROSS_WORKSPACE_LOAD_MSG, str(ctx.exception))
        finally:
            os.chdir(old)


if __name__ == '__main__':
    unittest.main()
