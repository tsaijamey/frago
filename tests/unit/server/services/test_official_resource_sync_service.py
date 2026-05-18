"""Tests for frago.server.services.official_resource_sync_service module.

Tests official resource synchronization from GitHub.
"""
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.official_resource_sync_service import (
    OfficialResourceSyncService,
)


@pytest.fixture(autouse=True)
def reset_sync_state():
    """Reset sync state before each test."""
    OfficialResourceSyncService._sync_running = False
    OfficialResourceSyncService._sync_result = None
    yield
    OfficialResourceSyncService._sync_running = False
    OfficialResourceSyncService._sync_result = None


class TestOfficialResourceSyncServiceUrls:
    """Test URL generation methods."""

    def test_get_github_api_url(self):
        """Should generate correct GitHub API URL."""
        url = OfficialResourceSyncService.get_github_api_url("src/frago/resources")

        assert "api.github.com" in url
        assert "contents" in url
        assert "src/frago/resources" in url

    def test_get_raw_url(self):
        """Should generate correct raw content URL."""
        url = OfficialResourceSyncService.get_raw_url("README.md")

        assert "raw.githubusercontent.com" in url
        assert "README.md" in url


class TestOfficialResourceSyncServiceStartSync:
    """Test OfficialResourceSyncService.start_sync() method."""

    def test_returns_started_status(self):
        """Should return started status."""
        with patch.object(
            OfficialResourceSyncService, "_do_sync", return_value={}
        ):
            result = OfficialResourceSyncService.start_sync()

        assert result["status"] == "started"

    def test_returns_running_if_already_syncing(self):
        """Should return running status if sync already in progress."""
        OfficialResourceSyncService._sync_running = True

        result = OfficialResourceSyncService.start_sync()

        assert result["status"] == "running"


class TestOfficialResourceSyncServiceGetSyncResult:
    """Test OfficialResourceSyncService.get_sync_result() method."""

    def test_returns_running_when_sync_in_progress(self):
        """Should return running status during sync."""
        OfficialResourceSyncService._sync_running = True

        result = OfficialResourceSyncService.get_sync_result()

        assert result["status"] == "running"

    def test_returns_idle_when_no_sync(self):
        """Should return idle status when no sync has run."""
        result = OfficialResourceSyncService.get_sync_result()

        assert result["status"] == "idle"

    def test_returns_result_when_available(self):
        """Should return sync result when available."""
        OfficialResourceSyncService._sync_result = {
            "status": "ok",
            "commands": {"files_synced": 5},
        }

        result = OfficialResourceSyncService.get_sync_result()

        assert result["status"] == "ok"
        assert result["commands"]["files_synced"] == 5


class TestOfficialResourceSyncServiceGetSyncStatus:
    """Test OfficialResourceSyncService.get_sync_status() method."""

    def test_returns_status_with_config(self):
        """Should return status with configuration info."""
        mock_config = MagicMock()
        mock_config.official_resource_sync_enabled = True
        mock_config.official_resource_last_sync = None
        mock_config.official_resource_last_commit = "abc123"

        with patch(
            "frago.server.services.official_resource_sync_service.load_config",
            return_value=mock_config,
        ):
            result = OfficialResourceSyncService.get_sync_status()

        assert "enabled" in result
        assert "repo" in result
        assert "branch" in result
        assert result["last_commit"] == "abc123"


class TestOfficialResourceSyncServiceSetSyncEnabled:
    """Test OfficialResourceSyncService.set_sync_enabled() method."""

    def test_enables_sync(self):
        """Should enable auto-sync."""
        mock_config = MagicMock()

        with (
            patch(
                "frago.server.services.official_resource_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.official_resource_sync_service.save_config"
            ),
        ):
            result = OfficialResourceSyncService.set_sync_enabled(True)

        assert result["status"] == "ok"
        assert result["enabled"] is True

    def test_disables_sync(self):
        """Should disable auto-sync."""
        mock_config = MagicMock()

        with (
            patch(
                "frago.server.services.official_resource_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.official_resource_sync_service.save_config"
            ),
        ):
            result = OfficialResourceSyncService.set_sync_enabled(False)

        assert result["status"] == "ok"
        assert result["enabled"] is False


class TestOfficialResourceSyncServiceCheckForUpdates:
    """Test OfficialResourceSyncService.check_for_updates() method."""

    def test_detects_updates_available(self):
        """Should detect when updates are available."""
        mock_config = MagicMock()
        mock_config.official_resource_last_commit = "old-commit"

        with (
            patch(
                "frago.server.services.official_resource_sync_service.load_config",
                return_value=mock_config,
            ),
            patch.object(
                OfficialResourceSyncService,
                "_get_latest_commit",
                return_value="new-commit",
            ),
        ):
            result = OfficialResourceSyncService.check_for_updates()

        assert result["has_updates"] is True
        assert result["current_commit"] == "old-commit"
        assert result["latest_commit"] == "new-commit"

    def test_detects_no_updates(self):
        """Should detect when no updates available."""
        mock_config = MagicMock()
        mock_config.official_resource_last_commit = "same-commit"

        with (
            patch(
                "frago.server.services.official_resource_sync_service.load_config",
                return_value=mock_config,
            ),
            patch.object(
                OfficialResourceSyncService,
                "_get_latest_commit",
                return_value="same-commit",
            ),
        ):
            result = OfficialResourceSyncService.check_for_updates()

        assert result["has_updates"] is False

    def test_handles_api_failure(self):
        """Should handle GitHub API failure gracefully."""
        mock_config = MagicMock()
        mock_config.official_resource_last_commit = "old-commit"

        with (
            patch(
                "frago.server.services.official_resource_sync_service.load_config",
                return_value=mock_config,
            ),
            patch.object(
                OfficialResourceSyncService,
                "_get_latest_commit",
                return_value=None,
            ),
        ):
            result = OfficialResourceSyncService.check_for_updates()

        # When API fails, has_updates is falsy (None due to short-circuit)
        assert not result["has_updates"]


class TestOfficialResourceSyncServicePrivateMethods:
    """Test private methods."""

    def test_get_latest_commit_success(self):
        """Should return commit SHA on success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"sha": "abc123def456"}

        with patch("requests.get", return_value=mock_response):
            result = OfficialResourceSyncService._get_latest_commit()

        assert result == "abc123def456"

    def test_get_latest_commit_failure(self):
        """Should return None on failure."""
        with patch("requests.get", side_effect=Exception("Network error")):
            result = OfficialResourceSyncService._get_latest_commit()

        assert result is None
