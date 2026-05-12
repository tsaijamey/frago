"""Ingestor: 外部信道 & scheduled trigger 进入 board 的唯一入口。

Phase 0: 仅 ingest_external (Ce Gap 3a 修订: scheduled fast-path 留 Phase 1)。
Phase 1: 增 ingest_scheduled(schedule_id, prompt, trigger_at, job_name)。
"""

from __future__ import annotations

from datetime import datetime

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import Intent, Msg, Source
from frago.server.services.taskboard.timeline import ulid_new


class Ingestor:
    def __init__(self, board: TaskBoard):
        self._board = board

    def ingest_external(
        self,
        *,
        channel: str,
        msg_id: str,
        sender_id: str,
        text: str,
        parent_ref: str | None,
        received_at: datetime,
        reply_context: dict | None,
        thread_id: str,
    ) -> Msg:
        """外部信道消息入 board (飞书 / 邮件 / webhook 共用此路径)。

        thread_id 由调用方 (scheduler + thread_classifier) 决定; Ingestor 不做归并。
        """
        msg = Msg(
            msg_id=f"{channel}:{msg_id}",
            status="received",
            source=Source(
                channel=channel,
                text=text,
                sender_id=sender_id,
                parent_ref=parent_ref,
                received_at=received_at,
                reply_context=reply_context,
            ),
        )
        self._board.append_msg(thread_id, msg, by="Ingestor")
        return msg

    def ingest_scheduled(
        self,
        *,
        schedule_id: str,
        prompt: str,
        trigger_at: datetime,
        job_name: str,
    ) -> Msg:
        """scheduled trigger fast-path (Yi B1 / Gap 3a 修订).

        - thread 不归并, 每次触发独立 (origin=scheduled, subkind=job_name)
        - Msg 状态: 通过 append_msg 进 received → append_task 自动转 dispatched
          (Phase 1 后续 commit 改成 真正 fast-path: Msg 直接 dispatched 跳过 awaiting_decision)
        - Source default: sender_id='__scheduler__', parent_ref=schedule_id
        - 同 transaction append type=run task with intent.prompt=锁定值
        """
        thread_id = ulid_new()
        self._board.create_thread(
            thread_id=thread_id,
            origin="scheduled",
            subkind=job_name,
            root_summary=prompt.split("\n", 1)[0][:80],
            by="Ingestor",
            created_at=trigger_at,
        )
        msg = Msg(
            msg_id=f"scheduled:{schedule_id}:{trigger_at.isoformat()}",
            status="awaiting_decision",  # 经过 append_task 后会转 dispatched
            source=Source(
                channel="scheduled",
                text=prompt,
                sender_id="__scheduler__",
                parent_ref=schedule_id,
                received_at=trigger_at,
                reply_context=None,
            ),
        )
        self._board.append_msg(thread_id, msg, by="Ingestor")
        self._board.append_task(
            msg.msg_id, Intent(prompt=prompt), task_type="run", by="Ingestor"
        )
        return msg
