"""opencode 翻译层单测（spec 20260729-session-workbench-webui Phase 1c）。

全部自建临时 SQLite 库（表结构照 opencode 1.18.0 实测），经 ``FRAGO_OPENCODE_DB``
指过去。NEVER 触碰用户真实的 ``~/.local/share/opencode/opencode.db``——那个库带着未合并
的日志文件，直接打开就会触发恢复写入。

三条回归用例对应三个实测出来的陷阱，各自单独一节，改坏了会当场红：

1. 工具的调用与结果在同一条片段的两个字段里 → 翻译后必须是两条，共用同一个调用编号
2. 带报错标记的 12 条里 11 条是用户按停 → 那 11 条归「打断」不归「报错」
3. 待办是 agent 主动写入，与另一家的引擎被动重发不是一回事 → 必须带来源标记
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.session.adapters import opencode_records
from frago.session.unified_record import (
    RECORD_KINDS,
    TOOL_FAMILIES,
    TRUNCATION_STATES,
    UnifiedRecord,
)

_SCHEMA = """
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    parent_id text,
    time_created integer NOT NULL,
    time_updated integer NOT NULL DEFAULT 0
);
CREATE TABLE message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
CREATE TABLE part (
    id text PRIMARY KEY,
    message_id text NOT NULL,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    time_updated integer NOT NULL DEFAULT 0,
    data text NOT NULL
);
CREATE TABLE session_message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    type text NOT NULL,
    seq integer NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
