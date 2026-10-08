"""定时任务的续跑包：这一趟接到哪，下一趟从这里接着走。

语料里最刺眼的一例是 10-06 同一天那条 git-push 任务相隔 82 秒跑两次，第二次把第一次
已经查明的「476 个未跟踪文件」「.gitignore 新规则挡下 2.3GB」原样重推了一遍；整理
agent-failure-modes 连着四天各自重新踩白名单那个坑。跨场继承下来的只有待办条目上那条
记录，不是「上一趟干到哪」——所以一条任务死在一次端点抖动上，第二天是从零重来的。

内核那边已经会在终止前留一份交接（「【收场交接】为什么停 / 走到第几轮 / 改过哪些文件 /
下一步」）。这里做两件事，都不改内核：

- **收**：一趟没跑完，把那份交接连同任务原文、会话编号、收场时刻收成一个续跑包，存在
  ``~/.frago/schedule-resume/<任务编号>.json``；
- **接**：同一条任务下一次跑起来时，把续跑包摆在任务原文前面——「接着上一趟跑，别把已经
  做过的重做一遍」。

**跑成了就清掉。** 任务办完还留着上一趟的交接，下一趟会去接着一件已经做完的事。

一条续跑包最多留 ``MAX_AGE_S``：隔了一周还接，接的已经不是同一件事了——世界变了、任务
说明可能也改了，那段交接只会把这一趟带偏。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 内核留下的交接那一行的开头（见 ``frago-core`` 的 ``kernel/loop.rs``）。
MARKER = "【收场交接】"
#: 续跑包放在这儿，一条任务一份。
ROOT = Path.home() / ".frago" / "schedule-resume"
#: 续跑包最多留这么久（秒）。
MAX_AGE_S = 7 * 24 * 3600
#: 从会话记录尾巴上读这么多字节找交接。交接就在收场前写下的那一段，用不着读整场。
TAIL_BYTES = 256 * 1024


def path_for(schedule_id: str) -> Path:
    return ROOT / f"{schedule_id}.json"


def load(schedule_id: str, *, now: float | None = None) -> str | None:
    """取这条任务上一次留下的续跑包正文。没有、读不动、或者已经过期，都交回 None。"""
    path = path_for(schedule_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[resume] %s 的续跑包读不动（%s），这一趟从头来", schedule_id, e)
        return None
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    saved_at = data.get("saved_at")
    age = (now if now is not None else time.time()) - (saved_at if isinstance(saved_at, (int, float)) else 0)
    if age > MAX_AGE_S:
        logger.info("[resume] %s 的续跑包放了 %.1f 天，不接了", schedule_id, age / 86400)
        clear(schedule_id)
        return None
    return text


def save(schedule_id: str, text: str, session_id: str | None = None) -> None:
    path = path_for(schedule_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"saved_at": time.time(), "session_id": session_id, "text": text},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        # 存不下是可惜，不是这一趟的失败：任务该报的成败照报。
        logger.exception("[resume] %s 的续跑包没写下去", schedule_id)


def clear(schedule_id: str) -> None:
    try:
        path_for(schedule_id).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("[resume] %s 的续跑包没删掉", schedule_id)


def handover_of(session_id: str | None) -> str | None:
    """从这场会话的记录里取内核留下的那段交接。取不到交回 None。

    ``find_session_file`` 与 ``record_reader`` 都 NEVER 抛，这里也一样——续跑包差一截
    不该让一条定时任务当场炸掉。
    """
    if not session_id:
        return None
    try:
        from frago.session import coreagent_store

        path = coreagent_store.find_session_file(session_id)
        if path is None:
            return None
        return _last_marked(path)
    except Exception:  # noqa: BLE001
        logger.exception("[resume] 读 %s 的会话记录找交接时出错", session_id)
        return None


def _last_marked(path: Path) -> str | None:
    """记录尾巴上最后一条以 :data:`MARKER` 开头的正文。

    会话记录是 Claude Code 那个形状（见 :mod:`frago.session.coreagent_store`）：交接在
    内核那边是一条 Thinking 事件，落盘就是一条 assistant 的文本行。
    """
    size = path.stat().st_size
    start = max(0, size - TAIL_BYTES)
    with path.open("rb") as fh:
        fh.seek(start)
        blob = fh.read()
    text = blob.decode("utf-8", errors="replace")
    if start:
        # 从半行切进来的第一段丢掉，它不是完整的一行。
        text = text.split("\n", 1)[-1]
    found: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for block in _text_blocks(row):
            if block.startswith(MARKER):
                found = block
    return found


def _text_blocks(row: Any) -> list[str]:
    """一条记录行里的正文块（形状与 Claude Code 一致）。"""
    if not isinstance(row, dict):
        return []
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [
        b["text"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]


def build(schedule: dict[str, Any], outcome: Any) -> str | None:
    """把这一趟的收场整理成续跑包。没有可接的就交回 None（跑成了、或者两手空空）。"""
    if outcome.ok:
        return None
    handover = handover_of(getattr(outcome, "session_id", None))
    if not handover:
        # 内核没留下交接（旧版二进制、或者它连发都没发出来）。这时只剩失败原因可写，
        # 而失败原因在执行记录里已经有了——不必再攒一份只有错误码的续跑包。
        return None
    lines = [
        "## 上一趟跑到这里",
        f"- 任务：{str(schedule.get('prompt') or '').strip()}",
    ]
    session_id = getattr(outcome, "session_id", None)
    if session_id:
        lines.append(f"- 上一趟的会话编号：{session_id}（会话页上能翻到它中途做了什么）")
    if getattr(outcome, "error", ""):
        lines.append(f"- 收场时报的错：{outcome.error}")
    lines += ["", handover]
    return "\n".join(lines)


def section(package: str) -> str:
    """续跑包本身那一段，摆在这次的任务原文前面。

    「上一趟」的外壳（开头那句提示与结尾那句分割）由 :func:`schedule_executor.previous_block`
    统一套——一张没人答的拍板卡片（:mod:`schedule_pending`）也要摆进同一个壳里，两处各写
    一层的话，两段「上一趟」会各自带着一个结尾，读起来像两次收尾。
    """
    return f"【上一趟没跑完，留下的交接】\n\n{package}"


def record(schedule: dict[str, Any], outcome: Any) -> None:
    """按这一趟的结果记账：跑成就清掉续跑包，没跑完就把新的存下。"""
    if str(schedule.get("kind") or "") not in ("", "prompt"):
        return
    schedule_id = str(schedule.get("id") or "")
    if not schedule_id:
        return
    try:
        package = build(schedule, outcome)
    except Exception:  # noqa: BLE001
        logger.exception("[resume] 给 %s 攒续跑包时出错", schedule_id)
        return
    if package is None:
        if outcome.ok:
            clear(schedule_id)
        return
    save(schedule_id, package, getattr(outcome, "session_id", None))
