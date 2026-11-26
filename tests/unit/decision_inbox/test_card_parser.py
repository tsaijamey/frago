"""纯卡片解析单测。"""

from __future__ import annotations

import json

from frago.decision_inbox.card_parser import card_in, extract_decision_card_detail


def test_card_in_parses_fence_and_ui_component_json() -> None:
    fence_text = """准备好了，请拍板：
```answer-needed-by-human
type: single-choice
question: 是否清理 30 天未访问缓存？
why: 已占用 1.2GB
options:
  - key: A
    label: 仅清理 tmp
    effect: 释放 800MB
    recommended: true
  - key: B
    label: 保留不动
    effect: 不改磁盘
```
"""
    card = card_in(fence_text)
    assert card is not None
    assert card["question"] == "是否清理 30 天未访问缓存？"
    assert card["options"] == ["仅清理 tmp", "保留不动"]
    assert card["recommended"] == "仅清理 tmp"

    detail = extract_decision_card_detail(fence_text)
    assert detail is not None
    assert detail["action_type"] == "single-choice"
    assert detail["why"] == "已占用 1.2GB"
    assert detail["recommended"] == "A"
    assert detail["options"][0]["effect"] == "释放 800MB"

    ui_payload = {
        "frago_ui_component": "decision-card",
        "data": {
            "type": "binary",
            "question": "是否发送日报？",
            "why": "外部群发不可撤回",
            "options": [
                {"key": "approve", "label": "确认发送", "effect": "推送飞书", "recommended": True},
                {"key": "reject", "label": "暂不发送", "effect": "保持草稿"},
            ],
        },
    }
    ui_text = "请看：\n" + json.dumps(ui_payload, ensure_ascii=False)
    ui_card = card_in(ui_text)
    assert ui_card is not None
    assert ui_card["question"] == "是否发送日报？"
    assert ui_card["recommended"] == "确认发送"

    ui_detail = extract_decision_card_detail(ui_text)
    assert ui_detail is not None
    assert ui_detail["action_type"] == "binary"
    assert ui_detail["recommended"] == "approve"
