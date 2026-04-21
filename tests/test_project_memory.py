from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class ProjectMemoryTests(unittest.TestCase):
    def test_priority_scream_over_claude(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, 'CLAUDE.md').write_text('claude rules', encoding='utf-8')
                Path(tmp, 'SCREAM.md').write_text('scream wins', encoding='utf-8')
                from src.project_memory import read_first_available_project_memory

                name, body = read_first_available_project_memory()
                self.assertEqual(name, 'SCREAM.md')
                self.assertEqual(body, 'scream wins')
        finally:
            os.chdir(old)

    def test_cursorrules_third_priority(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, '.cursorrules').write_text('cursor only', encoding='utf-8')
                from src.project_memory import read_first_available_project_memory

                name, body = read_first_available_project_memory()
                self.assertEqual(name, '.cursorrules')
                self.assertIn('cursor only', body or '')
        finally:
            os.chdir(old)

    def test_skips_empty_file(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, 'SCREAM.md').write_text('   \n', encoding='utf-8')
                Path(tmp, 'CLAUDE.md').write_text('real', encoding='utf-8')
                from src.project_memory import read_first_available_project_memory

                name, _ = read_first_available_project_memory()
                self.assertEqual(name, 'CLAUDE.md')
        finally:
            os.chdir(old)

    def test_system_suffix_format(self) -> None:
        from src.project_memory import format_project_memory_system_suffix

        s = format_project_memory_system_suffix('line1')
        self.assertIn('<project_memory>', s)
        self.assertIn('line1', s)
        self.assertIn('严格遵守', s)

    def test_build_system_init_includes_memory(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, 'SCREAM.md').write_text('# 记忆\n使用 Rust', encoding='utf-8')
                from src.system_init import build_system_init_message

                msg = build_system_init_message(trusted=True)
                self.assertIn('<project_memory>', msg)
                self.assertIn('使用 Rust', msg)
        finally:
            os.chdir(old)

    def test_append_long_term_memory_prefers_existing_scream(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, 'SCREAM.md').write_text('# 根\n正文', encoding='utf-8')
                from src.project_memory import append_long_term_memory_block, long_term_memory_target_path

                self.assertEqual(long_term_memory_target_path().name, 'SCREAM.md')
                msg = append_long_term_memory_block('- 偏好 A', source_tag='/memo')
                self.assertTrue(msg.startswith('已安全'))
                text = Path(tmp, 'SCREAM.md').read_text(encoding='utf-8')
                self.assertIn('# 根', text)
                self.assertIn('偏好 A', text)
                self.assertIn('长效记忆库', text)
        finally:
            os.chdir(old)

    def test_append_long_term_memory_uses_claude_when_no_scream(self) -> None:
        old = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path(tmp, 'CLAUDE.md').write_text('# Claude\n', encoding='utf-8')
                from src.project_memory import append_long_term_memory_block, long_term_memory_target_path

                self.assertEqual(long_term_memory_target_path().name, 'CLAUDE.md')
                append_long_term_memory_block('note', source_tag='/memo')
                self.assertIn('note', Path(tmp, 'CLAUDE.md').read_text(encoding='utf-8'))
        finally:
            os.chdir(old)


if __name__ == '__main__':
    unittest.main()
