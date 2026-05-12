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


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


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

        Phase 0 重建路径: thread_created / msg_received / task_appended /
        task_started / task_finished / decision_rejected。fold 期间直接改
        内存字典, 不调公有 mutation (避免再写 timeline 造成循环)。
        """
        from frago.server.services.taskboard.models import (
            Intent,
            Msg,
            RejectionRecord,
            Result,
            Session,
            Source,
            Task,
        )

        data_type = entry.get("data_type")
        data = entry.get("data") or {}
        thread_id = entry.get("thread_id")
        msg_id = entry.get("msg_id")
        task_id = entry.get("task_id")
        ts_raw = entry.get("ts")
        ts = _parse_dt(ts_raw) if ts_raw else datetime.now().astimezone()

        if data_type == "thread_created":
            if thread_id and thread_id not in self._threads:
                self._threads[thread_id] = Thread(
                    thread_id=thread_id,
                    status=data.get("status", "active"),
                    origin=data.get("origin", "external"),
                    subkind=data.get("subkind", ""),
                    root_summary=data.get("root_summary", ""),
                    created_at=ts,
                    last_active_at=ts,
                )
            return

        if data_type == "msg_received":
            if not thread_id or not msg_id:
                return
            thread = self._threads.get(thread_id)
            if thread is None:
                thread = Thread(
                    thread_id=thread_id,
                    status="active",
                    origin=data.get("origin", "external"),
                    subkind=data.get("channel", ""),
                    root_summary="",
                    created_at=ts,
                    last_active_at=ts,
                )
                self._threads[thread_id] = thread
            if any(m.msg_id == msg_id for m in thread.msgs):
                return
            channel = data.get("channel", thread.subkind or "external")
            source = Source(
                channel=channel,
                text=data.get("prompt", ""),
                sender_id=data.get("sender_id", ""),
                parent_ref=data.get("parent_ref"),
                received_at=ts,
                reply_context=data.get("reply_context"),
            )
            msg = Msg(
                msg_id=msg_id,
                status=data.get("status", "awaiting_decision"),
                source=source,
            )
            thread.msgs.append(msg)
            thread.last_active_at = ts
            if source.sender_id:
                thread.senders.add(source.sender_id)
            self._channelref_index[(channel, msg_id)] = thread_id
            if source.sender_id:
                self._sender_index.setdefault(
                    (channel, source.sender_id), set()
                ).add(thread_id)
            return

        if data_type == "task_appended":
            msg = self._find_msg(msg_id) if msg_id else None
            if msg is None or not task_id:
                return
            if any(t.task_id == task_id for t in msg.tasks):
                return
            task_type = data.get("type", "run")
            msg.tasks.append(
                Task(
                    task_id=task_id,
                    status="queued",
                    type=task_type,  # type: ignore[arg-type]
                    intent=Intent(prompt=data.get("prompt", "")),
                )
            )
            new_status = data.get("status")
            if new_status:
                msg.status = new_status  # type: ignore[assignment]
            return

        if data_type == "task_started":
            task = self._find_task(task_id) if task_id else None
            if task is None:
                return
            task.status = "executing"
            task.session = Session(
                run_id=data.get("run_id") or task_id,
                claude_session_id=data.get("csid"),
                pid=data.get("pid"),
                started_at=_parse_dt(data.get("started_at")) or ts,
            )
            return

        if data_type == "task_finished":
            task = self._find_task(task_id) if task_id else None
            if task is None:
                return
            status = data.get("status", "completed")
            task.status = status if status in {"completed", "failed"} else "completed"  # type: ignore[assignment]
            if task.session is not None:
                task.session.ended_at = _parse_dt(data.get("ended_at"))
            task.result = Result(
                summary=data.get("result_summary") or "",
                error=data.get("error"),
            )
            return

        if data_type == "decision_rejected":
            self._recent_rejections.append(
                RejectionRecord(
                    ts=ts,
                    reason=data.get("reason", ""),
                    offending_msg_id=msg_id,
                    offending_task_id=task_id,
                    original_action=data.get("original_action", ""),
                    original_prompt_head=data.get("original_prompt_head", ""),
                )
            )
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

    def _find_task(self, task_id: str) -> Task | None:
        for thread in self._threads.values():
            for msg in thread.msgs:
                for task in msg.tasks:
                    if task.task_id == task_id:
                        return task
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


def boot(home: Path) -> TaskBoard:
    """Server 启动序列: (可选 migration) → fold timeline → 写 startup_fold_completed。

    Phase 0 范围: fold 两遍重建内存 + 写 4 字段 entry。
    Phase 2 范围: vacuum bounded-progress 加入 + entry 扩展为 6 字段
                  (vacuum_duration_ms / archived_threads_count)。

    Yi 23:49:25 锁定 Phase 0 字段集: {fold_duration_ms, entries_read,
    entries_skipped, timeline_bytes}。
    """
    import time

    from frago.server.services.taskboard import migration

    if migration.needs_migration(home):
        migration.migrate(home)

    timeline_path = home / "timeline" / "timeline.jsonl"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    if not timeline_path.exists():
        timeline_path.touch()

    t0 = time.monotonic()
    board = TaskBoard.fold(timeline_path)
    fold_ms = int((time.monotonic() - t0) * 1000)
    timeline_bytes = timeline_path.stat().st_size

    board._timeline.append_entry(
        data_type="startup_fold_completed",
        by="boot",
        data={
            "fold_duration_ms": fold_ms,
            "entries_read": board.entries_read,
            "entries_skipped": board.entries_skipped,
            "timeline_bytes": timeline_bytes,
        },
    )
    return board
