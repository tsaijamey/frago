"""BaseApplier: 抽象基类, 四个 Applier 共享 reject + record_rejection 逻辑。

四个具体 Applier:
- Ingestor (taskboard/ingestor.py) — 外部信道 & scheduled trigger ingress
- DecisionApplier (taskboard/decision_applier.py) — PA decisions JSON 路由
- ExecutionApplier (taskboard/execution_applier.py) — Executor 启动 / 完成回写
- ResumeApplier (taskboard/resume_applier.py) — resume action 三档路由

公共职责: 状态机校验 reject + record_rejection 写 timeline + 推 recent_rejections 滚动窗口。
"""

from __future__ import annotations

from frago.server.services.taskboard.board import TaskBoard


class BaseApplier:
    """Applier 抽象基类。"""

    name: str = "applier"

    def __init__(self, board: TaskBoard):
        self._board = board

    def _reject(
        self,
        *,
        reason: str,
        offending_msg_id: str | None = None,
        offending_task_id: str | None = None,
        original_action: str = "",
        original_prompt_head: str = "",
    ) -> None:
        """走 board.record_rejection 写 decision_rejected timeline + 推 recent_rejections."""
        self._board.record_rejection(
            reason=reason,
            offending_msg_id=offending_msg_id,
            offending_task_id=offending_task_id,
            original_action=original_action,
            original_prompt_head=original_prompt_head,
        )
