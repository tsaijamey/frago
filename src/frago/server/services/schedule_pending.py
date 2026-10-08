"""无人应答的拍板卡片：下一次同类运行先查有没有新回答，超期按推荐项走。

语料里 25 场产出过 ``answer-needed-by-human`` 卡片，其中 13 场无人回答——提问题的多半是
无人值守的定时任务，卡片写进答复里，跑完就散了。于是同一类问题逐日重现：整理
agent-failure-modes 的索引体积问题 09-28 就提出、09-29 落盘 0 条、10-04 才重新出卡片问人；
那条 git-push 任务问过的话，下一趟又原样问了一遍。

卡片本身是给页面上的人看的，服务端从前一个字都不留。这里补上回收：

- **收**：一趟跑完，答复里若是挂着一张卡片（取最后一个区块），把它连同会话编号、问的话、
  选项、推荐项、提出的时刻存下来；
- **查**：同一条任务下一次跑起来时，先去那一场的记录里看卡片之后有没有人说过话——有就把
  原话摆到任务前面，人答了什么就按什么办；
- **降级**：挂了 ``OPEN_AFTER_S`` 还没人答，就不再问了：按推荐项办，并要求它在结论里注明
  这一项是按默认取值走的。**同一个问题反复提出，起算时刻不动**——不然每跑一趟都把钟拨回
  零点，这张卡片永远降不了级，正是「逐日重现」的成因。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: 卡片区块的开头（见 ``frago book answer-needed-by-human``）。
FENCE = re.compile(r"```answer-needed-by-human\s*\n(.*?)```", re.DOTALL)
#: 一张卡片挂多久没人答就按推荐项降级（秒）。三天：够跨过一个周末，也够人看见。
OPEN_AFTER_S = 3 * 24 * 3600
#: 挂着的卡片放在这儿，一条任务一份。
ROOT = Path.home() / ".frago" / "schedule-pending"
#: 读会话记录时的块大小。找人答复时从尾巴往前一块块翻，翻到比卡片更早的行就停。
TAIL_BYTES = 256 * 1024


def path_for(schedule_id: str) -> Path:
    return ROOT / f"{schedule_id}.json"


def card_in(answer: str) -> dict[str, Any] | None:
    """答复里有没有挂卡片。取最后一个区块；没有交回 None。

    YAML 写坏了也照样算一张卡片——它确实在等人，把它当没问过才是真丢东西。语料里那种
    手写的老式卡片（`Q1: …… / A: ……（推荐）` 几行）全落在这一档：这种只留下原文，问句
    退而取原文首行，选项与推荐项都空着。
    """
    found = FENCE.findall(answer or "")
    if not found:
        return None
    raw = found[-1].strip()
    card: dict[str, Any] = {"raw": raw, "question": _first_line(raw), "options": [], "recommended": None}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        logger.info("[pending] 卡片不是 YAML（大概是手写的那种），只留原文")
        return card
    if not isinstance(data, dict):
        return card
    options = [o for o in (data.get("options") or []) if isinstance(o, dict)]
    card["question"] = str(data.get("question") or "").strip() or card["question"]
    card["options"] = [str(o.get("label") or "").strip() for o in options]
    card["recommended"] = next(
        (str(o.get("label") or "").strip() for o in options if o.get("recommended")), None
    )
    return card


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def load(schedule_id: str) -> dict[str, Any] | None:
    try:
        data = json.loads(path_for(schedule_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[pending] %s 挂着的卡片读不动（%s），当没有", schedule_id, e)
        return None
    return data if isinstance(data, dict) else None


def save(schedule_id: str, card: dict[str, Any]) -> None:
    path = path_for(schedule_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("[pending] %s 的卡片没写下去", schedule_id)


def clear(schedule_id: str) -> None:
    try:
        path_for(schedule_id).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("[pending] %s 的卡片没删掉", schedule_id)


def collect(schedule: dict[str, Any], outcome: Any) -> None:
    """跑完记一笔：这一趟挂了卡片就记下，没挂就把上一张清掉。"""
    if str(schedule.get("kind") or "") not in ("", "prompt"):
        return
    schedule_id = str(schedule.get("id") or "")
    if not schedule_id:
        return
    try:
        card = card_in(str(getattr(outcome, "stdout", "") or ""))
        if card is None:
            # 这一趟没再问，说明上一次那张已经有了下文（答了、或者它自己办掉了）。
            clear(schedule_id)
            return
        old = load(schedule_id)
        if old and old.get("question") and old.get("question") == card.get("question"):
            # 同一个问题还挂着：起算时刻不动，否则这张卡片永远降不了级。
            card["raised_at"] = old.get("raised_at")
            card["session_id"] = old.get("session_id")
            card["asked_times"] = int(old.get("asked_times") or 1) + 1
        else:
            card["raised_at"] = time.time()
            card["session_id"] = getattr(outcome, "session_id", None)
        card.setdefault("asked_times", 1)
        save(schedule_id, card)
    except Exception:  # noqa: BLE001 — 记不住一张卡片不该让这条任务算失败
        logger.exception("[pending] 给 %s 记卡片时出错", schedule_id)


def reply_since(session_id: str | None, raised_at: float) -> str | None:
    """卡片挂出之后，人在那一场里说过的话。没有交回 None。

    人在会话页上作答，答复以一条用户消息送回同一场会话（卡片那一场跑完了，这一句会把它
    再拉起来接着跑）。所以就按「卡片之后的用户发言」找，最早的那句就是答复。

    **按时间找，不能只看文件尾巴。** 卡片挂出之后那一场多半又跑了一整天，人的答复早被
    后来的记录埋到前面去了——语料里 core_0b27d2d125064 就是这样，只看尾巴会当成没人答，
    于是一张已经拍过板的卡片又被当成默认取值办一遍。
    """
    if not session_id:
        return None
    try:
        from frago.session import coreagent_store

        path = coreagent_store.find_session_file(session_id)
        if path is None:
            return None
        for row in _rows_since(path, raised_at * 1000):
            if str(row.get("type")) != "user":
                continue
            text = _user_text(row)
            if text:
                return text
        return None
    except Exception:  # noqa: BLE001
        logger.exception("[pending] 读 %s 找人的答复时出错", session_id)
        return None


def note(schedule_id: str, *, now: float | None = None) -> str | None:
    """下一次跑起来时摆到任务前面的那段话。没有挂着的卡片就交回 None。"""
    card = load(schedule_id)
    if card is None:
        return None
    raised_at = card.get("raised_at")
    raised_at = raised_at if isinstance(raised_at, (int, float)) else 0.0
    answered = reply_since(card.get("session_id"), raised_at)
    if answered:
        return _answered(card, answered)
    age = (now if now is not None else time.time()) - raised_at
    if age < OPEN_AFTER_S:
        return None
    return _defaulted(card, age)


def _answered(card: dict[str, Any], reply: str) -> str:
    lines = [
        "【上一趟问的那件事有人答了】这条任务上一趟挂了一张要人拍板的卡片，人已经作答。"
        "按这个答复办，不要当它没答过：",
        "",
        f"- 当时问的是：{card.get('question') or '（见原文）'}",
        f"- 人的答复：{reply.strip()}",
    ]
    if card.get("raw"):
        lines += ["", "卡片原文：", card["raw"]]
    return "\n".join(lines)


def _defaulted(card: dict[str, Any], age: float) -> str:
    days = age / 86400
    recommended = card.get("recommended")
    ask = card.get("question") or "（见卡片原文）"
    if recommended:
        how = (
            f"按推荐项「{recommended}」办，并在结论里注明这一项是按默认取值走的、不是人拍的板。"
        )
    else:
        how = (
            "这张卡片没标推荐项：按你认为最稳妥的一条办，"
            "并在结论里注明这是你自己定的默认取值、还没有人拍板。"
        )
    lines = [
        f"【上一趟问的那件事至今没人答】这张卡片挂了 {days:.0f} 天没人回。"
        f"**不要再问第二遍**——同一张卡片逐日重现是最坏的结局：它占着每一趟的收尾，"
        f"而问题永远停在那儿。",
        "",
        f"- 当时问的是：{ask}",
        f"- 怎么办：{how}",
    ]
    if card.get("options"):
        lines.append(f"- 当时给的选项：{'、'.join(card['options'])}")
    if card.get("raw"):
        lines += ["", "卡片原文：", card["raw"]]
    return "\n".join(lines)


# ── 读会话记录那几个小动作 ──────────────────────────────────────────────


def _rows_since(path: Path, since_ms: float) -> list[dict[str, Any]]:
    """这一场里 ``since_ms`` 之后的行，按发生顺序（旧到新）。

    从尾巴往前一块块地找，撞见一条比 ``since_ms`` 早的行就停下——记录是按时间往后追加
    的，再往前只会更早。锚点落在哪一块都不必读整份记录，一场跑了一整天的会话也一样。
    """
    size = path.stat().st_size
    if size == 0:
        return []
    buf = b""
    start = size
    reached_start = False
    with path.open("rb") as fh:
        while start > 0:
            chunk_start = max(0, start - TAIL_BYTES)
            fh.seek(chunk_start)
            buf = fh.read(start - chunk_start) + buf
            start = chunk_start
            reached_start = start == 0
            if reached_start:
                break
            oldest = _oldest_ms(buf)
            if oldest is not None and oldest < since_ms:
                break
    text = buf.decode("utf-8", errors="replace")
    if not reached_start:
        # 从半行切进来的第一段丢掉，它不是完整的一行。
        text = text.split("\n", 1)[-1]
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _ms_of(row)
        # 认不出时刻的行留着：它可能是答复那个区块的一部分。
        if ts is None or ts >= since_ms:
            rows.append(row)
    return rows


def _oldest_ms(buf: bytes) -> float | None:
    """这一块里最早的那条记录的毫秒时刻。一条都认不出就交回 None。"""
    text = buf.decode("utf-8", errors="replace").split("\n", 1)[-1]
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ts = _ms_of(json.loads(line))
        except json.JSONDecodeError:
            continue
        if ts is not None:
            return ts
    return None


def _ms_of(row: Any) -> float | None:
    if not isinstance(row, dict):
        return None
    ts = row.get("timestamp")
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        parsed = _parse_iso_ms(ts)
        return float(parsed) if parsed is not None else None
    return None


def _user_text(row: dict[str, Any]) -> str:
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        b["text"].strip()
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]
    return "\n".join(p for p in parts if p)


def _parse_iso_ms(stamp: str) -> int | None:
    """``2026-10-06T07:12:03.581Z`` → 毫秒。认不出交回 None。"""
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None
