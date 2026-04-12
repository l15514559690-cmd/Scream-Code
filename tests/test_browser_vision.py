from __future__ import annotations

import unittest

from src.browser_vision import (
    BrowserVisionEngine,
    BrowserVisionError,
    _allocate_capture_path,
    _normalize_url,
)


class BrowserVisionUnitTests(unittest.TestCase):
    def test_normalize_empty_raises(self) -> None:
        with self.assertRaises(BrowserVisionError):
            _normalize_url('')

    def test_normalize_adds_https(self) -> None:
        u = _normalize_url('example.com')
        self.assertEqual(u, 'https://example.com')

    def test_normalize_rejects_ftp(self) -> None:
        with self.assertRaises(BrowserVisionError) as ctx:
            _normalize_url('ftp://x.com')
        self.assertIn('协议', str(ctx.exception))

    def test_capture_page_empty_url_raises(self) -> None:
        with self.assertRaises(BrowserVisionError):
            BrowserVisionEngine().capture_page('   ')

    def test_allocate_path_under_scream(self) -> None:
        p = _allocate_capture_path()
        self.assertTrue(str(p).endswith('.png'))
        self.assertIn('.scream', str(p))
        self.assertIn('screenshots', str(p))


if __name__ == '__main__':
    unittest.main()
