"""会话页右栏的旁路观察。

方案见 ``~/.frago/data/frago-dev/20260909-session-observer-research/plan.md``。

## 它不是一个活着的东西

旁路 AI 不常驻。会话流里四件事发生时——人发来一句话、agent 把话交还给人、人按了打断、
这场会话在页面上第一次被打开——往这场会话自己的队列里投一个任务。任务读游标之后的新增
记录，问一次 frago-core，把回答写进槽位文件，推给页面，结束。没有进程要看管，也就没有孤
儿；服务重启后游标还在槽位文件里，下次打开时一次补上。

前四件事全都要有人在看着（监听只跟着 tmux 里的会话走），于是长跑会话没人看的时候，右栏
一直是空的：语料里 29 次观察运行全部由「打开页面」触发，122 场里 101 场从没人打开过。
现在多一个来由——``CADENCE``（见 :mod:`frago.server.services.session_watchdog`）：会话还
开着、屏上还在干活时按节拍自己投一次，不看有没有人开着页面。触发名只影响说明书里那一句
「这一段截在干活途中」，与 ``WORKING`` 同一处境。

人那句话一到就跑一次，是因为「这场在做什么」「此刻在做什么」说的都是眼下：只等一轮结束
才更新，人刚下的指令要整整等一轮才出现在右栏，而那一刻正是他最想看右栏的时候。

agent 干活途中也叫，但离上次叫满 ``WORKING_GAP_S`` 才叫一次。不叫的话，一轮干十分钟，
「此刻」就停在「人提出了什么、agent 还没回话」十分钟，一轮结束直接跳成产出——人永远看
不到 agent 正在做什么（2026-09-18 实测：16:50 到 16:59 那一轮，末条一动没动）。

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
#:
#: 2 起「此刻在做什么」「最近一次产出」并成一个末条。1 版能就地转过来（见
#: ``_from_v1``），不必从头重算。
SLOTS_VERSION = 2

#: 末条的两种状态。
TAIL_NOW = "now"
TAIL_OUTPUT = "output"
TAIL_KINDS = (TAIL_NOW, TAIL_OUTPUT)

#: 事项总控表状态枚举。
TASK_STATUS_DOING = "doing"
TASK_STATUS_WAITING = "waiting"
TASK_STATUS_DONE = "done"
TASK_STATUS_BLOCKED = "blocked"
TASK_STATUSES = (
    TASK_STATUS_DOING,
    TASK_STATUS_WAITING,
    TASK_STATUS_DONE,
    TASK_STATUS_BLOCKED,
)
TASK_STATUS_SET = frozenset(TASK_STATUSES)
TASKS_KEEP = 50
TASK_UPSERTS_PER_RUN = 5

#: agent 干活途中叫旁路 AI 的最短间隔（秒）。离上一次跑还不到这么久，这一批就不叫。
WORKING_GAP_S = 60
WORKING = "working"
#: 没人看页面时按节拍叫一次的来由（见 ``session_watchdog``）。与 WORKING 同一处境——
#: 截的都是 agent 干活途中，只是这一次不是新记录把它招来的。
CADENCE = "cadence"
#: 默认每攒够多少个已发生对话块（人发言或 agent 回复）就成组触发一次总结。
BATCH_BLOCK_COUNT = 3
#: 会话停下但游标后已发生对话块还凑不够 BATCH_BLOCK_COUNT 时的时间兜底（秒）。
SETTLE_TIMEOUT_S = 10.0
BATCH_TRIGGER = "batch"
SETTLE_TRIGGER = "settle"

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
#: Watcher 视图里最多保留多少段游标总结。
RUNS_KEEP = 100

ASK_TIMEOUT_MS = 30_000
ASK_MAX_TOKENS = 1_500
#: 等 frago-core 的墙钟上限，比它自己的期限多留几秒给进程起落。
PROCESS_TIMEOUT_S = ASK_TIMEOUT_MS / 1000 + 10

#: 家族 → 备份目录名，与各家同步程序写 ``raw.jsonl`` 的落点一致。
#:
#: **CoreAgent 也要在这里。** 它的会话记录另有根（``~/.frago/coreagent/sessions/``），但槽位
#: 与标注是 frago 服务端自己产的旁挂文件，与另外三家同级存放——少这一格，``session_dir``
#: 当场抛 ``KeyError``，那一家的右栏和标注一律打不开（2026-09-29 实测：接口回 500）。
_FAMILY_DIR = {
    "claude-code": "claude",
    "opencode": "opencode",
    "codex": "codex",
    "coreagent": "coreagent",
    "agy": "agy",
}

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
CARD_ANSWER_PREFIX = "【answer】"


def _unplaceholder(text: str) -> str:
    return "" if text.strip() in _PLACEHOLDERS else text


def is_card_answer_text(text: Any) -> bool:
    """是不是人点击交互卡片发出的固定回执（以 ``【answer】`` 开头）。

    它是对上一轮待拍板问题的答复，算人开了口（用于清掉已答的 ``decision``），但绝不是整场
    会话的新总目标，不能进 ``anchor_seq`` 候选，也不能覆盖 ``anchor``。
    """
    return isinstance(text, str) and text.lstrip().startswith(CARD_ANSWER_PREFIX)


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
        # 上一次读到的那条记录的编号（身份）。**seq 会动**：整场会话每次都是重新编号的，
        # 引擎重写一条记录（例如每轮的花费账本只留最后一条）就会让它后面所有记录的编号
        # 往前挪一格。只记编号，编号一动就认不出「上次读到哪」了。
        "cursor_id": None,
        # {"seq": 这句人话的记录序号, "text": 原话}，还没找到时为 None。
        "anchor": None,
        # 当前所处阶段的目标（可随人新指令或 agent 阶段推进演进，不覆盖首句 anchor）。
        "phase_goal": "",
        # 「已经发生的事」的最后一条，也就是眼下的状态：{"kind": "now" | "output", "text": …}。
        # agent 在做就是「此刻」，东西落地了就是「产出」；产出被下一个状态顶掉时退进
        # happened，此刻被顶掉就不留（做完的事由 happened 记）。
        "tail": None,
        "decision": "",
        # 从旧到新。
        "happened": [],
        # 每一格自己上次变样的时刻（毫秒）。整份只记一个总的更新时刻不够用：右栏是按
        # 时间线读的，人要分得出哪一格是刚刚变的、哪一格半小时前就停在那儿了。老的槽位
        # 文件里没有这几格，读出来是 None，那几格照常显示，只是暂时不带时间。
        "anchor_at": None,
        "phase_goal_at": None,
        "tail_at": None,
        "decision_at": None,
        # 跟 happened 一一对齐，同样从旧到新。
        "happened_at": [],
        # 事项总控表（大助理汇报进度表第一张表）：每条含 id / proposed_at / updated_at / title / status / actor / conclusion。
        "tasks": [],
        # 按游标区间保存的每次定期 observer 总结（从旧到新），供中栏 Watcher 视图包裹对应 Talk 片段。
        "runs": [],
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
    if isinstance(data, dict) and data.get("version") == 1:
        data = _from_v1(data)
    if not isinstance(data, dict) or data.get("version") != SLOTS_VERSION:
        return empty_slots(session_id, family)
    base = empty_slots(session_id, family)
    base.update({k: v for k, v in data.items() if k in base})
    return base


def _from_v1(data: dict[str, Any]) -> dict[str, Any]:
    """1 版槽位就地转成 2 版。

    末条取「此刻」「产出」里后变样的那一个；两个都没时刻时，有产出取产出。另一个丢掉：
    旧文件里的「此刻」说的是过程，做完的事 happened 里已经记着；被压下去的那份产出，
    按 1 版的写法它本来也只是一格覆盖型的内容，没进过 happened。happened 原样保留，
    游标也不动——不从头重算，免得每场会话再问一遍模型。
    """
    out = dict(data)
    now, output = data.get("now") or "", data.get("output") or ""
    now_at, output_at = data.get("now_at"), data.get("output_at")
    if output and (not now or (output_at or 0) >= (now_at or 0)):
        tail, at = {"kind": TAIL_OUTPUT, "text": output}, output_at
    elif now:
        tail, at = {"kind": TAIL_NOW, "text": now}, now_at
    else:
        tail, at = None, None
    for key in ("now", "output", "now_at", "output_at"):
        out.pop(key, None)
    out.update(version=SLOTS_VERSION, tail=tail, tail_at=at)
    return out


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


def _clean_tail_text(text: str) -> str:
    s = re.sub(r"^\[(?:此刻|产出)\]\s*", "", text.strip())
    s = re.sub(r"。\s*[；;]+", "。", s)
    return s.strip("；; ")


def _join_clauses(items: Sequence[str]) -> str:
    cleaned = [_clean_tail_text(x) for x in items if _clean_tail_text(x)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return "；".join(x.rstrip("。；;") for x in cleaned)


_LEADING_IMAGE_TAG_RE = re.compile(
    r"^\s*(?:<image\b[^>]*>[\s\S]*?</image>\s*|<image\b[^>]*/>\s*)+",
    re.IGNORECASE,
)
_LEADING_ASYNC_CALLBACK_RE = re.compile(
    r"^\s*(?:<frago-async-callback\b[^>]*>[\s\S]*?</frago-async-callback>\s*)+"
)
_ATTACHMENT_BLOCK_RE = re.compile(
    r"(?:^|\r?\n{1,2})\[附带(?:图片，请用读文件的工具逐一打开查看|文档，请用读文件的工具逐一打开阅读)\]:\r?\n[\s\S]*?(?=\r?\n\s*\r?\n|\Z)"
)
_ROLE_PREAMBLE_RE = re.compile(
    r"^(?:你是[^\n。！？]*?(?:专家|导演|开发者|管理员|助手|参谋)|先运行以下命令|frago\s+book\b|请用读文件的?工具|请查看以下(?:图片|附件)|Spec\s*内容（位于|用户需求[：:]?$)"
)


def _strip_goal_scaffolding(text: str, *, strip_attachments: bool = True) -> str:
    """剥离消息头尾的系统注入脚手架（<image>/<frago-employee>/<must-use-skill>/<frago-async-callback>/附带附件清单）。"""
    from frago.session.session_index import split_employee_block
    from frago.skills.skill_prompt import split_skill_blocks

    current = text.strip()
    for _ in range(6):
        prev = current
        current = _LEADING_IMAGE_TAG_RE.sub("", current).strip()
        _, current = split_employee_block(current)
        _, current = split_skill_blocks(current)
        current = _LEADING_ASYNC_CALLBACK_RE.sub("", current).strip()
        if current == prev:
            break
    if strip_attachments:
        current = _ATTACHMENT_BLOCK_RE.sub("", current)
        current = re.sub(r"\r?\n{3,}", "\n\n", current)
    return current.strip()


def _safe_goal_text(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = _strip_goal_scaffolding(text, strip_attachments=True)
    if not cleaned or is_card_answer_text(cleaned):
        return None
    return cleaned


def extract_goal_summary(text: str | None, limit: int = 180) -> str:
    """从清洗后的长 Prompt / 任务书中提炼北极星核心目标摘要，短文本原样返回。"""
    if not isinstance(text, str):
        return ""
    cleaned = _strip_goal_scaffolding(text, strip_attachments=True)
    if not cleaned:
        return ""

    non_empty_lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    if len(cleaned) <= 110 and len(non_empty_lines) <= 3 and not any(
        ln.startswith("#") for ln in non_empty_lines
    ):
        return cleaned

    title = ""
    task_line = ""
    lead = ""

    for ln in non_empty_lines:
        m_named = re.match(r"^#{1,3}\s*((?:任务书|任务|目标)[：:]\s*.+)$", ln)
        if m_named:
            title = re.sub(r"\s+", " ", m_named.group(1)).strip()
            break
        if not title:
            m_h1 = re.match(r"^#\s+(.+)$", ln)
            if m_h1:
                cand = re.sub(r"\s+", " ", m_h1.group(1)).strip()
                if len(cand) >= 3:
                    title = cand

    for ln in non_empty_lines:
        m_task = re.match(r"^(?:任务|Task)[：:]\s*(.+)$", ln)
        if m_task:
            cand = re.sub(r"\s+", " ", m_task.group(1)).strip()
            if cand and cand not in title:
                task_line = f"任务：{cand}" if not cand.startswith("任务") else cand
                break

    in_code_fence = False
    lead_lines: list[str] = []
    for raw_ln in cleaned.splitlines():
        ln = raw_ln.strip()
        if ln.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence or not ln:
            continue
        if ln.startswith("#") or ln.startswith(">") or re.match(r"^[-*_]{3,}$", ln):
            continue
        if _ROLE_PREAMBLE_RE.match(ln):
            continue
        if task_line and ln in task_line:
            continue
        if title and ln in title:
            continue
        plain = re.sub(r"^[-*+]\s+", "", ln).strip()
        if len(plain) < 4:
            continue
        if (title or task_line) and plain.endswith((":", "：")):
            continue
        lead_lines.append(re.sub(r"\s+", " ", plain))
        if title or task_line:
            break
        if sum(len(x) for x in lead_lines) >= limit:
            break
    lead = " ".join(lead_lines).strip()

    parts: list[str] = []
    if title:
        parts.append(title)
    if task_line and task_line not in parts and (not title or task_line not in title):
        parts.append(task_line)
    if lead and not any(lead in p or p in lead for p in parts):
        parts.append(lead)

    if not parts:
        return _clip(cleaned, limit)
    joined = "\n".join(parts)
    if len(joined) <= limit:
        return joined
    if len(parts) >= 2 and len(parts[0]) < limit - 20:
        remain = limit - len(parts[0]) - 1
        return f"{parts[0]}\n{_clip(parts[1], remain)}"
    return _clip(joined, limit)


def _derive_doing_and_findings(
    tail: dict[str, Any] | None,
    happened_add: Sequence[str],
) -> tuple[str, list[str]]:
    tail_kind = (tail or {}).get("kind")
    tail_text = _clean_tail_text((tail or {}).get("text") or "")
    items: list[str] = []
    for item in happened_add:
        cleaned = _clean_tail_text(item or "")
        if cleaned and cleaned not in items:
            items.append(cleaned)

    doing = ""
    findings: list[str] = []
    if tail_kind == TAIL_NOW and tail_text:
        doing = tail_text
        findings = [x for x in items if x != tail_text]
    elif tail_kind == TAIL_OUTPUT and tail_text:
        without_tail = [x for x in items if x != tail_text]
        if without_tail:
            doing = _join_clauses(without_tail)
        findings = [tail_text]
    elif items:
        doing = items[0]
        findings = items[1:]
    return doing, findings


def _compose_run_summary(
    tail: dict[str, Any] | None,
    happened_add: Sequence[str],
    decision: str,
    anchor_text: str | None = None,
    *,
    doing_override: str = "",
    findings_override: Sequence[str] = (),
) -> str:
    """按「三段式（当前在做什么 + 关键发现或产出 + 待拍板背景）」拼出单段 Watcher 通报正文。"""
    doing, findings = _derive_doing_and_findings(tail, happened_add)
    if doing_override:
        doing = _clean_tail_text(doing_override)
    if findings_override:
        cleaned_findings = [_clean_tail_text(x) for x in findings_override if _clean_tail_text(x)]
        if cleaned_findings:
            findings = cleaned_findings
    decision_text = _clean_tail_text(decision or "")

    lines: list[str] = []
    if doing:
        lines.append(f"当前在做什么：{doing}")
    if findings:
        lines.append(f"关键发现或产出：{_join_clauses(findings)}")
    if decision_text:
        lines.append(f"待拍板背景：{decision_text}")
    safe_anchor = _safe_goal_text(anchor_text)
    if not lines and safe_anchor:
        lines.append(f"当前在做什么：{safe_anchor}")
    return "\n".join(lines)


def _fallback_runs(slots: dict[str, Any]) -> list[dict[str, Any]]:
    """老槽位文件还没有 runs 数组时，按已有 happened 与 tail 兜底拼出一段游标总结。"""
    raw_anchor = slots.get("anchor")
    anchor = _safe_goal_text(
        raw_anchor.get("text") if isinstance(raw_anchor, dict) else raw_anchor
    )
    phase_goal = _safe_goal_text(slots.get("phase_goal")) or anchor
    happened = list(slots.get("happened") or [])
    tail = slots.get("tail") or None
    decision = slots.get("decision") or ""
    if not (tail or happened or decision or anchor or phase_goal):
        return []
    doing, findings = _derive_doing_and_findings(tail, happened[-3:])
    summary = _compose_run_summary(tail, happened[-3:], decision, anchor)
    if not summary:
        return []
    cursor_to = int(slots.get("cursor") or 0)
    at = slots.get("updated_at") or slots.get("tail_at") or slots.get("anchor_at")
    return [
        {
            "id": "run-fallback-1",
            "run_id": 1,
            "task_id": "T1",
            "actor": "主会话",
            "at": at,
            "cursor_from": 0,
            "cursor_to": cursor_to,
            "phase_goal": phase_goal,
            "doing": doing or _clean_tail_text(phase_goal or anchor or ""),
            "findings": findings,
            "tail": tail,
            "happened_add": happened[-3:],
            "decision": decision,
            "summary": summary,
        }
    ]


def _normalize_task_item(raw: dict[str, Any], fallback_at: int | None = None) -> dict[str, Any]:
    tid = str(raw.get("id") or "T1").strip() or "T1"
    status = raw.get("status")
    if status not in TASK_STATUS_SET:
        status = TASK_STATUS_DOING
    proposed_at = raw.get("proposed_at")
    if not isinstance(proposed_at, int) or isinstance(proposed_at, bool):
        proposed_at = fallback_at
    updated_at = raw.get("updated_at")
    if not isinstance(updated_at, int) or isinstance(updated_at, bool):
        updated_at = proposed_at
    return {
        "id": tid,
        "proposed_at": proposed_at,
        "updated_at": updated_at,
        "title": str(raw.get("title") or "").strip(),
        "status": status,
        "actor": str(raw.get("actor") or "主会话").strip() or "主会话",
        "conclusion": str(raw.get("conclusion") or "").strip(),
    }


def _normalize_runs(raw_runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_runs):
        if not isinstance(raw, dict):
            continue
        run = dict(raw)
        run["run_id"] = (
            raw.get("run_id")
            if isinstance(raw.get("run_id"), int) and not isinstance(raw.get("run_id"), bool)
            else idx + 1
        )
        run["task_id"] = str(raw.get("task_id") or f"T{idx + 1}").strip() or f"T{idx + 1}"
        run["actor"] = str(raw.get("actor") or "主会话").strip() or "主会话"
        tail = raw.get("tail") if isinstance(raw.get("tail"), dict) else None
        happened_add = raw.get("happened_add") if isinstance(raw.get("happened_add"), list) else []
        derived_doing, derived_findings = _derive_doing_and_findings(tail, happened_add)
        raw_doing = raw.get("doing")
        if isinstance(raw_doing, str) and raw_doing.strip():
            run["doing"] = raw_doing.strip()
        elif derived_doing:
            run["doing"] = derived_doing
        else:
            run["doing"] = _clean_tail_text(str(raw.get("summary") or ""))
        raw_findings = raw.get("findings")
        if isinstance(raw_findings, list) and any(isinstance(x, str) and x.strip() for x in raw_findings):
            run["findings"] = [x.strip() for x in raw_findings if isinstance(x, str) and x.strip()]
        else:
            run["findings"] = derived_findings
        normalized.append(run)
    return normalized


def _synthesize_tasks(
    slots: dict[str, Any],
    runs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """磁盘旧 observer-slots.json 中 tasks 为空而 runs 非空时，从 runs + tail + decision 合成结构化 tasks。"""
    if not runs:
        return []
    raw_anchor = slots.get("anchor")
    anchor_text = _safe_goal_text(
        raw_anchor.get("text") if isinstance(raw_anchor, dict) else raw_anchor
    )
    fallback_ts = slots.get("anchor_at") or slots.get("updated_at") or slots.get("tail_at")
    tail = slots.get("tail") if isinstance(slots.get("tail"), dict) else None
    global_decision = _clean_tail_text(slots.get("decision") or "")

    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for idx, run in enumerate(runs):
        tid = str(run.get("task_id") or f"T{idx + 1}").strip() or f"T{idx + 1}"
        at = run.get("at")
        if not isinstance(at, int) or isinstance(at, bool):
            at = fallback_ts
        actor = str(run.get("actor") or "主会话").strip() or "主会话"
        phase_goal = _safe_goal_text(run.get("phase_goal"))
        doing = _clean_tail_text(str(run.get("doing") or ""))
        findings = [
            _clean_tail_text(str(f))
            for f in (run.get("findings") or [])
            if isinstance(f, str) and _clean_tail_text(str(f))
        ]
        run_tail = run.get("tail") if isinstance(run.get("tail"), dict) else None
        run_tail_text = _clean_tail_text((run_tail or {}).get("text") or "")
        run_decision = _clean_tail_text(str(run.get("decision") or ""))
        is_last = idx == len(runs) - 1

        conclusion = findings[-1] if findings else (run_tail_text or doing)
        if is_last and (global_decision or run_decision):
            status = TASK_STATUS_WAITING
        elif not is_last:
            status = TASK_STATUS_DONE
        elif (tail and tail.get("kind") == TAIL_OUTPUT) or (
            run_tail and run_tail.get("kind") == TAIL_OUTPUT
        ):
            status = TASK_STATUS_DONE
        else:
            status = TASK_STATUS_DOING

        title_src = phase_goal or anchor_text or doing or f"阶段 {tid}"
        title = _clip(title_src, 28) if len(title_src) > 28 else title_src
        concl = _clip(conclusion, 60) if len(conclusion) > 60 else conclusion

        if tid not in by_id:
            order.append(tid)
            by_id[tid] = {
                "id": tid,
                "proposed_at": at,
                "updated_at": at,
                "title": title,
                "status": status,
                "actor": actor,
                "conclusion": concl,
            }
        else:
            item = by_id[tid]
            if at is not None:
                item["updated_at"] = at
                if item["proposed_at"] is None:
                    item["proposed_at"] = at
            if title and not item["title"]:
                item["title"] = title
            item["status"] = status
            if actor:
                item["actor"] = actor
            if concl:
                item["conclusion"] = concl

    return [by_id[tid] for tid in order]


def _reconcile_decision_consistency(
    tasks: Sequence[dict[str, Any]],
    decision: Any,
) -> str:
    """本体不变量收敛：当事项总控表非空且没有任何待拍板（waiting）事项时，强制清空过期 decision。"""
    cleaned = _unplaceholder(decision.strip()) if isinstance(decision, str) else ""
    if not cleaned or cleaned.lower() in ("none", "null", "暂无"):
        return ""
    if tasks and not any(
        isinstance(t, dict) and t.get("status") == TASK_STATUS_WAITING for t in tasks
    ):
        return ""
    return cleaned


def public_state(slots: dict[str, Any], bound: bool) -> dict[str, Any]:
    """页面要的形状。「已经发生的事」给新的在前，页面按顺序露头三条。

    每一格带上它自己上次变样的时刻，右栏按时间线读要用。时刻跟着正文一起倒过来，免得
    第一条的时间落到最后一条头上。
    """
    raw_anchor = slots.get("anchor")
    anchor_text = _safe_goal_text(
        raw_anchor.get("text") if isinstance(raw_anchor, dict) else raw_anchor
    )
    phase_goal = _safe_goal_text(slots.get("phase_goal")) or anchor_text
    happened = list(slots.get("happened") or [])
    times = list(slots.get("happened_at") or [])
    times = [None] * max(0, len(happened) - len(times)) + times[: len(happened)]
    raw_runs = slots.get("runs")
    base_runs = list(raw_runs) if isinstance(raw_runs, list) and raw_runs else _fallback_runs(slots)
    runs = _normalize_runs(base_runs)
    raw_tasks = slots.get("tasks")
    fallback_at = slots.get("updated_at") or slots.get("tail_at") or slots.get("anchor_at")
    if isinstance(raw_tasks, list) and raw_tasks:
        tasks = [_normalize_task_item(t, fallback_at) for t in raw_tasks if isinstance(t, dict)]
    else:
        tasks = _synthesize_tasks(slots, runs)
    decision_out = _reconcile_decision_consistency(tasks, slots.get("decision"))
    return {
        "bound": bound,
        "anchor": anchor_text,
        "anchor_summary": extract_goal_summary(anchor_text) or None,
        "phase_goal": phase_goal,
        "tail": slots.get("tail") or None,
        "decision": decision_out,
        "happened": list(reversed(happened)),
        "happened_at": list(reversed(times)),
        "tasks": tasks,
        "runs": runs,
        "anchor_at": slots.get("anchor_at"),
        "phase_goal_at": slots.get("phase_goal_at") or slots.get("anchor_at"),
        "tail_at": slots.get("tail_at"),
        "decision_at": slots.get("decision_at"),
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
    """这条是不是人亲口说的话；是就返回剥掉 frago 注入之后的原话。"""
    if record.kind != "user.say":
        return None
    return spoken_text(record.payload)


def spoken_text(payload: Any) -> str | None:
    """一条 ``user.say`` 的正文，是不是人亲口说的。

    同样落在「人说的话」这一档里的，还有三种不是人说的：工具结果、frago 定时唤醒 PA 的
    唤醒词、opencode 把 hook 注入包在人话前面的那一段。

    按正文判而不是按记录判：实时监听那条线上，新来的那批还是字典（``asdict`` 过的统一
    记录），人刚发话时要在那里就问一句「这是不是人在说话」，那时还没有记录对象。
    """
    from frago.session.opencode_store import strip_hook_injection
    from frago.session.session_index import is_wake_text

    if not isinstance(payload, dict) or payload.get("is_tool_result"):
        return None
    text = payload.get("text")
    if is_wake_text(text) or not isinstance(text, str):
        return None
    stripped = strip_hook_injection(text)
    if not stripped:
        return None
    body = _strip_goal_scaffolding(stripped, strip_attachments=True)
    return body or None


def person_spoke(records: Sequence[Any]) -> bool:
    """这批新记录里有没有人亲口说话。"""
    return any(
        isinstance(record, dict)
        and record.get("kind") == "user.say"
        and spoken_text(record.get("payload")) is not None
        for record in records
    )


def agent_spoke(records: Sequence[Any]) -> bool:
    """这批记录里有没有 agent 已经产出的回复正文。"""
    for record in records:
        kind = record.get("kind") if isinstance(record, dict) else getattr(record, "kind", None)
        payload = (
            record.get("payload") if isinstance(record, dict) else getattr(record, "payload", None)
        )
        if kind == "agent.say" and isinstance(payload, dict):
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                return True
    return False


def is_substantive_block(record: Any) -> bool:
    """这条记录算不算 All 视图里「包含实质内容」的一个已发生块。

    涵盖：人的有效发言（``user.say``）、非空思考（``agent.think``）、工具调用（``tool.call``）、
    派发子 agent（``subagent.dispatch``）、AI 回复正文（``agent.say``）、有效待办（``todo.snapshot``）、
    报错（``error``）、权限结果（``permission.outcome``）、附件（``media.attach``）以及插话/任务通知。
    配对的 ``tool.result``、用量刻度 ``usage.tick``、调用边界 ``call.envelope`` 等记账条目不重复计数。
    """
    kind = record.get("kind") if isinstance(record, dict) else getattr(record, "kind", None)
    payload = (
        record.get("payload") if isinstance(record, dict) else getattr(record, "payload", None)
    )
    if not isinstance(payload, dict):
        payload = {}
    if kind == "user.say":
        return spoken_text(payload) is not None
    if kind in ("agent.say", "agent.think"):
        text = payload.get("text")
        return isinstance(text, str) and bool(text.strip())
    if kind in ("tool.call", "subagent.dispatch", "error", "permission.outcome", "media.attach"):
        return True
    if kind == "todo.snapshot":
        return (
            payload.get("source") != "engine-reminder"
            and _todo_line(payload.get("items")) is not None
        )
    if kind == "context.inject":
        return (
            payload.get("channel") == "queued_command"
            or payload.get("source") == "task-notification"
        )
    return False


def agent_acted(records: Sequence[Any]) -> bool:
    """这批记录里有没有 agent 产出的实质块（thinking、tool use、AI response 等）。"""
    for record in records:
        kind = record.get("kind") if isinstance(record, dict) else getattr(record, "kind", None)
        if kind != "user.say" and is_substantive_block(record):
            return True
    return False


def occurred_block_count(records: Sequence[Any]) -> int:
    """这批记录里包含实质内容的已发生块数量（涵盖 thinking、tool use、AI response、人发言等）。"""
    return sum(1 for record in records if is_substantive_block(record))


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


def _extract_decision_card(body: Any) -> dict[str, Any] | None:
    """从 tool.result 的输出里解析出 frago ask 交互卡（decision-card）的数据字典。"""
    if not isinstance(body, str) or '"frago_ui_component"' not in body:
        return None
    marker_idx = body.rfind('"frago_ui_component"')
    start = body.rfind("{", 0, marker_idx)
    if start < 0:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(body[start:])
    except ValueError:
        return None
    if not isinstance(parsed, dict) or parsed.get("frago_ui_component") != "decision-card":
        return None
    data = parsed.get("data")
    if not isinstance(data, dict):
        return None
    question = _clip(data.get("question") or "", 240)
    if not question:
        return None
    why = _clip(data.get("why") or "", 300)
    opts_raw = data.get("options")
    opts: list[str] = []
    if isinstance(opts_raw, list):
        for o in opts_raw:
            if isinstance(o, dict) and o.get("key") and o.get("label"):
                eff = f"（{o.get('effect')}）" if o.get("effect") else ""
                opts.append(_clip(f"{o.get('key')}·{o.get('label')}{eff}", 120))
    return {"question": question, "why": why, "options": opts}


def _decision_card_line(body: Any) -> str | None:
    """把 tool.result 里的 frago ask 交互卡格式化成一行给旁路 AI 读的文本。"""
    card = _extract_decision_card(body)
    if not card:
        return None
    parts = [f"问题：{card['question']}"]
    if card["why"]:
        parts.append(f"背景：{card['why']}")
    if card["options"]:
        parts.append(f"选项：{' / '.join(card['options'])}")
    return "[待拍板卡片] " + "；".join(parts)


def _trailing_unanswered_card_decision(records: Sequence[UnifiedRecord]) -> str:
    """若本段记录里发出了交互卡且直到段尾人都还没开口答复，提取兜底的待拍板背景。"""
    last_card: dict[str, Any] | None = None
    for r in records:
        if r.kind == "user.say" and human_text(r) is not None:
            last_card = None
            continue
        if r.kind == "tool.result" and r.payload.get("status") != "error":
            card = _extract_decision_card(r.payload.get("body"))
            if card:
                last_card = card
    if not last_card:
        return ""
    if last_card["why"]:
        return f"{last_card['question']}（{last_card['why']}）"
    return last_card["question"]


def record_line(record: UnifiedRecord) -> str | None:
    """一条记录喂给模型时的样子。不取的几类返回 None。

    不取：空思考（推理加密没落盘）、普通工具结果正文（体积最大、信息最少；仅取交互拍板卡）、
    引擎注入的内容、模型调用边界标记、会话状态变更、用量刻度（记账，不是这场在做什么）。
    """
    p = record.payload
    kind = record.kind
    if kind == "user.say":
        text = human_text(record)
        return f"[人·第{record.seq}条] {_clip(text, 800)}" if text else None
    if kind == "agent.think":
        text = p.get("text")
        return f"[思考] {_clip(text, 400)}" if isinstance(text, str) and text.strip() else None
    if kind == "agent.say":
        text = p.get("text")
        return f"[agent] {_clip(text, 600)}" if isinstance(text, str) and text.strip() else None
    if kind == "tool.call":
        return f"[工具] {p.get('tool_name') or '?'} {_tool_target(p.get('args'))}".rstrip()
    if kind == "tool.result":
        return None if p.get("status") == "error" else _decision_card_line(p.get("body"))
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


def showable(records: Sequence[UnifiedRecord]) -> list[str]:
    """这一批里真正给模型看的几行。

    一批新记录里大部分是给不出内容的（思考、工具结果、注入、调用边界），全过滤掉之后
    可能一行不剩。那种情况下**不能去问模型**：它看到的是一份空记录，只会如实回答「这
    一段什么都没有」，而那份空回答会盖掉右栏里本来有内容的格子。
    """
    return [line for line in (record_line(r) for r in records) if line]


_TAIL_LABEL = {TAIL_NOW: "此刻", TAIL_OUTPUT: "产出"}


def build_prompt(
    slots: dict[str, Any],
    fed: Sequence[UnifiedRecord],
    dropped: int,
    candidates: dict[int, str],
    trigger: str | None = None,
) -> str:
    raw_anchor = slots.get("anchor")
    anchor = _safe_goal_text(
        raw_anchor.get("text") if isinstance(raw_anchor, dict) else raw_anchor
    )
    phase_goal = _safe_goal_text(slots.get("phase_goal")) or anchor
    happened = list(slots.get("happened") or [])[-8:]
    tail = slots.get("tail") or {}
    tail_line = (
        f"[{_TAIL_LABEL.get(tail.get('kind'), '此刻')}] {tail.get('text')}"
        if tail.get("text")
        else EMPTY_MARK
    )
    anchor_prompt = extract_goal_summary(anchor, limit=280) if anchor else ""
    lines = [
        "## 当前右栏",
        f"- 这场在做什么（人的原话）：{anchor_prompt or EMPTY_MARK}",
        f"- 当前阶段目标：{_clip(phase_goal, 200) if phase_goal else EMPTY_MARK}",
        f"- 需要你决策：{slots.get('decision') or NONE_MARK}",
        "- 已经发生的事（最近几条，从旧到新）：",
    ]
    lines += [f"  - {h}" for h in happened] or [f"  - {EMPTY_MARK}"]
    lines.append(f"- 末条（眼下的状态）：{tail_line}")
    existing_tasks = [t for t in (slots.get("tasks") or []) if isinstance(t, dict)]
    if existing_tasks:
        lines.append("- 事项总控表（tasks，按 id 增量更新）：")
        for t in existing_tasks[-15:]:
            tid = t.get("id") or "T?"
            st = t.get("status") or TASK_STATUS_DOING
            title = t.get("title") or ""
            actor = t.get("actor") or "主会话"
            concl = t.get("conclusion") or ""
            lines.append(f"  - [{tid}] ({st}) {title} | 执行体：{actor} | 结论：{concl}")
    shown = showable(fed)
    head = f"## 这一段新增的会话记录（{len(shown)} 条"
    head += f"；更早的 {dropped} 条太多，没给）" if dropped else "）"
    lines += ["", head]
    if trigger in (WORKING, CADENCE, BATCH_TRIGGER):
        lines.append("（这一段截在 agent 干活途中，它还没停下。）")
    lines += shown or [NOTHING_TO_READ]
    goal_candidates = {
        seq: text for seq, text in candidates.items() if not is_card_answer_text(text)
    }
    lines += ["", "## 这一段里人说过的话（换目标时 anchor_seq 只能填这里的编号）"]
    lines += [f"- 第 {seq} 条：{_clip(text, 200)}" for seq, text in goal_candidates.items()] or [
        f"- {NOBODY_SPOKE}"
    ]
    return "\n".join(lines)


# ── 模型的回答 ────────────────────────────────────────────────────────────


def parse_answer(text: str) -> dict[str, Any]:
    """从回答里取出那个 JSON 对象，整理成固定的字段。

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
    raw_tail = obj.get("tail")
    tail = None
    if isinstance(raw_tail, dict) and raw_tail.get("kind") in TAIL_KINDS:
        text = raw_tail.get("text")
        text = _unplaceholder(text.strip()) if isinstance(text, str) else ""
        if text:
            tail = {"kind": raw_tail["kind"], "text": text}
    seq = obj.get("anchor_seq")

    raw_upserts = obj.get("task_upserts")
    task_upserts: list[dict[str, str]] = []
    if isinstance(raw_upserts, list):
        for item in raw_upserts[:TASK_UPSERTS_PER_RUN]:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            tid = _unplaceholder(raw_id.strip()) if isinstance(raw_id, str) else ""
            if not tid:
                continue
            raw_status = item.get("status")
            status = raw_status.strip() if isinstance(raw_status, str) else TASK_STATUS_DOING
            if status not in TASK_STATUS_SET:
                continue
            raw_title = item.get("title")
            title = _unplaceholder(raw_title.strip()) if isinstance(raw_title, str) else ""
            raw_actor = item.get("actor")
            actor = _unplaceholder(raw_actor.strip()) if isinstance(raw_actor, str) else ""
            raw_concl = item.get("conclusion")
            conclusion = _unplaceholder(raw_concl.strip()) if isinstance(raw_concl, str) else ""
            if not (title or actor or conclusion):
                continue
            task_upserts.append(
                {
                    "id": tid[:16],
                    "title": title,
                    "status": status,
                    "actor": actor,
                    "conclusion": conclusion,
                }
            )

    raw_run_row = obj.get("run_row")
    run_row: dict[str, Any] | None = None
    if isinstance(raw_run_row, dict):
        r_tid = raw_run_row.get("task_id")
        r_actor = raw_run_row.get("actor")
        r_doing = raw_run_row.get("doing")
        r_findings = raw_run_row.get("findings")
        task_id = _unplaceholder(r_tid.strip()) if isinstance(r_tid, str) else ""
        actor = _unplaceholder(r_actor.strip()) if isinstance(r_actor, str) else ""
        doing = _unplaceholder(r_doing.strip()) if isinstance(r_doing, str) else ""
        findings = (
            [
                f.strip()
                for f in r_findings
                if isinstance(f, str) and _unplaceholder(f.strip())
            ][:HAPPENED_PER_RUN]
            if isinstance(r_findings, list)
            else []
        )
        if task_id or actor or doing or findings:
            run_row = {
                "task_id": task_id[:16],
                "actor": actor,
                "doing": doing,
                "findings": findings,
            }

    return {
        "phase_goal": field("phase_goal"),
        "tail": tail,
        "decision": field("decision"),
        "happened_add": happened[:HAPPENED_PER_RUN],
        "anchor_seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        "task_upserts": task_upserts,
        "run_row": run_row,
    }


