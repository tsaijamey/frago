"""会话页的标注：记录流里被「引用」或「暂存」过的那些文字。

方案见 ``.claude/docs/spec-driven-plan/20260928-webui-session-stack/spec.md``。

## 为什么放服务端

标注跟着会话走，不跟着浏览器走。换浏览器、清站点数据、重开页面之后，右栏下半的暂存
列表和记录流里的底色都得还在——放浏览器本地存储做不到这一条。所以它与旁路 AI 的槽位
文件同一套办法：该会话备份目录里单独一份 ``workbench-marks.json``，由这里读写。

## 整份覆盖

页面每改一次（新增、改想法、删、排序、标用过）就把整份交回来，这里整份写下去。不做
逐条合并：两个标签页同时改，以后写入的为准（spec「不做什么」第 3 条）。写入走临时文件
加原子替换，写到一半断电不会留下半份文件。

## 坏文件不连累界面

文件不存在、读不出、内容不是这个形状，一律当成「还没有标注」，记一条日志，NEVER 抛给
页面——一份坏掉的标注文件不该让整场会话打不开。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARKS_FILENAME = "workbench-marks.json"
MARKS_VERSION = 1

KINDS = ("quote", "stack")

# 上限。原文取自人在记录流里圈的那一段，两万字已经是好几屏；想法是人自己打的一两句。
MAX_TEXT = 20_000
MAX_NOTE = 4_000
MAX_MARKS = 500
MAX_ID = 64
MAX_RECORD_ID = 256


class MarksError(ValueError):
    """交上来的这份标注不合规矩。路由据此回 400，原因照抄给页面。"""


def empty_marks() -> dict[str, Any]:
    return {"version": MARKS_VERSION, "marks": []}


def marks_dir(session_id: str) -> Path:
    """这场会话的备份目录，与 ``observer-slots.json`` 同一个。

    家族照旁路 AI 那一套判：认不出的编号抛 ``UnknownSessionFamily``；认得出、却没有备份
    目录的那一家（CoreAgent）抛 ``KeyError``。两种路由都回 404。
    """
    from frago.server.services.session_observer import session_dir
    from frago.session.record_reader import detect_family

    family = detect_family(session_id)
    return session_dir(session_id, family)


def _int(value: Any, field: str) -> int:
    # bool 是 int 的子类，true 混进时间戳里不该被当成 1。
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarksError(f"{field} 必须是整数")
    return value


def _str(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise MarksError(f"{field} 必须是字符串")
    if len(value) > limit:
        raise MarksError(f"{field} 超过 {limit} 字")
    return value


def normalize_mark(raw: Any) -> dict[str, Any]:
    """校验一条标注，只留下认得的字段。不合规矩抛 ``MarksError``。"""
    if not isinstance(raw, dict):
        raise MarksError("每一条标注必须是对象")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise MarksError(f"kind 只认 {' / '.join(KINDS)}")
    mark_id = _str(raw.get("id"), "id", MAX_ID)
    record_id = _str(raw.get("record_id"), "record_id", MAX_RECORD_ID)
    text = _str(raw.get("text"), "text", MAX_TEXT)
    if not mark_id or not record_id or not text:
        raise MarksError("id、record_id、text 都不能为空")
    occurrence = _int(raw.get("occurrence", 0), "occurrence")
    if occurrence < 0:
        raise MarksError("occurrence 不能是负数")
    used_at = raw.get("used_at")
    return {
        "id": mark_id,
        "kind": kind,
        "record_id": record_id,
        "text": text,
        "occurrence": occurrence,
        "note": _str(raw.get("note", ""), "note", MAX_NOTE),
        "used": raw.get("used") is True,
        "created_at": _int(raw.get("created_at", 0), "created_at"),
        "used_at": None if used_at is None else _int(used_at, "used_at"),
    }


def normalize_marks(payload: Any) -> dict[str, Any]:
    """校验整份。条数超限、任何一条不合规矩都整份拒收，不挑着存。"""
    if not isinstance(payload, dict):
        raise MarksError("标注必须是对象")
    marks = payload.get("marks")
    if not isinstance(marks, list):
        raise MarksError("marks 必须是数组")
    if len(marks) > MAX_MARKS:
        raise MarksError(f"标注最多 {MAX_MARKS} 条")
    out = [normalize_mark(m) for m in marks]
    ids = [m["id"] for m in out]
    if len(set(ids)) != len(ids):
        raise MarksError("id 有重复")
    return {"version": MARKS_VERSION, "marks": out}


def read_marks(directory: Path) -> dict[str, Any]:
    """读这一目录下的标注。没有、读不出、形状不对，都当空的。"""
    path = directory / MARKS_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_marks()
    except (OSError, ValueError) as exc:
        logger.warning("标注文件读不出，按空的算：%s（%s）", path, exc)
        return empty_marks()
    try:
        return normalize_marks(data)
    except MarksError as exc:
        logger.warning("标注文件形状不对，按空的算：%s（%s）", path, exc)
        return empty_marks()


def write_marks(directory: Path, marks: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MARKS_FILENAME
    tmp = target.with_name(f"{MARKS_FILENAME}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(marks, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_marks(session_id: str) -> dict[str, Any]:
    """这场会话的全部标注。"""
    return read_marks(marks_dir(session_id))


def save_marks(session_id: str, payload: Any) -> dict[str, Any]:
    """整份覆盖。先认会话、再校验，校验过了才落盘；交回落盘后的那一份。"""
    directory = marks_dir(session_id)
    marks = normalize_marks(payload)
    write_marks(directory, marks)
    return marks
