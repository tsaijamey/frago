"""Phase 2 单测：per-channel conv-key 派生契约。"""

from __future__ import annotations

from frago.server.services.routing.conv_key import (
    ConvKey,
    derive_conv_key,
)


def test_feishu_chat_id():
    key = derive_conv_key("feishu", {"chat_id": "oc_xxx"})
    assert key == ConvKey("feishu", "oc_xxx")
    assert key.tag == "conv:feishu:oc_xxx"


def test_email_account_address():
    key = derive_conv_key("email", {"sender_id": "alice@example.com"})
    assert key == ConvKey("email", "alice@example.com")
    assert key.tag == "conv:email:alice@example.com"


def test_email_falls_back_to_sender():
    key = derive_conv_key("email", {"sender": "bob@example.com"})
    assert key == ConvKey("email", "bob@example.com")


def test_slack_channel_id():
    key = derive_conv_key("slack", {"channel_id": "Cxxx"})
    assert key == ConvKey("slack", "Cxxx")
    assert key.tag == "conv:slack:Cxxx"


def test_unregistered_channel_returns_none():
    assert derive_conv_key("scheduled", {"foo": "bar"}) is None
    assert derive_conv_key("internal", {}) is None


def test_missing_field_returns_none_not_crash():
    assert derive_conv_key("feishu", {}) is None
    assert derive_conv_key("feishu", None) is None
    assert derive_conv_key("email", {"unrelated": "x"}) is None
    assert derive_conv_key("slack", None) is None
