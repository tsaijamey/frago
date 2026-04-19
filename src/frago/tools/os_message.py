"""
OS Message — structured message pushing from OS modules to the conversation flow.

Spec 20260418-timeline-event-coverage Phase 3: OSMessages are now timeline
entries (origin=internal, subkind=os, data_type=os_event) rather than a separate
HTTP push channel. The old `/api/conversation/push` endpoint is obsolete.

Fire-and-forget: trace write errors are silently swallowed.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OSMessage:
    """Structured message from OS modules (sync, workspace, deploy, etc.).

    Rendered in the timeline via `data_type=os_event`; UI can style based on
    `data.os_event_type`.
    """
    type: str                # "workspace-deploy", "sync-complete", ...
    title: str               # Human-readable title
    content: dict[str, Any]  # Structured payload (table data, change lists, etc.)
    actions: list[str] = field(default_factory=list)  # e.g. ["confirm", "skip"]
    created_at: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "actions": self.actions,
            "created_at": self.created_at.isoformat(),
        }


def push_os_message(message: OSMessage, *, thread_id: str | None = None) -> bool:
    """Fire-and-forget: write OSMessage to the timeline.

    Returns True if the entry was written, False on failure (silent).
    Pass `thread_id` to attach to a specific thread; otherwise the entry
    forms its own root thread.
    """
    try:
        from frago.server.services.trace import trace_entry

        trace_entry(
            origin="internal",
            subkind="os",
            data_type="os_event",
            thread_id=thread_id,
            parent_id=None,
            task_id=None,
            data={
                "os_event_type": message.type,
                "title": message.title,
                "content": message.content,
                "actions": message.actions,
            },
            event=message.title,
        )
        return True
    except Exception:
        logger.debug("push_os_message: trace_entry failed", exc_info=True)
        return False
