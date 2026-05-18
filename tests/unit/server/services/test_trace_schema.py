"""Tests for trace.py timeline entry schema (spec 20260418-timeline-entry-schema)."""

import json

import pytest

from frago.server.services import trace as trace_mod
from frago.server.services.trace import (
    KNOWN_DATA_TYPES,
    TimelineEntry,
    _infer_data_type,
    load_trace_events,
    trace,
    trace_entry,
    ulid_new,
)


class TestULID:
    def test_length_and_charset(self):
        uid = ulid_new()
        assert len(uid) == 26
        valid = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
        assert all(c in valid for c in uid), f"non-crockford char in {uid}"

    def test_monotonic_within_tight_loop(self):
        ids = [ulid_new() for _ in range(200)]
        assert ids == sorted(ids), "ULIDs must be monotonically increasing"
        assert len(set(ids)) == len(ids), "ULIDs must be unique"

    def test_monotonic_across_same_millisecond(self):
        # Force same-ms calls
        first = ulid_new()
        second = ulid_new()
        assert first < second


class TestTimelineEntrySerialization:
    def test_to_dict_full(self):
        e = TimelineEntry(
            id="01HW001",
            ts="2026-04-18T10:00:00",
            origin="external",
            subkind="feishu",
            thread_id="01HW001",
            parent_id=None,
            data_type="message",
            task_id="t_1",
            data={"text": "hi"},
            msg_id="om_x",
            role="scheduler",
            event="收到 feishu",
        )
        d = e.to_dict()
        # None values dropped
        assert "parent_id" not in d
        # Non-None values preserved
        assert d["id"] == "01HW001"
        assert d["data"] == {"text": "hi"}
        assert d["msg_id"] == "om_x"
        assert d["role"] == "scheduler"
        assert d["origin"] == "external"
        assert d["data_type"] == "message"

    def test_to_dict_minimal(self):
        e = TimelineEntry(
            id="01HW001",
            ts="2026-04-18T10:00:00",
            origin="internal",
            subkind="legacy",
            thread_id="01HW001",
        )
        d = e.to_dict()
        # All optional None fields dropped
        for k in ("parent_id", "task_id", "data", "msg_id", "role", "event"):
            assert k not in d, f"{k} should be dropped when None"
        # data_type defaults to "legacy"
        assert d["data_type"] == "legacy"

    def test_known_data_types_contains_canonical_values(self):
        for k in ("message", "thought", "task_state", "result", "os_event", "legacy"):
            assert k in KNOWN_DATA_TYPES


class TestInferDataType:
    @pytest.mark.parametrize("event,expected", [
        ("pa_ingestion", "message"),
        ("pa_decision", "thought"),
        ("pa_agent_launched", "task_state"),
        ("pa_agent_exited", "task_state"),
        ("pa_reply", "message"),
        ("收到 feishu 消息", "message"),
        ("决策 reply", "thought"),
        ("启动 agent, run=r1, pid=123", "task_state"),
        ("执行结束 completed", "task_state"),
        ("标记 FAILED: timeout", "task_state"),
        ("读取结果: stop_reason=end_turn", "result"),
        ("通知 PA: executor_result", "message"),
        ("unknown_event_xyz", "legacy"),
        ("", "legacy"),
    ])
    def test_infer(self, event, expected):
        assert _infer_data_type(event) == expected

    def test_infer_none(self):
        assert _infer_data_type(None) == "legacy"


