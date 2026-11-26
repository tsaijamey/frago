"""纯卡片解析工具（从原会话输出解析遗留 ``answer-needed-by-human`` 与 UI 组件 JSON）。

供 ``workbench_queue`` 判断会话尾部是否仍挂着未回答的拍板卡片，以及供统一决策收件箱
从在线等待会话的最后一条消息提取结构化问题与选项。本模块不做任何磁盘或网络 I/O。
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

#: 卡片围栏区块的正则（见 ``frago book answer-needed-by-human``）。
FENCE = re.compile(r"```answer-needed-by-human\s*\n(.*?)```", re.DOTALL)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def _extract_ui_component_dict(text: str) -> dict[str, Any] | None:
    """从文本中提取 ``frago ask`` / ``frago app ask`` 输出的 ``frago_ui_component == "decision-card"`` 数据字典。"""
    if not text or '"frago_ui_component"' not in text:
        return None
    idx = text.rfind('"frago_ui_component"')
    start = text.rfind("{", 0, idx)
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and obj.get("frago_ui_component") == "decision-card":
        data = obj.get("data")
        if isinstance(data, dict):
            return data
    return None


def card_in(answer: str) -> dict[str, Any] | None:
    """判断答复里是否挂有拍板卡片；取最后一个区块，没有返回 None。"""
    ui_data = _extract_ui_component_dict(answer or "")
    if ui_data is not None:
        raw_json = json.dumps(ui_data, ensure_ascii=False, indent=2)
        options = [o for o in (ui_data.get("options") or []) if isinstance(o, dict)]
        question = str(ui_data.get("question") or "").strip() or _first_line(raw_json)
        return {
            "raw": raw_json,
            "question": question,
            "options": [str(o.get("label") or "").strip() for o in options],
            "recommended": next(
                (str(o.get("label") or "").strip() for o in options if o.get("recommended")),
                None,
            ),
        }
    found = FENCE.findall(answer or "")
    if not found:
        return None
    raw = found[-1].strip()
    card: dict[str, Any] = {
        "raw": raw,
        "question": _first_line(raw),
        "options": [],
        "recommended": None,
    }
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return card
    if not isinstance(data, dict):
        return card
    options = [o for o in (data.get("options") or []) if isinstance(o, dict)]
    card["question"] = str(data.get("question") or "").strip() or card["question"]
    card["options"] = [str(o.get("label") or "").strip() for o in options]
    card["recommended"] = next(
        (str(o.get("label") or "").strip() for o in options if o.get("recommended")),
        None,
    )
    return card


def extract_decision_card_detail(answer: str) -> dict[str, Any] | None:
    """提取丰富结构化字段（含 option key/effect、why、action_type 等），供在线等待会话装配提案。"""
    ui_data = _extract_ui_component_dict(answer or "")
    if ui_data is not None:
        raw_options = [o for o in (ui_data.get("options") or []) if isinstance(o, dict)]
        options: list[dict[str, Any]] = []
        recommended_key: str | None = None
        for idx, opt in enumerate(raw_options):
            key = str(opt.get("key") or opt.get("id") or chr(65 + idx)).strip()
            label = str(opt.get("label") or key).strip()
            effect = str(opt.get("effect") or opt.get("description") or "").strip()
            is_rec = bool(opt.get("recommended"))
            if is_rec and recommended_key is None:
                recommended_key = key
            options.append(
                {
                    "key": key,
                    "label": label,
                    "effect": effect,
                    "recommended": is_rec,
                    "reversible": opt.get("reversible") is not False,
                }
            )
        if recommended_key is None and ui_data.get("recommended"):
            recommended_key = str(ui_data["recommended"]).strip()
        raw_type = str(ui_data.get("type") or ui_data.get("action_type") or "single-choice").strip()
        if raw_type not in {"single-choice", "multi-choice", "binary", "text-answer", "choice-and-text"}:
            raw_type = "single-choice" if options else "text-answer"
        question = str(ui_data.get("question") or "").strip()
        why = str(ui_data.get("why") or ui_data.get("context") or "").strip()
        if not question:
            question = _first_line(answer or "")
        return {
            "action_type": raw_type,
            "question": question,
            "why": why,
            "options": options,
            "recommended": recommended_key,
            "draft": ui_data.get("draft"),
            "suggestions": list(ui_data.get("suggestions") or []),
        }

    found = FENCE.findall(answer or "")
    if not found:
        return None
    raw = found[-1].strip()
    question = _first_line(raw)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        return {
            "action_type": "text-answer",
            "question": question,
            "why": raw[:400],
            "options": [],
            "recommended": None,
        }
    raw_options = [o for o in (data.get("options") or []) if isinstance(o, dict)]
    options = []
    recommended_key = None
    for idx, opt in enumerate(raw_options):
        key = str(opt.get("key") or opt.get("id") or chr(65 + idx)).strip()
        label = str(opt.get("label") or key).strip()
        effect = str(opt.get("effect") or "").strip()
        is_rec = bool(opt.get("recommended"))
        if is_rec and recommended_key is None:
            recommended_key = key
        options.append(
            {
                "key": key,
                "label": label,
                "effect": effect,
                "recommended": is_rec,
                "reversible": opt.get("reversible") is not False,
            }
        )
    raw_type = str(data.get("type") or "single-choice").strip()
    if raw_type not in {"single-choice", "multi-choice", "binary", "text-answer"}:
        raw_type = "single-choice" if options else "text-answer"
    return {
        "action_type": raw_type,
        "question": str(data.get("question") or "").strip() or question,
        "why": str(data.get("why") or data.get("context") or "").strip(),
        "options": options,
        "recommended": recommended_key,
    }
