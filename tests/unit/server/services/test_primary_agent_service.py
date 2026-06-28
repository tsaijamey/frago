"""Tests for PrimaryAgentService."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import frago.server.services.primary_agent_service as mod
from frago.server.services.primary_agent_service import PrimaryAgentService


class TestPrimaryAgentService:
    def _fresh_service(self):
        """Create a fresh instance (bypass singleton for testing)."""
        svc = PrimaryAgentService.__new__(PrimaryAgentService)
        svc.__init__()
        return svc

    def test_enqueue_worker_done_renders_and_routes(self):
        """Phase 3: enqueue_worker_done puts a worker_done msg that resolves to its conv_key
        and renders the result summary into the merged PA text."""
        svc = self._fresh_service()

        async def run():
            svc._broadcast_pa_event = AsyncMock()
            await svc.enqueue_worker_done(
                conv_key="feishu:oc_x",
                channel="feishu",
                result_summary="调研完成：找到 3 个候选方案",
            )
            msg = await svc._message_queue.get()
            assert msg["type"] == "worker_done"
            assert svc._resolve_thread_id(msg) == "feishu:oc_x"
            rendered = svc._format_queue_messages([msg])
            assert "调研完成：找到 3 个候选方案" in rendered
            assert "worker 完成" in rendered

        asyncio.run(run())

    def test_initialize_starts_heartbeat(self):
        """initialize starts the queue consumer + heartbeat; no claude-p session is created."""
        svc = self._fresh_service()

        async def run():
            with patch.object(
                svc, "_start_heartbeat", new_callable=AsyncMock
            ) as mock_hb:
                await svc.initialize()
                assert svc._queue_consumer_task is not None
                mock_hb.assert_called_once()

        asyncio.run(run())


class TestHeartbeat:
    def _fresh_service(self):
        svc = PrimaryAgentService.__new__(PrimaryAgentService)
        svc.__init__()
        return svc

    def test_record_external_message(self):
        svc = self._fresh_service()
        assert svc._last_external_message_at is None
        svc.record_external_message()
        assert svc._last_external_message_at is not None

    def test_format_duration(self):
        assert PrimaryAgentService._format_duration(30) == "30秒"
        assert PrimaryAgentService._format_duration(120) == "2分钟"
        assert PrimaryAgentService._format_duration(3600) == "1小时"
        assert PrimaryAgentService._format_duration(3900) == "1小时5分钟"

    def test_heartbeat_start_stop(self):
        svc = self._fresh_service()

        async def run():
            with patch.object(
                svc, "_load_heartbeat_config",
                return_value={"enabled": True, "interval_seconds": 1, "initial_delay_seconds": 0},
            ), patch.object(
                svc, "_send_heartbeat", new_callable=AsyncMock
            ):
                await svc._start_heartbeat()
                assert svc._heartbeat_task is not None
                assert not svc._heartbeat_task.done()

                await svc._stop_heartbeat()
                assert svc._heartbeat_task is None

        asyncio.run(run())

    def test_heartbeat_disabled_by_config(self):
        svc = self._fresh_service()

        async def run():
            with patch.object(
                svc, "_load_heartbeat_config",
                return_value={"enabled": False, "interval_seconds": 300, "initial_delay_seconds": 30},
            ):
                await svc._start_heartbeat()
                assert svc._heartbeat_task is None

        asyncio.run(run())

    def test_send_heartbeat_increments_seq(self):
        svc = self._fresh_service()

        async def run():
            assert svc._heartbeat_seq == 0
            await svc._send_heartbeat()
            assert svc._heartbeat_seq == 1
            await svc._send_heartbeat()
            assert svc._heartbeat_seq == 2

        asyncio.run(run())

    def test_send_heartbeat_skipped_when_busy(self):
        svc = self._fresh_service()
        svc._busy = True

        async def run():
            await svc._send_heartbeat()
            assert svc._heartbeat_seq == 0

        asyncio.run(run())

    def test_heartbeat_config_defaults(self):
        svc = self._fresh_service()
        # With no config file, should return defaults
        orig = mod.CONFIG_FILE
        mod.CONFIG_FILE = Path("/tmp/nonexistent-heartbeat-config.json")
        try:
            config = svc._load_heartbeat_config()
            assert config["enabled"] is True
            assert config["interval_seconds"] == 300
            assert config["initial_delay_seconds"] == 30
        finally:
            mod.CONFIG_FILE = orig

    def test_heartbeat_config_override(self, tmp_path):
        svc = self._fresh_service()
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "primary_agent": {
                "heartbeat": {
                    "interval_seconds": 60,
                    "initial_delay_seconds": 5,
                }
            }
        }))

        orig = mod.CONFIG_FILE
        mod.CONFIG_FILE = config_file
        try:
            config = svc._load_heartbeat_config()
            assert config["enabled"] is True  # default preserved
            assert config["interval_seconds"] == 60  # overridden
            assert config["initial_delay_seconds"] == 5  # overridden
        finally:
            mod.CONFIG_FILE = orig

    def _make_svc_for_reply(self):
        svc = self._fresh_service()
        svc._lifecycle = MagicMock()
        svc._lifecycle.deliver = MagicMock(return_value={"status": "ok"})
        svc._broadcast_pa_event = AsyncMock()
        return svc

    def test_deliver_pushes_text_with_route_context(self):
        """Phase 2: deliver(text, route) → lifecycle.deliver(channel, {text}, reply_context=...)."""
        svc = self._make_svc_for_reply()
        route = {"channel": "feishu", "task_id": "t1", "reply_context": {"chat_id": "c1"}}
        asyncio.run(svc.deliver("hi", route))
        _, kwargs = svc._lifecycle.deliver.call_args
        args = svc._lifecycle.deliver.call_args.args
        assert args[0] == "feishu"
        assert args[1] == {"text": "hi"}
        assert kwargs["reply_context"] == {"chat_id": "c1"}
        assert kwargs["task_id"] == "t1"

    def test_deliver_skips_empty_text(self):
        """空输出不推（Edge Cases: agent 最终输出为空 → 跳过）。"""
        svc = self._make_svc_for_reply()
        asyncio.run(svc.deliver("   ", {"channel": "feishu"}))
        svc._lifecycle.deliver.assert_not_called()

    def test_deliver_uses_reply_context_cache_when_route_lacks_it(self):
        """route 无 reply_context 时回落 conv→reply_context 缓存（按 channel: 前缀键）。"""
        svc = self._make_svc_for_reply()
        svc._reply_context_cache["channel:feishu"] = {"chat_id": "cached"}
        asyncio.run(svc.deliver("hi", {"channel": "feishu"}))
        kwargs = svc._lifecycle.deliver.call_args.kwargs
        assert kwargs["reply_context"] == {"chat_id": "cached"}

    def test_stop_calls_stop_heartbeat(self):
        svc = self._fresh_service()

        async def run():
            with patch.object(
                svc, "_stop_heartbeat", new_callable=AsyncMock
            ) as mock_stop:
                await svc.stop()
                mock_stop.assert_called_once()

        asyncio.run(run())
