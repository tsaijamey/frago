"""Phase 1 tests: conversation-unit thread attribution (L0 conv-key).

Spec: 20260522-pa-per-conversation-session Phase 1.

Acceptance criteria (3 core + 1 edge):
  1. Same chat_id messages (cross-time-window)歸入 same thread
  2. Different chat_id → different threads
  3. Same sender across two chat_ids within 15min → NOT merged (regression guard)
  4. No chat_id → falls back to L1/L2 (no crash)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from frago.server.services.taskboard.thread_classifier import (
    ClassifyResult,
    _extract_conv_key,
    classify,
    conv_tag,
    ensure_thread,
)
from frago.server.services.taskboard.timeline import ulid_new


def _mock_board(existing_threads: list[dict] | None = None):
    """Create a mock TaskBoard with thread search support."""
    board = MagicMock()
    board.search_threads_by_tag.return_value = existing_threads or []
    board.search_threads_by_sender.return_value = []
    board.get_thread.return_value = None
    return board


def _make_reply_context(chat_id: str | None, **kwargs) -> dict:
    ctx = dict(kwargs)
    if chat_id is not None:
        ctx["chat_id"] = chat_id
    return ctx


# ── _extract_conv_key ────────────────────────────────────────────────────────


def test_extract_conv_key_feishu_with_chat_id():
    key = _extract_conv_key("feishu", {"chat_id": "oc_abc123"})
    assert key == "feishu:oc_abc123"


def test_extract_conv_key_feishu_no_chat_id():
    key = _extract_conv_key("feishu", {"parent_message_id": "om_xxx"})
    assert key is None


def test_extract_conv_key_feishu_none_reply_context():
    key = _extract_conv_key("feishu", None)
    assert key is None


def test_extract_conv_key_feishu_empty_reply_context():
    key = _extract_conv_key("feishu", {})
    assert key is None


def test_extract_conv_key_email_returns_none():
    key = _extract_conv_key("email", {"in_reply_to": "<msg@id>"})
    assert key is None  # email not adapted yet


# ── classify L0 ──────────────────────────────────────────────────────────────


def test_classify_l0_hit_same_chat_id():
    """Same chat_id → L0 hit, returns existing thread."""
    board = _mock_board()
    existing_tid = ulid_new()
    board.search_threads_by_tag.return_value = [
        {"thread_id": existing_tid, "status": "active", "tags": [conv_tag("feishu", "feishu:oc_abc")]}
    ]
    ctx = _make_reply_context("oc_abc")

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        result = classify(channel="feishu", sender="u1", content="hello", reply_context=ctx)

    assert result.thread_id == existing_tid
    assert result.layer == "L0"
    assert not result.is_new
    assert result.parent_ref is None


def test_classify_l0_miss_falls_to_l1():
    """No conv tag match → falls through to L1."""
    board = _mock_board()
    board.search_threads_by_tag.side_effect = lambda tag: (
        [] if tag.startswith("conv:") else
        [{"thread_id": "tid_l1", "status": "active", "last_active_at": datetime.now(UTC).isoformat()}]
    )
    ctx = _make_reply_context("oc_new", parent_message_id="om_001")

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        result = classify(channel="feishu", sender="u1", content="hello", reply_context=ctx)

    # Falls to L1 (parent_message_id matched)
    assert result.layer == "L1"
    assert not result.is_new


def test_classify_l0_no_chat_id_falls_through():
    """No chat_id in reply_context → skip L0 entirely, falls to L1/L2/new."""
    board = _mock_board()
    ctx = {"parent_message_id": "om_001"}

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        result = classify(channel="feishu", sender="u1", content="hello", reply_context=ctx)

    # No L0 conv search happened; falls through L1 (no parent_ref match) → L2 → new
    assert result.layer in ("L1", "L2", "new")
    # The conv: tag search should NOT have been called (no conv_key extracted)
    conv_calls = [c for c in board.search_threads_by_tag.call_args_list if c.args[0].startswith("conv:")]
    assert len(conv_calls) == 0


# ── classify integration: same chat_id cross time window ─────────────────────


def test_same_chat_id_cross_window_same_thread():
    """Two messages from same chat_id, 30 min apart → L0 hit → same thread."""
    board = _mock_board()
    existing_tid = ulid_new()
    board.search_threads_by_tag.return_value = [
        {"thread_id": existing_tid, "status": "active", "tags": [conv_tag("feishu", "feishu:oc_abc")]}
    ]
    ctx = _make_reply_context("oc_abc")
    now = datetime.now(UTC)

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        r1 = classify(channel="feishu", sender="u1", content="first", reply_context=ctx, now=now)
        r2 = classify(
            channel="feishu", sender="u1", content="second",
            reply_context=ctx, now=now,
        )

    assert r1.thread_id == existing_tid
    assert r2.thread_id == existing_tid
    assert r1.layer == "L0"
    assert r2.layer == "L0"


def test_different_chat_ids_different_threads():
    """Different chat_ids → cannot both L0-hit a single thread → new threads."""
    board = _mock_board()
    board.search_threads_by_tag.return_value = []  # no L0 match for either

    ctx_a = _make_reply_context("oc_A")
    ctx_b = _make_reply_context("oc_B")
    now = datetime.now(UTC)

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        r_a = classify(channel="feishu", sender="u1", content="在A群", reply_context=ctx_a, now=now)
        r_b = classify(channel="feishu", sender="u1", content="在B群", reply_context=ctx_b, now=now)

    assert r_a.thread_id != r_b.thread_id
    assert r_a.is_new
    assert r_b.is_new
    assert r_a.layer == "new"
    assert r_b.layer == "new"


def test_diff_chat_id_same_sender_15min_not_merged():
    """Regression guard: same sender in 2 chat_ids within 15min → NOT merged.

    This was the old L2 bug: (sender, time-window) merged cross-group messages.
    L0 conv: tags prevent this by routing each chat_id to its own thread.
    """
    board = _mock_board()
    # L0 returns no match for oc_A (first msg) → goes to new.
    # oc_A's thread gets created, then oc_B comes — L0 also no match → new.
    board.search_threads_by_tag.return_value = []

    ctx_a = _make_reply_context("oc_diff_A")
    ctx_b = _make_reply_context("oc_diff_B")
    now = datetime.now(UTC)

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        r_a = classify(
            channel="feishu", sender="same_U", content="msg in A",
            reply_context=ctx_a, now=now,
        )
        r_b = classify(
            channel="feishu", sender="same_U", content="msg in B",
            reply_context=ctx_b, now=now + timedelta(seconds=60),
        )

    assert r_a.thread_id != r_b.thread_id, (
        "Same sender within 15min but different chat_ids MUST NOT merge"
    )


# ── ensure_thread conv tag ───────────────────────────────────────────────────


def test_ensure_thread_new_with_conv_tag():
    """New thread gets conv tag on creation."""
    board = _mock_board()
    board.get_thread.return_value = None
    board.create_thread = MagicMock()
    tid = ulid_new()
    result = ClassifyResult(thread_id=tid, parent_ref=None, layer="new", is_new=True)
    ctx = _make_reply_context("oc_ensure_new")

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        ensure_thread(
            result, channel="feishu", sender="u1",
            msg_id="om_001", root_summary="test",
            reply_context=ctx,
        )

    board.create_thread.assert_called_once()
    call_args = board.create_thread.call_args[1]
    tags = call_args["tags"]
    assert conv_tag("feishu", "feishu:oc_ensure_new") in tags
    assert "channelref:feishu:om_001" in tags
    assert "sender:feishu:u1" in tags


def test_ensure_thread_existing_adds_conv_tag():
    """Existing thread without conv tag gets it added."""
    board = _mock_board()
    tid = ulid_new()
    board.get_thread.return_value = {"tags": ["channelref:feishu:om_old"]}
    board.add_tag = MagicMock()
    board.touch_thread = MagicMock()
    result = ClassifyResult(thread_id=tid, parent_ref=None, layer="L2", is_new=False)
    ctx = _make_reply_context("oc_existing")

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        ensure_thread(
            result, channel="feishu", sender="u1",
            msg_id="om_002", root_summary="test",
            reply_context=ctx,
        )

    # Should have added the conv tag
    add_tag_calls = board.add_tag.call_args_list
    conv_added = any(
        c.args[1] == conv_tag("feishu", "feishu:oc_existing")
        for c in add_tag_calls
    )
    assert conv_added, "Conv tag should be added to existing thread"


def test_ensure_thread_no_reply_context_no_crash():
    """No reply_context at all → ensure_thread still works (no conv tag)."""
    board = _mock_board()
    board.get_thread.return_value = None
    board.create_thread = MagicMock()
    tid = ulid_new()
    result = ClassifyResult(thread_id=tid, parent_ref=None, layer="new", is_new=True)

    with patch("frago.server.services.taskboard.thread_classifier.get_board", return_value=board):
        ensure_thread(
            result, channel="feishu", sender="u1",
            msg_id="om_003", root_summary="test",
            # no reply_context
        )

    board.create_thread.assert_called_once()
    tags = board.create_thread.call_args[1]["tags"]
    # No conv: tag
    conv_tags = [t for t in tags if t.startswith("conv:")]
    assert len(conv_tags) == 0
