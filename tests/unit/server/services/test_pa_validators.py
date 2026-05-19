"""Tests for PA validators — format validation for PA agent I/O."""

from frago.server.services.pa_validators import (
    VALID_PA_ACTIONS,
    VALID_QUEUE_MESSAGE_TYPES,
    ValidationResult,
    validate_pa_output,
    validate_queue_message,
)


class TestValidationResult:
    def test_ok_result(self):
        r = ValidationResult(ok=True)
        assert r.ok is True
        assert r.error == ""
        assert r.raw_data is None

    def test_error_result(self):
        r = ValidationResult(ok=False, error="bad", raw_data={"x": 1})
        assert r.ok is False
        assert r.error == "bad"
        assert r.raw_data == {"x": 1}


class TestValidatePaOutput:
    def test_valid_empty_array(self):
        r = validate_pa_output("[]")
        assert r.ok is True
        assert r.raw_data == []

    def test_valid_reply_action(self):
        text = '[{"action":"reply","task_id":"t1","channel":"email","text":"hi"}]'
        r = validate_pa_output(text)
        assert r.ok is True

    def test_valid_run_action(self):
        text = '[{"action":"run","task_id":"t1","channel":"feishu","description":"test","prompt":"do something"}]'
        r = validate_pa_output(text)
        assert r.ok is True

    def test_valid_resume_action(self):
        text = '[{"action":"resume","task_id":"t1","prompt":"continue"}]'
        r = validate_pa_output(text)
        assert r.ok is True

    def test_valid_multiple_actions(self):
        text = '[{"action":"reply","task_id":"t1","channel":"c","text":"ok"},{"action":"run","task_id":"t2","channel":"c","description":"test","prompt":"do it"}]'
        r = validate_pa_output(text)
        assert r.ok is True
        assert len(r.raw_data) == 2

    def test_invalid_not_json(self):
        r = validate_pa_output("not json at all")
        assert r.ok is False
        assert "No valid JSON array" in r.error

    def test_invalid_json_object_not_array(self):
        r = validate_pa_output('{"action":"reply"}')
        assert r.ok is False

    def test_invalid_unknown_action(self):
        r = validate_pa_output('[{"action":"dance"}]')
        assert r.ok is False
        assert "unknown action" in r.error

    def test_invalid_missing_action_field(self):
        r = validate_pa_output('[{"task_id":"t1"}]')
        assert r.ok is False
        assert 'missing "action"' in r.error

    def test_invalid_element_not_dict(self):
        r = validate_pa_output('["not a dict"]')
        assert r.ok is False
        assert "not a JSON object" in r.error

    def test_missing_required_field_reply(self):
        # reply requires task_id, channel, text — first missing one is reported
        r = validate_pa_output('[{"action":"reply","task_id":"t1"}]')
        assert r.ok is False
        assert "missing required field" in r.error

    def test_missing_required_field_run(self):
        r = validate_pa_output('[{"action":"run","task_id":"t1"}]')
        assert r.ok is False
        assert "channel" in r.error or "description" in r.error or "prompt" in r.error

    def test_missing_required_field_resume(self):
        r = validate_pa_output('[{"action":"resume","prompt":"x"}]')
        assert r.ok is False
        assert "task_id" in r.error

    def test_tolerates_markdown_code_block(self):
        text = '```json\n[{"action":"reply","task_id":"t1","channel":"c","text":"hi"}]\n```'
        r = validate_pa_output(text)
        assert r.ok is True

    def test_tolerates_prefix_text(self):
        text = 'Here is my decision:\n[{"action":"reply","task_id":"t1","channel":"c","text":"ok"}]'
        r = validate_pa_output(text)
        assert r.ok is True

    def test_tolerates_suffix_text(self):
        text = '[{"action":"reply","task_id":"t1","channel":"c","text":"ok"}]\nDone!'
        r = validate_pa_output(text)
        assert r.ok is True