class TestTraceLegacyCompat:
    """Verify old trace() signature still works and produces backward-compat output."""

    def test_writes_new_schema_with_legacy_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        trace(
            msg_id="om_abc",
            task_id="t_1",
            role="pa",
            event="pa_decision",
            data={"action": "reply"},
        )
        files = list(tmp_path.glob("trace-*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])

        # Legacy fields preserved for existing consumers
        assert entry["msg_id"] == "om_abc"
        assert entry["task_id"] == "t_1"
        assert entry["role"] == "pa"
        assert entry["event"] == "pa_decision"
        assert entry["data"] == {"action": "reply"}
        assert "ts" in entry

        # New timeline fields present
        assert len(entry["id"]) == 26
        assert entry["origin"] == "internal"
        assert entry["subkind"] == "legacy"
        assert entry["thread_id"] == "om_abc"
        assert entry["data_type"] == "thought"   # inferred from pa_decision
        # None values filtered
        assert "parent_id" not in entry

    def test_empty_msg_id_generates_thread_ulid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        trace(msg_id="", task_id=None, role="pa", event="pa_decision")
        entry = json.loads(list(tmp_path.glob("trace-*.jsonl"))[0].read_text().strip())
        assert len(entry["thread_id"]) == 26
        assert "msg_id" not in entry
        assert "task_id" not in entry
        assert "data" not in entry

    def test_no_data_omits_data_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        trace(msg_id="om_1", task_id="t_1", role="pa", event="pa_reply")
        entry = json.loads(list(tmp_path.glob("trace-*.jsonl"))[0].read_text().strip())
        assert "data" not in entry
        assert entry["data_type"] == "message"  # pa_reply → message


class TestTraceEntryRichAPI:
    def test_root_entry_self_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        root = trace_entry(
            origin="external",
            subkind="feishu",
            data_type="message",
            data={"text": "hello"},
        )
        # Root: thread_id equals own id
        assert root.thread_id == root.id
        assert root.parent_id is None
        assert len(root.id) == 26

    def test_child_entry_inherits_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        root = trace_entry(
            origin="external",
            subkind="feishu",
            data_type="message",
            data={"text": "hello"},
        )
        child = trace_entry(
            origin="internal",
            subkind="pa",
            data_type="thought",
            thread_id=root.thread_id,
            parent_id=root.id,
            data={"decision": "reply"},
        )
        assert child.thread_id == root.thread_id
        assert child.parent_id == root.id

        # File has both entries in order
        lines = list(tmp_path.glob("trace-*.jsonl"))[0].read_text().strip().splitlines()
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        e2 = json.loads(lines[1])
        assert e1["id"] == root.id
        assert e2["id"] == child.id
        assert e2["parent_id"] == root.id
        assert e2["thread_id"] == root.thread_id

    def test_returns_entry_for_chaining(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        entry = trace_entry(origin="internal", subkind="reflection", data_type="thought")
        assert isinstance(entry, TimelineEntry)
        assert entry.origin == "internal"


class TestBackwardCompatConsumer:
    """Verify load_trace_events still reads new-schema entries correctly."""

    def test_load_trace_events_reads_new_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        # Write an entry via legacy trace() with data.event_type (as executor does)
        trace(
            msg_id="om_1",
            task_id="t_1",
            role="executor",
            event="启动 agent",
            data={"event_type": "pa_agent_launched", "run_id": "r_1", "task_id": "t_1"},
        )
        # load_trace_events filters data-bearing entries
        events = load_trace_events(limit=10)
        assert len(events) == 1
        assert events[0]["event_type"] == "pa_agent_launched"
        assert events[0]["data"]["run_id"] == "r_1"
        # msg_id should be resolved
        assert events[0]["data"]["msg_id"] == "om_1"

    def test_load_trace_events_skips_no_data_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        # Entry without data (just plain trace log)
        trace(msg_id="om_1", task_id="t_1", role="executor", event="读取结果")
        events = load_trace_events(limit=10)
        assert events == []   # filtered out

    def test_mixed_old_and_new_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path)
        # Simulate pre-migration entry (no new fields)
        path = tmp_path / f"trace-{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.jsonl"
        old_line = json.dumps({
            "msg_id": "om_old",
            "task_id": "t_old",
            "role": "pa",
            "event": "pa_decision",
            "ts": "2026-04-01T10:00:00",
            "data": {"event_type": "pa_decision", "action": "reply"},
        })
        path.write_text(old_line + "\n")

        # Append a new-schema entry
        trace(
            msg_id="om_new",
            task_id="t_new",
            role="pa",
            event="pa_decision",
            data={"event_type": "pa_decision", "action": "run"},
        )

        events = load_trace_events(limit=10)
        # Both should be loaded
        assert len(events) == 2
        actions = {e["data"]["action"] for e in events}
        assert actions == {"reply", "run"}
