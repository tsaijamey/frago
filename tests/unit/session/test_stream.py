"""SessionStream 的三条纪律各有一条测试兜着。

这三条都是"没人会一眼看出来"的那种病：不回放历史、去抖真的合并、没人看的会话不处理。
坏掉的时候界面上的症状是"更新很慢"或者"旧内容排在新内容后面"，从代码上看不出任何异常。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from frago.session import stream as stream_mod
from frago.session.stream import SessionStream


def _write_session(path: Path, count: int, start: int = 0) -> None:
    """往会话文件里追加 *count* 条最朴素的用户发言。"""
    with path.open("a", encoding="utf-8") as fh:
        for i in range(start, start + count):
            fh.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": f"u{i}",
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
def watch_dir(tmp_path, monkeypatch):
    """把 SessionStream 的会话目录指到 tmp_path，免得测试碰真档案。"""
    projects = tmp_path / "projects"
    encoded = "-tmp-proj"
    (projects / encoded).mkdir(parents=True)
    monkeypatch.setattr(stream_mod, "CLAUDE_PROJECTS_DIR", projects)
    monkeypatch.setattr(stream_mod, "encode_project_path", lambda _p: encoded)
    from frago.session.adapters import claude_code_records

    claude_code_records.clear_cache()
    yield projects / encoded
    claude_code_records.clear_cache()


def _drain(stream: SessionStream, timeout: float = 3.0) -> None:
    """等工作线程把手上的活干完。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with stream._cv:  # noqa: SLF001 — 测试要看内部队列
            if not stream._pending:  # noqa: SLF001
                break
        time.sleep(0.02)
    time.sleep(stream._debounce + 0.15)  # noqa: SLF001


def test_first_sight_of_existing_file_emits_nothing(watch_dir):
    """开始盯之前就在盘上的会话，第一次被碰不该把整场历史当成新内容推出去。

    坏掉时的症状：页面开着，某个老会话被碰一下，几千条旧记录接在流的尾巴上，
    最老的内容排在最新内容后面。
    """
    session = watch_dir / "aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    _write_session(session, 5)

    seen: list[tuple[str, int]] = []
    stream = SessionStream(
        project_path="/tmp/proj",
        on_records=lambda sid, recs: seen.append((sid, len(recs))),
        debounce_seconds=0.05,
        session_id_filter=session.stem,
    )
    stream.start()
    try:
        stream._on_file_event(  # noqa: SLF001 — 直接喂事件，不依赖真的文件系统通知
            stream_mod.FileEvent(
                path=str(session), event_type="modified", is_directory=False, timestamp=0.0
            )
        )
        _drain(stream)
        assert seen == [], "第一次看见已存在的文件时不该出货"

        # 水位已经对齐，此后真正新长出来的那几条照常推。
        _write_session(session, 2, start=5)
        stream._on_file_event(  # noqa: SLF001
            stream_mod.FileEvent(
                path=str(session), event_type="modified", is_directory=False, timestamp=0.0
            )
        )
        _drain(stream)
        assert [n for _sid, n in seen] == [2]
    finally:
        stream.stop()


def test_new_file_created_after_start_is_emitted_whole(watch_dir):
    """开始盯之后才出现的会话文件照常全发——那是页面新开的那一场，本来就只有几行。"""
    stream = SessionStream(project_path="/tmp/proj", debounce_seconds=0.05)
    seen: list[int] = []
    stream._on_records = lambda _sid, recs: seen.append(len(recs))  # noqa: SLF001
    stream.start()
    try:
        session = watch_dir / "bbbbbbbb-1111-2222-3333-444444444444.jsonl"
        stream.watch_session(session.stem)
        _write_session(session, 3)
        stream._on_file_event(  # noqa: SLF001
            stream_mod.FileEvent(
                path=str(session), event_type="modified", is_directory=False, timestamp=0.0
            )
        )
        _drain(stream)
        assert seen == [3]
    finally:
        stream.stop()


