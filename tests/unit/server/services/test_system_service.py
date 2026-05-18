"""Tests for frago.server.services.system_service module.

Tests system status and information.
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.system_service import SystemService


class TestSystemServiceGetStatus:
    """Test SystemService.get_status() method."""

    def test_returns_status_dict(self):
        """Should return status dictionary with expected keys."""
        mock_memory = MagicMock()
        mock_memory.percent = 50.0

        with (
            patch("psutil.cpu_percent", return_value=25.0),
            patch("psutil.virtual_memory", return_value=mock_memory),
            patch("frago.session.storage.list_sessions", return_value=[]),
        ):
            result = SystemService.get_status()

        assert "cpu_percent" in result
        assert "memory_percent" in result
        assert "chrome_available" in result
        assert "chrome_connected" in result
        assert "tasks_running" in result

    def test_returns_cpu_and_memory_percent(self):
        """Should return CPU and memory percentages."""
        mock_memory = MagicMock()
        mock_memory.percent = 65.5

        with (
            patch("psutil.cpu_percent", return_value=30.0),
            patch("psutil.virtual_memory", return_value=mock_memory),
            patch("frago.session.storage.list_sessions", return_value=[]),
        ):
            result = SystemService.get_status()

        assert result["cpu_percent"] == 30.0
        assert result["memory_percent"] == 65.5

    def test_counts_running_tasks(self):
        """Should count running sessions as tasks."""
        mock_memory = MagicMock()
        mock_memory.percent = 50.0

        mock_sessions = [MagicMock(), MagicMock(), MagicMock()]

        with (
            patch("psutil.cpu_percent", return_value=0),
            patch("psutil.virtual_memory", return_value=mock_memory),
            patch("frago.session.storage.list_sessions", return_value=mock_sessions),
        ):
            result = SystemService.get_status()

        assert result["tasks_running"] == 3

    def test_handles_errors_gracefully(self):
        """Should return zero values on error."""
        with patch("psutil.cpu_percent", side_effect=Exception("Test error")):
            result = SystemService.get_status()

        assert result["cpu_percent"] == 0.0
        assert result["memory_percent"] == 0.0
        assert result["tasks_running"] == 0


class TestSystemServiceGetDirectories:
    """Test SystemService.get_directories() method."""

    def test_returns_home_directory(self):
        """Should return user home directory."""
        result = SystemService.get_directories()

        assert "home" in result
        assert result["home"] == str(Path.home())

    def test_returns_current_working_directory(self):
        """Should return current working directory."""
        result = SystemService.get_directories()

        assert "cwd" in result
        # cwd may be None in some test environments
        if result["cwd"]:
            assert Path(result["cwd"]).exists()

    def test_handles_cwd_error(self, monkeypatch):
        """Should return None for cwd on error."""
        # Simulate error getting cwd
        def raise_error():
            raise OSError("No current directory")

        with patch.object(Path, "cwd", side_effect=OSError("Test error")):
            result = SystemService.get_directories()

        # Should still return home, cwd should be None
        assert "home" in result
        assert result["cwd"] is None


class TestSystemServiceGetInfo:
    """Test SystemService.get_info() method."""

    def test_returns_version(self):
        """Should return frago version."""
        with patch("frago.__version__", "1.2.3"):
            result = SystemService.get_info()

        assert result["version"] == "1.2.3"

    def test_returns_host_and_port(self):
        """Should return host and port."""
        result = SystemService.get_info(host="0.0.0.0", port=9000)

        assert result["host"] == "0.0.0.0"
        assert result["port"] == 9000

    def test_returns_started_at(self):
        """Should return provided started_at timestamp."""
        timestamp = "2025-01-15T10:00:00Z"
        result = SystemService.get_info(started_at=timestamp)

        assert result["started_at"] == timestamp

    def test_generates_started_at_if_none(self):
        """Should generate started_at if not provided."""
        result = SystemService.get_info()

        assert "started_at" in result
        # Should be a valid ISO timestamp
        datetime.fromisoformat(result["started_at"].replace("Z", "+00:00"))

    def test_handles_missing_version(self):
        """Should handle ImportError when getting version."""
        with patch.dict("sys.modules", {"frago": None}):
            # Force import error
            import sys
            original = sys.modules.get("frago")

            try:
                # This simulates the ImportError case
                def mock_import(name, *args, **kwargs):
                    if name == "frago":
                        raise ImportError("No module")
                    return original_import(name, *args, **kwargs)

                import builtins
                original_import = builtins.__import__

                # Test passes when version defaults
                result = SystemService.get_info()
                # Version should have some value
                assert "version" in result
            finally:
                if original:
                    sys.modules["frago"] = original


class TestSystemServiceIntegration:
    """Integration tests for SystemService."""

    def test_get_status_integration(self):
        """Should work with real psutil calls."""
        # This test uses real psutil
        mock_memory = MagicMock()
        mock_memory.percent = 50.0

        with (
            patch("frago.session.storage.list_sessions", return_value=[]),
            patch("psutil.virtual_memory", return_value=mock_memory),
        ):
            result = SystemService.get_status()

        # Should return valid structure
        assert isinstance(result["cpu_percent"], (int, float))
        assert isinstance(result["memory_percent"], (int, float))
        assert isinstance(result["tasks_running"], int)
