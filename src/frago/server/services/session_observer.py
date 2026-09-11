"""会话页右栏的旁路观察。

方案见 ``~/.frago/data/frago-dev/20260909-session-observer-research/plan.md``。

## 它不是一个活着的东西

旁路 AI 不常驻。会话流里三件事发生时——agent 把话交还给人、人按了打断、这场会话在页面
上第一次被打开——往这场会话自己的队列里投一个任务。任务读游标之后的新增记录，问一次
frago-core，把回答写进槽位文件，推给页面，结束。没有进程要看管，也就没有孤儿；会话不再
动，就不再有人投任务；服务重启后游标还在槽位文件里，下次打开时一次补上。

## 切换会话不能打断它

检测和运行都在服务端，跟页面停在哪场会话无关：

1. 每场会话一条队列，互不抢占。同一场同一时刻只跑一次，跑着时又来了就记一笔「还欠一次」。
2. 不在监听那条线上等模型。监听只把任务投进来，frago-core 在这里的执行位上跑。
3. 打开时的补读也投进队列，投出去就不管，人切走了照样跑完、照样写进文件。
4. 页面切回来先读槽位文件，不靠离开期间的推送。

## 只有 frago-core 调模型

这里不碰任何模型的地址和钥匙。问模型一律交给 ``frago-core ask --role observer``，用哪个
连接由设置页里「旁路 AI」那一格决定，没绑就不跑。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

SLOTS_FILENAME = "observer-slots.json"
RUNS_FILENAME = "observer-runs.jsonl"

#: 槽位文件的结构版本。字段或判据一改就升：读到别的版本当作没有，从头重算——槽位是从
#: 会话记录投影出来的，丢了能重建，旧数据被当成新数据读才是真麻烦。
SLOTS_VERSION = 1

#: 说明书的文件名，在 ``~/.frago/hook/`` 下，随包发、人可以改，改过的升级时不覆盖。
INSTRUCTIONS_FILE = "observer.md"

WS_OBSERVER_UPDATE = "session_observer_update"

#: 一次最多喂多少条新增记录。第一次打开一场跑了一整天的会话时，游标之后有几千条；全塞进
#: 一次调用既慢又贵，只喂最近这些再加上锚槽，够判「此刻」。
BACKLOG_CAP = 300
PAGE = 500
#: 往前找第一句人话时最多翻几页。
ANCHOR_SCAN_PAGES = 20
#: 「已经发生的事」在文件里最多留多少条。页面默认只露最新三条。
HAPPENED_KEEP = 300
#: 每一段最多新添几条「已经发生的事」。
HAPPENED_PER_RUN = 3

ASK_TIMEOUT_MS = 30_000
ASK_MAX_TOKENS = 1_500
#: 等 frago-core 的墙钟上限，比它自己的期限多留几秒给进程起落。
PROCESS_TIMEOUT_S = ASK_TIMEOUT_MS / 1000 + 10

#: 家族 → 备份目录名，与三家同步程序写 ``raw.jsonl`` 的落点一致。
_FAMILY_DIR = {"claude-code": "claude", "opencode": "opencode", "codex": "codex"}

# ── 问话里的占位字 ────────────────────────────────────────────────────────
#
# 拼给模型的问话里，空着的格子写成这几个字，模型才看得出「这一格现在是空的」。模型有时把
# 它们原样抄回来当内容（2026-09-11 实测：一场会话的「此刻在做什么」被写成了「（还没有）」），
# 所以回答里出现它们一律当空。两处用的是同一组字，改一处必须改另一处。
EMPTY_MARK = "（还没有）"
NONE_MARK = "（无）"
NOTHING_TO_READ = "（这一段没有要看的内容）"
NOBODY_SPOKE = "（这一段里人没说话）"
_PLACEHOLDERS = frozenset({EMPTY_MARK, NONE_MARK, NOTHING_TO_READ, NOBODY_SPOKE, "还没有", "无"})


def _unplaceholder(text: str) -> str:
    return "" if text.strip() in _PLACEHOLDERS else text


# ── 禁令的检查 ────────────────────────────────────────────────────────────
#
# 右栏只许出现已经发生的绝对数。依据是业内三家一起撤掉前瞻式待办清单：Codex issue #21327
# 记下的原话是「人会把进度面板当成产品状态读，而不是当成模型的自述」——靠模型自觉维持真实
# 的东西，漏一次就在撒谎。说明书里讲了规矩，这里再拦一道：违反的整份作废，槽位保持原样。
_ALWAYS_BANNED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d+(?:\.\d+)?\s*[%％]"), "百分比"),
    # 「3/5」这种计数。前后贴着字母、斜杠或点的不算，免得把 2026/09/11 和路径误伤。
    (re.compile(r"(?<![\w/.-])\d+\s*/\s*\d+(?![\w/.-])"), "几之几的计数"),
    (re.compile(r"预计|还剩|剩余时间"), "预计与剩余"),
)
#: 只查「需要你决策」以外的格：待决那一格说的就是人要选的往后怎么走，这些字眼在那里正当。
_FUTURE_BANNED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"接下来|下一步|将要|即将"), "还没发生的步骤"),
)


# ── 槽位文件 ──────────────────────────────────────────────────────────────


def empty_slots(session_id: str, family: str) -> dict[str, Any]:
    return {
        "version": SLOTS_VERSION,
        "session_id": session_id,
        "family": family,
        # 下一条要读的记录的 seq。
        "cursor": 0,
        # {"seq": 这句人话的记录序号, "text": 原话}，还没找到时为 None。
        "anchor": None,
        "now": "",
        "decision": "",
        "output": "",
        # 从旧到新。
        "happened": [],
        "updated_at": None,
        "model": None,
        # ok / failed / empty。未绑定不写文件，由读取时现判。
        "status": "empty",
        "status_detail": None,
    }


def session_dir(session_id: str, family: str) -> Path:
    from frago.session.storage import get_session_base_dir

    return get_session_base_dir() / _FAMILY_DIR[family] / session_id


def load_slots(directory: Path, session_id: str, family: str) -> dict[str, Any]:
    try:
        data = json.loads((directory / SLOTS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_slots(session_id, family)
    if not isinstance(data, dict) or data.get("version") != SLOTS_VERSION:
        return empty_slots(session_id, family)
    base = empty_slots(session_id, family)
    base.update({k: v for k, v in data.items() if k in base})
    return base


def save_slots(directory: Path, slots: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / SLOTS_FILENAME
    tmp = target.with_name(f"{SLOTS_FILENAME}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(slots, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def append_run(directory: Path, entry: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / RUNS_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def public_state(slots: dict[str, Any], bound: bool) -> dict[str, Any]:
    """页面要的形状。「已经发生的事」给新的在前，页面按顺序露头三条。"""
    anchor = slots.get("anchor") or {}
    happened = list(slots.get("happened") or [])
    return {
        "bound": bound,
        "anchor": anchor.get("text"),
        "now": slots.get("now") or "",
        "decision": slots.get("decision") or "",
        "output": slots.get("output") or "",
        "happened": list(reversed(happened)),
        "updated_at": slots.get("updated_at"),
        "model": slots.get("model"),
        "status": "unbound" if not bound else slots.get("status") or "empty",
        "status_detail": None if not bound else slots.get("status_detail"),
    }


def load_public_state(session_id: str) -> dict[str, Any]:
    """右栏打开或切回一场会话时读这一份，不靠离开期间收到的推送。"""
    from frago.session.record_reader import detect_family

    family = detect_family(session_id)
    slots = load_slots(session_dir(session_id, family), session_id, family)
    return public_state(slots, observer_bound())


def observer_bound() -> bool:
    from frago.init.profile_manager import OBSERVER_ROLE, role_binding_id

    try:
        return role_binding_id(OBSERVER_ROLE) is not None
    except Exception:  # noqa: BLE001 — 读不了设置就当没绑，不让右栏因此报错
        return False


# ── 从会话记录里取什么 ────────────────────────────────────────────────────


def human_text(record: UnifiedRecord) -> str | None:
    """这条是不是人亲口说的话；是就返回剥掉 frago 注入之后的原话。

    同样落在「人说的话」这一档里的，还有三种不是人说的：工具结果、frago 定时唤醒 PA 的
    唤醒词、opencode 把 hook 注入包在人话前面的那一段。
    """
    from frago.session.opencode_store import strip_hook_injection
    from frago.session.session_index import _is_wake_prompt

    if record.kind != "user.say" or record.payload.get("is_tool_result"):
        return None
    if _is_wake_prompt(record):
        return None
    text = record.payload.get("text")
    if not isinstance(text, str):
        return None
    return strip_hook_injection(text) or None


def is_heartbeat_batch(records: Sequence[UnifiedRecord]) -> bool:
    """这一段是不是只有 frago 定时唤醒 PA、agent 回一句空话。

    判据跟会话列表用的是同一条：唤醒词是 frago 自己写的。中间调过工具就是真干了活，不算。
    """
    from frago.session.session_index import _is_wake_prompt

    users = [
        r for r in records if r.kind == "user.say" and not r.payload.get("is_tool_result")
    ]
    if not users or not all(_is_wake_prompt(u) for u in users):
        return False
    return not any(r.kind in ("tool.call", "subagent.dispatch") for r in records)


def _clip(text: Any, limit: int) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[:limit] + "…"


def _tool_target(args: Any) -> str:
    if isinstance(args, dict):
        for key in (
            "command",
            "file_path",
            "path",
            "notebook_path",
            "url",
            "pattern",
            "query",
            "skill",
            "description",
            "prompt",
        ):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return _clip(value, 160)
        return _clip(json.dumps(args, ensure_ascii=False), 120) if args else ""
    return _clip(args, 120) if args else ""


def _todo_line(items: Any) -> str | None:
    # 只给做完的和正在做的。还没开始的那些正是右栏禁止出现的「还没发生的步骤」，喂进去
    # 就等于请模型把它们抄出来。
    done: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if status in ("completed", "in_progress"):
            label = "做完" if status == "completed" else "在做"
            done.append(f"{_clip(item.get('content') or '', 60)}（{label}）")
    return "[待办] " + "；".join(done) if done else None


def record_line(record: UnifiedRecord) -> str | None:
    """一条记录喂给模型时的样子。不取的几类返回 None。

    不取：agent 的思考（大量是空的，推理加密没落盘）、工具结果正文（体积最大、信息最少）、
    引擎注入的内容、模型调用边界标记、会话状态变更。
    """
    p = record.payload
    kind = record.kind
    if kind == "user.say":
        text = human_text(record)
        return f"[人·第{record.seq}条] {_clip(text, 800)}" if text else None
    if kind == "agent.say":
        text = p.get("text")
        return f"[agent] {_clip(text, 600)}" if isinstance(text, str) and text.strip() else None
    if kind == "tool.call":
        return f"[工具] {p.get('tool_name') or '?'} {_tool_target(p.get('args'))}".rstrip()
    if kind == "subagent.dispatch":
        return f"[派子 agent] {_tool_target(p)}".rstrip()
    if kind == "todo.snapshot":
        # 引擎被动重发的那种一个字都没改，跳过。
        return None if p.get("source") == "engine-reminder" else _todo_line(p.get("items"))
    if kind == "error":
        return f"[报错] {p.get('scope') or ''} {p.get('code') or ''} {_clip(p.get('message') or '', 200)}"
    if kind == "interrupt":
        return "[人按了打断]"
    if kind == "permission.outcome":
        return f"[权限] {p.get('decision') or ''} {p.get('reason') or ''}".rstrip()
    if kind == "context.compact":
        return "[上下文被压缩]"
    if kind == "media.attach":
        return "[附件]"
    return None


def build_prompt(
    slots: dict[str, Any],
    fed: Sequence[UnifiedRecord],
    dropped: int,
    candidates: dict[int, str],
) -> str:
    anchor = (slots.get("anchor") or {}).get("text")
    happened = list(slots.get("happened") or [])[-8:]
    lines = [
        "## 当前右栏",
        f"- 这场在做什么（人的原话）：{_clip(anchor, 300) if anchor else EMPTY_MARK}",
        f"- 此刻在做什么：{slots.get('now') or EMPTY_MARK}",
        f"- 需要你决策：{slots.get('decision') or NONE_MARK}",
        f"- 最近一次产出：{slots.get('output') or NONE_MARK}",
        "- 已经发生的事（最近几条，从旧到新）：",
    ]
    lines += [f"  - {h}" for h in happened] or [f"  - {EMPTY_MARK}"]
    shown = [line for line in (record_line(r) for r in fed) if line]
    head = f"## 这一段新增的会话记录（{len(shown)} 条"
    head += f"；更早的 {dropped} 条太多，没给）" if dropped else "）"
    lines += ["", head]
    lines += shown or [NOTHING_TO_READ]
    lines += ["", "## 这一段里人说过的话（换目标时 anchor_seq 只能填这里的编号）"]
    lines += [f"- 第 {seq} 条：{_clip(text, 200)}" for seq, text in candidates.items()] or [
        f"- {NOBODY_SPOKE}"
    ]
    return "\n".join(lines)


# ── 模型的回答 ────────────────────────────────────────────────────────────


def parse_answer(text: str) -> dict[str, Any]:
    """从回答里取出那个 JSON 对象，整理成固定的五个字段。

    容忍代码块围栏和前后多出来的话；取不出对象就是没答对，抛 ValueError。
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("回答里没有 JSON 对象")
    obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise ValueError("回答不是一个 JSON 对象")

    def field(key: str) -> str:
        value = obj.get(key)
        return _unplaceholder(value.strip()) if isinstance(value, str) else ""

    adds = obj.get("happened_add")
    happened = (
        [a.strip() for a in adds if isinstance(a, str) and _unplaceholder(a.strip())]
        if isinstance(adds, list)
        else []
    )
    seq = obj.get("anchor_seq")
    return {
        "now": field("now"),
        "decision": field("decision"),
        "output": field("output"),
        "happened_add": happened[:HAPPENED_PER_RUN],
        "anchor_seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
    }


