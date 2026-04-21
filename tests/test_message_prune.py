from __future__ import annotations

import unittest

from src.message_prune import prune_historical_messages


class MessagePruneTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(prune_historical_messages([]), [])

    def test_short_chain_no_fold(self) -> None:
        msgs = [
            {'role': 'system', 'content': 'SYS'},
            {'role': 'user', 'content': 'a'},
            {'role': 'assistant', 'content': 'b'},
        ]
        out = prune_historical_messages(msgs)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]['content'], 'SYS')

    def test_tail_tool_long_preserved(self) -> None:
        long_t = 'T' * 35_000
        # 尾部保留 256 条：需足够多的 tool 行，使首条落入 middle 并被折叠
        n_tools = 270
        body_tools = [{'role': 'tool', 'tool_call_id': f'id{i}', 'content': long_t} for i in range(n_tools)]
        msgs = [{'role': 'system', 'content': 'S'}] + body_tools
        out = prune_historical_messages(msgs)
        self.assertEqual(out[0]['content'], 'S')
        self.assertIn('历史执行输出过长已折叠', out[1]['content'])
        self.assertLess(len(out[1]['content']), 5000)
        self.assertEqual(out[-1]['content'], long_t)

    def test_middle_tool_list_content_folded(self) -> None:
        long_payload = {'x': 'y' * 40_000}
        tools = []
        for i in range(270):
            tools.append({'role': 'tool', 'tool_call_id': str(i), 'content': long_payload})
        msgs = [{'role': 'system', 'content': 'S'}] + tools
        out = prune_historical_messages(msgs)
        self.assertIn('历史执行输出过长已折叠', out[1]['content'])
        self.assertIsInstance(out[-1]['content'], dict)

    def test_input_not_mutated(self) -> None:
        long_t = 'Z' * 35_000
        inner = [{'role': 'tool', 'tool_call_id': f'a{i}', 'content': long_t} for i in range(270)]
        msgs = [{'role': 'system', 'content': 'S'}] + inner
        before = msgs[1]['content']
        prune_historical_messages(msgs)
        self.assertEqual(msgs[1]['content'], before)


if __name__ == '__main__':
    unittest.main()
