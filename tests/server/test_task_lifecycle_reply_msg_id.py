"""Regression tests for TaskLifecycle.reply msg_id fallback path.

Background: PA decisions sometimes reply directly to a msg without creating
a task (task_id empty in the decision). Prior to this fix, reply() only
injected reply_context when task_id was non-empty — bare msg_id path skipped
the injection, so chat_id / message_id never reached the notify recipe.
Symptom: feishu_send_message exited with code 1 because chat_id was missing.

Fix: reply() now accepts msg_id as a keyword arg and falls back to looking up
board.msg.source.reply_context when task_id is empty.
"""
from frago.server.services.task_lifecycle import TaskLifecycle


def test_merge_preserves_text_and_injects_context():
    out = TaskLifecycle._merge_reply_context(
        {"text": "hi"},
        {"chat_id": "oc_xxx", "message_id": "om_yyy"},
    )
    assert out == {
        "text": "hi",
        "reply_context": {"chat_id": "oc_xxx", "message_id": "om_yyy"},
    }


def test_merge_preserves_attachment_fields():
    out = TaskLifecycle._merge_reply_context(
        {
            "text": "hi",
            "file_path": "/tmp/a.pdf",
            "image_path": "/tmp/b.png",
            "html_body": "<p>hi</p>",
        },
        {"chat_id": "oc_xxx"},
    )
    assert out["file_path"] == "/tmp/a.pdf"
    assert out["image_path"] == "/tmp/b.png"
    assert out["html_body"] == "<p>hi</p>"
    assert out["reply_context"] == {"chat_id": "oc_xxx"}


def test_merge_drops_unknown_fields():
    """Only the whitelisted attachment keys are forwarded — drops the rest."""
    out = TaskLifecycle._merge_reply_context(
        {"text": "hi", "unknown_field": "noise"},
        {"chat_id": "oc_xxx"},
    )
    assert "unknown_field" not in out
    assert set(out.keys()) == {"text", "reply_context"}


def test_merge_empty_text_defaults_to_empty_string():
    out = TaskLifecycle._merge_reply_context({}, {"chat_id": "oc_xxx"})
    assert out["text"] == ""
    assert out["reply_context"] == {"chat_id": "oc_xxx"}
