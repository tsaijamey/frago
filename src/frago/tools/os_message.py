"""
OS Message — structured message pushing from OS modules to the conversation flow.

Fire-and-forget: if the message API is unavailable, messages are silently dropped.
The deployment plan is already persisted to disk, so users can always access it
via `frago workspace pending`.

Interface contract defined by 20260212-continuous-conversation.md spec.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Server endpoint for pushing messages
OS_MESSAGE_ENDPOINT = "http://127.0.0.1:8093/api/conversation/push"


@dataclass
class OSMessage:
    """Structured message pushed from OS modules to the conversation flow.

    The receiving side (defined by continuous-conversation spec) renders
    the content appropriately. This module is only a producer.
    """
    type: str                # "workspace-deploy", "sync-complete", ...
    title: str               # Human-readable title
    content: dict[str, Any]  # Structured payload (table data, change lists, etc.)
    actions: list[str] = field(default_factory=list)  # Optional: ["confirm", "skip", "elaborate"]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "actions": self.actions,
            "created_at": self.created_at.isoformat(),
        }


def push_os_message(message: OSMessage) -> bool:
    """Fire-and-forget push to OS message API.

    Returns True if message was accepted, False otherwise.
    Failure is silent — the deployment plan is already on disk.
    """
    try:
        import httpx
        httpx.post(
            OS_MESSAGE_ENDPOINT,
            json=message.to_dict(),
            timeout=2,
        )
        return True
    except ImportError:
        # httpx not available, try urllib
        try:
            import json
            import urllib.request
            req = urllib.request.Request(
                OS_MESSAGE_ENDPOINT,
                data=json.dumps(message.to_dict()).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            return False
    except Exception:
        return False