class TestValidateQueueMessage:
    def test_valid_user_message(self):
        msg = {"type": "user_message", "task_id": "t1", "channel": "email", "prompt": "hi"}
        r = validate_queue_message(msg)
        assert r.ok is True

    def test_valid_agent_completed(self):
        msg = {"type": "agent_completed", "task_id": "t1", "channel": "email"}
        r = validate_queue_message(msg)
        assert r.ok is True

    def test_valid_agent_failed(self):
        msg = {"type": "agent_failed", "task_id": "t1", "channel": "email"}
        r = validate_queue_message(msg)
        assert r.ok is True

    def test_valid_reply_failed(self):
        msg = {"type": "reply_failed"}
        r = validate_queue_message(msg)
        assert r.ok is True

    def test_invalid_not_dict(self):
        r = validate_queue_message("string")
        assert r.ok is False

    def test_invalid_unknown_type(self):
        r = validate_queue_message({"type": "unknown"})
        assert r.ok is False
        assert "Invalid message type" in r.error

    def test_user_message_missing_fields(self):
        msg = {"type": "user_message", "task_id": "t1"}
        r = validate_queue_message(msg)
        assert r.ok is False
        assert "channel" in r.error or "prompt" in r.error

    def test_valid_actions_constant(self):
        assert VALID_PA_ACTIONS == {"reply", "run", "resume", "dismiss"}


class TestBrokenJSONRecovery:
    """Regression for LLM-produced broken JSON that locked PA in correction loops.

    PA's output comes from a Claude subprocess and produces these shapes
    in production. stdlib json.loads gives up on most of them, so the
    parser delegates to json-repair.
    """

    def test_natural_language_prefix_before_json(self):
        """2026-05-20 stuck-PA incident: PA prefixed the run decision with
        'Now dispatching the research sub-agent.\\n\\n' before the array.
        """
        text = (
            'Now dispatching the research sub-agent.\n\n'
            '[{"action":"run","msg_id":"om_x","channel":"feishu",'
            '"description":"japan stock","prompt":"调查\\n\\n详细"}]'
        )
        r = validate_pa_output(text)
        assert r.ok is True
        assert r.raw_data[0]["action"] == "run"

    def test_markdown_code_fence_wrapper(self):
        text = (
            '```json\n'
            '[{"action":"reply","msg_id":"om_x","channel":"feishu","text":"hi"}]'
            '\n```'
        )
        r = validate_pa_output(text)
        assert r.ok is True

    def test_trailing_comma_in_object(self):
        text = (
            '[{"action":"run","msg_id":"om_x","channel":"feishu",'
            '"description":"d","prompt":"a\\n\\nb",}]'
        )
        r = validate_pa_output(text)
        assert r.ok is True

    def test_real_newline_inside_prompt_string(self):
        """Multi-line `prompt` field with literal newlines (not \\n escapes)
        is the shape PA produces for run actions — the body is real Chinese
        text with paragraph breaks.
        """
        text = (
            '[{"action":"run","msg_id":"om_x","channel":"feishu",'
            '"description":"d","prompt":"调查日本股市\n\n详细：2026-05-20 开盘情况"}]'
        )
        r = validate_pa_output(text)
        assert r.ok is True
        assert "\n" in r.raw_data[0]["prompt"]

    def test_bare_object_without_outer_array(self):
        """PA sometimes forgets the outer [] on a single-action turn.
        Parser wraps it so DecisionApplier can still route.
        """
        text = '{"action":"reply","msg_id":"om_x","channel":"feishu","text":"hi"}'
        r = validate_pa_output(text)
        assert r.ok is True
        assert len(r.raw_data) == 1
        assert r.raw_data[0]["action"] == "reply"

    def test_single_quotes_instead_of_double(self):
        text = "[{'action':'reply','msg_id':'om_x','channel':'feishu','text':'hi'}]"
        r = validate_pa_output(text)
        assert r.ok is True

    def test_unparseable_garbage_returns_failure(self):
        """json-repair is permissive but truly empty / non-JSON-shaped input
        must still surface as a validation failure so PA's correction loop
        engages instead of silently treating garbage as idle.
        """
        r = validate_pa_output("this is just prose, no json anywhere")
        assert r.ok is False

    def test_valid_queue_message_types_constant(self):
        assert VALID_QUEUE_MESSAGE_TYPES == {
            "user_message",
            "agent_completed", "agent_failed", "reply_failed",
            "scheduled_task",
            "recovered_failed_task",
            "internal_reflection",  # spec 20260418-timeline-event-coverage Phase 5
            "resume_failed",
            "run_failed",
            "schedule_failed",
        }
