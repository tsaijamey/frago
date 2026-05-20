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
        """主路由入口, 接收 PA 输出 list[dict].

        msg-closing is deferred to AFTER the whole batch is applied. PA
        commonly emits [reply(ack), run] in one decision — closing the msg
        the moment the reply lands would mark all-tasks-terminal before the
        run is appended, so the run would hit a closed msg and be rejected
        (illegal_transition) and never dispatch. Evaluating close once at
        the end lets the queued run keep the msg open.
        """
        reply_msg_ids: list[str] = []
        for d in decisions:
            affected = self._handle_one(d)
            if affected:
                reply_msg_ids.append(affected)
        seen: set[str] = set()
        for mid in reply_msg_ids:
            if mid in seen:
                continue
            seen.add(mid)
            self._board.close_msg_if_terminal(mid, by=self.name)

    def _handle_one(self, d: dict) -> str | None:
        """Route one decision. Returns the parent msg_id of a reply action
        (so the caller can evaluate close after the full batch), else None."""
        action = d.get("action")
        if action not in VALID_MSG_ACTIONS:
            self._reject(
                reason="action_invalid",
                offending_msg_id=d.get("msg_id"),
                offending_task_id=d.get("task_id"),
                original_action=str(action or ""),
                original_prompt_head=(d.get("prompt") or "").split("\n", 1)[0][:80],
            )
            return None

        prompt = d.get("prompt", "")
        # Only run/resume carry a sub-agent prompt subject to the
        # "首行摘要 + 空行 + 正文" contract. reply carries free-form `text`
        # (no `prompt`), so validating prompt-format on reply wrongly
        # rejected every reply with prompt_format_invalid — the board reply
        # task was never created and the parent msg never closed (the channel
        # push still happened via the separate _send_reply path, masking it).
        if action in {"run", "resume"}:
            err = validate_prompt_format(prompt)
            if err:
                self._reject(
                    reason="prompt_format_invalid",
                    offending_msg_id=d.get("msg_id"),
                    offending_task_id=d.get("task_id"),
                    original_action=action,
                    original_prompt_head=prompt.split("\n", 1)[0][:80],
                )
                return None

        msg_id = _normalize_msg_id(d.get("msg_id"), d.get("channel"))
        task_id = d.get("task_id")

        try:
            if action == "run":
                self._board.append_task(
                    msg_id, Intent(prompt=prompt), task_type="run", by=self.name
                )
            elif action == "reply":
                # Resolve the parent msg. PA replies either by msg_id (new
                # message) or by task_id (replying to a finished run's
                # result). The task_id path must still attach the reply to the
                # parent msg so it can be closed (deferred to end of batch by
                # handle_pa_output) — otherwise the msg lingers in `dispatched`
                # and a later reflection tick judges it unanswered and
                # re-replies, re-sending the same artefact.
                reply_msg_id = msg_id
                if not reply_msg_id and task_id:
                    parent = self._board.get_msg_for_task(task_id)
                    reply_msg_id = parent.msg_id if parent else None
                if reply_msg_id:
                    task = self._board.append_task(
                        reply_msg_id, Intent(prompt=prompt),
                        task_type="reply", by=self.name,
                    )
                    self._board.mark_task_replied(task.task_id, by=self.name)
                    return reply_msg_id
            elif action == "resume":
                self._resume_applier.route_resume(task_id, prompt)
            elif action == "dismiss" and hasattr(self._board, "mark_msg_dismissed"):
                self._board.mark_msg_dismissed(
                    msg_id, reason=prompt or "(no reason)", by=self.name
                )
        except IllegalTransitionError as e:
            # board records its own rejection for archived/status-violation
            # paths. The "msg missing" path raises before recording — surface
            # that here so PA's recent_rejections shows the lookup failure
            # instead of the action vanishing silently (sub-agent never
            # launches, no trace, no warning).
            err_text = str(e)
            if "missing" in err_text:
                self._reject(
                    reason="msg_not_found",
                    offending_msg_id=msg_id,
                    offending_task_id=task_id,
                    original_action=action,
                    original_prompt_head=prompt.split("\n", 1)[0][:80],
                )
        return None


def _normalize_msg_id(msg_id: str | None, channel: str | None) -> str | None:
    """Prepend {channel}: prefix when PA gave the raw msg_id.

    PA sees msg_id via PA_MESSAGE_TEMPLATE which renders the unprefixed
    `channel_message_id` (e.g. `om_x100b...`). Board stores the prefixed
    form (e.g. `feishu:om_x100b...`) — that mismatch makes _find_msg miss
    and IllegalTransitionError gets swallowed silently, so the run task
    never lands and the executor never picks anything up. Scheduled msgs
    already arrive in `scheduled:...` shape, so only prefix when missing.
    """
    if not msg_id or not channel:
        return msg_id
    prefix = f"{channel}:"
    if msg_id.startswith(prefix):
        return msg_id
    return f"{prefix}{msg_id}"


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
