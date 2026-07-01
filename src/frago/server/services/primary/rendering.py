"""PA 队列消息 → prompt 文本的渲染（Phase 4 抽出）。

从 primary_agent_service.py 搬来：`format_queue_messages` 把一批队列消息渲染成喂给 PA 的
单块文本。它唯一的状态写入是 `svc._schedule_msg_map`（scheduled_task 的 msg_id→schedule_id
映射），故接 `svc` 首参；其余全是 msg dict + 模板。行为与原 _format_queue_messages 逐字一致。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from frago.server.services.pa_prompts import (
    PA_AGENT_COMPLETED_TEMPLATE,
    PA_AGENT_FAILED_TEMPLATE,
    PA_MERGED_MESSAGES_TEMPLATE,
    PA_MESSAGE_TEMPLATE,
    PA_QUEUE_GROUP_LINE_TEMPLATE,
    PA_QUEUE_LAST_STATUS_LINE_TEMPLATE,
    PA_QUEUE_LOGS_SECTION_TEMPLATE,
    PA_QUEUE_OUTPUTS_LINE_TEMPLATE,
    PA_QUEUE_PARAMS_LINE_TEMPLATE,
    PA_QUEUE_RECIPE_LINE_TEMPLATE,
    PA_QUEUE_RECOVERED_NOTE,
    PA_QUEUE_TIME_HEADER_TEMPLATE,
    PA_QUEUE_UNKNOWN_FALLBACK_TEMPLATE,
    PA_RECOVERED_FAILED_TASK_TEMPLATE,
    PA_REPLY_FAILED_TEMPLATE,
    PA_SCHEDULED_TASK_TEMPLATE,
)


def format_logs_section(recent_logs: list[str]) -> str:
    """Format recent log lines into PA_QUEUE_LOGS_SECTION_TEMPLATE body."""
    if not recent_logs:
        return ""
    body = "\n".join(f"  {line}" for line in recent_logs)
    return PA_QUEUE_LOGS_SECTION_TEMPLATE.format(logs_body=body)


def format_queue_messages(svc: Any, messages: list[dict[str, Any]]) -> str:
    """Format a batch of queued messages into a single text block for PA.

    svc 仅用于写 scheduled_task 的 ``_schedule_msg_map``（保持原副作用）。
    """
    now = datetime.now()
    msg_parts: list[str] = []
    msg_parts.append(PA_QUEUE_TIME_HEADER_TEMPLATE.format(
        current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
    ))

    for msg in messages:
        msg_type = msg.get("type", "unknown")
        msg_parts.append("")

        if msg_type == "user_message":
            recovered_note = PA_QUEUE_RECOVERED_NOTE if msg.get("_recovered") else ""
            channel_name = msg.get("channel", "?")
            reply_ctx = msg.get("reply_context") or {}
            chat_name = reply_ctx.get("chat_name")
            group_line = (
                PA_QUEUE_GROUP_LINE_TEMPLATE.format(chat_name=chat_name)
                if chat_name else ""
            )

            msg_parts.append(PA_MESSAGE_TEMPLATE.format(
                channel=channel_name,
                channel_message_id=msg.get("channel_message_id", msg.get("msg_id", "?")),
                prompt=msg.get("prompt", ""),
                group_line=group_line,
                received_at=msg.get("received_at") or "unknown",
            ) + recovered_note)

        elif msg_type == "agent_completed":
            outputs = msg.get("output_files", [])
            outputs_section = (
                PA_QUEUE_OUTPUTS_LINE_TEMPLATE.format(outputs_list=", ".join(outputs))
                if outputs else ""
            )
            logs_section = format_logs_section(msg.get("recent_logs", []))

            msg_parts.append(PA_AGENT_COMPLETED_TEMPLATE.format(
                task_id=msg.get("task_id", "?"),
                channel=msg.get("channel", "?"),
                run_id=msg.get("run_id", "?"),
                session_id=msg.get("session_id", "?"),
                result_summary=msg.get("result_summary", "(无)"),
                outputs_section=outputs_section,
                recent_logs_section=logs_section,
                event_at=msg.get("event_at") or "unknown",
            ))

        elif msg_type == "agent_failed":
            logs_section = format_logs_section(msg.get("recent_logs", []))

            msg_parts.append(PA_AGENT_FAILED_TEMPLATE.format(
                task_id=msg.get("task_id", "?"),
                channel=msg.get("channel", "?"),
                run_id=msg.get("run_id", "?"),
                session_id=msg.get("session_id", "?"),
                result_summary=msg.get("result_summary", "(无)"),
                recent_logs_section=logs_section,
                event_at=msg.get("event_at") or "unknown",
            ))

        elif msg_type == "scheduled_task":
            recipe = msg.get("recipe")
            recipe_line = (
                PA_QUEUE_RECIPE_LINE_TEMPLATE.format(recipe=recipe)
                if recipe else ""
            )
            params = msg.get("params") or {}
            params_line = (
                PA_QUEUE_PARAMS_LINE_TEMPLATE.format(
                    params_json=json.dumps(params, ensure_ascii=False)
                )
                if params else ""
            )
            last_status = msg.get("last_status")
            last_status_line = (
                PA_QUEUE_LAST_STATUS_LINE_TEMPLATE.format(last_status=last_status)
                if last_status else ""
            )
            msg_channel = msg.get("channel", "schedule")
            msg_parts.append(PA_SCHEDULED_TASK_TEMPLATE.format(
                msg_id=msg.get("msg_id", "?"),
                channel=msg_channel,
                schedule_id=msg.get("schedule_id", "?"),
                schedule_name=msg.get("schedule_name", "?"),
                prompt=msg.get("prompt", ""),
                recipe_line=recipe_line,
                params_line=params_line,
                last_status_line=last_status_line,
                run_count=msg.get("run_count", 0),
                fired_at=msg.get("triggered_at") or "unknown",
            ))
            # Phase finish: scheduled_task reply_context is now carried inline on
            # board.Source (ingest_scheduled writes it through Ingestor) and on the
            # queue dict above. No separate cache_message shim needed.
            if msg.get("msg_id") and msg.get("schedule_id"):
                svc._schedule_msg_map[msg["msg_id"]] = msg["schedule_id"]

        elif msg_type in ("reply_failed", "task_failed"):
            if msg.get("content"):
                msg_parts.append(msg["content"])
            else:
                msg_parts.append(PA_REPLY_FAILED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    error=msg.get("error", "unknown"),
                    reply_text=msg.get("reply_text", msg.get("original_text", "")),
                ))

        elif msg_type == "recovered_failed_task":
            msg_parts.append(PA_RECOVERED_FAILED_TASK_TEMPLATE.format(
                task_id=msg.get("task_id", "?"),
                channel=msg.get("channel", "?"),
                original_error=msg.get("original_error", "unknown"),
                original_prompt=msg.get("original_prompt", ""),
            ))

        elif msg_type == "worker_done":
            # Phase 3: worker(frago agent start 起的 sub-agent)完成重入。带 conv
            # 归属 + 结果摘要，PA 读完组织最终回复。无专用模板，用简洁自然语言块。
            status = msg.get("status", "completed")
            summary = msg.get("result_summary") or msg.get("summary") or "(无摘要)"
            outputs = msg.get("output_files") or []
            outputs_line = f"\n输出文件: {', '.join(outputs)}" if outputs else ""
            msg_parts.append(
                f"[worker 完成] agent_type={msg.get('agent_type', '?')} "
                f"status={status} worker={msg.get('worker_id', '?')}\n"
                f"结果摘要:\n{summary}{outputs_line}\n"
                f"（这是你之前派出去的 worker 跑完后的回传，读完组织最终回复给用户。）"
            )

        elif msg_type == "resume_failed":
            from frago.server.services.pa_prompts import (
                PA_RESUME_FAILED_TEMPLATE,
            )
            msg_parts.append(PA_RESUME_FAILED_TEMPLATE.format(
                task_id=msg.get("task_id", "?"),
                reason=msg.get("reason", "unknown"),
                detail=msg.get("detail", "") or f"(original prompt: {msg.get('original_prompt', '')[:200]})",
            ))

        elif msg_type == "run_failed":
            from frago.server.services.pa_prompts import (
                PA_RUN_FAILED_TEMPLATE,
            )
            msg_parts.append(PA_RUN_FAILED_TEMPLATE.format(
                msg_id=msg.get("msg_id", "-") or "-",
                task_id=msg.get("task_id", "-") or "-",
                reason=msg.get("reason", "unknown"),
                detail=msg.get("detail", ""),
            ))

        else:
            msg_parts.append(PA_QUEUE_UNKNOWN_FALLBACK_TEMPLATE.format(
                msg_type=msg_type,
                msg_json=json.dumps(msg, ensure_ascii=False, default=str),
            ))

    return PA_MERGED_MESSAGES_TEMPLATE.format(
        count=len(messages),
        messages_body="\n".join(msg_parts),
    )
