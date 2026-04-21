from __future__ import annotations

from typing import Any
from unittest import mock

import pytest


class _SimpleMocker:
    """Minimal stand-in for pytest-mock's ``mocker`` (patch start/stop per test)."""

    def __init__(self) -> None:
        self._patches: list[Any] = []

    def patch(self, target: str, **kwargs: Any) -> Any:
        p = mock.patch(target, **kwargs)
        started = p.start()
        self._patches.append(p)
        return started

    def stopall(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._patches.clear()


@pytest.fixture
def mocker() -> _SimpleMocker:
    m = _SimpleMocker()
    yield m
    m.stopall()
