"""DecisionApplier: PA decisions JSON 路由器。

接收 PA 输出 list[dict], 按 action 词汇 (run/reply/resume/dismiss) 路由:
- 词汇校验 → reject reason=action_invalid
- prompt 格式校验 (首行 ≤80 + 空行 + 正文) → reject reason=prompt_format_invalid
- 状态机校验 (msg.status / task.status) → board 公有方法内部抛 IllegalTransitionError, 已 record_rejection
- 路由: run → append_task(type=run); reply → append_task(type=reply) + lifecycle.send_reply + mark_task_replied + close_msg_if_terminal; resume → ResumeApplier.route_resume; dismiss → board.mark_msg_dismissed

Phase 1 范围: 接口 + 词汇路由 + prompt 格式校验 + 集成 ResumeApplier。
Phase 1 后续 commit: PA wire-up (primary_agent_service._handle_pa_output 改调本类) + reply 推送集成 task_lifecycle。
"""

from __future__ import annotations

from frago.server.services.taskboard.applier import BaseApplier
from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import (
    IllegalTransitionError,
    Intent,
)
from frago.server.services.taskboard.resume_applier import ResumeApplier

# 4 action 词汇集 (Phase 1 freeze v1.1 §3 — 不含 schedule, schedule 走独立 SchedulerService 通路)
VALID_MSG_ACTIONS = {"run", "reply", "resume", "dismiss"}


class DecisionApplier(BaseApplier):
    name = "DecisionApplier"

    def __init__(self, board: TaskBoard, resume_applier: ResumeApplier | None = None):
        super().__init__(board)
        self._resume_applier = resume_applier or ResumeApplier(board)

    def handle_pa_output(self, decisions: list[dict]) -> None:
        """主路由入口, 接收 PA 输出 list[dict]."""
        for d in decisions:
            self._handle_one(d)

    def _handle_one(self, d: dict) -> None:
        action = d.get("action")
        if action not in VALID_MSG_ACTIONS:
            self._reject(
                reason="action_invalid",
                offending_msg_id=d.get("msg_id"),
                offending_task_id=d.get("task_id"),
                original_action=str(action or ""),
                original_prompt_head=(d.get("prompt") or "").split("\n", 1)[0][:80],
            )
            return

        prompt = d.get("prompt", "")
        if action in {"run", "reply", "resume"}:
            err = validate_prompt_format(prompt)
            if err:
                self._reject(
                    reason="prompt_format_invalid",
                    offending_msg_id=d.get("msg_id"),
                    offending_task_id=d.get("task_id"),
                    original_action=action,
                    original_prompt_head=prompt.split("\n", 1)[0][:80],
                )
                return

        msg_id = d.get("msg_id")
        task_id = d.get("task_id")

        try:
            if action == "run":
                self._board.append_task(
                    msg_id, Intent(prompt=prompt), task_type="run", by=self.name
                )
            elif action == "reply":
                task = self._board.append_task(
                    msg_id, Intent(prompt=prompt), task_type="reply", by=self.name
                )
                # Phase 1 后续 commit: lifecycle.send_reply(channel, payload) 集成
                # 当前仅落 task + mark_replied + close_msg, 不实际推送
                self._board.mark_task_replied(task.task_id, by=self.name) if hasattr(
                    self._board, "mark_task_replied"
                ) else None
                self._board.close_msg_if_terminal(msg_id, by=self.name) if hasattr(
                    self._board, "close_msg_if_terminal"
                ) else None
            elif action == "resume":
                self._resume_applier.route_resume(task_id, prompt)
            elif action == "dismiss":
                if hasattr(self._board, "mark_msg_dismissed"):
                    self._board.mark_msg_dismissed(
                        msg_id, reason=prompt or "(no reason)", by=self.name
                    )
                # Phase 1 后续 commit: board.mark_msg_dismissed 公有方法实装
        except IllegalTransitionError:
            # board 内部已 record_rejection, 不重复
            pass


def validate_prompt_format(prompt: str) -> str | None:
    """校验 PA prompt 格式: 首行 ≤80 字摘要 + 空行 + 正文。

    返回 None = 合法; 返回 str = 非法理由。
    Phase 1 范围: 严格校验首行长度 + 含空行分隔。
    """
    if not prompt:
        return "prompt is empty"
    parts = prompt.split("\n", 2)
    if len(parts) < 2:
        return "prompt missing newline (need '首行摘要\\n\\n正文')"
    first_line = parts[0]
    if len(first_line) > 80:
        return f"first line length {len(first_line)} > 80 chars"
    if "```" in first_line:
        return "first line contains code fence"
    # 第二行必须是空 (摘要 + 空行 + 正文)
    if len(parts) >= 2 and parts[1].strip() != "":
        return "missing blank line between summary and body"
    return None
