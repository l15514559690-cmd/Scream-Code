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
    purge_feishu_channel_artifacts,
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

    def test_most_recent_skips_feishu_channel_sessions(self) -> None:
        """最新文件为 feishu_ 时，主通道应回退到上一条非飞书会话。"""
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(
                        session_id='main_terminal',
                        messages=('a',),
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                time.sleep(0.02)
                save_session(
                    StoredSession(
                        session_id='feishu_chat123',
                        messages=('b',),
                        input_tokens=1,
                        output_tokens=1,
                    )
                )
                self.assertEqual(most_recent_saved_session_id(), 'main_terminal')
        finally:
            os.chdir(old)

    def test_most_recent_none_when_only_feishu_sessions(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(
                        session_id='feishu_only',
                        messages=('x',),
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                self.assertIsNone(most_recent_saved_session_id())
        finally:
            os.chdir(old)

    def test_purge_feishu_removes_json_and_refreshes_index(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(
                        session_id='feishu_test1',
                        messages=('x',),
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                save_session(
                    StoredSession(
                        session_id='main_keep',
                        messages=('y',),
                        input_tokens=1,
                        output_tokens=1,
                    )
                )
                inbox = Path(tmp) / '.scream_cache' / 'feishu_inbox'
                inbox.mkdir(parents=True, exist_ok=True)
                (inbox / 'a.bin').write_bytes(b'z')
                rep = purge_feishu_channel_artifacts()
                self.assertEqual(rep['removed_feishu_session_files'], 1)
                self.assertFalse((get_workspace_data_root() / 'sessions' / 'feishu_test1.json').is_file())
                self.assertTrue((get_workspace_data_root() / 'sessions' / 'main_keep.json').is_file())
                self.assertFalse((inbox / 'a.bin').is_file())
        finally:
            os.chdir(old)

    def test_load_session_still_loads_feishu_id(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                save_session(
                    StoredSession(
                        session_id='feishu_explicit',
                        messages=('m',),
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                loaded = load_session('feishu_explicit')
                self.assertEqual(loaded.session_id, 'feishu_explicit')
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
