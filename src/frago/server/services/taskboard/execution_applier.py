"""ExecutionApplier: Executor 启动 / 完成回写 board.

接口:
- start_task(task_id, run_id, pid, csid) — Executor spawn 后调
- finish_task(task_id, result, error) — sub-agent 完成 / 失败时调

Spec 20260512 v1.2 freeze: board.timeline.jsonl 是唯一持久化源,
executor 直接调本类(及 board public methods)无 TaskStore 旁路.
"""

from __future__ import annotations

from datetime import datetime

from frago.server.services.taskboard.applier import BaseApplier
from frago.server.services.taskboard.models import (
    IllegalTransitionError,
    Result,
    Session,
)


class ExecutionApplier(BaseApplier):
    name = "ExecutionApplier"

    def start_task(
        self,
        task_id: str,
        *,
        run_id: str,
        pid: int,
        csid: str | None,
        started_at: datetime | None = None,
    ) -> None:
        with self._board._lock:
            task = self._board._find_task(task_id)
            if task is None:
                self._reject(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="start_task",
                )
                return
            if task.status not in {"queued", "executing"}:
                self._reject(
                    reason="illegal_transition",
                    offending_task_id=task_id,
                    original_action="start_task",
                )
                raise IllegalTransitionError(
                    f"task {task_id}.status={task.status} cannot start"
                )
            task.status = "executing"
            task.session = Session(
                run_id=run_id,
                claude_session_id=csid,
                pid=pid,
                started_at=started_at or datetime.now().astimezone(),
            )
            self._board._timeline.append_entry(
                data_type="task_started",
                by=self.name,
                task_id=task_id,
                data={"run_id": run_id, "pid": pid, "csid": csid},
            )

    def finish_task(
        self,
        task_id: str,
        *,
        result_summary: str = "",
        error: str | None = None,
        status: str = "completed",
    ) -> None:
        with self._board._lock:
            task = self._board._find_task(task_id)
            if task is None:
                self._reject(
                    reason="task_not_found",
                    offending_task_id=task_id,
                    original_action="finish_task",
                )
                return
            if task.status != "executing":
                self._reject(
                    reason="illegal_transition",
                    offending_task_id=task_id,
                    original_action="finish_task",
                )
                raise IllegalTransitionError(
                    f"task {task_id}.status={task.status} cannot finish"
                )
            task.status = "completed" if status == "completed" else "failed"  # type: ignore[assignment]
            if task.session is not None:
                task.session.ended_at = datetime.now().astimezone()
            task.result = Result(summary=result_summary, error=error)
            self._board._timeline.append_entry(
                data_type="task_finished",
                by=self.name,
                task_id=task_id,
                data={"status": task.status, "result_summary": result_summary, "error": error},
            )
