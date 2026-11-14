"""针对 agy 会话在 WorkbenchStreamBridge 与 SessionStream 中的定位与流式增量推送测试。

验证关键链路：
1. record_reader.locate_session_file / workbench_stream_bridge.locate_stream_file 单一事实源收口；
2. SessionStream 路径解析 (_resolve_session_id) 识别 transcript.jsonl 所属 conversation_id；
3. SessionStream 增量记录推送 (on_records) 与完成探针翻面 (on_turn_complete) 契约自洽；
4. SessionStream.unwatch_session 状态清理。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from frago.server.services.workbench_stream_bridge import locate_stream_file
from frago.session import agy_store, record_reader
from frago.session.store import SessionOntologyStore
from frago.session.stream import SessionStream
from frago.watcher import FileEvent

CONVERSATION_ID = "03d110d3-0124-4e24-aef3-5844318b8b4f"


@pytest.fixture(autouse=True)
def _isolated_session_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionOntologyStore:
    """把默认会话存储指到临时目录，别让这条用例的流去读写真人的那份账本。

    哪个环节出事：`SessionStream` 不传 `ontology_service` 时会自己造一个
    `SessionOntologyService()`，而它取的是模块级的默认存储——落在
    `~/.frago/workbench/session-ontology-store.json`，本机那份有 1.4MB。

    当事人看到什么现象：处理一批记录要先把那份 1.4MB 的 JSON 整份读回来解析，
    一次 `_process_file` 实测 926ms；而这条用例只等 200ms 就断言，于是完成探针还没翻面
    就判成「没完成」，报出来的却是 `assert 0 == 1`。单跑时机器闲，勉强赶上；和
    `test_ontology_kernel.py` 合跑时机器忙，就翻车——这就是那条「单跑通过、合跑失败」的真身。

    另外这也是一条写真人数据的通道：流会把会话登记与步数写回那份默认存储，
    当前靠 `tests/conftest.py` 的守门人拦下（拦截时抛的错被存储层吞掉，只在日志里留痕）。
    指到临时目录后，这条路根本不通向真人数据。
    """
    store = SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    import frago.session.store as store_module

    monkeypatch.setattr(store_module, "_DEFAULT_SESSION_STORE", store)
    return store


@pytest.fixture()
def app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 agy 应用数据目录至临时目录。"""
    root = tmp_path / "antigravity-cli"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(root))
    return root


def _write_records(records: list[dict], conversation_id: str = CONVERSATION_ID) -> Path:
    """写入 agy 记录至 transcript.jsonl。"""
    path = agy_store.transcript_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


