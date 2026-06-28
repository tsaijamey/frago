"""Tests for the PA queue-message validator.

Phase 2 (spec 20260627-pa-deboard-resident-agent) removed the JSON decision
protocol: ``validate_pa_output`` and the whole ``pa_validators`` module are gone.
The only surviving gate is the minimal structural check that keeps dirty data out
of the PA queue, now inlined as ``primary_agent_service._validate_queue_message``.
"""

from frago.server.services.primary_agent_service import (
    VALID_QUEUE_MESSAGE_TYPES,
    _validate_queue_message,
)


class TestValidateQueueMessage:
    def test_valid_user_message(self):
        msg = {"type": "user_message", "task_id": "t1", "channel": "email", "prompt": "hi"}
        ok, _ = _validate_queue_message(msg)
        assert ok is True

    def test_valid_user_message_with_msg_id(self):
        msg = {"type": "user_message", "msg_id": "om_x", "channel": "feishu", "prompt": "hi"}
        ok, _ = _validate_queue_message(msg)
        assert ok is True

    def test_valid_agent_completed(self):
        ok, _ = _validate_queue_message(
            {"type": "agent_completed", "task_id": "t1", "channel": "email"}
        )
        assert ok is True

    def test_worker_done_requires_conv_attribution(self):
        # Phase 3: worker_done 重入消息至少要带 conv_key 或 channel 之一。
        ok, err = _validate_queue_message({"type": "worker_done"})
        assert ok is False
        assert "conv" in err

    def test_worker_done_valid_with_conv_key(self):
        ok, _ = _validate_queue_message(
            {"type": "worker_done", "conv_key": "feishu:oc_x", "result_summary": "done"}
        )
        assert ok is True

    def test_worker_done_valid_with_channel(self):
        ok, _ = _validate_queue_message({"type": "worker_done", "channel": "feishu"})
        assert ok is True

    def test_valid_agent_failed(self):
        ok, _ = _validate_queue_message(
            {"type": "agent_failed", "task_id": "t1", "channel": "email"}
        )
        assert ok is True

    def test_valid_reply_failed(self):
        ok, _ = _validate_queue_message({"type": "reply_failed"})
        assert ok is True

    def test_invalid_not_dict(self):
        ok, err = _validate_queue_message("string")
        assert ok is False
        assert "Expected dict" in err

    def test_invalid_unknown_type(self):
        ok, err = _validate_queue_message({"type": "unknown"})
        assert ok is False
        assert "Invalid message type" in err

    def test_user_message_missing_fields(self):
        ok, err = _validate_queue_message({"type": "user_message", "task_id": "t1"})
        assert ok is False
        assert "channel" in err or "prompt" in err

    def test_scheduled_task_missing_fields(self):
        ok, err = _validate_queue_message({"type": "scheduled_task", "msg_id": "s1"})
        assert ok is False
        assert "schedule_id" in err or "prompt" in err

    def test_valid_queue_message_types_constant(self):
        assert {
            "user_message",
            "agent_completed", "agent_failed", "reply_failed",
            "scheduled_task",
            "recovered_failed_task",
            "resume_failed",
            "run_failed",
            "schedule_failed",
            "worker_done",
        } == VALID_QUEUE_MESSAGE_TYPES
