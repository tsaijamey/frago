"""Anti-bot detection RPC contract tests.

The actual classifier logic is JS in service_worker.js — exercised by
the live e2e demo and (manually) on real anti-bot-protected sites.
These Python-side tests verify the Python wrapper sends the right RPC
and surfaces the result without surprises.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from frago.chrome.backends.extension import ExtensionChromeBackend


def _be_with_rpc(response):
    """ExtensionChromeBackend with _rpc patched to return ``response``."""
    be = ExtensionChromeBackend()
    be._rpc = MagicMock(return_value=response)
    return be


def test_detect_anti_bot_clean_page():
    """No challenge → recipe layer should proceed."""
    be = _be_with_rpc({"challenge": False, "title": "Example", "url": "https://example.com/"})
    result = be.detect_anti_bot(group="x")
    be._rpc.assert_called_once_with("detect.anti_bot", {"group": "x"})
    assert result["challenge"] is False


def test_detect_anti_bot_interactive_flag():
    """Turnstile-like challenge → needs_human=True signaled."""
    be = _be_with_rpc({
        "challenge": True,
        "type": "interactive",
        "needs_human": True,
        "detector": "selector",
        "detector_match": ".cf-turnstile",
        "title": "Verify you are human",
        "url": "https://example.com/",
    })
    result = be.detect_anti_bot(group="x")
    assert result["needs_human"] is True
    assert result["type"] == "interactive"


def test_detect_anti_bot_invisible_challenge():
    """JS-only challenge → needs_human=False, recipe should wait + retry."""
    be = _be_with_rpc({
        "challenge": True,
        "type": "invisible_or_static",
        "needs_human": False,
        "detector": "title",
        "title": "Just a moment...",
        "url": "https://example.com/",
        "body_preview": "Cloudflare Ray ID: ...",
    })
    result = be.detect_anti_bot(group="x")
    assert result["challenge"] is True
    assert result["needs_human"] is False
    assert result["type"] == "invisible_or_static"


def test_detect_anti_bot_blocked():
    """Hard block → fail loud, no retry helps."""
    be = _be_with_rpc({
        "challenge": True,
        "type": "blocked",
        "needs_human": False,
        "detector": "body-blocked-text",
        "title": "Access Denied",
        "url": "https://example.com/",
    })
    result = be.detect_anti_bot(group="x")
    assert result["type"] == "blocked"


def test_detect_anti_bot_propagates_rpc_error():
    """RPC layer errors (extension not connected, etc.) bubble up."""
    from frago.chrome.backends.extension import ExtensionBackendError

    be = ExtensionChromeBackend()
    be._rpc = MagicMock(side_effect=ExtensionBackendError(-32003, "extension not connected"))
    with pytest.raises(ExtensionBackendError):
        be.detect_anti_bot(group="x")