class _DrainSpy:
    """数一数工作线程真正把 `_process_file` 跑完了几次。

    等「队列空了」是不够的：工作线程把待处理项从队列里取走那一刻队列就空了，而重活
    才刚刚开始。从前这里接着固定睡 200ms 当等待，机器一忙就不够——修的是存储隔离，
    但等待本身也不该靠猜。这里给等待一个确凿的终点：处理真跑完，计数才 +1。
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        original = SessionStream._process_file

        def counting(stream_self: SessionStream, path: str) -> None:
            try:
                original(stream_self, path)
            finally:
                self.count += 1

        monkeypatch.setattr(SessionStream, "_process_file", counting)

    def wait_for_next_round(self, stream: SessionStream, timeout: float = 5.0) -> None:
        """等到工作线程又跑完一轮处理。"""
        start = self.count
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.count > start:
                return
            time.sleep(0.01)
        raise AssertionError(
            f"等 {timeout}s 也没等到工作线程处理这一批记录（已处理 {start} 轮）。"
            "多半是这次文件事件压根没登记进待处理队列。"
        )


def _drain(spy: _DrainSpy, stream: SessionStream, timeout: float = 5.0) -> None:
    """等这次文件事件被工作线程处理完。"""
    spy.wait_for_next_round(stream, timeout=timeout)


def test_session_stream_precise_mapping_and_isolation(tmp_path: Path):
    """测试 SessionStream 精确双向映射、软链规范化及多会话并发隔离（零盲猜兜底）。"""
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    session_a_file = work_dir / "session_a" / "transcript.jsonl"
    session_a_file.parent.mkdir(parents=True, exist_ok=True)
    session_a_file.write_text('{"type": "init"}\n', encoding="utf-8")

    session_b_file = work_dir / "session_b" / "transcript.jsonl"
    session_b_file.parent.mkdir(parents=True, exist_ok=True)
    session_b_file.write_text('{"type": "init"}\n', encoding="utf-8")

    # 创建指向 session_a_file 的软链接
    symlink_file = work_dir / "symlink_a.jsonl"
    try:
        symlink_file.symlink_to(session_a_file)
        has_symlink = True
    except OSError:
        has_symlink = False

    stream = SessionStream(
        project_path=str(work_dir),
        watch_dir=work_dir,
        session_id_filter="session-a",
        watch_file=session_a_file,
    )
    try:
        # 并发注册第二场会话
        stream.watch_session("session-b", watch_file=session_b_file)

        # 确凿双向映射
        assert stream.get_session_for_path(session_a_file) == "session-a"
        assert stream.get_session_for_path(session_b_file) == "session-b"
        assert stream.get_session_file("session-a") == session_a_file.resolve()
        assert stream.get_session_file("session-b") == session_b_file.resolve()

        # 软链规范化解析
        if has_symlink:
            assert stream.get_session_for_path(symlink_file) == "session-a"

        # 零盲猜：未登记的同名 transcript.jsonl 绝不瞎猜兜底，返回 None
        unrelated_file = work_dir / "other" / "transcript.jsonl"
        assert stream.get_session_for_path(unrelated_file) is None

        # 取消 session-a 监听，双向映射同步注销，session-b 保持隔离完好
        stream.unwatch_session("session-a")
        assert stream.get_session_for_path(session_a_file) is None
        assert stream.get_session_file("session-a") is None
        assert stream.get_session_for_path(session_b_file) == "session-b"
        assert stream.get_session_file("session-b") == session_b_file.resolve()
    finally:
        stream.stop()


def test_locate_session_file_agy(app_dir: Path):
    """测试单一事实源 locate_session_file 能精确定位 agy 会话文件。"""
    # 尚未存在时返回 None
    assert record_reader.locate_session_file(CONVERSATION_ID) is None
    assert locate_stream_file(CONVERSATION_ID) is None

    # 创建会话文件
    initial_record = {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-11-11T10:00:00Z",
        "content": "<USER_REQUEST>你好</USER_REQUEST>",
    }
    transcript_file = _write_records([initial_record])

    # 能够正确定位
    located = record_reader.locate_session_file(CONVERSATION_ID)
    assert located == transcript_file
    assert located.is_file()

    # 桥接层的 locate_stream_file 也能委托拿到一致的结果
    assert locate_stream_file(CONVERSATION_ID) == transcript_file


def test_session_stream_agy_incremental_and_done(app_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """测试 SessionStream 对 agy 会话的实时监听、增量推送与完成判定。"""
    # 初始记录
    initial_user = {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-11-11T10:00:00Z",
        "content": "<USER_REQUEST>请计算 1+1</USER_REQUEST>",
    }
    transcript_file = _write_records([initial_user])

    emitted_records: list[tuple[str, list[dict]]] = []
    completed_turns: list[tuple[str, bool, str | None]] = []
    spy = _DrainSpy(monkeypatch)

    stream = SessionStream(
        project_path=str(transcript_file.parent),
        watch_dir=transcript_file.parent,
        on_records=lambda sid, recs: emitted_records.append((sid, recs)),
        on_turn_complete=lambda sid, done, reason: completed_turns.append((sid, done, reason)),
        debounce_seconds=0.05,
        session_id_filter=CONVERSATION_ID,
    )
    stream.start()

    try:
        # 1. 模拟初始文件被碰：由于是开始盯之前就存在的文件，符合纪律 1，只对齐水位不出货
        stream._on_file_event(  # noqa: SLF001
            FileEvent(path=str(transcript_file), event_type="modified", is_directory=False, timestamp=0.0)
        )
        _drain(spy, stream)
        assert len(emitted_records) == 0, "首次看见已有文件不应出货"

        # 2. 模型执行中：追加一行 PLANNER，含 tool_call，尚未完成
        mid_planner = {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-11-11T10:00:01Z",
            "content": "正在计算...",
            "tool_calls": [{"name": "calculator", "arguments": {"expr": "1+1"}}],
        }
        _write_records([mid_planner])
        stream._on_file_event(  # noqa: SLF001
            FileEvent(path=str(transcript_file), event_type="modified", is_directory=False, timestamp=0.0)
        )
        _drain(spy, stream)

        # 应该收到了增量记录，且 session_id 正确识别为 CONVERSATION_ID，非 transcript
        assert len(emitted_records) > 0
        sid, recs = emitted_records[-1]
        assert sid == CONVERSATION_ID
        assert any(r.get("kind") == "agent.say" for r in recs)
        # 尚未真正完成收尾（还在调工具），不应触发 on_turn_complete
        assert len(completed_turns) == 0

        # 3. 工具结果返回与最终完成回复
        tool_result = {
            "step_index": 2,
            "source": "TOOL",
            "type": "TOOL_RESPONSE",
            "status": "DONE",
            "created_at": "2026-11-11T10:00:02Z",
            "content": "2",
        }
        final_planner = {
            "step_index": 3,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-11-11T10:00:03Z",
            "content": "计算结果是 2。",
            "tool_calls": [],
        }
        _write_records([tool_result, final_planner])
        stream._on_file_event(  # noqa: SLF001
            FileEvent(path=str(transcript_file), event_type="modified", is_directory=False, timestamp=0.0)
        )
        _drain(spy, stream)

        # 应该触发了 on_turn_complete，且 stop_reason 正确
        assert len(completed_turns) == 1
        done_sid, is_done, stop_reason = completed_turns[0]
        assert done_sid == CONVERSATION_ID
        assert is_done is True
        assert stop_reason == "end_turn"

    finally:
        stream.stop()


def test_session_stream_unwatch_session(app_dir: Path):
    """测试 SessionStream.unwatch_session 能正确清理 agy 会话状态。"""
    user_record = {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-11-11T10:00:00Z",
        "content": "<USER_REQUEST>测试取消关注</USER_REQUEST>",
    }
    transcript_file = _write_records([user_record])

    stream = SessionStream(
        project_path=str(transcript_file.parent),
        watch_dir=transcript_file.parent,
        debounce_seconds=0.05,
        session_id_filter=CONVERSATION_ID,
    )
    assert stream.watching_any() is True

    # 模拟一次处理
    stream._process_file(str(transcript_file))  # noqa: SLF001
    assert str(transcript_file.resolve()) in stream._file_seqs  # noqa: SLF001

    # 取消关注
    stream.unwatch_session(CONVERSATION_ID)
    assert stream.watching_any() is False
    assert str(transcript_file.resolve()) not in stream._file_seqs  # noqa: SLF001
