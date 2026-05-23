"""Tests for PrimaryAgentService."""

import asyncio
import json
import tempfile
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

    def test_initialize_starts_heartbeat(self):
        """Phase 3: initialize no longer creates a session — sessions are per-thread, created on demand."""
        svc = self._fresh_service()

        async def run():
            with patch.object(
                svc, "_start_heartbeat", new_callable=AsyncMock
            ) as mock_hb:
                await svc.initialize()
                assert svc.get_session_id() is None  # no default session
                mock_hb.assert_called_once()

        asyncio.run(run())

    def test_session_for_creates_and_caches_session(self):
        """_session_for creates a session for a thread and caches it."""
        svc = self._fresh_service()
        svc._create_pa_session = AsyncMock(return_value="internal_001")

        async def run():
            board = MagicMock()
            board.bind_pa_session = MagicMock()

            with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
                from frago.server.services.agent_service import AgentService
                AgentService._attached_sessions = {}

                # Simulate a session that will be returned
                fake_session = MagicMock()
                fake_session.is_running = True
                svc._sessions["thread_A"] = fake_session
                svc._session_ids["thread_A"] = "sess_A"

                sess = await svc._session_for("thread_A")
                assert sess is fake_session
                assert svc.get_session_id("thread_A") == "sess_A"

        asyncio.run(run())

    def test_get_session_id_by_thread(self):
        """get_session_id(thread_id) returns that thread's session."""
        svc = self._fresh_service()
        svc._session_ids["thread_X"] = "sess_X"

        assert svc.get_session_id("thread_X") == "sess_X"
        assert svc.get_session_id("nonexistent") is None
        assert svc.get_session_id() is None  # no current thread

    def test_config_persistence_save(self):
        """Save session_id to config.json."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({}, f)
            config_path = Path(f.name)

        orig = mod.CONFIG_FILE
        mod.CONFIG_FILE = config_path
        try:
            PrimaryAgentService._save_session_id("test-session-xyz")

            # Verify config structure
            raw = json.loads(config_path.read_text())
            assert raw["primary_agent"]["session_id"] == "test-session-xyz"
        finally:
            mod.CONFIG_FILE = orig


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
        svc._lifecycle.reply = MagicMock(return_value={"status": "ok"})
        svc._create_task_from_cache = MagicMock(return_value=None)
        svc._broadcast_pa_event = AsyncMock()
        return svc

    def test_send_reply_text_only_excludes_file_image_keys(self):
        svc = self._make_svc_for_reply()
        decision = {"task_id": "t1", "channel": "feishu", "text": "hi"}
        asyncio.run(svc._send_reply(decision))
        args, _ = svc._lifecycle.reply.call_args
        reply_params = args[2]
        assert reply_params == {"text": "hi"}
        assert "file_path" not in reply_params
        assert "image_path" not in reply_params

    def test_send_reply_passes_file_path(self):
        svc = self._make_svc_for_reply()
        decision = {
            "task_id": "t1", "channel": "feishu", "text": "done",
            "file_path": "/tmp/out.pdf",
        }
        asyncio.run(svc._send_reply(decision))
        reply_params = svc._lifecycle.reply.call_args.args[2]
        assert reply_params["file_path"] == "/tmp/out.pdf"
        assert reply_params["text"] == "done"
        assert "image_path" not in reply_params

    def test_send_reply_passes_image_path(self):
        svc = self._make_svc_for_reply()
        decision = {
            "task_id": "t1", "channel": "feishu", "text": "chart",
            "image_path": "/tmp/chart.png",
        }
        asyncio.run(svc._send_reply(decision))
        reply_params = svc._lifecycle.reply.call_args.args[2]
        assert reply_params["image_path"] == "/tmp/chart.png"
        assert "file_path" not in reply_params

    def test_stop_calls_stop_heartbeat(self):
        svc = self._fresh_service()

        async def run():
            with patch.object(
                svc, "_stop_heartbeat", new_callable=AsyncMock
            ) as mock_stop:
                await svc.stop()
                mock_stop.assert_called_once()

        asyncio.run(run())
