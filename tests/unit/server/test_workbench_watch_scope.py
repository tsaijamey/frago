"""会话页只盯还活着的会话（主人 09-30 定的省法）。

"活着"两种：开在 tmux 里，或者它是 CoreAgent 那一场、常驻进程还在。**CoreAgent NEVER 开在
tmux 里**，只认 tmux 就等于它这一场永远不盯——实时推送一次都不建立、兜底轮询又在静默 15
分钟后自己关掉，页面停在发出那句话的那一刻（2026-10-08 修）。

三处接线各有测试兜着：会话文件流撤掉一场时真的忘掉它；桥接层撤到一场不剩时整条流停掉；
取记录那条接口按活不活分流——活着的登记监听，不活着的只补一次旁路观察的「打开」。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from frago.server.services import session_observer as so
from frago.server.services import workbench_stream_bridge as wsb
from frago.server.services.workbench_stream_bridge import WorkbenchStreamBridge
from frago.session import stream as stream_mod
from frago.session.stream import SessionStream

A = "aaaaaaaa-1111-2222-3333-444444444444"
B = "bbbbbbbb-1111-2222-3333-444444444444"
CORE = "core_1b1a419957324f25a53914ede703c501"


def _write_session(path: Path, count: int, start: int = 0) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for i in range(start, start + count):
            fh.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": f"{path.stem[:4]}-u{i}",
                        "sessionId": path.stem,
                        "timestamp": "2026-09-01T00:00:00.000Z",
                        "cwd": "/tmp/proj",
                        "message": {"role": "user", "content": f"第 {i} 句"},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


@pytest.fixture
def watch_dir(tmp_path):
    from frago.session.adapters import claude_code_records

    d = tmp_path / "-tmp-proj"
    d.mkdir()
    claude_code_records.clear_cache()
    yield d
    claude_code_records.clear_cache()


@pytest.fixture
def opened(monkeypatch):
    """旁路观察收到了哪些「打开」。"""
    seen: list[tuple[str, str]] = []

    class FakeObserver:
        def notify(self, session_id, trigger):
            seen.append((session_id, trigger))

    monkeypatch.setattr(so, "get_observer", lambda *a, **k: FakeObserver())
    return seen


@pytest.fixture
def bridge(watch_dir, monkeypatch, opened):
    monkeypatch.setattr(wsb, "locate_stream_file", lambda sid: watch_dir / f"{sid}.jsonl")
    b = WorkbenchStreamBridge(loop=None)
    yield b
    b.stop_all()


def _touch(stream: SessionStream, path: Path) -> None:
    stream._on_file_event(  # noqa: SLF001 — 直接喂事件，不依赖真的文件系统通知
        stream_mod.FileEvent(path=str(path), event_type="modified", is_directory=False, timestamp=0.0)
    )
    time.sleep(stream._debounce + 0.2)  # noqa: SLF001


def test_撤过又回来的会话不把整场历史再推一遍(watch_dir):
    """开始盯之后才新建的那一场，撤掉再登记，第一次处理只对水位——它已经不是「新文件」了。"""
    seen: list[int] = []
    stream = SessionStream(
        project_path="/tmp/proj",
        watch_dir=watch_dir,
        on_records=lambda _sid, recs: seen.append(len(recs)),
        debounce_seconds=0.05,
    )
    stream.start()
    try:
        session = watch_dir / f"{A}.jsonl"
        stream.watch_session(A)
        _write_session(session, 3)
        _touch(stream, session)
        assert seen == [3]

        stream.unwatch_session(A)
        assert not stream.watching_any()
        _write_session(session, 2, start=3)
        _touch(stream, session)
        assert seen == [3], "撤掉之后这一场的改动一条都不处理"

        stream.watch_session(A)
        _touch(stream, session)
        assert seen == [3], "重新登记后第一次只对水位，不把整场当新内容推出去"
        _write_session(session, 1, start=5)
        _touch(stream, session)
        assert seen == [3, 1]
    finally:
        stream.stop()


def test_同一个项目撤到一场不剩整条流停掉(bridge, watch_dir):
    _write_session(watch_dir / f"{A}.jsonl", 1)
    _write_session(watch_dir / f"{B}.jsonl", 1)
    bridge.ensure_watching(A)
    bridge.ensure_watching(B)
    assert len(bridge._streams) == 1  # noqa: SLF001

    bridge.release(A)
    assert len(bridge._streams) == 1, "另一场还在盯，流不能停"  # noqa: SLF001
    bridge.release(B)
    assert bridge._streams == {}  # noqa: SLF001
    assert bridge._registered == set()  # noqa: SLF001


def test_只留清单说还活着的那几场(bridge, watch_dir):
    _write_session(watch_dir / f"{A}.jsonl", 1)
    _write_session(watch_dir / f"{B}.jsonl", 1)
    bridge.ensure_watching(A)
    bridge.ensure_watching(B)

    bridge.keep_only({B})
    assert bridge._registered == {B}  # noqa: SLF001
    (stream,) = bridge._streams.values()  # noqa: SLF001
    assert stream._watch_ids == {B}  # noqa: SLF001


def test_监听撤了又登记旁路观察的打开只投一次(bridge, watch_dir, opened):
    _write_session(watch_dir / f"{A}.jsonl", 1)
    bridge.ensure_watching(A)
    bridge.release(A)
    bridge.ensure_watching(A)
    bridge.note_opened(A)
    assert opened == [(A, "open")]


class TestTheRecordsRoute:
    """取记录那条接口按"这场还活不活"分流。"""

    @pytest.fixture
    def calls(self, monkeypatch):
        from frago.server.routes import workbench as route
        from frago.server.services import coreagent_runner
        from frago.server.services import tmux_sessions_service as tsvc

        seen: list[tuple[str, str]] = []

        class FakeBridge:
            def ensure_watching(self, sid):
                seen.append(("watch", sid))

            def release(self, sid):
                seen.append(("release", sid))

            def note_opened(self, sid):
                seen.append(("open", sid))

        monkeypatch.setattr(WorkbenchStreamBridge, "get_instance", classmethod(lambda cls, loop=None: FakeBridge()))
        monkeypatch.setattr(tsvc, "open_session_names", lambda: {f"frago-agent-{A}"})
        # 默认：CoreAgent 一场都没开着。要它活着的用例自己再打一次桩。
        monkeypatch.setattr(coreagent_runner, "running", lambda _sid: False)
        return route, seen

    def test_开在tmux里的登记监听(self, calls):
        route, seen = calls
        route._ensure_watching(A)  # noqa: SLF001
        assert seen == [("watch", A)]

    def test_不在tmux里也没活着的只补一次打开(self, calls):
        route, seen = calls
        route._ensure_watching(B)  # noqa: SLF001
        assert seen == [("release", B), ("open", B)]

    def test_coreagent那一场没开在tmux里也登记监听(self, calls, monkeypatch):
        """这一条就是本缺陷的守卫。

        CoreAgent 不跑在 tmux 里，从前它在"不活着的"那一侧：实时推送一次都不建立，兜底
        轮询又在静默 15 分钟后自己关掉，页面停在发出那句话的那一刻。它的活法要看自己的
        常驻进程。
        """
        from frago.server.services import coreagent_runner

        route, seen = calls
        monkeypatch.setattr(coreagent_runner, "running", lambda sid: sid == CORE)

        route._ensure_watching(CORE)  # noqa: SLF001
        assert seen == [("watch", CORE)], "CoreAgent 活着就该盯它的记录文件"

    def test_coreagent那一场收摊了照旧撤登记(self, calls, monkeypatch):
        """省资源的本意不变：空闲回收掉、真正关了的那一场回落成不盯。"""
        from frago.server.services import coreagent_runner

        route, seen = calls
        monkeypatch.setattr(coreagent_runner, "running", lambda _sid: False)

        route._ensure_watching(CORE)  # noqa: SLF001
        assert seen == [("release", CORE), ("open", CORE)]

    def test_判活着查不动时不盯也不炸(self, calls, monkeypatch):
        """一次读盘失败不该把取记录这条接口带崩，宁可不盯。"""
        from frago.server.services import coreagent_runner

        route, seen = calls

        def _boom(_sid):
            raise RuntimeError("锁坏了")

        monkeypatch.setattr(coreagent_runner, "running", _boom)

        route._ensure_watching(CORE)  # noqa: SLF001
        assert seen == [("release", CORE), ("open", CORE)]
