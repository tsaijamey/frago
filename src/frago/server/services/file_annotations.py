"""会话页文件预览（FileViewer）的文档批注：按会话关联落盘，支持溯源与打包填入对话框。

## 为什么放会话目录

用户对会话改动文件的逐行/选区批注，与当前会话是一体的数据，用来组装完整的新 prompt 发给
当前会话继续处理，后续也需要溯源当时对哪份文件哪几行提了什么修改意见。因此与
``observer-slots.json``、``workbench-marks.json`` 一样，存放在
``~/.frago/sessions/<family>/<session_id>/file-annotations.json``。

## 整份覆盖与原子写入

前端在浮窗里新增、修改或删除批注时，整份提交覆盖。落盘走同目录临时文件 + ``os.replace``
原子替换，避免半截文件损坏。读取时若文件不存在或损坏，按空列表兜底并记日志，不阻塞界面。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from frago.server.services.workbench_marks import MarksError, marks_dir

logger = logging.getLogger(__name__)

ANNOTATIONS_FILENAME = "file-annotations.json"
ANNOTATIONS_VERSION = 1

MAX_ANNOTATIONS = 500
MAX_ID = 64
MAX_FILE = 1024
MAX_QUOTE = 20_000
MAX_NOTE = 4_000


def _display_path(path: Path) -> str:
    """把本机用户主目录前缀折叠为 ``~/...``，供界面溯源展示与打包引用。"""
    try:
        rel = path.resolve().relative_to(Path.home().resolve())
        return f"~/{rel.as_posix()}"
    except ValueError:
        try:
            rel = path.relative_to(Path.home())
            return f"~/{rel.as_posix()}"
        except ValueError:
            return path.as_posix()


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarksError(f"{field} 必须是整数")
    return value


def _str(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise MarksError(f"{field} 必须是字符串")
    if len(value) > limit:
        raise MarksError(f"{field} 超过 {limit} 字")
    return value


def normalize_annotation(raw: Any) -> dict[str, Any]:
    """校验单条文档批注。不合规则抛 ``MarksError``。"""
    if not isinstance(raw, dict):
        raise MarksError("每一条文档批注必须是对象")
    ann_id = _str(raw.get("id"), "id", MAX_ID).strip()
    file_path = _str(raw.get("file"), "file", MAX_FILE).strip()
    quote = _str(raw.get("quote", ""), "quote", MAX_QUOTE)
    note = _str(raw.get("note", ""), "note", MAX_NOTE).strip()
    if not ann_id or not file_path or not note:
        raise MarksError("id、file、note 都不能为空")
    line_start = _int(raw.get("line_start"), "line_start")
    line_end = _int(raw.get("line_end", line_start), "line_end")
    if line_start < 1 or line_end < line_start:
        raise MarksError("行号范围不合法（须满足 1 <= line_start <= line_end）")
    created_at = _int(raw.get("created_at", 0), "created_at")
    return {
        "id": ann_id,
        "file": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "quote": quote,
        "note": note,
        "created_at": created_at,
    }


def normalize_annotations(payload: Any) -> dict[str, Any]:
    """校验整份文档批注。"""
    if not isinstance(payload, dict):
        raise MarksError("批注数据必须是对象")
    items = payload.get("annotations")
    if not isinstance(items, list):
        raise MarksError("annotations 必须是数组")
    if len(items) > MAX_ANNOTATIONS:
        raise MarksError(f"文档批注最多 {MAX_ANNOTATIONS} 条")
    out = [normalize_annotation(item) for item in items]
    ids = [item["id"] for item in out]
    if len(set(ids)) != len(ids):
        raise MarksError("批注 id 有重复")
    return {"version": ANNOTATIONS_VERSION, "annotations": out}


def read_file_annotations(directory: Path) -> dict[str, Any]:
    """读取会话目录下的文档批注，附带可读溯源路径 ``trace_path``。"""
    target = directory / ANNOTATIONS_FILENAME
    trace_path = _display_path(target)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": ANNOTATIONS_VERSION, "trace_path": trace_path, "annotations": []}
    except (OSError, ValueError) as exc:
        logger.warning("文档批注文件读不出，按空的算：%s（%s）", target, exc)
        return {"version": ANNOTATIONS_VERSION, "trace_path": trace_path, "annotations": []}
    try:
        normalized = normalize_annotations(data)
    except MarksError as exc:
        logger.warning("文档批注文件形状不对，按空的算：%s（%s）", target, exc)
        return {"version": ANNOTATIONS_VERSION, "trace_path": trace_path, "annotations": []}
    return {
        "version": ANNOTATIONS_VERSION,
        "trace_path": trace_path,
        "annotations": normalized["annotations"],
    }


def write_file_annotations(directory: Path, data: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ANNOTATIONS_FILENAME
    tmp = target.with_name(f"{ANNOTATIONS_FILENAME}.tmp{os.getpid()}")
    disk_payload = {
        "version": ANNOTATIONS_VERSION,
        "annotations": data["annotations"],
    }
    tmp.write_text(json.dumps(disk_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_file_annotations(session_id: str) -> dict[str, Any]:
    """读取指定会话的全部文档批注。"""
    return read_file_annotations(marks_dir(session_id))


def save_file_annotations(session_id: str, payload: Any) -> dict[str, Any]:
    """整份覆盖保存指定会话的文档批注，返回含 ``trace_path`` 的最新状态。"""
    directory = marks_dir(session_id)
    normalized = normalize_annotations(payload)
    write_file_annotations(directory, normalized)
    return {
        "version": ANNOTATIONS_VERSION,
        "trace_path": _display_path(directory / ANNOTATIONS_FILENAME),
        "annotations": normalized["annotations"],
    }
