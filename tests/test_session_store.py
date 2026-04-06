from __future__ import annotations

import os
import tempfile
import time
import unittest

from src.session_store import StoredSession, most_recent_saved_session_id, save_session


class SessionStoreTests(unittest.TestCase):
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

    def test_most_recent_none_when_empty(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertIsNone(most_recent_saved_session_id())
        finally:
            os.chdir(old)


if __name__ == '__main__':
    unittest.main()
