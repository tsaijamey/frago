"""会话页「交接到新会话」—— 把一场上下文已经太长的会话，交给一场新会话接着做。

## 现象先说

一场会话聊到三十多万 token，模型明显变慢、变笨，人想换一场接着干，但新会话什么都不知道：
这件事是什么、做到哪了、停在哪、改过哪些文件。从前人只能自己写一段交代，或者让旧会话
在那三十多万 token 里再费力写一份交接。

这里用**已经现成的材料**直接拼出新会话的第一句话，不再问任何模型：

| 段落 | 出处 |
|---|---|
| 这场在做什么 / 已经发生的事 / 停在哪 / 等人拍板的事 | 右栏旁路 AI 每轮写的槽位文件 |
| 人的原话（最近几句，逐字） | 会话记录 |
| 原会话最后一段回复（逐字） | 会话记录 |
| 动过的文件 | 会话记录里写文件那一类工具调用的目标路径 |

人的原话与最后一段回复一律逐字给：目标和约束最准的出处是人说过的话，停在哪一步最准的
出处是 agent 最后说的话，经过模型转述都会走样。

**只给回原话的办法，不复述整场。** 换场就是为了躲开那三十多万 token，把它们搬进新会话
等于白换。新会话需要细节时，自己按会话编号回去翻。

## 新会话起在哪

同一家 agent、同一个目录——判法与「对着这场会话发话」完全相同
（:func:`~frago.server.services.session_send.resolve_target`），NEVER 另写一份：同一场
会话两条路判出两个目录，新会话就会在另一个仓库里接手。

## 两场各叫什么

交接之后左栏并排两场说同一件事的会话。原会话改叫「甲 #1」，新会话叫「甲 #2」，名字只写进
frago 自己的名字表（:mod:`~frago.server.services.workbench_titles`），档案不动。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from frago.server.services import (
    session_observer,
    session_send,
    workbench_new_session,
    workbench_titles,
)
from frago.session import record_reader
from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

#: 人的原话最多带几句。
HUMAN_KEEP = 5
#: 单句人话最多带多少字。人偶尔贴进来一整份日志，全带上会把交接本身撑成下一个长上下文。
HUMAN_CLIP = 1500
#: 最后一段回复最多带多少字。
LAST_REPLY_CLIP = 2000
#: 「已经发生的事」带最近几条。
HAPPENED_KEEP = 8
#: 动过的文件最多列几个。
FILES_KEEP = 30
#: 往回翻记录时一页多少条、最多翻几页。人的原话可能在很早之前——agent 一轮干上百个工具
#: 调用很常见——但一场会话不必全翻：翻满这么多还凑不够就用已经凑到的。
PAGE = record_reader.MAX_LIMIT
MAX_PAGES = 8

#: 家族在第一句话里的叫法。
_FAMILY_LABEL = {
    "claude-code": "Claude Code",
    "codex": "codex",
    "opencode": "opencode",
    "coreagent": "CoreAgent",
}

#: 写文件的工具把目标路径放在这几个参数里（三家各有各的写法）。
_PATH_KEYS = ("file_path", "filePath", "path", "notebook_path")
#: codex 的 apply_patch 没有路径参数，路径写在补丁正文里。
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


class HandoffUnavailable(LookupError):
    """这场会话交接不了（还没有任何记录）。服务层据此回 409。"""


@dataclass(frozen=True)
class Handoff:
    """一次交接：新会话由哪一家、在哪个目录起，第一句话是什么。"""

    agent_type: str
    cwd: str
    text: str


def compose(session_id: str) -> Handoff:
    """拼出交接给新会话的第一句话。

    抛 :class:`~frago.session.record_reader.UnknownSessionFamily`（编号不属于任何一家）、
    ``session_send`` 那几种判不出落点的异常（记录没了、问不出目录、这一家接不上话），以及
    :class:`HandoffUnavailable`（这场会话还没有记录，没有东西可交接）。
    """
    target = session_send.resolve_target(session_id)
    if target.is_new or not target.cwd:
        raise HandoffUnavailable(f"会话 {session_id} 还没有任何记录，没有东西可交接")

    slots = _load_slots(session_id, target.family)
    records = _recent_records(session_id)
    text = render(
        session_id=session_id,
        family=target.family,
        cwd=target.cwd,
        slots=slots,
        humans=human_lines(records),
        last_reply=last_reply(records),
        files=touched_files(records),
    )
    return Handoff(agent_type=target.agent_type, cwd=target.cwd, text=text)


#: 编号要等认领的那两家，最多等多久给新会话起名。首轮本身的上限是十分钟，认领远早于它。
CLAIM_WAIT_S = 600.0
CLAIM_POLL_S = 1.0


def current_title(session_id: str) -> str:
    """原会话此刻在左栏叫什么：起过名的用起过的，否则用清单里那个标题。"""
    named = workbench_titles.load().get(session_id)
    if named:
        return named
    for card in record_reader.list_sessions():
        if card.session_id == session_id:
            return card.title
    return session_id[:8]


def name_pair(session_id: str, launch: workbench_new_session.PendingLaunch) -> tuple[str, str]:
    """给交接的两场各起一个带序号的名字，回 ``(原会话的名字, 新会话的名字)``。

    起名失败不拦交接：新会话已经起来了，名字只是让人分得清，写不进去就照旧叫原来的名字。
    """
    old_title, new_title = workbench_titles.numbered_pair(current_title(session_id))
    try:
        workbench_titles.set_title(session_id, old_title)
        if launch.session_id:
            workbench_titles.set_title(launch.session_id, new_title)
        else:
            threading.Thread(
                target=_name_when_claimed,
                args=(launch.handle, new_title),
                name=f"webui-handoff-name-{launch.handle[:12]}",
                daemon=True,
            ).start()
    except (OSError, ValueError):
        logger.warning("交接时给会话起名失败（%s）", session_id, exc_info=True)
    return old_title, new_title


def _name_when_claimed(handle: str, title: str) -> None:
    """等认领到新会话的编号再起名。首轮跑完还没认到就算了——那一场多半没起来。"""
    deadline = time.monotonic() + CLAIM_WAIT_S
    while time.monotonic() < deadline:
        launch = workbench_new_session.status(handle)
        if launch is None:
            return
        if launch.session_id:
            try:
                workbench_titles.set_title(launch.session_id, title)
            except (OSError, ValueError):
                logger.warning("给新会话 %s 起名失败", launch.session_id, exc_info=True)
            return
        if launch.finished:
            return
        time.sleep(CLAIM_POLL_S)


def _load_slots(session_id: str, family: str) -> dict[str, Any]:
    """右栏的槽位。没有（旁路 AI 没配连接、没跑过、或者这一家不归它管）就是空的一份。"""
    try:
        directory = session_observer.session_dir(session_id, family)
    except KeyError:
        return session_observer.empty_slots(session_id, family)
    return session_observer.load_slots(directory, session_id, family)


def _recent_records(session_id: str) -> list[UnifiedRecord]:
    """从尾巴往回翻，直到凑够人的原话或翻满 :data:`MAX_PAGES` 页。按物理序从旧到新。"""
    records = list(record_reader.read_records(session_id, limit=PAGE, tail=True))
    pages = 1
    while (
        records
        and records[0].seq > 0
        and pages < MAX_PAGES
        and len(human_lines(records)) < HUMAN_KEEP
    ):
        first = records[0].seq
        start = max(0, first - PAGE)
        older = record_reader.read_records(session_id, after=start, limit=first - start)
        older = [r for r in older if r.seq < first]
        if not older:
            break
        records = older + records
        pages += 1
    return records


def human_lines(records: Sequence[UnifiedRecord]) -> list[str]:
    """最近几句人亲口说的话，从旧到新。工具结果、唤醒词、hook 注入都不算。"""
    said = [
        text.strip()
        for text in (session_observer.human_text(r) for r in records if not r.agent_path)
        if text and text.strip()
    ]
    return [_clip(text, HUMAN_CLIP) for text in said[-HUMAN_KEEP:]]


def last_reply(records: Sequence[UnifiedRecord]) -> str:
    """主会话最后一段有字的 agent 回复。子 agent 说的话不算——那是它交回来的中间结果。"""
    for record in reversed(records):
        if record.kind != "agent.say" or record.agent_path:
            continue
        text = record.payload.get("text")
        if isinstance(text, str) and text.strip():
            return _clip(text.strip(), LAST_REPLY_CLIP)
    return ""


def touched_files(records: Sequence[UnifiedRecord]) -> list[str]:
    """写过的文件，去重，按最后一次写的先后排，最近写的在最后。"""
    seen: dict[str, None] = {}
    for record in records:
        if record.kind != "tool.call" or record.payload.get("tool_family") != "file-write":
            continue
        for path in _write_targets(record.payload.get("args")):
            seen.pop(path, None)
            seen[path] = None
    return list(seen)[-FILES_KEEP:]


def _write_targets(args: Any) -> list[str]:
    if isinstance(args, dict):
        for key in _PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        args = json.dumps(args, ensure_ascii=False).replace("\\n", "\n")
    if isinstance(args, str):
        return [m.strip() for m in _PATCH_FILE.findall(args)]
    return []


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…（后略）"


def render(
    *,
    session_id: str,
    family: str,
    cwd: str,
    slots: dict[str, Any],
    humans: Sequence[str],
    last_reply: str,
    files: Sequence[str],
) -> str:
    """拼第一句话。哪一段没有材料就整段不写，NEVER 留一个空标题让新会话去猜。"""
    label = _FAMILY_LABEL.get(family, family)
    parts = [
        f"你接手会话 {session_id}（{label}，目录 {cwd}）。"
        "原会话上下文太长、已经变慢，人让你把没做完的接着做完。"
    ]

    anchor = slots.get("anchor")
    anchor_text = anchor.get("text") if isinstance(anchor, dict) else None
    if isinstance(anchor_text, str) and anchor_text.strip():
        parts.append(f"## 这场在做什么\n{anchor_text.strip()}")

    happened = [
        h.strip() for h in (slots.get("happened") or []) if isinstance(h, str) and h.strip()
    ]
    if happened:
        recent = happened[-HAPPENED_KEEP:]
        lines = "\n".join(f"- {h}" for h in recent)
        parts.append(f"## 已经发生的事（最近 {len(recent)} 条）\n{lines}")

    tail = slots.get("tail")
    tail_text = tail.get("text") if isinstance(tail, dict) else None
    if isinstance(tail_text, str) and tail_text.strip():
        kind = "产出" if tail.get("kind") == session_observer.TAIL_OUTPUT else "此刻"
        parts.append(f"## 停在哪\n（{kind}）{tail_text.strip()}")

    decision = str(slots.get("decision") or "").strip()
    if decision:
        parts.append(f"## 等人拍板的事\n{decision}")

    if humans:
        quoted = "\n\n".join(f'"""\n{h}\n"""' for h in humans)
        parts.append(f"## 人的原话（最近 {len(humans)} 句，逐字，从旧到新）\n{quoted}")

    if last_reply:
        parts.append(f'## 原会话最后一段回复（逐字）\n"""\n{last_reply}\n"""')

    if files:
        parts.append("## 动过的文件\n" + "\n".join(f"- {f}" for f in files))

    parts.append(
        "## 需要细节时回原话\n"
        f"`frago session show {session_id} --steps`（查不到就先 `frago session sync`），"
        '或 `frago session search "<一句话>"`。只按需翻，不要整场读进来——换场就是为了躲开它。'
    )

    steps = ["看一眼现状（git status、打开上面列的文件），确认跟上面说的一致"]
    if decision:
        steps.append("「等人拍板的事」还没定，先问人，得到答复再动手")
    else:
        steps.append("核对完直接接着做")
    parts.append("## 你第一步\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))

    return "\n\n".join(parts)
