"""Phase 3 单测：WarmSessionPool 保活、复用、LRU 驱逐、崩溃重建。

仍用 FakeTmux 替身，不拉真实 tmux。FakeTmux 默认对 has-session 返回成功
(is_alive=True)，个别用例脚本化为崩溃。
"""

from __future__ import annotations

from frago.agent_driver.pool import WarmSessionPool
from tests.agent_driver.test_tmux_session import FakeTmux


class AlivePane:
    """capture 永远返回 opencode 就绪+完成的屏，has-session 永远成功。"""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.killed: list[str] = []
        self.alive: dict[str, bool] = {}

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        verb = argv[1] if len(argv) > 1 else ""
        if verb == "capture-pane":
            return "Ask anything\n▣ Build · m · 1.0s\nanswer"
        if verb == "has-session":
            name = argv[argv.index("-t") + 1]
            if not self.alive.get(name, True):
                raise _CalledProcessError(argv)
            return ""
        if verb == "kill-session":
            self.killed.append(argv[argv.index("-t") + 1])
        return ""


class _CalledProcessError(Exception):
    """模拟 subprocess.CalledProcessError（is_alive 捕获它）。"""

    def __init__(self, argv):
        super().__init__(argv)


# is_alive() 捕获的是 subprocess.CalledProcessError；用真实类型。
import subprocess  # noqa: E402


def _make_runner():
    fake = AlivePane()

    def runner(argv):
        try:
            return fake(argv)
        except _CalledProcessError as exc:
            raise subprocess.CalledProcessError(1, exc.args[0]) from exc

    runner.fake = fake
    return runner


def test_acquire_reuses_alive_session() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    s1 = pool.acquire("opencode", "sid", "/tmp")
    s2 = pool.acquire("opencode", "sid", "/tmp")
    assert s1 is s2
    assert len(pool) == 1
    # 只 open 一次：new-session 只出现一次。
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 1


def test_lru_eviction_kills_oldest() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(max_size=2, runner=runner)
    pool.acquire("opencode", "a", "/tmp")
    pool.acquire("opencode", "b", "/tmp")
    # 触碰 a 使其变为最近使用，b 成为最久未用。
    pool.acquire("opencode", "a", "/tmp")
    pool.acquire("opencode", "c", "/tmp")  # 超限 → 驱逐 b
    assert set(pool.active_ids()) == {"a", "c"}
    assert "frago-agent-b" in runner.fake.killed


def test_dead_session_is_rebuilt_with_resume_hook() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    pool.acquire("opencode", "x", "/tmp")
    # 标记该 tmux 会话已死。
    runner.fake.alive["frago-agent-x"] = False

    resumed = []
    pool.acquire("opencode", "x", "/tmp", resume_hook=lambda s: resumed.append(s.session_id))
    # 触发了重建 + resume_hook。
    assert resumed == ["x"]
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 2  # 首建 + 重建


def test_run_keeps_session_alive_for_reuse() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    r1 = pool.run("hi", agent_type="opencode", session_id="s", cwd="/tmp", timeout_s=5)
    r2 = pool.run("yo", agent_type="opencode", session_id="s", cwd="/tmp", timeout_s=5)
    assert r1.status == "ok" and r2.status == "ok"
    # 第二轮复用，未再 new-session。
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 1


def test_evict_and_shutdown() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    pool.acquire("opencode", "a", "/tmp")
    pool.acquire("opencode", "b", "/tmp")
    assert pool.evict("a") is True
    assert pool.evict("missing") is False
    pool.shutdown()
    assert len(pool) == 0
    assert "frago-agent-a" in runner.fake.killed
    assert "frago-agent-b" in runner.fake.killed


def test_invalid_max_size_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        WarmSessionPool(max_size=0)


def test_fake_runner_helper_unused_import_guard() -> None:
    # 守护：FakeTmux 仍可从同目录导入（被其它用例间接依赖）。
    assert FakeTmux is not None
