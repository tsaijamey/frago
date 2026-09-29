"""会话页「分支」—— 圈一段原文，起一场新会话专门处理这个旁支问题，主线原地不动。

方案见 ``.claude/docs/spec-driven-plan/20260928-webui-session-branch/spec.md``。

## 现象先说

读代理的长回复时常碰到一个跟主线相关、却不该在主线里展开的问题：某个报错要不要查、
某个名词是什么意思。在主线里问，主线的上下文被旁支撑大；手动另开一场，得自己把原文和
背景复制过去，事后也没有任何记录说明那一场是从哪来的。

「交接到新会话」（:mod:`~frago.server.services.workbench_handoff`）是把整场搬家，这里只
交出一个问题：

- 第一句话只带原会话编号、圈的那段原文、人写的那句话，由服务端拼，不经模型；
- 原会话不改名，页面也不跳走——主线接着谈，分支那一场人想看再点开；
- 起完当场往会话关系账记一条「分支」（:mod:`frago.session.session_origin`），往主线的
  标注文件追加一条分支标注（:mod:`~frago.server.services.workbench_marks`）。

## 新会话起在哪

同一家 agent、同一个目录，判法与交接、与「对着这场会话发话」完全相同
（:func:`~frago.server.services.session_send.resolve_target`），NEVER 另写一份。

## 编号到手才记账

claude 与 CoreAgent 的编号起会话那一刻就有，当场记。codex 与 opencode 的编号要等认领，
后台等到认领到再记；首轮跑完仍没认到就不记——**NEVER 为了关系好看编一个编号出来**。

## 收口

分支会话里「带回主线」、或主线那段原文上手动「标记已收口」，都走 :func:`close`：关系账
与主线标注在同一次调用里一起改。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from frago.server.services import (
    session_send,
    workbench_handoff,
    workbench_marks,
    workbench_new_session,
)
from frago.session import session_origin
from frago.session.record_reader import UnknownSessionFamily

logger = logging.getLogger(__name__)

#: 原地提示里拿人写的那句话当标题时，最多露多少字。
TITLE_CLIP = 40


class BranchRequestInvalid(ValueError):
    """交上来的起分支请求不合规矩（没写那句话、原文为空、超长）。路由据此回 400。"""


class BranchUnavailable(LookupError):
    """这场会话起不了分支（还没有任何记录）。路由据此回 409。"""


class BranchNotFound(LookupError):
    """关系账上没有这条分支，收不了口。路由据此回 404。"""


@dataclass(frozen=True)
class BranchAnchor:
    """从主线哪条记录、哪段原文分出去。字段与标注同一套，见 ``workbench_marks``。"""

    record_id: str
    text: str
    occurrence: int


@dataclass(frozen=True)
class Branch:
    """一次起分支：新会话由哪一家、在哪个目录起，第一句话是什么。"""

    parent_session_id: str
    agent_type: str
    cwd: str
    anchor: BranchAnchor
    note: str
    text: str


def validate(record_id: str, text: str, occurrence: int, note: str) -> tuple[BranchAnchor, str]:
    """校验起分支的请求，交回整理好的原文锚点与那句话。上限与标注同一套。"""
    note = (note or "").strip()
    text = (text or "").strip()
    if not note:
        raise BranchRequestInvalid("起分支要写一句话：这个旁支问题要问什么")
    if not text:
        raise BranchRequestInvalid("原文不能是空的")
    if not record_id or len(record_id) > workbench_marks.MAX_RECORD_ID:
        raise BranchRequestInvalid("record_id 不对")
    if len(text) > workbench_marks.MAX_TEXT:
        raise BranchRequestInvalid(f"原文超过 {workbench_marks.MAX_TEXT} 字")
    if len(note) > workbench_marks.MAX_NOTE:
        raise BranchRequestInvalid(f"那句话超过 {workbench_marks.MAX_NOTE} 字")
    if occurrence < 0:
        raise BranchRequestInvalid("occurrence 不能是负数")
    return BranchAnchor(record_id=record_id, text=text, occurrence=occurrence), note


def compose(session_id: str, anchor: BranchAnchor, note: str) -> Branch:
    """判出分支会话起在哪、拼好第一句话。

    抛 :class:`~frago.session.record_reader.UnknownSessionFamily`（编号不属于任何一家）、
    ``session_send`` 那几种判不出落点的异常，以及 :class:`BranchUnavailable`（原会话还没有
    记录）。
    """
    target = session_send.resolve_target(session_id)
    if target.is_new or not target.cwd:
        raise BranchUnavailable(f"会话 {session_id} 还没有任何记录，起不了分支")
    return Branch(
        parent_session_id=session_id,
        agent_type=target.agent_type,
        cwd=target.cwd,
        anchor=anchor,
        note=note,
        text=render(session_id, anchor.text, note),
    )


def render(session_id: str, text: str, note: str) -> str:
    """拼分支会话的第一句话。格式照 spec，回原会话翻记录的办法与交接共用同一句。"""
    body = (
        "这是从另一场会话分出来的旁支问题。主线仍在原会话继续，这里只处理下面这个问题。\n\n"
        f"原会话编号：{session_id}（需要细节时按编号回去翻原会话记录）\n"
        f"翻法：{workbench_handoff.lookup_hint(session_id)}。\n"
        "原文：\n"
        f'"""\n{text}\n"""\n'
        f">>> {note}"
    )
    return workbench_handoff.strip_image_refs(body)


def title_for(note: str) -> str:
    """原地提示里这场分支叫什么：新会话还没有常规标题时，用人写的那句话的开头。"""
    head = " ".join(note.split())
    return head if len(head) <= TITLE_CLIP else head[:TITLE_CLIP] + "…"


@dataclass
class Recorded:
    """记账结果。``relation`` 为假时标注一定也没记（两边要么都有、要么都没有）。"""

    relation: bool = False
    mark_saved: bool = False
    mark_id: str | None = None


def record(branch: Branch, child_session_id: str) -> Recorded:
    """编号到手之后记关系账、往主线标注文件追加分支标注。

    关系账先记：它记不上就不写标注——主线上画着一道虚线、账上却查不到这条分支，收口时
    就只能改掉一边。标注存不下（CoreAgent 那一家没有备份目录）不影响关系照记，结果里说明。
    """
    result = Recorded()
    mark_id = f"mk_{uuid.uuid4().hex[:16]}"
    anchor = branch.anchor
    result.relation = session_origin.record_relation(
        kind="branch",
        child_session_id=child_session_id,
        parent_session_id=branch.parent_session_id,
        agent_type=branch.agent_type,
        cwd=branch.cwd,
        prompt_head=branch.note,
        anchor={
            "record_id": anchor.record_id,
            "text": anchor.text,
            "occurrence": anchor.occurrence,
            "mark_id": mark_id,
        },
        note=branch.note,
    )
    if not result.relation:
        logger.warning("分支 %s → %s 没记进关系账", branch.parent_session_id, child_session_id)
        return result
    try:
        workbench_marks.append_branch_mark(
            branch.parent_session_id,
            {
                "id": mark_id,
                "record_id": anchor.record_id,
                "text": anchor.text,
                "occurrence": anchor.occurrence,
                "note": branch.note,
                "created_at": int(time.time() * 1000),
                "child_session_id": child_session_id,
                "closed": False,
            },
        )
    except (UnknownSessionFamily, KeyError):
        # CoreAgent 那一家没有备份目录，标注存不了（与暂存同一条限制）。关系照记。
        logger.info("会话 %s 存不了标注，分支只记进关系账", branch.parent_session_id)
        return result
    except (OSError, workbench_marks.MarksError):
        logger.warning("往 %s 追加分支标注失败", branch.parent_session_id, exc_info=True)
        return result
    result.mark_saved = True
    result.mark_id = mark_id
    return result


def record_when_claimed(branch: Branch, handle: str) -> None:
    """编号要等认领的那两家：后台等认到编号再记账。首轮跑完仍没认到就不记。"""
    threading.Thread(
        target=_record_when_claimed,
        args=(branch, handle),
        name=f"webui-branch-record-{handle[:12]}",
        daemon=True,
    ).start()


def _record_when_claimed(branch: Branch, handle: str) -> None:
    deadline = time.monotonic() + workbench_handoff.CLAIM_WAIT_S
    while time.monotonic() < deadline:
        launch = workbench_new_session.status(handle)
        if launch is None:
            return
        if launch.session_id:
            record(branch, launch.session_id)
            return
        if launch.finished:
            logger.info("分支 %s 首轮跑完仍没认到编号，关联不记", handle)
            return
        time.sleep(workbench_handoff.CLAIM_POLL_S)


def close(parent_session_id: str, child_session_id: str, closed_by: str) -> dict[str, Any]:
    """把一条分支记为已收口：关系账与主线标注在这一次调用里一起改。

    关系账上没有这条分支抛 :class:`BranchNotFound`；关系账写不进去抛 ``OSError``。
    标注改不了（那一家存不了标注、或标注文件里没有这条）不算失败，结果里如实说明。
    """
    if closed_by not in session_origin.CLOSE_BY:
        raise BranchRequestInvalid(f"收口来路只认 {' / '.join(session_origin.CLOSE_BY)}")
    entry = session_origin.close_relation(
        child_session_id=child_session_id,
        parent_session_id=parent_session_id,
        closed_by=closed_by,  # type: ignore[arg-type]
    )
    if entry is None:
        raise BranchNotFound(f"会话 {parent_session_id} 没有分到 {child_session_id} 的分支")
    mark_updated = False
    try:
        mark_updated = workbench_marks.set_branch_closed(parent_session_id, child_session_id)
    except (UnknownSessionFamily, KeyError):
        pass
    except OSError:
        logger.warning("主线 %s 的分支标注没改成已收口", parent_session_id, exc_info=True)
    return {
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "closed_at": entry.get("closed_at"),
        "closed_by": entry.get("closed_by"),
        "mark_updated": mark_updated,
    }
