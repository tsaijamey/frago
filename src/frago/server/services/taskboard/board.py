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

    # ── fold (两遍算法; 实现迁到 taskboard.fold 模块) ───────────────

    @classmethod
    def fold(cls, timeline_path: Path) -> TaskBoard:
        """从 timeline.jsonl 重建内存投影 (thin wrapper around fold.fold).

        Two-pass algorithm (T5.1):
        - First pass: collect ``archived_thread_ids`` (data_type=='thread_archived')
        - Second pass: replay entries, skip those whose thread_id is in the set

        Phase finish: 算法主体迁入 ``frago.server.services.taskboard.fold``;
        本方法保留为 backward-compat 入口, 行为不变.
        """
        from frago.server.services.taskboard.fold import fold as _fold

        return _fold(timeline_path)

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
                    tags=list(data.get("tags") or []),
                    run_instance_id=data.get("run_instance_id"),
                )
            return

        if data_type == "thread_tag_added":
            thread = self._threads.get(thread_id) if thread_id else None
            tag = data.get("tag")
            if thread and tag and tag not in thread.tags:
                thread.tags.append(tag)
            return

        if data_type == "thread_touched":
            thread = self._threads.get(thread_id) if thread_id else None
            if thread:
                new_ts = _parse_dt(data.get("ts")) or ts
                if new_ts > thread.last_active_at:
                    thread.last_active_at = new_ts
                if thread.status == "dormant":
                    thread.status = "active"  # type: ignore[assignment]
            return

        if data_type == "thread_bound_to_run":
            thread = self._threads.get(thread_id) if thread_id else None
            if thread:
                thread.run_instance_id = data.get("run_instance_id")
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
                    created_at=ts,
                )
            )
            new_status = data.get("status")
            if new_status:
                msg.status = new_status  # type: ignore[assignment]
            return

        if data_type == "task_state":
            task = self._find_task(task_id) if task_id else None
            if task is None:
                return
            new_status = data.get("status")
            if new_status in {
                "queued", "executing", "completed", "failed",
                "resume_failed", "replied",
            }:
                task.status = new_status  # type: ignore[assignment]
                if new_status == "completed":
                    summary = data.get("result_summary") or ""
                    task.result = Result(summary=summary)
                elif new_status == "failed":
                    err = data.get("error") or ""
                    task.result = Result(summary="", error=err)
            return

        if data_type == "task_session_updated":
            task = self._find_task(task_id) if task_id else None
            if task is None:
                return
            task.session = Session(
                run_id=data.get("run_id") or task_id,
                claude_session_id=data.get("csid"),
                pid=data.get("pid"),
                started_at=_parse_dt(data.get("started_at")) or ts,
            )
            return

        if data_type == "task_retry":
            task = self._find_task(task_id) if task_id else None
            if task is None:
                return
            new_count = data.get("retry_count")
            if isinstance(new_count, int):
                task.retry_count = new_count
            return

        if data_type == "task_recovery":
            task = self._find_task(task_id) if task_id else None
            if task is None:
                return
            new_count = data.get("recovery_count")
            if isinstance(new_count, int):
                task.recovery_count = new_count
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
        tags: list[str] | None = None,
    ) -> Thread:
        with self._lock:
            if thread_id in self._threads:
                raise IllegalTransitionError(
                    f"thread {thread_id} already exists"
                )
            now = created_at or datetime.now().astimezone()
            tag_list = [t for t in (tags or []) if t]
            thread = Thread(
                thread_id=thread_id,
                status="active",
                origin=origin,
                subkind=subkind,
                root_summary=root_summary,
                created_at=now,
                last_active_at=now,
                tags=list(tag_list),
            )
            self._threads[thread_id] = thread
            self._timeline.append_entry(
                data_type="thread_created",
                by=by,
                thread_id=thread_id,
                data={
                    "origin": origin,
                    "subkind": subkind,
                    "root_summary": root_summary,
                    "tags": list(tag_list),
                },
            )
            return thread

    def append_msg(self, thread_id: str, msg: Msg, *, by: str) -> None:
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise IllegalTransitionError(f"thread {thread_id} missing")
            # Phase 2: post-archive append 走 reject 通道, 不抛 + 不改 thread.
            if thread.status == "archived":
                self.record_rejection(
                    reason="post_archive_append",
                    offending_msg_id=msg.msg_id,
                    original_action="append_msg",
                    original_prompt_head=msg.source.text.split("\n", 1)[0][:80],
                )
                return
            # Phase 1 part B: 重复响应根因消除 — 同 msg_id 重复 ingest 直接 dedup,
            # 落 timeline duplicate_msg_ingest 让 PA 可见 (recent_rejections), 不重复 append.
            # 这是替代 message_cache 兜底的核心修复.
            if any(m.msg_id == msg.msg_id for m in thread.msgs):
                self._timeline.append_entry(
                    data_type="duplicate_msg_ingest",
                    by=by,
                    thread_id=thread_id,
                    msg_id=msg.msg_id,
                    data={"channel": msg.source.channel},
                )
                return
            # spec §2: received → awaiting_decision 立即转换 (心跳前).
            # Phase 0 未实施, Phase 1 part B 在 append_msg 内自动转 (scheduled fast-path
            # 在 Ingestor.ingest_scheduled 后续 append_task 时直接 dispatch, 此处不影响).
            if msg.status == "received":
                msg.status = "awaiting_decision"  # type: ignore[assignment]
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
            # Phase 2: thread archived 后 append_task 走 reject 通道.
            thread_id = self._thread_of_msg(msg_id)
            if thread_id and self._threads[thread_id].status == "archived":
                self.record_rejection(
                    reason="post_archive_append",
                    offending_msg_id=msg_id,
                    original_action=task_type,
                    original_prompt_head=intent.prompt.split("\n", 1)[0][:80],
                )
                raise IllegalTransitionError(
                    f"thread {thread_id} is archived, cannot append task"
                )
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
                created_at=datetime.now().astimezone(),
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
                data={
                    "prev_status": prev,
                    "status": "dispatched",
                    "type": task_type,
                    "prompt": intent.prompt,
                },
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

    # ── 公有 mutation 方法 — Phase 1 part B 补 (Applier 调用) ──

    def mark_task_replied(self, task_id: str, *, by: str) -> None:
        """reply task 推送完成后调用. task.status = 'replied' + 落 timeline."""
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="mark_replied",
                )
                return
            if task.type != "reply":
                self.record_rejection(
                    reason="illegal_transition",
                    offending_task_id=task_id,
                    original_action="mark_replied",
                )
                return
            task.status = "replied"  # type: ignore[assignment]
            self._timeline.append_entry(
                data_type="task_replied",
                by=by,
                task_id=task_id,
                data={"status": "replied"},
            )

    def close_msg_if_terminal(self, msg_id: str, *, by: str) -> None:
        """全部 task 终态 + 至少 1 个 reply 已 replied → msg.status = closed."""
        with self._lock:
            msg = self._find_msg(msg_id)
            if msg is None:
                return
            if msg.status in {"closed", "dismissed"}:
                return
            terminal_statuses = {"completed", "failed", "replied", "resume_failed"}
            all_terminal = all(t.status in terminal_statuses for t in msg.tasks)
            has_replied = any(
                t.type == "reply" and t.status == "replied" for t in msg.tasks
            )
            if all_terminal and has_replied:
                prev = msg.status
                msg.status = "closed"
                self._timeline.append_entry(
                    data_type="msg_closed",
                    by=by,
                    thread_id=self._thread_of_msg(msg_id),
                    msg_id=msg_id,
                    data={"prev_status": prev, "status": "closed"},
                )

    def record_thread_archived(
        self, thread_id: str, *, by: str, archived_to: str | None = None
    ) -> None:
        """Phase 2 vacuum: 把 thread 标记为 archived 并落 marker.

        marker schema (Yi #92):
            data_type='thread_archived', thread_id=<tid>,
            data={archived_at: <iso>, archived_to: 'archive/<tid>.jsonl',
                  by: <vacuum|applier|user>}

        runtime 调用 (applier / user CLI) 只标记 thread.status='archived' + 落
        marker; 下次 server 启动时 vacuum 物理抽 entries 到 archive 目录.

        重复 archive 同 thread_id 落 duplicate_marker reject entry (不抛).
        """
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                self.record_rejection(
                    reason="thread_not_found",
                    offending_msg_id=None,
                    original_action="record_thread_archived",
                )
                return
            if thread.status == "archived":
                self.record_rejection(
                    reason="duplicate_marker",
                    offending_msg_id=None,
                    original_action="record_thread_archived",
                )
                return
            thread.status = "archived"  # type: ignore[assignment]
            target = archived_to or f"archive/{thread_id}.jsonl"
            self._timeline.append_entry(
                data_type="thread_archived",
                by=by,
                thread_id=thread_id,
                data={
                    "archived_at": datetime.now().astimezone().isoformat(),
                    "archived_to": target,
                    "by": by,
                },
            )

    # ── B-2b 新公有方法 (取代 thread_service.ThreadStore) ──────────────

    def add_tag(self, thread_id: str, tag: str, *, by: str) -> None:
        """Append tag to thread.tags (idempotent). 写 timeline thread_tag_added.

        B-2b: 替代 ThreadStore.add_tag. tag 通常为 channelref:<channel>:<msg_id>
        或 sender:<channel>:<sender>; thread_classifier ensure_thread 调用.
        """
        if not tag:
            return
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                self.record_rejection(
                    reason="thread_not_found",
                    original_action="add_tag",
                )
                return
            if tag in thread.tags:
                return
            thread.tags.append(tag)
            self._timeline.append_entry(
                data_type="thread_tag_added",
                by=by,
                thread_id=thread_id,
                data={"tag": tag},
            )

    def touch_thread(
        self, thread_id: str, *, by: str, ts: datetime | None = None
    ) -> None:
        """Advance thread.last_active_at; dormant → active. 写 thread_touched.

        B-2b: 替代 ThreadStore.touch. classifier 在归并已有 thread 时调用.
        """
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                return
            new_ts = ts or datetime.now().astimezone()
            if new_ts <= thread.last_active_at and thread.status != "dormant":
                return
            if new_ts > thread.last_active_at:
                thread.last_active_at = new_ts
            if thread.status == "dormant":
                thread.status = "active"  # type: ignore[assignment]
            self._timeline.append_entry(
                data_type="thread_touched",
                by=by,
                thread_id=thread_id,
                data={"ts": new_ts.isoformat()},
            )

    def bind_run(
        self, thread_id: str, run_instance_id: str, *, by: str
    ) -> None:
        """Attach run_instance_id to thread (idempotent). 写 thread_bound_to_run.

        B-2b: 替代 ThreadStore.bind_run. executor._get_or_create_run_for_thread
        在确定/重新绑定 run 时调用. Yi #94 (b'): mutation 返回 None.
        """
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                self.record_rejection(
                    reason="thread_not_found",
                    original_action="bind_run",
                )
                return
            if thread.run_instance_id == run_instance_id:
                return
            thread.run_instance_id = run_instance_id
            self._timeline.append_entry(
                data_type="thread_bound_to_run",
                by=by,
                thread_id=thread_id,
                data={"run_instance_id": run_instance_id},
            )

    def _thread_to_dict(self, t: Thread) -> dict:
        """Yi #94 (b'): board 公有方法返回 dict 风格. 序列化 Thread → dict."""
        return {
            "thread_id": t.thread_id,
            "status": t.status,
            "origin": t.origin,
            "subkind": t.subkind,
            "root_summary": t.root_summary,
            "created_at": t.created_at.isoformat(),
            "last_active_at": t.last_active_at.isoformat(),
            "tags": list(t.tags),
            "run_instance_id": t.run_instance_id,
            "senders": sorted(t.senders),
            "msg_count": len(t.msgs),
            "task_ids": [
                tk.task_id for m in t.msgs for tk in m.tasks
            ],
        }

    def search_threads_by_tag(self, tag: str) -> list[dict]:
        """B-2b L1 classifier 替代: 按 tag 精确匹配返回 thread dict 列表.

        排序: last_active_at desc. 仅包含 status ∈ {active, dormant} 的 thread
        (closed/archived 不参与 classifier 归并).
        """
        if not tag:
            return []
        with self._lock:
            matches = [
                t for t in self._threads.values()
                if tag in t.tags and t.status in {"active", "dormant"}
            ]
            matches.sort(key=lambda t: t.last_active_at, reverse=True)
            return [self._thread_to_dict(t) for t in matches]

    def search_threads_by_sender(
        self, channel: str, sender: str, *, active_only: bool = True
    ) -> list[dict]:
        """B-2b L2 classifier 替代: 同 channel 同 sender 的 thread.

        组合 sender:<channel>:<sender> tag + subkind=channel 过滤.
        active_only=True 时仅含 status==active. 排序 last_active_at desc.
        """
        if not channel or not sender:
            return []
        sender_label = f"sender:{channel}:{sender}"
        target_status = {"active"} if active_only else {"active", "dormant"}
        with self._lock:
            matches = [
                t for t in self._threads.values()
                if t.subkind == channel
                and sender_label in t.tags
                and t.status in target_status
            ]
            matches.sort(key=lambda t: t.last_active_at, reverse=True)
            return [self._thread_to_dict(t) for t in matches]

    def list_threads(
        self, *, statuses: set[str] | None = None
    ) -> list[dict]:
        """B-2b: 替代 ThreadStore.get_all/count. timeline_service.get_thread_context 用.

        statuses=None 返回全部. 否则按 status 集合过滤. 排序 last_active_at desc.
        """
        target = statuses if statuses is not None else {
            "active", "dormant", "closed", "archived"
        }
        with self._lock:
            matches = [t for t in self._threads.values() if t.status in target]
            matches.sort(key=lambda t: t.last_active_at, reverse=True)
            return [self._thread_to_dict(t) for t in matches]

    def get_thread(self, thread_id: str) -> dict | None:
        """B-2b: 替代 ThreadStore.get. dict 风格 (Yi #94 b')."""
        with self._lock:
            t = self._threads.get(thread_id)
            return self._thread_to_dict(t) if t else None

    # ── Executor-facing API (single-source: replaces TaskStore.* lookups) ──
    # All mutations enter via the _lock and write a timeline entry so the
    # board (timeline.jsonl) is the only persistence layer.

    def get_task(self, task_id: str) -> Task | None:
        """Return the live Task object (or None). Read-only — no timeline entry."""
        with self._lock:
            return self._find_task(task_id)

    def get_msg_for_task(self, task_id: str) -> Msg | None:
        """Reverse lookup: which Msg owns this task_id (or None)."""
        with self._lock:
            for thread in self._threads.values():
                for msg in thread.msgs:
                    for tk in msg.tasks:
                        if tk.task_id == task_id:
                            return msg
            return None

    def get_thread_for_task(self, task_id: str) -> Thread | None:
        """Reverse lookup: which Thread owns this task_id (or None)."""
        with self._lock:
            for thread in self._threads.values():
                for msg in thread.msgs:
                    for tk in msg.tasks:
                        if tk.task_id == task_id:
                            return thread
            return None

    def get_queued_tasks(self) -> list[Task]:
        """All tasks with status=='queued' across every thread/msg.

        Returned in insertion order (board scan order). Executor uses this to
        discover new work each tick — replaces TaskStore.get_by_status(QUEUED).
        """
        with self._lock:
            out: list[Task] = []
            for thread in self._threads.values():
                for msg in thread.msgs:
                    for tk in msg.tasks:
                        if tk.status == "queued":
                            out.append(tk)
            return out

    def get_executing_tasks(self) -> list[Task]:
        """All tasks with status=='executing'. Daemon zombie-scan callers."""
        with self._lock:
            out: list[Task] = []
            for thread in self._threads.values():
                for msg in thread.msgs:
                    for tk in msg.tasks:
                        if tk.status == "executing":
                            out.append(tk)
            return out

    def increment_retry_count(self, task_id: str, *, by: str) -> int:
        """Bump task.retry_count by 1, append timeline task_retry entry.

        Returns the new count. Returns 0 + reject if task missing.
        """
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="increment_retry_count",
                )
                return 0
            task.retry_count += 1
            new_count = task.retry_count
            self._timeline.append_entry(
                data_type="task_retry",
                by=by,
                thread_id=self._thread_of_task(task_id),
                msg_id=self._msg_id_of_task(task_id),
                task_id=task_id,
                data={"retry_count": new_count},
            )
            return new_count

    def increment_recovery_count(self, task_id: str, *, by: str) -> int:
        """Bump task.recovery_count by 1, append timeline task_recovery entry."""
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="increment_recovery_count",
                )
                return 0
            task.recovery_count += 1
            new_count = task.recovery_count
            self._timeline.append_entry(
                data_type="task_recovery",
                by=by,
                thread_id=self._thread_of_task(task_id),
                msg_id=self._msg_id_of_task(task_id),
                task_id=task_id,
                data={"recovery_count": new_count},
            )
            return new_count

    def update_task_session(
        self,
        task_id: str,
        *,
        run_id: str,
        claude_session_id: str | None,
        pid: int | None,
        started_at: datetime | None = None,
        by: str,
    ) -> None:
        """Set / replace Task.session and append task_session_updated timeline entry.

        Used by executor to record run_id / claude_session_id / pid as the
        sub-agent process is launched (or rebound on resume). The status
        transition itself goes through ``mark_task_executing`` /
        ``ExecutionApplier.start_task``; this method is the field-level write.
        """
        from frago.server.services.taskboard.models import Session as _Session
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="update_task_session",
                )
                return
            task.session = _Session(
                run_id=run_id,
                claude_session_id=claude_session_id,
                pid=pid,
                started_at=started_at or datetime.now().astimezone(),
            )
            self._timeline.append_entry(
                data_type="task_session_updated",
                by=by,
                thread_id=self._thread_of_task(task_id),
                msg_id=self._msg_id_of_task(task_id),
                task_id=task_id,
                data={
                    "run_id": run_id,
                    "csid": claude_session_id,
                    "pid": pid,
                },
            )

    def mark_task_executing(self, task_id: str, *, by: str) -> None:
        """status queued → executing. Appends task_state timeline entry.

        For setting session fields use ``update_task_session`` after this call
        (or rely on ExecutionApplier.start_task which does both in one shot).
        """
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="mark_task_executing",
                )
                return
            if task.status == "executing":
                return
            if task.status != "queued":
                self.record_rejection(
                    reason="illegal_transition",
                    offending_task_id=task_id,
                    original_action="mark_task_executing",
                )
                raise IllegalTransitionError(
                    f"task {task_id}.status={task.status} cannot move to executing"
                )
            prev = task.status
            task.status = "executing"
            self._timeline.append_entry(
                data_type="task_state",
                by=by,
                thread_id=self._thread_of_task(task_id),
                msg_id=self._msg_id_of_task(task_id),
                task_id=task_id,
                data={"prev_status": prev, "status": "executing"},
            )

    def mark_task_completed(
        self, task_id: str, *, summary: str, by: str
    ) -> None:
        """status executing → completed + record Result. Appends task_state."""
        from frago.server.services.taskboard.models import Result as _Result
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="mark_task_completed",
                )
                return
            if task.status == "completed":
                return
            prev = task.status
            task.status = "completed"
            task.result = _Result(summary=summary or "")
            if task.session is not None:
                task.session.ended_at = datetime.now().astimezone()
            self._timeline.append_entry(
                data_type="task_state",
                by=by,
                thread_id=self._thread_of_task(task_id),
                msg_id=self._msg_id_of_task(task_id),
                task_id=task_id,
                data={
                    "prev_status": prev,
                    "status": "completed",
                    "result_summary": (summary or "")[:200],
                },
            )

    def mark_task_failed(
        self, task_id: str, *, error: str, by: str
    ) -> None:
        """status → failed + record Result.error. Appends task_state."""
        from frago.server.services.taskboard.models import Result as _Result
        with self._lock:
            task = self._find_task(task_id)
            if task is None:
                self.record_rejection(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="mark_task_failed",
                )
                return
            if task.status == "failed":
                return
            prev = task.status
            task.status = "failed"
            task.result = _Result(summary="", error=error or "")
            if task.session is not None:
                task.session.ended_at = datetime.now().astimezone()
            self._timeline.append_entry(
                data_type="task_state",
                by=by,
                thread_id=self._thread_of_task(task_id),
                msg_id=self._msg_id_of_task(task_id),
                task_id=task_id,
                data={
                    "prev_status": prev,
                    "status": "failed",
                    "error": (error or "")[:200],
                },
            )

    # ── private reverse-lookup helpers (must hold _lock) ─────────────────

    def _thread_of_task(self, task_id: str) -> str | None:
        for thread in self._threads.values():
            for msg in thread.msgs:
                for tk in msg.tasks:
                    if tk.task_id == task_id:
                        return thread.thread_id
        return None

    def _msg_id_of_task(self, task_id: str) -> str | None:
        for thread in self._threads.values():
            for msg in thread.msgs:
                for tk in msg.tasks:
                    if tk.task_id == task_id:
                        return msg.msg_id
        return None

    def mark_msg_dismissed(self, msg_id: str, *, reason: str, by: str) -> None:
        """PA dismiss action 路径: msg.status = dismissed (终态, 不再 dispatch)."""
        with self._lock:
            msg = self._find_msg(msg_id)
            if msg is None:
                self.record_rejection(
                    reason="msg_not_found",
                    offending_msg_id=msg_id,
                    original_action="dismiss",
                )
                return
            if msg.status in {"closed", "dismissed"}:
                return
            prev = msg.status
            msg.status = "dismissed"
            self._timeline.append_entry(
                data_type="msg_dismissed",
                by=by,
                thread_id=self._thread_of_msg(msg_id),
                msg_id=msg_id,
                data={"prev_status": prev, "status": "dismissed", "reason": reason},
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
                                "channel": m.source.channel,
                                "sender_id": m.source.sender_id,
                                "reply_context": (
                                    dict(m.source.reply_context)
                                    if m.source.reply_context else None
                                ),
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
    """Server 启动序列: (可选 migration) → vacuum → fold → startup_fold_completed.

    Phase 0 范围: fold 两遍重建内存 + 写 4 字段 entry.
    Phase 2 范围: vacuum bounded-progress 加入 + entry 扩展为 6 字段
                  (vacuum_duration_ms / archived_threads_count).

    Yi #92 锁定 Phase 2 字段集: {fold_duration_ms, vacuum_duration_ms,
    entries_read, entries_skipped, timeline_bytes, archived_threads_count}.
    """
    import time

    from frago.server.services.taskboard import migration
    from frago.server.services.taskboard import vacuum as vac

    if migration.needs_migration(home):
        migration.migrate(home)

    timeline_path = home / "timeline" / "timeline.jsonl"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    if not timeline_path.exists():
        timeline_path.touch()

    # Phase 2: bounded vacuum 在 fold 之前 (markers > 0 时实际处理).
    vac_t0 = time.monotonic()
    vac_report = vac.run_bounded_vacuum(home)
    vacuum_ms = int((time.monotonic() - vac_t0) * 1000)

    fold_t0 = time.monotonic()
    board = TaskBoard.fold(timeline_path)
    fold_ms = int((time.monotonic() - fold_t0) * 1000)
    timeline_bytes = timeline_path.stat().st_size

    board._timeline.append_entry(
        data_type="startup_fold_completed",
        by="boot",
        data={
            "fold_duration_ms": fold_ms,
            "vacuum_duration_ms": vacuum_ms,
            "entries_read": board.entries_read,
            "entries_skipped": board.entries_skipped,
            "timeline_bytes": timeline_bytes,
            "archived_threads_count": vac_report.processed,
        },
    )
    return board
