"""Phase 8 单测：PaTmuxRunner.warm —— 预热只 acquire、不投喂，已活则跳过。"""

from __future__ import annotations

from frago.server.services.pa_tmux_runner import PaTmuxRunner


class _FakeSession:
    def __init__(self, alive: bool = True) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _FakePool:
    def __init__(self, present: dict[str, _FakeSession] | None = None) -> None:
        self._present = present or {}
        self.acquired: list[str] = []

    def has(self, key: str) -> bool:
        return key in self._present

    def peek(self, key: str):
        return self._present.get(key)

    def acquire(self, _agent_type: str, session_id: str, _cwd: str, *, conv_key=None):  # noqa: ARG002
        sess = _FakeSession(alive=True)
        self._present[session_id] = sess
        self.acquired.append(session_id)
        return sess


def test_warm_acquires_when_absent():
    pool = _FakePool()
    runner = PaTmuxRunner(pool=pool)
    assert runner.warm("conv-x") is True
    assert pool.acquired == ["conv-x"]


def test_warm_skips_alive():
    pool = _FakePool(present={"conv-y": _FakeSession(alive=True)})
    runner = PaTmuxRunner(pool=pool)
    assert runner.warm("conv-y") is False
    assert pool.acquired == []


def test_warm_rebuilds_dead():
    pool = _FakePool(present={"conv-z": _FakeSession(alive=False)})
    runner = PaTmuxRunner(pool=pool)
    assert runner.warm("conv-z") is True
    assert pool.acquired == ["conv-z"]