def violation(answer: dict[str, Any]) -> str | None:
    """回答里有没有犯禁令。有就说出犯在哪一格、犯了什么。"""
    tail = answer["tail"] or {}
    plain = [(f"末条（{_TAIL_LABEL.get(tail.get('kind'), '')}）", tail.get("text") or "")]
    if answer.get("phase_goal"):
        plain.append(("当前阶段目标", answer["phase_goal"]))
    plain += [("已经发生的事", h) for h in answer["happened_add"]]
    for t in answer.get("task_upserts") or []:
        if t.get("title"):
            plain.append((f"事项[{t['id']}]简述", t["title"]))
        if t.get("actor"):
            plain.append((f"事项[{t['id']}]执行体", t["actor"]))
        if t.get("conclusion"):
            plain.append((f"事项[{t['id']}]结论", t["conclusion"]))
    run_row = answer.get("run_row")
    if isinstance(run_row, dict):
        if run_row.get("actor"):
            plain.append(("里程碑执行主体", run_row["actor"]))
        if run_row.get("doing"):
            plain.append(("里程碑阶段进展", run_row["doing"]))
        plain += [("里程碑关键发现", f) for f in (run_row.get("findings") or [])]
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
    keys = ("anchor", "phase_goal", "tail", "decision", "happened", "tasks")
    return json.dumps({k: slots.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)


def _legacy_content(slots: dict[str, Any]) -> str:
    keys = ("anchor", "phase_goal", "tail", "decision", "happened")
    return json.dumps({k: slots.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)


def apply_answer(
    slots: dict[str, Any],
    answer: dict[str, Any],
    candidates: dict[int, str],
    stamp_ms: int | None = None,
    *,
    cursor_from: int | None = None,
    cursor_to: int | None = None,
    has_trailing_card: bool = False,
) -> bool:
    """把回答合进槽位，返回槽位是否真的变了。

    - 末条：有新值就换。换下来的如果是一份产出，先退进「已经发生的事」，排在这一段新加的
      几条前面——它比这一段的事早；换下来的是「此刻」就不留，它说的是过程，做完的事由
      「已经发生的事」记。没给新值就不动。
    - 需要你决策：**只有人在这一段里开过口，空串才算「已经答了、清掉」。**
      这一格说的是眼下还有什么在等人回话，是个常驻状态；模型每次只看得见新增的那一段，
      问题是上一段提的，这一段里自然不会再出现一遍。人没开口就把空串当成「没有待决」，
      等于agent 一问完、下一批记录一到就把问题擦掉——实测就是这么丢的：21:08:23 填上
      「改法要人挑」，21:08:25 一条轮次边界落盘，这一格就空了。人只要没答，问题就还在。
    - 已经发生的事：只追加，跟最近几条或末条重复的不加。
    - 锚：只认这一段里人说过的话的编号；指别的编号当没指。

    每一格另记它自己上次变样的时刻，右栏按时间线读要用。``stamp_ms`` 只给测试用。
    """
    before = _content(slots)
    legacy_before = _legacy_content(slots)
    at = int(time.time() * 1000) if stamp_ms is None else stamp_ms

    def put(key: str, value: str) -> None:
        """写一格，值真的变了才动它的时刻。

        时刻记的是「这一格上次变样是什么时候」，不是「上次被写过」。旁路每轮都跑，值没变
        也照写一遍；跟着写时刻的话，一格半小时没动的内容会一直显示成「刚刚」。
        """
        if slots.get(key) != value:
            slots[key] = value
            slots[f"{key}_at"] = at

    upserts_raw = answer.get("task_upserts") or []
    upserts_have_waiting = any(
        isinstance(u, dict) and u.get("status") == TASK_STATUS_WAITING for u in upserts_raw
    )
    if answer["decision"] or candidates or (upserts_raw and not upserts_have_waiting):
        put("decision", answer["decision"])
    if answer.get("phase_goal"):
        put("phase_goal", answer["phase_goal"])

    happened = list(slots.get("happened") or [])
    # 老槽位文件只有正文没有时刻，左边补空对齐，别让新加的那条错位到老内容头上。
    times = list(slots.get("happened_at") or [])
    times = times[-len(happened) :] if happened and len(times) > len(happened) else times
    times = [None] * max(0, len(happened) - len(times)) + times

    def add(item: str, when: int | None) -> None:
        if item not in happened[-20:]:
            happened.append(item)
            times.append(when)

    old_tail = slots.get("tail") or None
    new_tail = answer["tail"]
    if new_tail and new_tail != old_tail:
        if old_tail and old_tail.get("kind") == TAIL_OUTPUT and old_tail.get("text"):
            # 产出不丢：被顶掉时退成历史，带着它当初落地的时刻。
            add(old_tail["text"], slots.get("tail_at"))
        slots["tail"] = new_tail
        slots["tail_at"] = at
    tail_text = (slots.get("tail") or {}).get("text")
    for item in answer["happened_add"]:
        if item != tail_text:
            add(item, at)
    slots["happened"] = happened[-HAPPENED_KEEP:]
    slots["happened_at"] = times[-HAPPENED_KEEP:]

    seq = answer["anchor_seq"]
    current = (slots.get("anchor") or {}).get("seq")
    if (
        seq is not None
        and seq in candidates
        and seq != current
        and not is_card_answer_text(candidates[seq])
    ):
        slots["anchor"] = {"seq": seq, "text": candidates[seq]}
        slots["anchor_at"] = at

    legacy_changed = _legacy_content(slots) != legacy_before
    raw_anchor = slots.get("anchor")
    anchor_text = _safe_goal_text(
        raw_anchor.get("text") if isinstance(raw_anchor, dict) else raw_anchor
    )
    phase_goal_text = _safe_goal_text(slots.get("phase_goal")) or anchor_text
    run_row = answer.get("run_row")
    upserts = answer.get("task_upserts") or []

    tasks = [dict(t) for t in (slots.get("tasks") or []) if isinstance(t, dict)]
    if upserts:
        by_id = {str(t.get("id") or ""): i for i, t in enumerate(tasks) if t.get("id")}
        for u in upserts:
            tid = u["id"]
            if tid in by_id:
                existing = dict(tasks[by_id[tid]])
                next_title = u["title"] or existing.get("title") or ""
                next_status = u["status"]
                next_actor = u["actor"] or existing.get("actor") or "主会话"
                next_concl = u["conclusion"] or existing.get("conclusion") or ""
                if (
                    next_title != existing.get("title")
                    or next_status != existing.get("status")
                    or next_actor != existing.get("actor")
                    or next_concl != existing.get("conclusion")
                ):
                    existing.update(
                        title=next_title,
                        status=next_status,
                        actor=next_actor,
                        conclusion=next_concl,
                        updated_at=at,
                    )
                    tasks[by_id[tid]] = existing
            else:
                by_id[tid] = len(tasks)
                tasks.append(
                    {
                        "id": tid,
                        "proposed_at": at,
                        "updated_at": at,
                        "title": u["title"] or phase_goal_text or "当前事项",
                        "status": u["status"],
                        "actor": u["actor"] or ((run_row or {}).get("actor") or "主会话"),
                        "conclusion": u["conclusion"],
                    }
                )
    elif legacy_changed:
        cur_tail = slots.get("tail") or None
        cur_tail_text = _clean_tail_text((cur_tail or {}).get("text") or "")
        cur_decision = _clean_tail_text(slots.get("decision") or "")
        if phase_goal_text or cur_tail_text or cur_decision or answer["happened_add"]:
            auto_status = (
                TASK_STATUS_WAITING
                if cur_decision
                else (
                    TASK_STATUS_DONE
                    if (cur_tail or {}).get("kind") == TAIL_OUTPUT
                    else TASK_STATUS_DOING
                )
            )
            title_src = phase_goal_text or anchor_text or cur_tail_text or "当前阶段"
            auto_title = _clip(title_src, 28) if len(title_src) > 28 else title_src
            auto_actor = ((run_row or {}).get("actor") or "").strip() or "主会话"
            concl_src = (
                cur_tail_text
                or (answer["happened_add"][-1] if answer["happened_add"] else "")
                or cur_decision
            )
            auto_concl = _clip(concl_src, 60) if len(concl_src) > 60 else concl_src
            target_tid = ((run_row or {}).get("task_id") or "").strip()

            matched_idx: int | None = None
            if target_tid:
                for i, t in enumerate(tasks):
                    if t.get("id") == target_tid:
                        matched_idx = i
                        break
            elif tasks:
                last = tasks[-1]
                # If previous task is done and phase_goal moved to a new title, start a new task row
                if not (
                    last.get("status") == TASK_STATUS_DONE
                    and answer.get("phase_goal")
                    and auto_title
                    and auto_title != last.get("title")
                ):
                    matched_idx = len(tasks) - 1

            if matched_idx is not None:
                existing = dict(tasks[matched_idx])
                next_title = auto_title or existing.get("title") or ""
                next_concl = auto_concl or existing.get("conclusion") or ""
                if (
                    next_title != existing.get("title")
                    or auto_status != existing.get("status")
                    or auto_actor != existing.get("actor")
                    or next_concl != existing.get("conclusion")
                ):
                    existing.update(
                        title=next_title,
                        status=auto_status,
                        actor=auto_actor,
                        conclusion=next_concl,
                        updated_at=at,
                    )
                    tasks[matched_idx] = existing
            else:
                new_tid = target_tid or f"T{len(tasks) + 1}"
                tasks.append(
                    {
                        "id": new_tid,
                        "proposed_at": at,
                        "updated_at": at,
                        "title": auto_title,
                        "status": auto_status,
                        "actor": auto_actor,
                        "conclusion": auto_concl,
                    }
                )
    if tasks:
        if has_trailing_card and not any(t.get("status") == TASK_STATUS_WAITING for t in tasks):
            target_tid = ((run_row or {}).get("task_id") or "").strip()
            target_idx = next(
                (i for i, t in enumerate(tasks) if target_tid and t.get("id") == target_tid),
                len(tasks) - 1,
            )
            tasks[target_idx] = {**tasks[target_idx], "status": TASK_STATUS_WAITING, "updated_at": at}
        slots["tasks"] = tasks[-TASKS_KEEP:]

    reconciled_decision = _reconcile_decision_consistency(tasks, slots.get("decision") or "")
    if reconciled_decision != (slots.get("decision") or ""):
        put("decision", reconciled_decision)

    changed = _content(slots) != before
    if changed:
        runs = list(slots.get("runs") or [])
        c_from = int(cursor_from) if cursor_from is not None else (runs[-1].get("cursor_to", 0) if runs else 0)
        c_to = int(cursor_to) if cursor_to is not None else int(slots.get("cursor") or c_from)
        derived_doing, derived_findings = _derive_doing_and_findings(
            slots.get("tail") or None,
            answer["happened_add"],
        )
        run_task_id = (
            ((run_row or {}).get("task_id") or "").strip()
            or (upserts[0]["id"] if upserts else "")
            or (tasks[-1]["id"] if tasks else f"T{len(runs) + 1}")
        )
        run_actor = (
            ((run_row or {}).get("actor") or "").strip()
            or next((t["actor"] for t in tasks if t["id"] == run_task_id), "")
            or "主会话"
        )
        run_doing = ((run_row or {}).get("doing") or "").strip() or derived_doing
        run_findings = (
            list((run_row or {}).get("findings") or [])
            if isinstance(run_row, dict) and run_row.get("findings")
            else derived_findings
        )
        summary = _compose_run_summary(
            slots.get("tail") or None,
            answer["happened_add"],
            slots.get("decision") or "",
            anchor_text,
            doing_override=run_doing,
            findings_override=run_findings,
        )
        if summary:
            runs.append(
                {
                    "id": f"run-{len(runs) + 1}-{at}",
                    "run_id": len(runs) + 1,
                    "task_id": run_task_id,
                    "actor": run_actor,
                    "at": at,
                    "cursor_from": c_from,
                    "cursor_to": c_to,
                    "phase_goal": phase_goal_text,
                    "doing": run_doing,
                    "findings": run_findings,
                    "tail": slots.get("tail") or None,
                    "happened_add": list(answer["happened_add"]),
                    "decision": slots.get("decision") or "",
                    "summary": summary,
                }
            )
            slots["runs"] = runs[-RUNS_KEEP:]
    return changed


# ── 服务 ──────────────────────────────────────────────────────────────────


@dataclass
class _Lane:
    running: bool = False
    #: 跑着的时候又来了触发，记下最后一次的原因。多次触发并成一次：下一次本来就会读到
    #: 游标之后的全部新增，不丢东西。
    owed: str | None = None
    #: 上一次开跑的时刻（单调钟）。干活途中的触发按它节流。
    last_started: float = float("-inf")


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
        self._pending_push_states: dict[str, dict[str, Any]] = {}

    # ---- 投任务 ---------------------------------------------------------

    def notify(self, session_id: str, trigger: str) -> None:
        """投一个任务就走。从监听线上调，NEVER 在这里等模型。

        干活途中的触发（``working`` / ``batch``）每批新记录都会来一次，离上一次开跑不满
        ``WORKING_GAP_S`` 就直接丢掉；也不去顶掉已经欠着的别的触发——人发话、一轮结束
        这些原因要留在执行记录里。
        """
        with self._lock:
            if self._closed:
                return
            lane = self._lanes.setdefault(session_id, _Lane())
            if (
                trigger in (WORKING, BATCH_TRIGGER)
                and time.monotonic() - lane.last_started < WORKING_GAP_S
            ):
                return
            if lane.running:
                if trigger not in (WORKING, BATCH_TRIGGER) or lane.owed is None:
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
            with self._lock:
                self._lanes[session_id].last_started = time.monotonic()
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

        new, total = self._read_after(session_id, cursor, slots.get("cursor_id"))
        if any(r.kind != "user.say" for r in new):
            # 若前面已有完成的动作/回复，而末尾挂着人刚发出、agent 尚未回应的新提问，
            # 先不把末尾这句未回应的提问吞进本段总结，留给下一段跟它的回复一起总结。
            while new and new[-1].kind == "user.say" and human_text(new[-1]) is not None:
                new.pop()
        if not new:
            entry.update(skipped="nothing-new", dur_ms=_ms(started))
            if trigger == "prompt" and directory.exists():
                # 人刚说了一句话，监听那边是看见了才叫我们的，这里却一条都没读到——位置
                # 对不上了。这一笔留着：下次人对右栏没动静起疑时，能看出「叫过我，我什么
                # 都没读到」。平时读空（定时补读、页面轮询）不记，免得把执行记录泡满。
                append_run(directory, entry)
            return entry
        if trigger in (BATCH_TRIGGER, SETTLE_TRIGGER, WORKING, CADENCE) and all(
            r.kind == "user.say" for r in new
        ):
            # 只有人的提问、agent 还没任何动作或回复时不抢跑建槽，等发生后再总结。
            entry.update(skipped="awaiting-reply", dur_ms=_ms(started))
            return entry
        entry["records"] = total
        last_seq = new[-1].seq

        if is_heartbeat_batch(new):
            slots["cursor"] = last_seq + 1
            slots["cursor_id"] = new[-1].id
            save_slots(directory, slots)
            entry.update(skipped="pa-heartbeat", cursor_to=last_seq + 1, dur_ms=_ms(started))
            append_run(directory, entry)
            return entry

        if not showable(new):
            # 这一批全是看不见的东西（思考、工具结果、注入、轮次边界）。问了也是白问：
            # 模型看到一份空记录，只会如实答「这一段什么都没有」，而那份空回答会把右栏
            # 里本来有内容的格子盖掉——实测过一次，agent 刚摆出三条改法等人挑，两秒后
            # 一条轮次边界落盘，「需要你决策」当场被清空。游标照样往前，人什么都不会看到。
            slots["cursor"] = last_seq + 1
            slots["cursor_id"] = new[-1].id
            save_slots(directory, slots)
            entry.update(skipped="nothing-to-read", cursor_to=last_seq + 1, dur_ms=_ms(started))
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
        prompt = build_prompt(slots, new, total - len(new), candidates, trigger)
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
        slots["cursor_id"] = new[-1].id
        entry["cursor_to"] = last_seq + 1
        if answer is None or why:
            # 答了但不合规矩：整份作废，槽位保持原样；游标照样往前，免得同一段反复踩同一个坑。
            entry.update(rejected=why, changed=False)
            changed = False
        else:
            fallback_decision = _trailing_unanswered_card_decision(new)
            has_trailing_card = bool(fallback_decision)
            if not answer["decision"] and fallback_decision:
                answer["decision"] = fallback_decision
            changed = apply_answer(
                slots,
                answer,
                candidates,
                cursor_from=cursor,
                cursor_to=last_seq + 1,
                has_trailing_card=has_trailing_card,
            )
            entry["changed"] = changed
        prev_status = slots.get("status")
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
        if changed or prev_status != "ok":
            self._push(session_id, slots)
        return entry

    def _read_after(
        self, session_id: str, cursor: int, cursor_id: str | None = None
    ) -> tuple[list[UnifiedRecord], int]:
        """游标之后的新增记录：只留最后 BACKLOG_CAP 条，另外报总共有多少。

        游标是个**位置**，而位置会动：整场会话每次都是重新编号的。引擎重写一条记录
        （每轮的花费账本只留最后一条）就让它后面所有记录的编号整体往前挪一格，于是
        「下一次从第几号读」这个说法本身失效——人刚说的那句话可能排在游标**之前**，
        而且读出来的那一批看上去很正常。所以每次先验一下位置：游标前面那条，现在还是
        我们上次读到的那条吗？不是就退回尾部，从认得的那条接着往下喂。宁可重喂，
        NEVER 当作没有新的——被吞掉那次是无声无息吞的：执行记录里一笔都没留，右栏
        看上去就是「人对它说话它不理」。

        ``cursor_id`` 是上一次读到的那条记录的编号。老槽位文件里没有这一格（None），
        位置对不对无从判断，就退到尾部重读一段——重喂一遍比漏掉一句强，而且这种槽位
        文件只会遇到一次，第一次跑完就把身份补上了。
        """
        if cursor > 0:
            aligned = False
            if cursor_id is not None:
                standing = self._read(session_id, after=cursor - 1, limit=1)
                aligned = (
                    bool(standing) and standing[0].seq == cursor - 1 and standing[0].id == cursor_id
                )
            if not aligned:
                return self._re_anchor(session_id, cursor_id)

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
        return list(kept), total

    def _re_anchor(self, session_id: str, cursor_id: str | None) -> tuple[list[UnifiedRecord], int]:
        """位置靠不住时退回尾部：认得身份就接在它后面，认不得就整段尾巴都当新的。"""
        window = self._read(session_id, tail=True, limit=BACKLOG_CAP)
        if cursor_id:
            for index, record in enumerate(window):
                if record.id == cursor_id:
                    return list(window[index + 1 :]), len(window) - index - 1
        return list(window), len(window)

    def _first_human(self, session_id: str) -> tuple[int, str] | None:
        after = 0
        for _ in range(ANCHOR_SCAN_PAGES):
            batch = self._read(session_id, after=after, limit=PAGE)
            for record in batch:
                text = human_text(record)
                if text and not is_card_answer_text(text):
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

        state = public_state(slots, True)
        with self._lock:
            already_queued = session_id in self._pending_push_states
            self._pending_push_states[session_id] = state
        if already_queued:
            return

        async def _flush_push() -> None:
            with self._lock:
                latest = self._pending_push_states.pop(session_id, None)
            if latest is None:
                return
            message = create_message(
                WS_OBSERVER_UPDATE,
                {"session_id": session_id, "state": latest},
            )
            await manager.broadcast(message)

        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(_flush_push(), self._loop)

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
