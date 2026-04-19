"""Thread attribution classifier (spec 20260418-thread-organization Phase 2).

Given an incoming external message, decide which thread it belongs to.
Layered cost model:

  L1 (free)  — channel-native reply reference (feishu parent_message_id,
               email In-Reply-To, webhook conversation_id)
  L2 (rules) — same channel + same sender, within time window, no new-topic keyword
  L3 (LLM)   — PA classification (deferred, Phase 5)
  L4 (user)  — user anchoring via `frago thread follow` (deferred, Phase 5)

If nothing matches, a new thread root is generated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from frago.server.services.thread_service import (
    STATUS_ACTIVE,
    get_thread_store,
)
from frago.server.services.trace import ulid_new

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_MIN = 15
NEW_TOPIC_KEYWORDS = (
    "新问题",
    "另一个",
    "换个话题",
    "新话题",
    "new topic",
    "another question",
)


@dataclass
class ClassifyResult:
    thread_id: str                  # existing or newly minted ulid
    parent_ref: str | None          # channel-native parent message id (for L1)
    layer: str                      # "L1" | "L2" | "new"
    is_new: bool


# ---------------------------------------------------------------------------
# Tag conventions
# ---------------------------------------------------------------------------

def channel_ref_tag(channel: str, msg_id: str) -> str:
    """Tag indicating this thread contains the channel message `msg_id`.

    Used for L1 lookup: to find thread containing a replied-to message.
    """
    return f"channelref:{channel}:{msg_id}"


def sender_tag(channel: str, sender: str) -> str:
    """Tag indicating this thread was initiated by / continued by `sender`.

    Used for L2 heuristic grouping.
    """
    return f"sender:{channel}:{sender}"


# ---------------------------------------------------------------------------
# Layer implementations
# ---------------------------------------------------------------------------

def _extract_parent_ref(channel: str, reply_context: dict) -> str | None:
    """Extract channel-native parent message id, if present."""
    if not reply_context:
        return None

    # Feishu: parent_message_id is set when user replies in a thread.
    # We intentionally don't use message_id (that's the current msg itself).
    if channel == "feishu":
        parent = reply_context.get("parent_message_id")
        if parent:
            return str(parent)
        return None

    if channel == "email":
        # RFC 5322: In-Reply-To / References (first entry)
        irt = reply_context.get("in_reply_to")
        if irt:
            return str(irt)
        refs = reply_context.get("references")
        if isinstance(refs, list) and refs:
            return str(refs[0])
        if isinstance(refs, str) and refs:
            return refs.split()[0]
        return None

    if channel in ("webhook", "ui_input"):
        cid = reply_context.get("conversation_id") or reply_context.get("thread_id")
        if cid:
            return str(cid)
        return None

    return None


def _is_new_topic_marker(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(kw.lower() in low for kw in NEW_TOPIC_KEYWORDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(
    *,
    channel: str,
    sender: str,
    content: str,
    reply_context: dict | None = None,
    now: datetime | None = None,
    window_min: int = DEFAULT_WINDOW_MIN,
) -> ClassifyResult:
    """Determine thread_id for an incoming external message."""
    store = get_thread_store()
    reply_context = reply_context or {}
    now = now or datetime.now()

    # ── Layer 1: channel-native threading ──────────────────────────────────
    parent_ref = _extract_parent_ref(channel, reply_context)
    if parent_ref:
        matches = store.search(required_tags=[channel_ref_tag(channel, parent_ref)])
        if matches:
            logger.debug(
                "classify L1 hit: channel=%s parent=%s → thread=%s",
                channel, parent_ref, matches[0].thread_id,
            )
            return ClassifyResult(
                thread_id=matches[0].thread_id,
                parent_ref=parent_ref,
                layer="L1",
                is_new=False,
            )

    # ── Layer 2: heuristic (same sender, within window, no new-topic marker) ─
    if sender and not _is_new_topic_marker(content):
        cutoff = now - timedelta(minutes=window_min)
        candidates = store.search(
            required_tags=[sender_tag(channel, sender)],
            status=STATUS_ACTIVE,
            subkind=channel,
        )
        for c in candidates:
            try:
                last = datetime.fromisoformat(c.last_active_ts)
            except ValueError:
                continue
            if last >= cutoff:
                logger.debug(
                    "classify L2 hit: sender=%s last_active=%s → thread=%s",
                    sender, c.last_active_ts, c.thread_id,
                )
                return ClassifyResult(
                    thread_id=c.thread_id,
                    parent_ref=None,
                    layer="L2",
                    is_new=False,
                )

    # ── New thread ─────────────────────────────────────────────────────────
    new_tid = ulid_new()
    logger.debug("classify: new thread %s for %s/%s", new_tid, channel, sender)
    return ClassifyResult(
        thread_id=new_tid,
        parent_ref=None,
        layer="new",
        is_new=True,
    )


def ensure_thread(
    result: ClassifyResult,
    *,
    channel: str,
    sender: str,
    msg_id: str,
    root_summary: str,
) -> None:
    """Create or touch the thread indicated by a classification result.

    Adds channelref and sender tags so future messages can be grouped.
    """
    store = get_thread_store()
    if result.is_new:
        store.create(
            result.thread_id,
            origin="external",
            subkind=channel,
            root_summary=root_summary,
            tags=[
                channel_ref_tag(channel, msg_id),
                sender_tag(channel, sender) if sender else "",
            ],
        )
        # Drop empty tag if sender absent
        idx = store.get(result.thread_id)
        if idx and "" in idx.tags:
            idx.tags = [t for t in idx.tags if t]
    else:
        # Existing thread: record new message as a channelref (so reply to
        # THIS msg will also land in the same thread) and touch activity.
        store.add_tag(result.thread_id, channel_ref_tag(channel, msg_id))
        store.touch(result.thread_id)
