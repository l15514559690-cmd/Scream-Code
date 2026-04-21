from __future__ import annotations

import unittest

from src.skills.look_skill import _DEFAULT_MAX_CAPTURE_HEIGHT, _parse_look_cmdline


class LookSkillArgsTests(unittest.TestCase):
    def test_url_only_viewport(self) -> None:
        url, prompt, full, mh = _parse_look_cmdline('https://example.com')
        self.assertEqual(url, 'https://example.com')
        self.assertEqual(prompt, '')
        self.assertFalse(full)
        self.assertIsNone(mh)

    def test_url_with_prompt(self) -> None:
        url, prompt, full, mh = _parse_look_cmdline('https://a.com hello world')
        self.assertEqual(url, 'https://a.com')
        self.assertEqual(prompt, 'hello world')
        self.assertFalse(full)
        self.assertIsNone(mh)

    def test_full_and_max_height(self) -> None:
        url, prompt, full, mh = _parse_look_cmdline(
            'https://example.com --full --max-height 4000'
        )
        self.assertEqual(url, 'https://example.com')
        self.assertEqual(prompt, '')
        self.assertTrue(full)
        self.assertEqual(mh, 4000)

    def test_flags_mixed_with_prompt(self) -> None:
        url, prompt, full, mh = _parse_look_cmdline(
            'https://b.com intro --full tail'
        )
        self.assertEqual(url, 'https://b.com')
        self.assertEqual(prompt, 'intro tail')
        self.assertTrue(full)
        self.assertIsNone(mh)

    def test_default_constant_documented(self) -> None:
        self.assertEqual(_DEFAULT_MAX_CAPTURE_HEIGHT, 2400)


if __name__ == '__main__':
    unittest.main()