def violation(answer: dict[str, Any]) -> str | None:
    """回答里有没有犯禁令。有就说出犯在哪一格、犯了什么。"""
    plain = [("此刻在做什么", answer["now"]), ("最近一次产出", answer["output"])]
    plain += [("已经发生的事", h) for h in answer["happened_add"]]
    for name, text in plain + [("需要你决策", answer["decision"])]:
        for pattern, why in _ALWAYS_BANNED:
            if pattern.search(text):
                return f"「{name}」里出现了{why}：{_clip(text, 60)}"
    for name, text in plain:
        for pattern, why in _FUTURE_BANNED:
            if pattern.search(text):
                return f"「{name}」里出现了{why}：{_clip(text, 60)}"
    return None


def _content(slots: dict[str, Any]) -> str:
    keys = ("anchor", "now", "decision", "output", "happened")
    return json.dumps({k: slots.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)


def apply_answer(
    slots: dict[str, Any], answer: dict[str, Any], candidates: dict[int, str]
) -> bool:
    """把回答合进槽位，返回槽位是否真的变了。

    - 此刻在做什么：有新值就盖掉。
    - 需要你决策：照回答写，空串就是没有待决——人答过了，这一格就该清掉。
    - 最近一次产出：空串表示这一段没有新产出，沿用上一次。
    - 已经发生的事：只追加，跟最近几条重复的不加。
    - 锚：只认这一段里人说过的话的编号；指别的编号当没指。
    """
    before = _content(slots)
    if answer["now"]:
        slots["now"] = answer["now"]
    slots["decision"] = answer["decision"]
    if answer["output"]:
        slots["output"] = answer["output"]
    happened = list(slots.get("happened") or [])
    for item in answer["happened_add"]:
        if item not in happened[-20:]:
            happened.append(item)
    slots["happened"] = happened[-HAPPENED_KEEP:]
    seq = answer["anchor_seq"]
    current = (slots.get("anchor") or {}).get("seq")
    if seq is not None and seq in candidates and seq != current:
        slots["anchor"] = {"seq": seq, "text": candidates[seq]}
    return _content(slots) != before


# ── 服务 ──────────────────────────────────────────────────────────────────


@dataclass
class _Lane:
    running: bool = False
    #: 跑着的时候又来了触发，记下最后一次的原因。多次触发并成一次：下一次本来就会读到
    #: 游标之后的全部新增，不丢东西。
    owed: str | None = None


AskFn = Callable[[str], dict]
ReadFn = Callable[..., list]


class SessionObserver:
    """每场会话一条队列的旁路观察。

    ``ask`` / ``read_records`` / ``bound`` / ``base_dir`` 可以换成假的，测试靠它们不碰真的
    frago-core、真的会话和真的设置。
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        ask: AskFn | None = None,
        read_records: ReadFn | None = None,
        bound: Callable[[], bool] | None = None,
        base_dir: Callable[[str, str], Path] | None = None,
        detect_family: Callable[[str], str] | None = None,
        max_workers: int = 4,
    ) -> None:
        from frago.session import record_reader

        self._loop = loop
        self._ask = ask or self._ask_frago_core
        self._read = read_records or record_reader.read_records
        self._bound = bound or observer_bound
        self._dir = base_dir or session_dir
        self._family = detect_family or record_reader.detect_family
        self._lanes: dict[str, _Lane] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="observer")
        self._procs: set[subprocess.Popen] = set()
        self._closed = False
        self._ask_support: dict[str, tuple[float, int, bool]] = {}

    # ---- 投任务 ---------------------------------------------------------

    def notify(self, session_id: str, trigger: str) -> None:
        """投一个任务就走。从监听线上调，NEVER 在这里等模型。"""
        with self._lock:
            if self._closed:
                return
            lane = self._lanes.setdefault(session_id, _Lane())
            if lane.running:
                lane.owed = trigger
                return
            lane.running = True
        try:
            self._pool.submit(self._drain, session_id, trigger)
        except RuntimeError:
            # 服务正在停，执行位已经收了。
            with self._lock:
                lane.running = False

    def _drain(self, session_id: str, trigger: str) -> None:
        while True:
            try:
                self.run_once(session_id, trigger)
            except Exception:  # noqa: BLE001 — 一场会话出错不能把这条队列卡死
                logger.exception("observer run failed (session=%s)", session_id)
            with self._lock:
                lane = self._lanes[session_id]
                if lane.owed is None or self._closed:
                    lane.running = False
                    return
                trigger, lane.owed = lane.owed, None

    # ---- 跑一次 ---------------------------------------------------------

    def run_once(self, session_id: str, trigger: str) -> dict[str, Any]:
        """读新增记录、问一次、写槽位。返回写进执行记录的那一行，测试直接看它。"""
        started = time.monotonic()
        if not self._bound():
            # 没绑不写任何文件：一场只是被点开看了一眼的会话，不该因此多出一个目录。
            return {"skipped": "unbound", "trigger": trigger}

        family = self._family(session_id)
        directory = self._dir(session_id, family)
        slots = load_slots(directory, session_id, family)
        cursor = int(slots.get("cursor") or 0)
        entry: dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "trigger": trigger,
            "cursor_from": cursor,
        }

        new, total = self._read_after(session_id, cursor)
        if not new:
            entry.update(skipped="nothing-new", dur_ms=_ms(started))
            return entry
        entry["records"] = total
        last_seq = new[-1].seq

        if is_heartbeat_batch(new):
            slots["cursor"] = last_seq + 1
            save_slots(directory, slots)
            entry.update(skipped="pa-heartbeat", cursor_to=last_seq + 1, dur_ms=_ms(started))
            append_run(directory, entry)
            return entry

        if slots.get("anchor") is None:
            first = self._first_human(session_id)
            if first is not None:
                slots["anchor"] = {"seq": first[0], "text": first[1]}

        candidates: dict[int, str] = {}
        for record in new:
            text = human_text(record)
            if text:
                candidates[record.seq] = text
        prompt = build_prompt(slots, new, total - len(new), candidates)
        entry["fed"] = len(new)

        reply = self._ask(prompt)
        entry["model"] = reply.get("model")
        if not reply.get("ok"):
            # 没问到就不挪游标：下一次连同这一段一起再问，东西不丢。积压有 BACKLOG_CAP 兜着。
            slots["status"] = "failed"
            slots["status_detail"] = reply.get("error") or "没问到"
            self._save_if_alive(session_id, directory, slots)
            entry.update(error=reply.get("error"), kind=reply.get("kind"), dur_ms=_ms(started))
            append_run(directory, entry)
            self._push(session_id, slots)
            return entry

        try:
            answer = parse_answer(reply.get("text") or "")
            why = violation(answer)
        except ValueError as exc:
            answer, why = None, f"回答不是约定的格式：{exc}"
        slots["cursor"] = last_seq + 1
        entry["cursor_to"] = last_seq + 1
        if answer is None or why:
            # 答了但不合规矩：整份作废，槽位保持原样；游标照样往前，免得同一段反复踩同一个坑。
            entry.update(rejected=why, changed=False)
            changed = False
        else:
            changed = apply_answer(slots, answer, candidates)
            entry["changed"] = changed
        slots["status"] = "ok"
        slots["status_detail"] = None
        slots["model"] = reply.get("model")
        if changed:
            slots["updated_at"] = int(time.time() * 1000)
        if not self._save_if_alive(session_id, directory, slots):
            entry.update(skipped="session-gone", dur_ms=_ms(started))
            return entry
        entry["dur_ms"] = _ms(started)
        append_run(directory, entry)
        self._push(session_id, slots)
        return entry

    def _read_after(self, session_id: str, cursor: int) -> tuple[list[UnifiedRecord], int]:
        """游标之后的新增记录：只留最后 BACKLOG_CAP 条，另外报总共有多少。

        游标比整场的末尾还靠后，说明会话被重新解析过、序号变了——这时退回到末尾往前
        BACKLOG_CAP 条重读，而不是永远读空。
        """
        kept: deque[UnifiedRecord] = deque(maxlen=BACKLOG_CAP)
        total = 0
        after = cursor
        while True:
            batch = self._read(session_id, after=after, limit=PAGE)
            if not batch:
                break
            kept.extend(batch)
            total += len(batch)
            if len(batch) < PAGE:
                break
            after = batch[-1].seq + 1
        if total == 0 and cursor > 0:
            tail = self._read(session_id, tail=True, limit=1)
            if tail and tail[-1].seq + 1 < cursor:
                return self._read_after(session_id, max(0, tail[-1].seq + 1 - BACKLOG_CAP))
        return list(kept), total

    def _first_human(self, session_id: str) -> tuple[int, str] | None:
        after = 0
        for _ in range(ANCHOR_SCAN_PAGES):
            batch = self._read(session_id, after=after, limit=PAGE)
            for record in batch:
                text = human_text(record)
                if text:
                    return record.seq, text
            if len(batch) < PAGE:
                return None
            after = batch[-1].seq + 1
        return None

    def _save_if_alive(self, session_id: str, directory: Path, slots: dict[str, Any]) -> bool:
        """会话还在才写。调用回来时会话已经没了，就丢掉这次结果——这是唯一的孤儿处理。"""
        try:
            alive = bool(self._read(session_id, tail=True, limit=1))
        except Exception:  # noqa: BLE001
            alive = False
        if not alive:
            return False
        save_slots(directory, slots)
        return True

    # ---- 问 frago-core --------------------------------------------------

    def _ask_frago_core(self, prompt: str) -> dict:
        from frago.init.hook_binary import get_hook_binary_path

        binary = get_hook_binary_path()
        if not self._supports_ask(binary):
            return {
                "ok": False,
                "kind": "binary",
                "error": "装着的 frago-core 还没有 ask 入口，旁路 AI 用不了；升级 frago 后恢复",
            }
        argv = [
            binary,
            "ask",
            "--role",
            "observer",
            "--instructions",
            INSTRUCTIONS_FILE,
            "--timeout-ms",
            str(ASK_TIMEOUT_MS),
            "--max-tokens",
            str(ASK_MAX_TOKENS),
        ]
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            return {"ok": False, "kind": "binary", "error": f"起不来 frago-core：{exc}"}
        with self._lock:
            self._procs.add(proc)
        try:
            out, _err = proc.communicate(prompt, timeout=PROCESS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return {"ok": False, "kind": "read", "error": "frago-core 超时没回来"}
        finally:
            with self._lock:
                self._procs.discard(proc)
        line = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
        try:
            reply = json.loads(line)
        except ValueError:
            return {"ok": False, "kind": "binary", "error": "frago-core 的输出不是约定的 JSON"}
        return reply if isinstance(reply, dict) else {"ok": False, "error": "frago-core 输出形状不对"}

    def _supports_ask(self, binary: str) -> bool:
        """装着的 frago-core 有没有 ask 入口。

        NEVER 省掉这一步：旧版遇到不认识的第一个参数会进入带工具的完整 agent 循环，
        对它调 ``frago-core ask`` 等于在这台机器上起了一个会动手的 agent。按文件大小和
        修改时刻记住结论，换了二进制就重查。
        """
        try:
            st = os.stat(binary)
        except OSError:
            return False
        cached = self._ask_support.get(binary)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return cached[2]
        try:
            out = subprocess.run(
                [binary, "--help"], capture_output=True, text=True, timeout=10
            ).stdout
            ok = "frago-core ask" in out
        except (OSError, subprocess.SubprocessError):
            ok = False
        self._ask_support[binary] = (st.st_mtime, st.st_size, ok)
        return ok

    # ---- 推给页面 -------------------------------------------------------

    def _push(self, session_id: str, slots: dict[str, Any]) -> None:
        if self._loop is None:
            return
        from frago.server.websocket import create_message, manager

        message = create_message(
            WS_OBSERVER_UPDATE,
            {"session_id": session_id, "state": public_state(slots, True)},
        )
        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(manager.broadcast(message), self._loop)

    # ---- 停 -------------------------------------------------------------

    def shutdown(self) -> None:
        """服务停下时一起停：还在跑的 frago-core 直接收掉，排着的任务不再开。"""
        with self._lock:
            self._closed = True
            procs = list(self._procs)
        for proc in procs:
            with contextlib.suppress(OSError):
                proc.kill()
        self._pool.shutdown(wait=False, cancel_futures=True)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


_instance: SessionObserver | None = None
_instance_lock = threading.Lock()


def get_observer(loop: asyncio.AbstractEventLoop | None = None) -> SessionObserver:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SessionObserver(loop)
        elif loop is not None and _instance._loop is None:
            _instance._loop = loop
        return _instance


def reset_observer() -> None:
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.shutdown()
            _instance = None
