"""Task Lifecycle — outbound delivery (spec 20260627 Phase 3: 去账本).

去账本后，本模块只剩"出去投递"这一个无状态薄动作：把 agent 的最终文本按 channel
查 notify_recipe 推回去。reply_context 由调用方（入队消息 / PrimaryAgentService 的
conv_key→reply_context 缓存）携带，不再 task_id→board.Task→reply_context。
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"
CONFIG_FILE = FRAGO_HOME / "config.json"


class TaskLifecycle:
    """Outbound delivery coordinator (Phase 3: stateless, no board).

    Not a singleton — instantiated by PrimaryAgentService.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _merge_reply_context(
        reply_params: dict[str, Any], reply_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build full notify-recipe params: text + reply_context + preserved attachments."""
        full = {
            "text": reply_params.get("text", ""),
            "reply_context": reply_context,
        }
        for k in ("html_body", "file_path", "image_path"):
            if reply_params.get(k):
                full[k] = reply_params[k]
        return full

    @staticmethod
    def _resolve_notify_recipe(channel: str) -> str | None:
        """查 channel 的 notify_recipe（config.json）。无则 None。"""
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        channels = (raw.get("task_ingestion") or {}).get("channels") or []
        for ch in channels:
            if ch.get("name") == channel:
                return ch.get("notify_recipe")
        return None

    @staticmethod
    def _attachment_params(
        att: dict[str, Any], reply_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """把一条 outbox 制品记录转成 notify_recipe 的附件入参（对齐飞书 recipe）。

        飞书 notify_recipe 按 ``file_path`` / ``image_path`` 单文件投递，模式
        file > image > text，一次只发一个附件——故每条制品独立成一次 notify 调用。
        目录先打成 zip 再当文件投。定位不到的路径返回 None（跳过 + 上层记日志）。
        """
        import shutil
        import tempfile

        kind = att.get("kind", "file")
        raw_path = att.get("path", "")
        if not raw_path:
            return None
        p = Path(raw_path).expanduser()
        if not p.exists():
            return None
        params: dict[str, Any] = {}
        if reply_context:
            params["reply_context"] = reply_context
        if kind == "dir":
            staging = Path(tempfile.mkdtemp(prefix="frago-outbox-"))
            archive = shutil.make_archive(str(staging / p.name), "zip", root_dir=str(p))
            params["file_path"] = archive
        elif kind == "image":
            params["image_path"] = str(p)
        else:
            params["file_path"] = str(p)
        return params

    def deliver(
        self,
        channel: str,
        reply_params: dict[str, Any],
        *,
        reply_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        task_id: str = "",  # noqa: ARG002 — accepted for call-site compat, unused
        msg_id: str = "",  # noqa: ARG002
    ) -> dict[str, Any]:
        """Push text back to a channel via notify recipe. Returns {"status": ...}.

        Phase 3: reply_context comes from the caller (inbound queue message or
        PrimaryAgentService's conv_key→reply_context cache); no board lookup.

        Phase 8（spec 20260627 交付即核心）：``attachments`` 是该 conv outbox drain
        出的制品（``{"kind","path"}`` 列表）。文本作一条消息先发，每条制品作为独立的
        notify 调用随后发（飞书 recipe 单文件投递、模式 file>image>text），文本+制品
        一起送达才算一次完整响应。
        """
        if channel == "cli":
            return {"status": "ok"}

        if reply_context:
            reply_params = self._merge_reply_context(reply_params, reply_context)

        try:
            notify_recipe = self._resolve_notify_recipe(channel)
            if not notify_recipe:
                logger.warning("No notify_recipe configured for channel %s", channel)
                return {"status": "error", "error": f"no notify_recipe for {channel}"}

            from frago.recipes.runner import RecipeRunner
            runner = RecipeRunner()

            # 先发文本正文（非空时）。
            if (reply_params.get("text") or "").strip():
                logger.info(
                    "Reply params for %s: %s",
                    notify_recipe,
                    json.dumps(reply_params, ensure_ascii=False, default=str),
                )
                runner.run(notify_recipe, params=reply_params)
                logger.info("Reply sent via %s for channel %s", notify_recipe, channel)

            # 再逐条发制品附件。
            sent_attachments = 0
            for att in attachments or []:
                params = self._attachment_params(att, reply_context)
                if params is None:
                    logger.warning(
                        "deliver: attachment skipped (missing/empty path): %s", att,
                    )
                    continue
                logger.info(
                    "Delivering attachment via %s: %s",
                    notify_recipe,
                    json.dumps(params, ensure_ascii=False, default=str),
                )
                runner.run(notify_recipe, params=params)
                sent_attachments += 1
            if attachments:
                logger.info(
                    "deliver: drained %d attachment(s), sent %d for channel %s",
                    len(attachments), sent_attachments, channel,
                )
            return {"status": "ok"}

        except Exception as e:
            logger.exception("Failed to send reply for channel %s", channel)
            return {"status": "error", "error": str(e)}

    def reply(
        self,
        task_id: str,  # noqa: ARG002 — legacy signature, task_id no longer board-resolved
        channel: str,
        reply_params: dict[str, Any],
        *,
        msg_id: str = "",  # noqa: ARG002
    ) -> dict[str, Any]:
        """Backward-compatible reply entrypoint → deliver().

        Retained for the server-level online-notification path. reply_context
        must be carried in reply_params (no board fallback in Phase 3).
        """
        reply_context = reply_params.pop("reply_context", None) if isinstance(reply_params, dict) else None
        return self.deliver(channel, reply_params, reply_context=reply_context)
