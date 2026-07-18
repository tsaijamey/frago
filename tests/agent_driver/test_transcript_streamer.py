"""TranscriptStreamer tests (spec 20260607 Phase 6).

attached 流式改由 tail transcript 驱动后，这里守住四件事：text 块 → 文本记录、
tool_use 块 → **完整** input 对象、断点续读不重复发射、文件不存在时不崩。

用真实 claude JSONL 形状造样本（``message.content`` 为内容块数组），经真实的
``ClaudeCodeAdapter`` 解析——不 mock adapter，否则守不住"JSONL 里有完整 input"
这个本 phase 赖以成立的事实。
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from frago.agent_driver.streamer import TranscriptStreamer


def _rec(uuid: str, role: str, content: list[dict]) -> str:
    return json.dumps({
        "type": role,
        "uuid": uuid,
        "sessionId": "sess-1",
        "timestamp": "2026-07-17T10:00:00.000Z",
        "message": {"role": role, "content": content},
    })


def _append(path, *lines: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def _streamer(path) -> TranscriptStreamer:
    return TranscriptStreamer("claude", lambda: path if path.exists() else None)


def test_text_block_becomes_text_record(tmp_path):
    path = tmp_path / "sess-1.jsonl"
    _append(path, _rec("u1", "assistant", [{"type": "text", "text": "hello world"}]))

    records = _streamer(path).poll_once()

    assert len(records) == 1
    assert records[0].role == "assistant"
    assert records[0].content_text == "hello world"
    assert records[0].tool_calls == []


def test_tool_use_block_carries_complete_input_object(tmp_path):
    """parameters 直接取 tool_use.input —— 完整对象，NEVER 碎片拼装。"""
    path = tmp_path / "sess-1.jsonl"
    tool_input = {
        "command": "ls -la /tmp",
        "description": "list files",
        "timeout": 5000,
        "nested": {"deep": ["a", "b"]},
    }
    _append(path, _rec("u1", "assistant", [
        {"type": "tool_use", "id": "toolu_01", "name": "Bash", "input": tool_input},
    ]))

    records = _streamer(path).poll_once()

    assert len(records) == 1
    assert len(records[0].tool_calls) == 1
    block = records[0].tool_calls[0]
    assert block["id"] == "toolu_01"
    assert block["name"] == "Bash"
    # 完整 input 原样保留，一个键都不少、嵌套结构不丢。
    assert block["input"] == tool_input


def test_tool_result_block_parsed_from_user_record(tmp_path):
    path = tmp_path / "sess-1.jsonl"
    _append(path, _rec("u2", "user", [
        {"type": "tool_result", "tool_use_id": "toolu_01", "content": "file1\nfile2"},
    ]))

    records = _streamer(path).poll_once()

    assert len(records) == 1
    assert records[0].tool_results[0]["tool_use_id"] == "toolu_01"
    assert records[0].tool_results[0]["content"] == "file1\nfile2"


def test_resumed_read_never_re_emits(tmp_path):
    """断点续读：第二拍只给新增，已消费的记录 NEVER 再发一次。"""
    path = tmp_path / "sess-1.jsonl"
    _append(path, _rec("u1", "assistant", [{"type": "text", "text": "first"}]))

    streamer = _streamer(path)
    first = streamer.poll_once()
    assert [r.uuid for r in first] == ["u1"]

    # 没有新增 → 空，不重放 u1。
    assert streamer.poll_once() == []

    _append(path, _rec("u2", "assistant", [{"type": "text", "text": "second"}]))
    second = streamer.poll_once()
    assert [r.uuid for r in second] == ["u2"]
    assert streamer.poll_once() == []


def test_partial_line_is_not_consumed_until_complete(tmp_path):
    """写入方正在追加半行时不解析，补全后完整发射一次（断点续读的正确性前提）。"""
    path = tmp_path / "sess-1.jsonl"
    line = _rec("u1", "assistant", [{"type": "text", "text": "whole"}])
    head, tail = line[:20], line[20:]

    path.write_text(head, encoding="utf-8")  # 半行，无换行
    streamer = _streamer(path)
    assert streamer.poll_once() == []

    with path.open("a", encoding="utf-8") as f:
        f.write(tail + "\n")
    records = streamer.poll_once()
    assert [r.content_text for r in records] == ["whole"]


def test_missing_file_does_not_raise(tmp_path):
    """文件不存在 → 空列表、路径为 None，NEVER 崩。"""
    path = tmp_path / "never-created.jsonl"
    streamer = _streamer(path)

    assert streamer.poll_once() == []
    assert streamer.path is None
    streamer.seek_to_end()  # 也不能崩
    assert streamer.poll_once() == []


def test_file_appearing_later_is_picked_up(tmp_path):
    """文件后生成（claude TUI 起来才落盘）时自动接上。"""
    path = tmp_path / "sess-1.jsonl"
    streamer = _streamer(path)
    assert streamer.poll_once() == []

    _append(path, _rec("u1", "assistant", [{"type": "text", "text": "late"}]))
    assert [r.content_text for r in streamer.poll_once()] == ["late"]


def test_seek_to_end_skips_existing_history(tmp_path):
    """baseline 锚定：--resume 既有会话时历史 NEVER 被当新增重放。"""
    path = tmp_path / "sess-1.jsonl"
    _append(path, _rec("old", "assistant", [{"type": "text", "text": "history"}]))

    streamer = _streamer(path)
    streamer.seek_to_end()
    assert streamer.poll_once() == []

    _append(path, _rec("new", "assistant", [{"type": "text", "text": "fresh"}]))
    assert [r.uuid for r in streamer.poll_once()] == ["new"]


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "sess-1.jsonl"
    _append(path, "{not json at all", _rec("u1", "assistant", [{"type": "text", "text": "ok"}]))

    records = _streamer(path).poll_once()
    assert [r.content_text for r in records] == ["ok"]


def test_run_emits_records_then_cancels(tmp_path):
    """异步循环：能被 asyncio 消费，发射后可 cancel 收尾。"""
    path = tmp_path / "sess-1.jsonl"
    _append(path, _rec("u1", "assistant", [{"type": "text", "text": "streamed"}]))
    streamer = TranscriptStreamer(
        "claude", lambda: path if path.exists() else None, poll_interval_s=0.01
    )
    seen: list[str] = []

    async def scenario():
        async def on_record(record):
            seen.append(record.content_text)

        task = asyncio.create_task(streamer.run(on_record))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if seen:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert seen == ["streamed"]


def test_run_backs_off_while_file_missing(tmp_path):
    """文件未生成时退避轮询：不死等（文件出现后接上）、也不立刻放弃。"""
    path = tmp_path / "sess-1.jsonl"
    streamer = TranscriptStreamer(
        "claude",
        lambda: path if path.exists() else None,
        poll_interval_s=0.01,
        missing_backoff_start_s=0.01,
        missing_backoff_max_s=0.05,
    )
    seen: list[str] = []

    async def scenario():
        async def on_record(record):
            seen.append(record.content_text)

        task = asyncio.create_task(streamer.run(on_record))
        await asyncio.sleep(0.05)  # 文件还不存在，循环必须活着
        assert seen == []
        assert not task.done()

        _append(path, _rec("u1", "assistant", [{"type": "text", "text": "appeared"}]))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if seen:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert seen == ["appeared"]
