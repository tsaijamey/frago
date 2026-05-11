"""Ingestor: 外部信道 & scheduled trigger 进入 board 的唯一入口。

Phase 0: 仅 ingest_external (Ce Gap 3a 修订: scheduled fast-path 留 Phase 1)。
Phase 1: 增 ingest_scheduled(schedule_id, prompt, trigger_at, job_name)。
"""

from __future__ import annotations

from datetime import datetime

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import Msg, Source


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
