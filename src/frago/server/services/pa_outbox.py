"""Conv outbox —— 以 conv_key 为键的「待交付制品箱」（spec 20260627 Phase 8）。

新 PA 架构「自然说话、pane 文本直接变 reply」丢了旧 JSON 协议 ``reply.files`` 的
文件交付能力：agent 产出一个文件，正文里只能写一句路径文字，用户收不到真附件。
本模块补回这条能力，做成 agent 通用原语——任何 agent 会话（PA、worker）产出文件时
经 ``frago agent attach`` 把制品登记进**自己所属 conv** 的 outbox，交付层在转发 pane
文本前 drain 该 conv 的 outbox，文本作正文、文件作附件一起送达。

落盘 ``~/.frago/outbox/<sanitized conv_key>.jsonl``：
- 每行一条 JSON 记录 ``{"kind": "file"|"image"|"dir", "path": "<abs>", "conv_key": ...}``。
- attach 追加（append），交付层 drain（读取并清空），与「投递按 conv 来源回投」对齐。
- 以 conv_key 为键，跨进程（attach 是独立 CLI 进程，交付层在 server 进程）共享。

NEVER 截断数据；落盘位置可经 ``FRAGO_OUTBOX_DIR`` 覆盖（测试用）。
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

# 当成图片附件投递的扩展名（飞书 notify_recipe 区分 image / file 两种 msg_type）。
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def outbox_dir() -> Path:
    """outbox 根目录。可经 ``FRAGO_OUTBOX_DIR`` 覆盖（测试 / 隔离用）。"""
    override = os.environ.get("FRAGO_OUTBOX_DIR")
    base = Path(override) if override else Path.home() / ".frago" / "outbox"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sanitize(conv_key: str) -> str:
    """conv_key（形如 ``feishu:oc_xxx``）→ 合法文件名。

    与 tmux_name 同套规则：非 ``[A-Za-z0-9_-]`` 一律替换为 ``_``。同一 conv_key
    稳定映射到同一文件名，跨进程定位一致。
    """
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in conv_key)


def _outbox_path(conv_key: str) -> Path:
    return outbox_dir() / f"{_sanitize(conv_key)}.jsonl"


def classify(path: str) -> str:
    """把一个路径归类成 outbox 记录的 ``kind``：dir / image / file。"""
    p = Path(path).expanduser()
    if p.is_dir():
        return "dir"
    if p.suffix.lower() in _IMAGE_EXTS:
        return "image"
    return "file"


def append(
    conv_key: str,
    *,
    files: list[str] | None = None,
    dirs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """把文件/目录登记进该 conv 的 outbox（追加）。返回本次登记的记录列表。

    路径统一展开 ``~`` 并取绝对路径落盘——attach 在 worker 的 cwd 里跑，交付层在
    server 进程 drain，相对路径会失锚。文件按扩展名分 image / file，目录记 dir。
    """
    records: list[dict[str, Any]] = []
    for raw in files or []:
        abspath = str(Path(raw).expanduser().resolve())
        records.append({"kind": classify(abspath), "path": abspath, "conv_key": conv_key})
    for raw in dirs or []:
        abspath = str(Path(raw).expanduser().resolve())
        records.append({"kind": "dir", "path": abspath, "conv_key": conv_key})
    if not records:
        return []
    path = _outbox_path(conv_key)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return records


def drain(conv_key: str) -> list[dict[str, Any]]:
    """读取并清空该 conv 的 outbox。无则返回空列表。

    drain 后删除文件，避免下一轮交付误带旧附件（spec 关键实现点：drain 后清空）。
    """
    path = _outbox_path(conv_key)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    path.unlink(missing_ok=True)
    return records


def peek(conv_key: str) -> list[dict[str, Any]]:
    """只读该 conv 的 outbox（不清空）。测试 / 观测用。"""
    path = _outbox_path(conv_key)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
    return out