def test_unwatched_session_is_never_processed(watch_dir):
    """没人在看的那场会话，事件当场丢——一个项目目录下能躺一千个会话文件。"""
    watched = watch_dir / "cccccccc-1111-2222-3333-444444444444.jsonl"
    other = watch_dir / "dddddddd-1111-2222-3333-444444444444.jsonl"

    stream = SessionStream(project_path="/tmp/proj", debounce_seconds=0.05)
    stream.start()
    try:
        stream.watch_session(watched.stem)
        _write_session(other, 4)
        stream._on_file_event(  # noqa: SLF001
            stream_mod.FileEvent(
                path=str(other), event_type="modified", is_directory=False, timestamp=0.0
            )
        )
        with stream._cv:  # noqa: SLF001
            assert str(other) not in stream._pending  # noqa: SLF001
    finally:
        stream.stop()


def test_watchdog_thread_is_not_blocked(watch_dir):
    """事件回调必须立刻返回。它跑在 watchdog 的**单线程**分发器上，堵在这里等于整个
    观察者停摆，后面排队的事件全被拖住——从前正是在这里睡 0.3 秒。"""
    session = watch_dir / "eeeeeeee-1111-2222-3333-444444444444.jsonl"
    _write_session(session, 2)
    stream = SessionStream(project_path="/tmp/proj", debounce_seconds=0.5)
    stream.start()
    try:
        stream.watch_session(session.stem)
        started = time.monotonic()
        for _ in range(20):
            stream._on_file_event(  # noqa: SLF001
                stream_mod.FileEvent(
                    path=str(session), event_type="modified", is_directory=False, timestamp=0.0
                )
            )
        elapsed = time.monotonic() - started
        assert elapsed < 0.2, f"二十次事件登记花了 {elapsed:.2f} 秒，回调里还有重活"
    finally:
        stream.stop()


def test_debounce_actually_coalesces(watch_dir):
    """安静期内的多次改动合并成一次处理。

    从前这条去抖一次都没生效过：睡在分发线程上时后续事件根本进不来，"睡醒了看看有没有
    更新的事件"永远不成立，于是每一次落盘都各睡一次、各整翻一遍文件。
    """
    session = watch_dir / "ffffffff-1111-2222-3333-444444444444.jsonl"
    _write_session(session, 1)

    processed: list[str] = []
    stream = SessionStream(project_path="/tmp/proj", debounce_seconds=0.25)
    original = stream._process_file  # noqa: SLF001

    def counting(path: str) -> None:
        processed.append(path)
        original(path)

    stream._process_file = counting  # type: ignore[method-assign]  # noqa: SLF001
    stream.start()
    try:
        stream.watch_session(session.stem)
        for _ in range(10):
            stream._on_file_event(  # noqa: SLF001
                stream_mod.FileEvent(
                    path=str(session), event_type="modified", is_directory=False, timestamp=0.0
                )
            )
            time.sleep(0.02)
        _drain(stream, timeout=2.0)
        assert len(processed) == 1, f"十次改动被处理了 {len(processed)} 次，去抖没生效"
    finally:
        stream.stop()


def test_stop_joins_worker(watch_dir):
    """停了就是停了：工作线程要收得回来，不能留一条常驻线程在后台空转。"""
    stream = SessionStream(project_path="/tmp/proj", debounce_seconds=0.05)
    stream.start()
    worker = stream._worker  # noqa: SLF001
    assert worker is not None and worker.is_alive()
    stream.stop()
    assert not worker.is_alive()
    assert threading.active_count() >= 1


def test_watch_dir_is_used_verbatim_when_given(tmp_path, monkeypatch):
    """给了目录就用它，不再由工作目录推算。

    推算那条路有个致命前提：先得读得出这场会话的工作目录。而会话开头躺的常常是模式、
    权限之类不带工作目录的旁挂记录——实测抽样 300 场里 60 场（20%）读不出来，那些会话的
    实时推送因此**一次都没启动过**，页面只能靠轮询兜底，切到后台连轮询都被节流。
    会话文件本来就躺在它该被监听的目录里，用它既不用读内容，也不经过一次有损的编码往返。
    """
    elsewhere = tmp_path / "someone-elses-place"
    elsewhere.mkdir()

    def explode(_p):  # noqa: ANN001
        raise AssertionError("给了 watch_dir 就不该再去推算目录")

    monkeypatch.setattr(stream_mod, "encode_project_path", explode)
    stream = SessionStream(
        project_path="/whatever/does/not/matter",
        watch_dir=elsewhere,
        debounce_seconds=0.05,
    )
    stream.start()
    try:
        assert stream._watch_dir == elsewhere  # noqa: SLF001
    finally:
        stream.stop()
