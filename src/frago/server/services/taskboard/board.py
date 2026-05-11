"""TaskBoard 单例: 强封装的对象树 + 单一持久化通过 timeline.

公有方法是 board 之外 (4 Applier) 修改对象的唯一入口。状态变更同锁段必写 timeline entry,
不维护快照 (HUMAN decision 锁定: 单一 timeline.jsonl 源)。

Phase 0 范围: schema + fold (两遍) + 基础 mutation 公有方法。
Phase 1 范围: Applier 接入 + status transition 完整校验。
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from frago.server.services.taskboard.models import (
    IllegalTransitionError,
    Intent,
    Msg,
    RejectionRecord,
    Source,
    Task,
    Thread,
)
from frago.server.services.taskboard.timeline import Timeline, ulid_new

_RECENT_REJECTIONS_WINDOW = 10


class TaskBoard:
    """单例 (per process)。状态变更走公有方法 + 同锁段必写 timeline entry。"""

    def __init__(self, timeline: Timeline):
        self._lock = threading.RLock()
        self._timeline = timeline
        self._threads: dict[str, Thread] = {}
        # 反查索引 (L1/L2 归并 O(1) 查找)
        self._channelref_index: dict[tuple[str, str], str] = {}
        self._sender_index: dict[tuple[str, str], set[str]] = {}
        # PA 可见的最近拒绝记录 (滚动窗口)
        self._recent_rejections: deque[RejectionRecord] = deque(
            maxlen=_RECENT_REJECTIONS_WINDOW
        )
        # fold 统计 (Ce ask #3: 作 board attribute 不引入 BoardSnapshot)
        self.entries_read = 0
        self.entries_skipped = 0

    # ── fold (两遍算法) ──────────────────────────────────────────────

    @classmethod
    def fold(cls, timeline_path: Path) -> "TaskBoard":
        """从 timeline.jsonl 重建内存投影。

        两遍算法 (T5.1):
        - 第一遍: 扫全文件收 archived_thread_ids set (data_type=='thread_archived')
        - 第二遍: 读 entries 跳过该 set 内 thread_id 的全部 entries
        """
        timeline = Timeline(timeline_path)
        board = cls(timeline)

        # 第一遍
        archived_thread_ids: set[str] = set()
        for entry in timeline.iter_entries():
            if entry.get("data_type") == "thread_archived":
                tid = entry.get("thread_id")
                if tid:
                    archived_thread_ids.add(tid)

        # 第二遍
        entries_read = 0
        entries_skipped = 0
        for entry in timeline.iter_entries():
            entries_read += 1
            tid = entry.get("thread_id")
            if tid in archived_thread_ids:
                entries_skipped += 1
                continue
            board._apply_entry(entry)

        board.entries_read = entries_read
        board.entries_skipped = entries_skipped
        return board

    def _apply_entry(self, entry: dict) -> None:
        """根据 data_type 把 timeline entry 转化为内存对象变更。

        Phase 0 实现基础 data_type: msg_received / task_appended / task_started /
        task_finished / thread_created。其余 data_type Phase 1+ 补全。
        """
        # Phase 0 占位实现 — 详细 fold 逻辑随 Applier 同期完善
        # 当前只确保 fold 不抛错, 实际 board 状态恢复留 Phase 1
        return

    # ── 公有 mutation 方法 (skeleton) ───────────────────────────────

    def create_thread(
        self,
        *,
        thread_id: str,
        origin: str,
        subkind: str,
        root_summary: str,
        by: str,
        created_at: datetime | None = None,
    ) -> Thread:
        with self._lock:
            if thread_id in self._threads:
                raise IllegalTransitionError(
                    f"thread {thread_id} already exists"
                )
            now = created_at or datetime.now().astimezone()
            thread = Thread(
                thread_id=thread_id,
                status="active",
                origin=origin,
                subkind=subkind,
                root_summary=root_summary,
                created_at=now,
                last_active_at=now,
            )
            self._threads[thread_id] = thread
            self._timeline.append_entry(
                data_type="thread_created",
                by=by,
                thread_id=thread_id,
                data={"origin": origin, "subkind": subkind},
            )
            return thread

    def append_msg(self, thread_id: str, msg: Msg, *, by: str) -> None:
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise IllegalTransitionError(f"thread {thread_id} missing")
            thread.msgs.append(msg)
            thread.last_active_at = datetime.now().astimezone()
            thread.senders.add(msg.source.sender_id)
            # 维护反查索引
            self._channelref_index[(msg.source.channel, msg.msg_id)] = thread_id
            self._sender_index.setdefault(
                (msg.source.channel, msg.source.sender_id), set()
            ).add(thread_id)
            self._timeline.append_entry(
                data_type="msg_received",
                by=by,
                thread_id=thread_id,
                msg_id=msg.msg_id,
                data={
                    "channel": msg.source.channel,
                    "sender_id": msg.source.sender_id,
                    "status": msg.status,
                },
            )

    def append_task(
        self, msg_id: str, intent: Intent, *, task_type: str, by: str
    ) -> Task:
        with self._lock:
            msg = self._find_msg(msg_id)
            if msg is None:
                raise IllegalTransitionError(f"msg {msg_id} missing")
            if msg.status not in {"awaiting_decision", "dispatched"}:
                self.record_rejection(
                    reason="illegal_transition",
                    offending_msg_id=msg_id,
                    original_action=task_type,
                    original_prompt_head=intent.prompt.split("\n", 1)[0][:80],
                )
                raise IllegalTransitionError(
                    f"msg {msg_id}.status={msg.status} cannot accept task"
                )
            task = Task(
                task_id=ulid_new(),
                status="queued",
                type=task_type,  # type: ignore[arg-type]
                intent=intent,
            )
            msg.tasks.append(task)
            prev = msg.status
            msg.status = "dispatched"
            self._timeline.append_entry(
                data_type="task_appended",
                by=by,
                thread_id=self._thread_of_msg(msg_id),
                msg_id=msg_id,
                task_id=task.task_id,
                data={"prev_status": prev, "status": "dispatched", "type": task_type},
            )
            return task

    # ── 内部 helper ────────────────────────────────────────────────

    def _find_msg(self, msg_id: str) -> Msg | None:
        for thread in self._threads.values():
            for msg in thread.msgs:
                if msg.msg_id == msg_id:
                    return msg
        return None

    def _thread_of_msg(self, msg_id: str) -> str | None:
        for thread in self._threads.values():
            for msg in thread.msgs:
                if msg.msg_id == msg_id:
                    return thread.thread_id
        return None

    # ── PA 可见接口 ────────────────────────────────────────────────

    def record_rejection(
        self,
        *,
        reason: str,
        offending_msg_id: str | None = None,
        offending_task_id: str | None = None,
        original_action: str = "",
        original_prompt_head: str = "",
    ) -> None:
        with self._lock:
            record = RejectionRecord(
                ts=datetime.now().astimezone(),
                reason=reason,
                offending_msg_id=offending_msg_id,
                offending_task_id=offending_task_id,
                original_action=original_action,
                original_prompt_head=original_prompt_head,
            )
            self._recent_rejections.append(record)
            self._timeline.append_entry(
                data_type="decision_rejected",
                by="board",
                msg_id=offending_msg_id,
                task_id=offending_task_id,
                data={
                    "reason": reason,
                    "original_action": original_action,
                    "original_prompt_head": original_prompt_head,
                },
            )

    def view_for_pa(self) -> dict:
        """返回 PA 心跳可见的 board 切片。Phase 1 完善 (thread 折叠 / recent_rejections)。"""
        with self._lock:
            return {
                "threads": [
                    {
                        "id": t.thread_id,
                        "subkind": t.subkind,
                        "status": t.status,
                        "root_summary": t.root_summary,
                        "msgs": [
                            {
                                "id": m.msg_id,
                                "status": m.status,
                                "tasks": [
                                    {"id": tk.task_id, "type": tk.type, "status": tk.status}
                                    for tk in m.tasks
                                ],
                            }
                            for m in t.msgs
                        ],
                    }
                    for t in self._threads.values()
                ],
                "recent_rejections": [
                    {
                        "ts": r.ts.isoformat(),
                        "reason": r.reason,
                        "offending_msg_id": r.offending_msg_id,
                        "offending_task_id": r.offending_task_id,
                        "original_action": r.original_action,
                        "original_prompt_head": r.original_prompt_head,
                    }
                    for r in self._recent_rejections
                ],
            }
