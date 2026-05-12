"""ResumeApplier: resume action 三档路由器。

按 task.status 分流:
- completed / failed (session 已结束) → Case A: Executor.spawn_resume(csid, prompt) → 新 run_id, CSID 沿用
- executing (session 在跑) → Case B: ResumeInbox.enqueue + board.record_resume_pending (复用 spec 20260501)
- queued / replied / not_found → reject

Case A CSID 失效 (ClaudeSessionNotFoundError) → task.status=resume_failed (新终态) + timeline resume_csid_lost.

Phase 1 stage-gate: Case A 默认 disabled (FRAGO_CASE_A_ENABLED=1 才启用),
未启用期 resume completed/failed task → reject(reason=case_a_not_implemented).
"""

from __future__ import annotations

import os

from frago.server.services.taskboard.applier import BaseApplier
from frago.server.services.taskboard.models import ClaudeSessionNotFoundError


def case_a_enabled() -> bool:
    """Phase 1 灰度开关. 默认 False, 通过 env var 显式启用。"""
    return os.environ.get("FRAGO_CASE_A_ENABLED", "0") == "1"


class ResumeApplier(BaseApplier):
    name = "ResumeApplier"

    def __init__(self, board, executor=None, resume_inbox=None):
        super().__init__(board)
        self._executor = executor  # Phase 1 后续 commit 注入实际 Executor
        self._resume_inbox = resume_inbox  # Phase 1 后续 commit 注入 ResumeInbox

    def route_resume(self, task_id: str | None, prompt: str) -> None:
        if not task_id:
            self._reject(
                reason="task_id_missing",
                original_action="resume",
                original_prompt_head=prompt.split("\n", 1)[0][:80] if prompt else "",
            )
            return

        task = self._board._find_task(task_id)
        if task is None:
            self._reject(
                reason="task_not_found",
                offending_task_id=task_id,
                original_action="resume",
                original_prompt_head=prompt.split("\n", 1)[0][:80] if prompt else "",
            )
            return

        # 非法状态: queued / replied / resume_failed
        if task.status in {"queued", "replied", "resume_failed"}:
            self._reject(
                reason="resume_illegal_state",
                offending_task_id=task_id,
                original_action="resume",
                original_prompt_head=prompt.split("\n", 1)[0][:80] if prompt else "",
            )
            return

        # Case A: session 已结束
        if task.status in {"completed", "failed"}:
            if not case_a_enabled():
                self._reject(
                    reason="case_a_not_implemented",
                    offending_task_id=task_id,
                    original_action="resume",
                    original_prompt_head=prompt.split("\n", 1)[0][:80] if prompt else "",
                )
                return
            if self._executor is None:
                self._reject(
                    reason="executor_not_wired",
                    offending_task_id=task_id,
                    original_action="resume",
                )
                return
            csid = task.session.claude_session_id if task.session else None
            try:
                new_run_id, new_pid = self._executor.spawn_resume(csid, prompt)
            except ClaudeSessionNotFoundError:
                self._mark_resume_failed(task_id, reason="resume_csid_lost", prev_csid=csid)
                return
            # 成功 spawn → 通过 ExecutionApplier.start_task 标记 (单一通路)
            # Phase 1 后续 commit: 注入 ExecutionApplier 并调用 start_task
            with self._board._lock:
                task.status = "executing"
                self._board._timeline.append_entry(
                    data_type="task_resumed_caseA",
                    by=self.name,
                    task_id=task_id,
                    data={"new_run_id": new_run_id, "new_pid": new_pid, "csid": csid},
                )
            return

        # Case B: session 在跑 (executing) → ResumeInbox 注入
        if task.status == "executing":
            if self._resume_inbox is None:
                # Phase 1 后续 commit: 注入实际 ResumeInbox 实例
                # 当前 fallback: 仅 record_resume_pending + 落 timeline, 不实际 enqueue
                with self._board._lock:
                    self._board._timeline.append_entry(
                        data_type="task_resume_pending_caseB",
                        by=self.name,
                        task_id=task_id,
                        data={"prompt_head": prompt.split("\n", 1)[0][:80]},
                    )
                return
            csid = task.session.claude_session_id if task.session else None
            self._resume_inbox.enqueue(csid, task_id, prompt)
            with self._board._lock:
                self._board._timeline.append_entry(
                    data_type="task_resume_pending_caseB",
                    by=self.name,
                    task_id=task_id,
                    data={"prompt_head": prompt.split("\n", 1)[0][:80]},
                )
            return

    def _mark_resume_failed(self, task_id: str, *, reason: str, prev_csid: str | None) -> None:
        with self._board._lock:
            task = self._board._find_task(task_id)
            if task is None:
                return
            task.status = "resume_failed"  # type: ignore[assignment]
            self._board._timeline.append_entry(
                data_type=reason,  # resume_csid_lost
                by=self.name,
                task_id=task_id,
                data={"prev_csid": prev_csid},
            )
