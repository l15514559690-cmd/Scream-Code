from __future__ import annotations

import sys
from dataclasses import replace
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class DirectModeReport:
    mode: str
    target: str
    active: bool

    def as_text(self) -> str:
        active_zh = '是' if self.active else '否'
        return f'模式={self.mode}\n目标={self.target}\n已激活={active_zh}'


def run_direct_connect(target: str) -> DirectModeReport:
    return DirectModeReport(mode='direct-connect', target=target, active=True)


def run_deep_link(target: str) -> DirectModeReport:
    return DirectModeReport(mode='deep-link', target=target, active=True)


def detect_piped_stdin(stdin: TextIO | None = None) -> bool:
    """
    判断当前是否为管道/重定向输入（Silent Pipe Mode 入口判断）。
    """
    stream = stdin or sys.stdin
    try:
        return not bool(stream.isatty())
    except Exception:
        return False


def read_piped_stdin_text(stdin: TextIO | None = None) -> str:
    """
    读取标准输入全部文本；仅在 ``detect_piped_stdin`` 为真时使用。
    """
    stream = stdin or sys.stdin
    try:
        return str(stream.read() or '')
    except Exception:
        return ''


def run_headless_query(query_text: str, *, llm_enabled: bool = True) -> int:
    """
    无头单次执行：不初始化 prompt_toolkit / rich.Live，处理后直接退出。
    """
    prompt = (query_text or '').strip()
    if not prompt:
        return 0
    try:
        from .query_engine import QueryEnginePort

        engine = QueryEnginePort.from_workspace()
        engine.config = replace(engine.config, llm_enabled=llm_enabled)
        result = engine.submit_message(prompt)
        output = str(getattr(result, 'output', '') or '')
        if output:
            sys.stdout.write(output)
            if not output.endswith('\n'):
                sys.stdout.write('\n')
            sys.stdout.flush()
        try:
            engine.persist_session()
        except OSError:
            pass
        return 0
    except Exception as exc:
        sys.stderr.write(f'[Headless] {type(exc).__name__}: {exc}\n')
        sys.stderr.flush()
        return 1
