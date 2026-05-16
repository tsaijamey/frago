"""Tests for TimelineService — timeline aggregation."""

import json
from datetime import datetime
from unittest.mock import patch

from frago.server.services.timeline_service import (
    TimelineAggEvent,
    _humanize_pa_event,
    humanize_event,
    get_timeline,
)


class TestTimelineAggEvent:
    def test_to_dict_excludes_none(self):
        event = TimelineAggEvent(
            id="e1",
            timestamp="2025-01-01T00:00:00",
            event_type="test",
            source="unit",
            title="test event",
        )
        d = event.to_dict()
        assert "subtitle" not in d
        assert "task_id" not in d
        assert d["id"] == "e1"
        assert d["title"] == "test event"

    def test_to_dict_includes_set_fields(self):
        event = TimelineAggEvent(
            id="e1",
            timestamp="2025-01-01T00:00:00",
            event_type="test",
            source="unit",
            title="test",
            subtitle="sub",
            task_id="t1",
            run_id="r1",
        )
        d = event.to_dict()
        assert d["subtitle"] == "sub"
        assert d["task_id"] == "t1"
        assert d["run_id"] == "r1"


class TestHumanizePaEvent:
    def test_ingestion_event(self):
        title, subtitle = _humanize_pa_event("pa_ingestion", {
            "channel": "feishu",
            "prompt": "帮我查一下天气",
        })
        assert "feishu" in title
        assert subtitle is not None

    def test_ingestion_with_instruction_tag(self):
        title, subtitle = _humanize_pa_event("pa_ingestion", {
            "channel": "email",
            "prompt": "prefix <instruction>do this</instruction> suffix",
        })
        assert subtitle == "do this"

    def test_decision_run(self):
        title, subtitle = _humanize_pa_event("pa_decision", {
            "action": "run",
            "details": {"description": "compare products"},
        })
        assert title == "分配任务给 Agent"
        assert subtitle == "compare products"

    def test_decision_reply(self):
        title, _ = _humanize_pa_event("pa_decision", {"action": "reply", "details": {}})
        assert title == "回复消息"

    def test_agent_launched(self):
        title, subtitle = _humanize_pa_event("pa_agent_launched", {"description": "making ppt"})
        assert title == "Agent 开始执行"
        assert subtitle == "making ppt"

    def test_agent_exited_with_completion(self):
        title, subtitle = _humanize_pa_event("pa_agent_exited", {
            "has_completion": True,
            "duration_seconds": 120,
        })
        assert "完毕" in title
        assert "120s" in subtitle

    def test_agent_exited_without_completion(self):
        title, _ = _humanize_pa_event("pa_agent_exited", {"has_completion": False})
        assert "异常" in title

    def test_reply_event(self):
        title, subtitle = _humanize_pa_event("pa_reply", {
            "channel": "feishu",
            "reply_text": "已完成",
        })
        assert "feishu" in title
        assert subtitle == "已完成"

    def test_unknown_event_type(self):
        title, subtitle = _humanize_pa_event("unknown_type", {})
        assert title == "unknown_type"
        assert subtitle is None


class TestHumanizeEvent:
    def test_returns_mapped_event_type(self):
        result = humanize_event("pa_ingestion", {"channel": "feishu", "prompt": "test"})
        assert result["event_type"] == "ingestion"
        assert result["title"] == "收到 feishu 消息"
        assert "icon" not in result

    def test_decision_mapping(self):
        result = humanize_event("pa_decision", {"action": "run", "details": {"description": "task"}})
        assert result["event_type"] == "pa_decision"
        assert result["title"] == "分配任务给 Agent"

    def test_agent_exited_mapping(self):
        result = humanize_event("pa_agent_exited", {"has_completion": True, "duration_seconds": 60})
        assert result["event_type"] == "agent_exited"


class TestGetTimeline:
    def test_returns_trace_events(self, tmp_path):
        trace_dir = tmp_path / "traces"
        trace_dir.mkdir()
        trace_file = trace_dir / f"trace-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        trace_file.write_text(
            json.dumps({
                "msg_id": "m1", "task_id": "t1", "role": "scheduler",
                "event": "test", "ts": "2025-06-01T10:00:00",
                "data": {"event_type": "pa_ingestion", "channel": "feishu", "prompt": "hello"},
            }) + "\n"
        )
        with patch("frago.server.services.trace.TRACE_DIR", trace_dir):
            events = get_timeline(limit=10)
        assert len(events) == 1
        assert events[0]["event_type"] == "ingestion"
        assert events[0]["source"] == "trace"
        assert "icon" not in events[0]

    def test_empty_traces(self, tmp_path):
        trace_dir = tmp_path / "traces"
        trace_dir.mkdir()
        with patch("frago.server.services.trace.TRACE_DIR", trace_dir):
            events = get_timeline(limit=10)
        assert events == []
