"""replLauncher：助手定稿前折叠连续重复段落/行。"""

from __future__ import annotations

import unittest

from src.replLauncher import _dedupe_assistant_scrollback_echoes


class ReplEchoDedupeTests(unittest.TestCase):
    def test_duplicate_paragraph_collapse(self) -> None:
        a = '你好！我是 ScreamCode。\n\n你好！我是 ScreamCode。'
        self.assertEqual(_dedupe_assistant_scrollback_echoes(a), '你好！我是 ScreamCode。')

    def test_consecutive_duplicate_lines(self) -> None:
        a = 'line one\nline one\nline two'
        self.assertEqual(_dedupe_assistant_scrollback_echoes(a), 'line one\nline two')


if __name__ == '__main__':
    unittest.main()
