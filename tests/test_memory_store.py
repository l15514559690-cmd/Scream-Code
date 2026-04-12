from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src import memory_store
from src.system_init import build_system_init_message


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._fd, self._path = tempfile.mkstemp(suffix='.db')
        os.close(self._fd)
        self._old = os.environ.get('SCREAM_MEMORY_DB')
        os.environ['SCREAM_MEMORY_DB'] = self._path

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop('SCREAM_MEMORY_DB', None)
        else:
            os.environ['SCREAM_MEMORY_DB'] = self._old
        Path(self._path).unlink(missing_ok=True)

    def test_count_core_memory_entries(self) -> None:
        self.assertEqual(memory_store.count_core_memory_entries(), 0)
        memory_store.memorize_core_rule('a', '1')
        memory_store.memorize_core_rule('b', '2')
        self.assertEqual(memory_store.count_core_memory_entries(), 2)
        memory_store.forget_core_rule('a')
        self.assertEqual(memory_store.count_core_memory_entries(), 1)

    def test_memorize_upsert_and_list(self) -> None:
        self.assertIn('已记入', memory_store.memorize_core_rule('rust.edition', '2021'))
        self.assertIn('已记入', memory_store.memorize_core_rule('rust.edition', '2024'))
        rows = memory_store.list_core_rules()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['key_name'], 'rust.edition')
        self.assertEqual(rows[0]['content'], '2024')
        self.assertTrue(rows[0]['updated_at'])

    def test_get_and_forget(self) -> None:
        memory_store.memorize_core_rule('k1', 'v1')
        self.assertEqual(memory_store.get_core_rule('k1'), 'v1')
        self.assertIsNone(memory_store.get_core_rule('missing'))
        self.assertIn('删除', memory_store.forget_core_rule('k1'))
        self.assertIsNone(memory_store.get_core_rule('k1'))
        self.assertIn('未找到', memory_store.forget_core_rule('k1'))

    def test_validate_empty_key(self) -> None:
        self.assertIn('[错误]', memory_store.memorize_core_rule('', 'x'))

    def test_validate_empty_content(self) -> None:
        self.assertIn('[错误]', memory_store.memorize_core_rule('k', '   '))

    def test_format_project_long_term_memory_xml_block(self) -> None:
        self.assertEqual(memory_store.format_project_long_term_memory_xml_block(), '')
        memory_store.memorize_core_rule('rule.one', 'line1\nline2')
        xml = memory_store.format_project_long_term_memory_xml_block()
        self.assertIn('<Project_LongTerm_Memory>', xml)
        self.assertIn('</Project_LongTerm_Memory>', xml)
        self.assertIn('rule.one', xml)
        self.assertIn('line1', xml)

    def test_build_system_init_appends_long_term_xml(self) -> None:
        memory_store.memorize_core_rule('sys.test', 'injected')
        text = build_system_init_message(trusted=True)
        self.assertIn('<Project_LongTerm_Memory>', text)
        self.assertIn('sys.test', text)
        self.assertIn('injected', text)


if __name__ == '__main__':
    unittest.main()
