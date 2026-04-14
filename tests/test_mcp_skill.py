from __future__ import annotations

import unittest

from src.skills.base_skill import ReplSkillContext
from src.skills.mcp_skill import McpSkill


class _FakeEngine:
    def __init__(self) -> None:
        self._snap = {
            'enabled': True,
            'running': True,
            'command': 'npx -y @browsermcp/mcp',
            'tools_count': 1,
            'tools': [{'name': 'web.search', 'description': 'search web'}],
        }
        self.restarted = False

    def mcp_status_snapshot(self):  # noqa: D401
        return dict(self._snap)

    def restart_mcp_client(self) -> bool:
        self.restarted = True
        return True


class McpSkillTests(unittest.TestCase):
    def test_status_subcommand(self) -> None:
        sk = McpSkill()
        ctx = ReplSkillContext(console=None, engine=_FakeEngine())  # type: ignore[arg-type]
        out = sk.execute(ctx, 'status')
        self.assertFalse(out.trigger_llm_followup)

    def test_restart_subcommand(self) -> None:
        sk = McpSkill()
        eng = _FakeEngine()
        ctx = ReplSkillContext(console=None, engine=eng)  # type: ignore[arg-type]
        sk.execute(ctx, 'restart')
        self.assertTrue(eng.restarted)


if __name__ == '__main__':
    unittest.main()