"""

SESSION = "ses_test000000000000000000000"


class Builder:
    """一场会话的搭建器。消息与片段按调用顺序落盘，时刻自动递增。"""

    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self.clock = 1_785_000_000_000
        self.msg_seq = 0
        self.part_seq = 0
        self.event_seq = 0
        self.conn.execute(
            "INSERT INTO session (id, directory, title, parent_id, time_created, time_updated) "
            "VALUES (?, '/tmp/proj', 'T', NULL, ?, ?)",
            (SESSION, self.clock, self.clock),
        )

    def _tick(self) -> int:
        self.clock += 1000
        return self.clock

    def message(self, role: str, **extra: Any) -> str:
        self.msg_seq += 1
        mid = f"msg_{self.msg_seq:04d}"
        created = self._tick()
        data: dict[str, Any] = {"role": role, "time": {"created": created}}
        data.update(extra)
        self.conn.execute(
            "INSERT INTO message (id, session_id, time_created, data) VALUES (?, ?, ?, ?)",
            (mid, SESSION, created, json.dumps(data)),
        )
        return mid

    def part(self, message_id: str, data: dict[str, Any]) -> str:
        self.part_seq += 1
        pid = f"prt_{self.part_seq:04d}"
        created = self._tick()
        self.conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, message_id, SESSION, created, created, json.dumps(data)),
        )
        return pid

    def event(self, event_type: str, data: dict[str, Any]) -> str:
        self.event_seq += 1
        eid = f"msg_evt{self.event_seq:03d}"
        created = self._tick()
        self.conn.execute(
            "INSERT INTO session_message (id, session_id, type, seq, time_created, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, SESSION, event_type, self.event_seq, created, json.dumps(data)),
        )
        return eid

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()


@pytest.fixture
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """返回一个搭建器工厂。库路径经环境变量指过去，真实用户库全程不参与。"""
    path = tmp_path / "opencode.db"
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))

    created: list[Builder] = []

    def _make() -> Builder:
        builder = Builder(path)
        created.append(builder)
        return builder

    yield _make
    for builder in created:
        # 用例体里已经 close 过是常态，这里只兜没 close 的那种。
        with contextlib.suppress(sqlite3.ProgrammingError):
            builder.close()


def _tool_part(
    tool: str,
    call_id: str,
    *,
    status: str = "completed",
    output: str | None = "ok",
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    input_args: dict[str, Any] | None = None,
    title: str | None = "t",
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": status,
        "input": input_args if input_args is not None else {"command": "ls"},
        "metadata": metadata if metadata is not None else {"truncated": False},
        "time": {"start": 1_785_000_000_000, "end": 1_785_000_000_120},
    }
    if output is not None:
        state["output"] = output
    if error is not None:
        state["error"] = error
    if title is not None:
        state["title"] = title
    return {"type": "tool", "tool": tool, "callID": call_id, "state": state}


def _kinds(records: list[UnifiedRecord]) -> list[str]:
    return [record.kind for record in records]


def _by_kind(records: list[UnifiedRecord], kind: str) -> list[UnifiedRecord]:
    return [record for record in records if record.kind == kind]


# ══ 回归一：调用与结果拆成两条，共用同一个调用编号 ══════════════════
def test_tool_part_splits_into_call_and_result(build) -> None:  # type: ignore[no-untyped-def]
    """opencode 把参数与返回放在同一条片段的两个字段里。翻译后必须是两条。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(mid, {"type": "step-start", "snapshot": "a" * 40})
    part_id = builder.part(mid, _tool_part("bash", "bash_19", output="hello"))
    builder.part(mid, {"type": "step-finish", "reason": "tool-calls"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    calls = _by_kind(records, "tool.call")
    results = _by_kind(records, "tool.result")

    assert len(calls) == 1
    assert len(results) == 1
    # 共用同一个调用编号——界面靠它把两张卡拼成一张。
    assert calls[0].payload["call_id"] == results[0].payload["call_id"] == "bash_19"
    # 记录编号必须分开，否则按编号去重会吃掉一条。
    assert calls[0].id == part_id
    assert results[0].id == f"{part_id}:result"
    # 参数在调用那条，正文在结果那条，不重复。
    assert calls[0].payload["args"] == {"command": "ls"}
    assert results[0].payload["body"] == "hello"
    assert "body" not in calls[0].payload
    # 顺序：调用在结果之前。
    assert calls[0].seq < results[0].seq


def test_tool_pairing_has_no_orphan_result(build) -> None:  # type: ignore[no-untyped-def]
    """多个工具混在一条消息里时，配对率仍是 100%，无孤儿结果。"""
    builder = build()
    mid = builder.message("assistant")
    for index in range(5):
        builder.part(mid, _tool_part("bash", f"call_{index}"))
    builder.close()

    records = opencode_records.to_unified(SESSION)
    call_ids = [r.payload["call_id"] for r in _by_kind(records, "tool.call")]
    result_ids = [r.payload["call_id"] for r in _by_kind(records, "tool.result")]
    assert call_ids == result_ids == [f"call_{i}" for i in range(5)]


def test_tool_without_call_id_falls_back_to_part_id(build) -> None:  # type: ignore[no-untyped-def]
    """callID 形态由供应商决定，缺失时退回片段编号，配对照样成立。"""
    builder = build()
    mid = builder.message("assistant")
    part = _tool_part("bash", "x")
    del part["callID"]
    part_id = builder.part(mid, part)
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _by_kind(records, "tool.call")[0].payload["call_id"] == part_id
    assert _by_kind(records, "tool.result")[0].payload["call_id"] == part_id


# ══ 回归二：带报错标记的用户中断归「打断」，不归「报错」 ════════════
def test_aborted_message_becomes_interrupt_not_error(build) -> None:  # type: ignore[no-untyped-def]
    """11/12 条带 error 的消息是人按了停止。归报错会让界面显示成老崩。"""
    builder = build()
    mid = builder.message(
        "assistant",
        error={"name": "MessageAbortedError", "data": {"message": "Aborted"}},
    )
    builder.part(mid, {"type": "step-start"})
    builder.part(mid, {"type": "reasoning", "text": "想到一半"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    interrupts = _by_kind(records, "interrupt")
    assert len(interrupts) == 1
    assert not _by_kind(records, "error")
    assert interrupts[0].payload["target"] == mid
    # 断在模型吐字中途。
    assert interrupts[0].payload["phase"] == "generating"
    assert interrupts[0].payload["source"] == "message-error"


def test_real_api_error_stays_error(build) -> None:  # type: ignore[no-untyped-def]
    """12 条里真出错的那 1 条照旧归报错，且只留三个字段。"""
    builder = build()
    builder.message(
        "assistant",
        error={
            "name": "APIError",
            "data": {
                "message": "Bad gateway",
                "statusCode": 502,
                "isRetryable": True,
                # 响应头里带 Cloudflare 的登录凭据，一个字都不许进 payload。
                "responseHeaders": {"set-cookie": "__cf_bm=SECRET"},
                "responseBody": "<html>SECRET</html>",
            },
        },
    )
    builder.close()

    records = opencode_records.to_unified(SESSION)
    errors = _by_kind(records, "error")
    assert len(errors) == 1
    assert not _by_kind(records, "interrupt")
    assert errors[0].payload == {"scope": "api", "code": "APIError:502", "message": "Bad gateway"}
    # 原文入口恒不可用。
    assert errors[0].raw_available is False
    assert errors[0].is_raw_readable() is False
    assert "SECRET" not in json.dumps(errors[0].payload)


def test_interrupt_phase_variants(build) -> None:  # type: ignore[no-untyped-def]
    """打断位置从最后一个内容片段反推；一个片段都没有时照实写未知。"""
    builder = build()
    aborted = {"name": "MessageAbortedError", "data": {"message": "Aborted"}}

    tool_mid = builder.message("assistant", error=aborted)
    builder.part(tool_mid, {"type": "step-start"})
    builder.part(tool_mid, _tool_part("bash", "c1"))

    text_mid = builder.message("assistant", error=aborted)
    builder.part(text_mid, {"type": "text", "text": "写到一半"})

    builder.message("assistant", error=aborted)  # 一个片段都没有
    builder.close()

    phases = [r.payload["phase"] for r in _by_kind(opencode_records.to_unified(SESSION), "interrupt")]
    assert phases == ["tool-executing", "generating", "unknown"]


def test_error_raw_is_refused(build) -> None:  # type: ignore[no-untyped-def]
    """报错类记录取原文恒返回 None——那条原文里带着登录凭据。"""
    builder = build()
    mid = builder.message(
        "assistant",
        error={"name": "APIError", "data": {"message": "x", "responseHeaders": {"set-cookie": "S"}}},
    )
    builder.close()

    assert opencode_records.read_raw(SESSION, f"{mid}:error") is None


# ══ 回归三：待办带来源标记 ══════════════════════════════════════════
def test_todowrite_carries_agent_write_source(build) -> None:  # type: ignore[no-untyped-def]
    """opencode 的待办是 agent 主动写入，与另一家引擎被动重发的清单不是一回事。"""
    builder = build()
    mid = builder.message("assistant")
    todos = [
        {"priority": "high", "content": "第一项", "status": "completed"},
        {"priority": "pending", "content": "第二项", "status": "in_progress"},
    ]
    builder.part(
        mid,
        _tool_part(
            "todowrite",
            "call_todo",
            input_args={"todos": todos},
            metadata={"todos": todos, "truncated": False},
            output=json.dumps(todos),
            title="2 todos",
        ),
    )
    builder.close()

    records = opencode_records.to_unified(SESSION)
    snapshots = _by_kind(records, "todo.snapshot")
    assert len(snapshots) == 1
    assert snapshots[0].payload["source"] == "agent-write"
    assert snapshots[0].payload["item_count"] == 2
    # priority 实测出现过 pending 这样的脏值，一个字不改地照搬。
    assert snapshots[0].payload["items"][1]["priority"] == "pending"
    # 待办不再另出一条工具调用/结果。
    assert not _by_kind(records, "tool.call")


def test_todo_items_fall_back_to_output_json(build) -> None:  # type: ignore[no-untyped-def]
    """input 与 metadata 都没有 todos 时，退回二次 parse ``state.output``。"""
    builder = build()
    mid = builder.message("assistant")
    todos = [{"content": "只在 output 里", "status": "pending", "priority": "high"}]
    builder.part(
        mid,
        _tool_part(
            "todowrite",
            "call_todo",
            input_args={},
            metadata={"truncated": False},
            output=json.dumps(todos),
        ),
    )
    builder.close()

    snapshot = _by_kind(opencode_records.to_unified(SESSION), "todo.snapshot")[0]
    assert snapshot.payload["items"] == todos


# ══ 两处容错 ═══════════════════════════════════════════════════════
def test_unbalanced_step_markers_render_without_error(build) -> None:  # type: ignore[no-untyped-def]
    """步骤开始与结束差 8 条，全是缺尾不缺头。单边缺失照常渲染，不报错。"""
    builder = build()
    mid = builder.message(
        "assistant", error={"name": "MessageAbortedError", "data": {"message": "Aborted"}}
    )
    builder.part(mid, {"type": "step-start", "snapshot": "b" * 40})
    builder.part(mid, {"type": "reasoning", "text": "想到一半"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    markers = [r for r in records if r.payload.get("channel") == "step-marker"]
    assert len(markers) == 1
    assert markers[0].payload["phase"] == "start"
    assert markers[0].payload["paired"] is False
    assert markers[0].payload["step_start_count"] == 1
    assert markers[0].payload["step_finish_count"] == 0


def test_step_pairing_never_crosses_messages(build) -> None:  # type: ignore[no-untyped-def]
    """配对只在单条消息内做。上一条缺尾，NEVER 拿下一条的结束去凑。"""
    builder = build()
    first = builder.message("assistant")
    builder.part(first, {"type": "step-start"})  # 缺尾
    second = builder.message("assistant")
    builder.part(second, {"type": "step-start"})
    builder.part(second, {"type": "step-finish", "reason": "stop", "cost": 0.1})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    markers = [r for r in records if r.payload.get("channel") == "step-marker"]
    assert [m.group_id for m in markers] == [first, second, second]
    # 第一条消息单边缺失，后两条自己配平——错位没有传染。
    assert [m.payload["paired"] for m in markers] == [False, True, True]


def test_message_without_parts_is_not_corruption(build) -> None:  # type: ignore[no-untyped-def]
    """4 条消息一个片段都没有。照常处理，不当作损坏，也不抛。"""
    builder = build()
    builder.message("assistant")  # 无片段、无报错
    mid = builder.message("user")
    builder.part(mid, {"type": "text", "text": "还在"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["user.say"]
    assert records[0].seq == 0


def test_empty_session_returns_empty_list(build) -> None:  # type: ignore[no-untyped-def]
    """一条记录都没有的空壳会话返回空列表，不抛。"""
    builder = build()
    builder.close()
    assert opencode_records.to_unified(SESSION) == []
    assert opencode_records.to_unified("ses_nonexistent") == []


# ══ 兜底：无法归类的片段归注入内容并标记未识别 ═════════════════════
def test_unknown_part_type_is_never_dropped(build) -> None:  # type: ignore[no-untyped-def]
    """认不出的片段类型归注入内容并标记未识别。NEVER 静默丢弃。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(mid, {"type": "hologram", "payload": {"x": 1}})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert len(records) == 1
    assert records[0].kind == "context.inject"
    assert records[0].payload["unrecognized"] is True
    assert records[0].payload["part_type"] == "hologram"
    assert records[0].payload["channel"] == "unknown"


def test_part_with_no_type_is_never_dropped(build) -> None:  # type: ignore[no-untyped-def]
    """连 type 字段都没有的片段同样保留。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(mid, {"whatever": 1})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert len(records) == 1
    assert records[0].kind == "context.inject"
    assert records[0].payload["unrecognized"] is True


def test_part_from_another_session_gets_fallback_envelope(build) -> None:  # type: ignore[no-untyped-def]
    """片段自报的会话与它所属消息的会话对不上时补兜底信封，片段本身不许消失。

    片段表冗余存了一份 ``session_id``。本机 1947 条与所属消息完全一致、0 例外，但那是数据
    现状不是结构保证：两者一旦分家，这条片段会出现在 A 会话的片段里、而它的信封在 B 会话
    的消息里。查不到信封就整条丢掉，那段内容在界面上等于没发生过。
    """
    builder = build()
    other = builder.message("assistant")
    builder.conn.execute("UPDATE message SET session_id = 'ses_other' WHERE id = ?", (other,))
    builder.part(other, {"type": "text", "text": "对不上的那条"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert len(records) == 1
    assert records[0].kind == "agent.say"
    assert records[0].payload["text"] == "对不上的那条"
    assert records[0].group_id == other


# ══ 逐种形态的映射 ═════════════════════════════════════════════════
def test_user_text_and_synthetic_injection(build) -> None:  # type: ignore[no-untyped-def]
    """用户消息下的合成片段不是用户打的字，归注入内容，不归用户发言。"""
    builder = build()
    mid = builder.message("user", agent="build")
    builder.part(mid, {"type": "text", "text": "帮我看看"})
    builder.part(
        mid,
        {
            "type": "text",
            "text": "<system-reminder>打开了某文件</system-reminder>",
            "synthetic": True,
            "metadata": {"kind": "editor_context", "source": "websocket", "filePath": "/a/b.py"},
        },
    )
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["user.say", "context.inject"]
    # 用户输入类不设分组键。
    assert records[0].group_id is None
    assert records[0].payload["text"] == "帮我看看"
    # opencode 不落输入来源，缺失就留空，NEVER 默认成「人手打的」。
    assert records[0].payload["input_mode"] is None
    assert records[1].group_id == mid
    assert records[1].payload["channel"] == "editor-context"
    assert records[1].payload["file_path"] == "/a/b.py"
    assert records[1].payload["unrecognized"] is False


def test_assistant_text_and_reasoning(build) -> None:  # type: ignore[no-untyped-def]
    """助手正文归 agent.say，思考归 agent.think，两者都带模型标识。"""
    builder = build()
    mid = builder.message("assistant", modelID="kimi-k3", providerID="openrouter")
    builder.part(mid, {"type": "reasoning", "text": "先读文件"})
    builder.part(mid, {"type": "text", "text": "读完了"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["agent.think", "agent.say"]
    assert all(r.group_id == mid for r in records)
    assert records[0].payload["model"] == "kimi-k3"
    assert records[1].payload["provider"] == "openrouter"


def test_task_tool_becomes_subagent_dispatch(build) -> None:  # type: ignore[no-untyped-def]
    """派发子 agent 归 subagent.dispatch，子会话编号从 metadata 取。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(
        mid,
        _tool_part(
            "task",
            "call_task",
            input_args={"description": "查目录", "prompt": "去查", "subagent_type": "explore"},
            metadata={
                "parentSessionId": SESSION,
                "sessionId": "ses_child",
                "truncated": False,
            },
            output="<task id='ses_child' state='completed'>…",
        ),
    )
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["subagent.dispatch"]
    assert records[0].payload["child_session_id"] == "ses_child"
    assert records[0].payload["agent_type"] == "explore"
    assert records[0].payload["trace_available"] is True
    # 子 agent 是独立会话，不混进父会话的轨迹。
    assert records[0].agent_path == []


def test_file_part_keeps_metadata_not_base64(build) -> None:  # type: ignore[no-untyped-def]
    """附件只留元数据。整段 base64 单条见过 1.9 MB，进 payload 就能打死浏览器。"""
    builder = build()
    mid = builder.message("user")
    builder.part(
        mid,
        {
            "type": "file",
            "mime": "application/pdf",
            "filename": "报告.pdf",
            "url": "data:application/pdf;base64," + "A" * 5000,
            "source": {"type": "file", "path": "/a/报告.pdf"},
        },
    )
    builder.close()

    record = opencode_records.to_unified(SESSION)[0]
    assert record.kind == "media.attach"
    assert record.payload["media_type"] == "application/pdf"
    assert record.payload["display_name"] == "报告.pdf"
    assert record.payload["ref"] == "/a/报告.pdf"
    assert record.payload["inline"] is True
    assert "AAAA" not in json.dumps(record.payload, ensure_ascii=False)


def test_patch_part_becomes_diff_injection(build) -> None:  # type: ignore[no-untyped-def]
    """文件改动汇总归注入内容的 diff 档，不当报错也不当工具。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(mid, {"type": "patch", "hash": "c" * 40, "files": ["/a/uv.lock"]})
    builder.close()

    record = opencode_records.to_unified(SESSION)[0]
    assert record.kind == "context.inject"
    assert record.payload["channel"] == "diff"
    assert record.payload["files"] == ["/a/uv.lock"]


def test_session_events_become_state_changes(build) -> None:  # type: ignore[no-untyped-def]
    """切 agent / 切模型在另一张表里，要与消息时间线归并。"""
    builder = build()
    builder.event("agent-switched", {"agent": "build"})
    builder.event("model-switched", {"model": {"id": "gpt-5", "providerID": "aiverse"}})
    mid = builder.message("user")
    builder.part(mid, {"type": "text", "text": "开工"})
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["session.state", "session.state", "user.say"]
    assert records[0].payload["field"] == "agent"
    assert records[0].payload["to"] == "build"
    assert records[1].payload["field"] == "model"
    assert records[1].payload["to"] == "gpt-5"
    # opencode 只记切成了什么，不记切之前是什么。
    assert records[0].payload["from"] is None


# ══ 工具结果的状态与截断 ═══════════════════════════════════════════
def test_offloaded_wins_over_truncated_flag(build) -> None:  # type: ignore[no-untyped-def]
    """溢出转存与截断标记是两套机制。先查 outputPath，只看标志一定误判。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(
        mid,
        _tool_part(
            "bash",
            "call_big",
            output="...output truncated...\n\nFull output saved to: /d/tool-output/tool_x",
            # 实测这个标志在溢出记录上写过 false 也写过 true，两种都不能当判据。
            metadata={"truncated": False, "outputPath": "/d/tool-output/tool_x", "exit": 0},
        ),
    )
    builder.close()

    result = _by_kind(opencode_records.to_unified(SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "offloaded"
    assert result.payload["truncation_ref"] == "/d/tool-output/tool_x"


def test_truncated_flag_becomes_clipped(build) -> None:  # type: ignore[no-untyped-def]
    """只有截断标记、没有溢出文件时是 clipped，全文永久丢失。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(mid, _tool_part("grep", "c", metadata={"truncated": True, "matches": 9}))
    builder.close()

    result = _by_kind(opencode_records.to_unified(SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "clipped"
    assert result.payload["truncation_ref"] is None


def test_normal_result_truncation_is_none(build) -> None:  # type: ignore[no-untyped-def]
    builder = build()
    mid = builder.message("assistant")
    builder.part(mid, _tool_part("bash", "c", metadata={"truncated": False, "exit": 0}))
    builder.close()

    result = _by_kind(opencode_records.to_unified(SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "none"
    assert result.payload["status"] == "ok"
    assert result.payload["exit_code"] == 0
    assert result.payload["duration_ms"] == 120


def test_interrupted_tool_is_not_plain_error(build) -> None:  # type: ignore[no-untyped-def]
    """工具被中断时状态是 interrupted，不是 error——同一个道理的第二处。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(
        mid,
        _tool_part(
            "read",
            "read_6",
            status="error",
            output=None,
            error="Tool execution aborted",
            metadata={"interrupted": True},
            title=None,
        ),
    )
    builder.close()

    result = _by_kind(opencode_records.to_unified(SESSION), "tool.result")[0]
    assert result.payload["status"] == "interrupted"
    # 失败时没有 output，正文取那句 error。
    assert result.payload["body"] == "Tool execution aborted"
    # 5 条 error 状态的工具片段没有 title 字段，渲染要兜底。
    assert _by_kind(opencode_records.to_unified(SESSION), "tool.call")[0].payload["title"] is None


def test_denied_tool_emits_permission_outcome(build) -> None:  # type: ignore[no-untyped-def]
    """用户拒绝的痕迹只在 error 文本里。拒绝是真事件，照实出一条拦截记录。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(
        mid,
        _tool_part(
            "read",
            "read_9",
            status="error",
            output=None,
            error="The user rejected permission to use this specific tool call.",
            metadata={},
            title=None,
        ),
    )
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["tool.call", "tool.result", "permission.outcome"]
    assert _by_kind(records, "tool.result")[0].payload["status"] == "denied"
    assert _by_kind(records, "permission.outcome")[0].payload["decision"] == "denied"


def test_bash_raw_output_kept_apart_from_model_view(build) -> None:  # type: ignore[no-untyped-def]
    """喂给模型的 output 与命令的原始 stdout 在 bash 上会不等，两份都要留。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(
        mid,
        _tool_part(
            "bash",
            "bash_1",
            output="<frago-NOTICE>规则</frago-NOTICE>\n真实输出",
            metadata={"output": "真实输出", "exit": 0, "truncated": False},
        ),
    )
    builder.close()

    result = _by_kind(opencode_records.to_unified(SESSION), "tool.result")[0]
    assert result.payload["body"].startswith("<frago-NOTICE>")
    assert result.payload["raw_output"] == "真实输出"


def test_missing_tool_time_gives_no_duration(build) -> None:  # type: ignore[no-untyped-def]
    """两端时刻缺一就不给耗时，NEVER 用 0 冒充「很快」。"""
    builder = build()
    mid = builder.message("assistant")
    part = _tool_part("bash", "c")
    del part["state"]["time"]
    builder.part(mid, part)
    builder.close()

    result = _by_kind(opencode_records.to_unified(SESSION), "tool.result")[0]
    assert result.payload["duration_ms"] is None


# ══ 工具大类 ═══════════════════════════════════════════════════════
@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("bash", "shell"),
        ("read", "file-read"),
        ("edit", "file-write"),
        ("write", "file-write"),
        ("grep", "search"),
        ("glob", "search"),
        ("webfetch", "web"),
        ("websearch", "web"),
        ("task", "agent"),
        ("todowrite", "todo"),
        ("question", "ask"),
        ("mcp__github__list_prs", "mcp"),
        ("Bash", "shell"),
        ("某个没见过的工具", "other"),
        ("", "other"),
    ],
)
def test_tool_family_mapping(tool_name: str, expected: str) -> None:
    """按大类分支，不按工具名穷举——工具名不是封闭集合。"""
    assert opencode_records.tool_family_of(tool_name) == expected
    assert expected in TOOL_FAMILIES


def test_question_tool_is_an_ordinary_tool(build) -> None:  # type: ignore[no-untyped-def]
    """向用户提问本次按普通工具渲染：决策回流不在这次范围内。"""
    builder = build()
    mid = builder.message("assistant")
    builder.part(
        mid,
        _tool_part(
            "question",
            "call_q",
            input_args={"questions": [{"question": "选哪个", "options": []}]},
            metadata={"answers": [["选项二"]], "truncated": False},
            output="User has answered your questions",
            title="Asked 1 question",
        ),
    )
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert _kinds(records) == ["tool.call", "tool.result"]
    assert records[0].payload["tool_family"] == "ask"


# ══ 序号、分页与取原文 ═════════════════════════════════════════════
def _busy_session(builder: Builder) -> None:
    user = builder.message("user")
    builder.part(user, {"type": "text", "text": "开工"})
    for index in range(3):
        mid = builder.message("assistant", modelID="m")
        builder.part(mid, {"type": "step-start"})
        builder.part(mid, {"type": "reasoning", "text": f"想 {index}"})
        builder.part(mid, _tool_part("bash", f"call_{index}"))
        builder.part(mid, {"type": "step-finish", "reason": "tool-calls"})


def test_seq_is_dense_and_starts_at_zero(build) -> None:  # type: ignore[no-untyped-def]
    """序号从 0 起密集递增，无空洞。顺序取物理序，不按记录时刻重排。"""
    builder = build()
    _busy_session(builder)
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert [r.seq for r in records] == list(range(len(records)))
    assert all(r.kind in RECORD_KINDS for r in records)
    assert all(r.session_id == SESSION for r in records)


def test_after_is_inclusive_and_limit_caps(build) -> None:  # type: ignore[no-untyped-def]
    """``after`` 是序号本身、含首条：after=0 拿到的第一条 seq 就是 0。"""
    builder = build()
    _busy_session(builder)
    builder.close()

    everything = opencode_records.to_unified(SESSION)
    first_five = opencode_records.to_unified(SESSION, after=0, limit=5)
    assert [r.seq for r in first_five] == [0, 1, 2, 3, 4]

    tail = opencode_records.to_unified(SESSION, after=5, limit=3)
    assert [r.seq for r in tail] == [5, 6, 7]
    assert [r.id for r in tail] == [r.id for r in everything[5:8]]

    assert opencode_records.to_unified(SESSION, after=len(everything), limit=10) == []
    # limit 不给就是不限。
    assert len(opencode_records.to_unified(SESSION, after=0)) == len(everything)


def test_tail_takes_the_last_records(build) -> None:  # type: ignore[no-untyped-def]
    """tail=True 忽略 after，取整场最后 limit 条——中栏打开要直接落在最新内容上。"""
    builder = build()
    _busy_session(builder)
    builder.close()

    everything = opencode_records.to_unified(SESSION)
    last_three = opencode_records.to_unified(SESSION, after=0, limit=3, tail=True)
    assert [r.id for r in last_three] == [r.id for r in everything[-3:]]
    # after 在 tail 模式下被忽略。
    ignored_cursor = opencode_records.to_unified(SESSION, after=5, limit=3, tail=True)
    assert [r.id for r in ignored_cursor] == [r.id for r in everything[-3:]]


def test_timestamps_are_plain_milliseconds(build) -> None:  # type: ignore[no-untyped-def]
    """opencode 存的是毫秒整数，直接用。本模块不产生 datetime，也就不涉及时区。"""
    builder = build()
    _busy_session(builder)
    builder.close()

    records = opencode_records.to_unified(SESSION)
    assert all(isinstance(r.ts, int) for r in records)
    assert all(r.ts > 1_700_000_000_000 for r in records)


def test_read_raw_returns_part_and_message(build) -> None:  # type: ignore[no-untyped-def]
    """取原文：调用与结果两条记录指回同一条片段；消息级记录指回信封。"""
    builder = build()
    mid = builder.message(
        "assistant", error={"name": "MessageAbortedError", "data": {"message": "Aborted"}}
    )
    part_id = builder.part(mid, _tool_part("bash", "call_x"))
    builder.close()

    call_raw = opencode_records.read_raw(SESSION, part_id)
    result_raw = opencode_records.read_raw(SESSION, f"{part_id}:result")
    assert call_raw is not None and result_raw is not None
    assert call_raw["data"]["callID"] == "call_x"
    assert call_raw == result_raw

    interrupt_raw = opencode_records.read_raw(SESSION, f"{mid}:interrupt")
    assert interrupt_raw is not None
    assert interrupt_raw["data"]["error"]["name"] == "MessageAbortedError"

    assert opencode_records.read_raw(SESSION, "prt_nope") is None


def test_read_raw_scrubs_credentials_from_message(build) -> None:  # type: ignore[no-untyped-def]
    """就算有人拿消息编号直接来要原文，凭据字段也要在这一层剥掉。"""
    builder = build()
    mid = builder.message(
        "assistant",
        error={
            "name": "APIError",
            "data": {
                "message": "boom",
                "responseHeaders": {"set-cookie": "__cf_bm=SECRET"},
                "responseBody": "SECRET",
            },
        },
    )
    builder.close()

    raw = opencode_records.read_raw(SESSION, mid)
    assert raw is not None
    assert "SECRET" not in json.dumps(raw, ensure_ascii=False)
    assert raw["data"]["error"]["data"]["message"] == "boom"


def test_read_raw_returns_session_event(build) -> None:  # type: ignore[no-untyped-def]
    builder = build()
    event_id = builder.event("agent-switched", {"agent": "build"})
    builder.close()

    raw = opencode_records.read_raw(SESSION, event_id)
    assert raw is not None
    assert raw["source"] == "session_message"
    assert raw["data"]["agent"] == "build"


# ══ 注册表要的那个形状 ═════════════════════════════════════════════
def test_adapter_shape_matches_protocol(build) -> None:  # type: ignore[no-untyped-def]
    """类形态与模块函数给的结果一致。登记动作留给统一入口做，这里不登记。"""
    from frago.session.adapters import RecordAdapter

    builder = build()
    _busy_session(builder)
    builder.close()

    adapter = opencode_records.OpencodeRecordAdapter()
    assert isinstance(adapter, RecordAdapter)
    assert adapter.family == "opencode"
    assert [r.id for r in adapter.to_unified(SESSION, 0, 4)] == [
        r.id for r in opencode_records.to_unified(SESSION, 0, 4)
    ]
    assert adapter.read_raw(SESSION, "prt_nope") is None


def test_payload_values_stay_inside_declared_enums(build) -> None:  # type: ignore[no-untyped-def]
    """截断状态与工具大类都不许跑出类型定义声明的取值集合。"""
    builder = build()
    _busy_session(builder)
    builder.close()

    for record in opencode_records.to_unified(SESSION):
        if "truncation" in record.payload:
            assert record.payload["truncation"] in TRUNCATION_STATES
        if "tool_family" in record.payload:
            assert record.payload["tool_family"] in TOOL_FAMILIES
