"""Tests for Executor._read_final_assistant_text and _notify_pa session_id fix."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from frago.server.services.executor import Executor


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _make_jsonl_path(home: Path, session_id: str) -> Path:
    cwd_slug = str(home).replace("/", "-")
    return home / ".claude" / "projects" / cwd_slug / f"{session_id}.jsonl"


def _assistant(text: str | None, stop_reason: str | None = "end_turn",
               extra_blocks: list | None = None) -> dict:
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if extra_blocks:
        content.extend(extra_blocks)
    return {
        "type": "assistant",
        "message": {"stop_reason": stop_reason, "content": content},
    }


class TestReadFinalAssistantText:
    def test_returns_none_when_jsonl_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        assert Executor._read_final_assistant_text("nonexistent-sid") is None

    def test_single_msg_no_separator(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-1"
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant("only answer"),
        ])
        assert Executor._read_final_assistant_text(sid) == "only answer"

    def test_collects_last_5_in_chronological_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-2"
        labels = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant(label, stop_reason="tool_use" if i < 5 else "end_turn")
            for i, label in enumerate(labels)
        ])
        result = Executor._read_final_assistant_text(sid, max_turns=5)
        assert result is not None
        # last 5 = bravo..foxtrot in chronological order, alpha dropped
        assert "alpha" not in result  # oldest dropped
        for label in labels[1:]:
            assert label in result
        # separators present for multi-msg
        assert "--- msg 1/5 ---" in result
        assert "--- msg 5/5 ---" in result
        # chronological: bravo appears before foxtrot
        assert result.index("bravo") < result.index("foxtrot")

    def test_skips_tool_use_only_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-3"
        tool_only = {
            "type": "assistant",
            "message": {
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": "tu1", "name": "Bash", "input": {}}],
            },
        }
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant("text 1"),
            tool_only,
            tool_only,
            _assistant("text 2"),
        ])
        result = Executor._read_final_assistant_text(sid, max_turns=5)
        assert result is not None
        assert "text 1" in result
        assert "text 2" in result
        # tool_use records contribute nothing, so just 2 msgs
        assert "--- msg 1/2 ---" in result
        assert "--- msg 2/2 ---" in result

    def test_mixed_content_only_text_extracted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-4"
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant("narration", extra_blocks=[
                {"type": "tool_use", "id": "t1", "name": "X", "input": {}},
                {"type": "thinking", "thinking": "private thoughts"},
            ]),
        ])
        result = Executor._read_final_assistant_text(sid)
        assert result == "narration"
        assert "private thoughts" not in result
        assert "tool_use" not in result

    def test_returns_none_when_no_text_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-5"
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            {
                "type": "assistant",
                "message": {
                    "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": "t1", "name": "X", "input": {}}],
                },
            },
        ])
        assert Executor._read_final_assistant_text(sid) is None

    def test_malformed_json_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-6"
        path = _make_jsonl_path(tmp_path, sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json\n", encoding="utf-8")
        assert Executor._read_final_assistant_text(sid) is None


class TestNotifyPASessionId:
    @pytest.mark.asyncio
    async def test_uses_updated_session_id(self, tmp_path, monkeypatch):
        """_notify_pa MUST read session_id from the live board task,
        not from the input context (which was a snapshot before launch)."""
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)

        enqueued: list[dict] = []

        async def fake_enqueue(msg):
            enqueued.append(msg)

        from frago.server.services.executor import _TaskContext

        board = MagicMock()
        # fresh task on board, post-launch with bound session
        fresh_task = MagicMock()
        fresh_task.session.run_id = "run-20260418-abc"
        fresh_task.session.started_at = None
        result_obj = MagicMock()
        result_obj.summary = "hello world"
        result_obj.error = None
        fresh_task.result = result_obj
        board.get_task.return_value = fresh_task

        ctx = _TaskContext(
            task_id="task-123",
            prompt="p", description="d",
            channel="feishu",
            channel_message_id="om_xxx",
            thread_id=None,
            reply_context={},
            created_at=None,
        )

        executor = Executor(
            board=board,
            pa_enqueue_message=fake_enqueue,
            broadcast_pa_event=AsyncMock(),
        )

        await executor._notify_pa(ctx, run_id="run-20260418-abc", stop_reason="end_turn")

        assert len(enqueued) == 1
        assert enqueued[0]["session_id"] == "run-20260418-abc"
        assert enqueued[0]["result_summary"] == "hello world"
        assert enqueued[0]["type"] == "agent_completed"

    @pytest.mark.asyncio
    async def test_falls_back_when_board_task_missing(self, tmp_path, monkeypatch):
        """If board.get_task returns None we still notify with a synthesized summary."""
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)

        enqueued: list[dict] = []

        async def fake_enqueue(msg):
            enqueued.append(msg)

        from frago.server.services.executor import _TaskContext

        board = MagicMock()
        board.get_task.return_value = None

        ctx = _TaskContext(
            task_id="task-xyz",
            prompt="p", description="d",
            channel="feishu",
            channel_message_id="om_yyy",
            thread_id=None,
            reply_context={},
            created_at=None,
        )

        executor = Executor(
            board=board,
            pa_enqueue_message=fake_enqueue,
            broadcast_pa_event=AsyncMock(),
        )

        await executor._notify_pa(ctx, run_id="run-x", stop_reason="end_turn")

        assert len(enqueued) == 1
        # session_id is None when board.get_task returned None
        assert enqueued[0]["session_id"] is None
        # synthesized fallback summary uses stop_reason
        assert "end_turn" in enqueued[0]["result_summary"]
