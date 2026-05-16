"""Tests for frago.server.services.multidevice_sync_service module.

Tests multi-device synchronization via GitHub.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.multidevice_sync_service import MultiDeviceSyncService


@pytest.fixture(autouse=True)
def reset_sync_state():
    """Reset sync state before each test."""
    MultiDeviceSyncService._sync_running = False
    MultiDeviceSyncService._sync_result = None
    MultiDeviceSyncService._needs_cache_refresh = False
    yield
    MultiDeviceSyncService._sync_running = False
    MultiDeviceSyncService._sync_result = None
    MultiDeviceSyncService._needs_cache_refresh = False


class TestMultiDeviceSyncServiceCreateSyncRepo:
    """Test MultiDeviceSyncService.create_sync_repo() method."""

    def test_creates_private_repo(self):
        """Should create private repository by default."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/test-repo"

        mock_config = MagicMock()

        with (
            patch(
                "frago.server.services.multidevice_sync_service.run_subprocess",
                return_value=mock_result,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.save_config"
            ),
        ):
            result = MultiDeviceSyncService.create_sync_repo("test-repo")

        assert result["status"] == "ok"
        assert result["repo_url"] == "https://github.com/user/test-repo"

    def test_creates_public_repo(self):
        """Should create public repository when specified."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/public-repo"

        mock_config = MagicMock()

        with (
            patch(
                "frago.server.services.multidevice_sync_service.run_subprocess",
                return_value=mock_result,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.save_config"
            ),
        ):
            result = MultiDeviceSyncService.create_sync_repo("public-repo", private=False)

        assert result["status"] == "ok"

    def test_handles_creation_failure(self):
        """Should handle repository creation failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Repository already exists"
        mock_result.stdout = ""

        with patch(
            "frago.server.services.multidevice_sync_service.run_subprocess",
            return_value=mock_result,
        ):
            result = MultiDeviceSyncService.create_sync_repo("existing-repo")

        assert result["status"] == "error"
        assert "already exists" in result["error"]

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        with patch(
            "frago.server.services.multidevice_sync_service.run_subprocess",
            side_effect=Exception("Network error"),
        ):
            result = MultiDeviceSyncService.create_sync_repo("test-repo")

        assert result["status"] == "error"
        assert "Network error" in result["error"]


class TestMultiDeviceSyncServiceListUserRepos:
    """Test MultiDeviceSyncService.list_user_repos() method."""

    def test_lists_repos_successfully(self):
        """Should list user repositories."""
        import json

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {
                "name": "repo1",
                "nameWithOwner": "user/repo1",
                "description": "Test repo",
                "isPrivate": True,
                "sshUrl": "git@github.com:user/repo1.git",
                "url": "https://github.com/user/repo1",
            }
        ])

        with patch(
            "frago.server.services.multidevice_sync_service.run_subprocess",
            return_value=mock_result,
        ):
            result = MultiDeviceSyncService.list_user_repos()

        assert result["status"] == "ok"
        assert len(result["repos"]) == 1
        assert result["repos"][0]["name"] == "repo1"

    def test_handles_gh_cli_failure(self):
        """Should handle GitHub CLI failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Not authenticated"
        mock_result.stdout = ""

        with patch(
            "frago.server.services.multidevice_sync_service.run_subprocess",
            return_value=mock_result,
        ):
            result = MultiDeviceSyncService.list_user_repos()

        assert result["status"] == "error"


class TestMultiDeviceSyncServiceSelectExistingRepo:
    """Test MultiDeviceSyncService.select_existing_repo() method."""

    def test_saves_https_url(self):
        """Should save HTTPS repository URL."""
        mock_config = MagicMock()

        with (
            patch(
                "frago.server.services.multidevice_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.save_config"
            ),
        ):
            result = MultiDeviceSyncService.select_existing_repo(
                "https://github.com/user/repo"
            )

        assert result["status"] == "ok"
        assert result["repo_url"] == "https://github.com/user/repo"

    def test_converts_ssh_to_https(self):
        """Should convert SSH URL to HTTPS for display."""
        mock_config = MagicMock()

        with (
            patch(
                "frago.server.services.multidevice_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.save_config"
            ),
        ):
            result = MultiDeviceSyncService.select_existing_repo(
                "git@github.com:user/repo.git"
            )

        assert result["status"] == "ok"
        assert "https://github.com/user/repo" in result["repo_url"]

    def test_rejects_empty_url(self):
        """Should reject empty repository URL."""
        result = MultiDeviceSyncService.select_existing_repo("")

        assert result["status"] == "error"
        assert "required" in result["error"]


class TestMultiDeviceSyncServiceCheckRepoVisibility:
    """Test MultiDeviceSyncService.check_repo_visibility() method."""

    def test_detects_public_repo(self):
        """Should detect public repository."""
        mock_config = MagicMock()
        mock_config.sync_repo_url = "https://github.com/user/repo"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "false"  # isPrivate = false

        with (
            patch(
                "frago.server.services.multidevice_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.run_subprocess",
                return_value=mock_result,
            ),
        ):
            result = MultiDeviceSyncService.check_repo_visibility()

        assert result["status"] == "ok"
        assert result["is_public"] is True

    def test_detects_private_repo(self):
        """Should detect private repository."""
        mock_config = MagicMock()
        mock_config.sync_repo_url = "https://github.com/user/repo"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "true"  # isPrivate = true

        with (
            patch(
                "frago.server.services.multidevice_sync_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.multidevice_sync_service.run_subprocess",
                return_value=mock_result,
            ),
        ):
            result = MultiDeviceSyncService.check_repo_visibility()

        assert result["status"] == "ok"
        assert result["is_public"] is False

    def test_handles_no_repo_configured(self):
        """Should return error when no repo configured."""
        with patch(
            "frago.tools.sync_repo.get_sync_repo_url",
            return_value=None,
        ):
            result = MultiDeviceSyncService.check_repo_visibility()

        assert result["status"] == "error"
        assert "configured" in result["error"].lower()


class TestMultiDeviceSyncServiceStartSync:
    """Test MultiDeviceSyncService.start_sync() method."""

    def test_starts_sync(self):
        """Should start sync and return ok status."""
        with patch.object(MultiDeviceSyncService, "_do_sync"):
            result = MultiDeviceSyncService.start_sync()

        assert result["status"] == "ok"
        assert "started" in result["message"].lower()

    def test_returns_error_if_already_running(self):
        """Should return error if sync already running."""
        MultiDeviceSyncService._sync_running = True

        result = MultiDeviceSyncService.start_sync()

        assert result["status"] == "error"
        assert "already" in result["error"].lower()


class TestMultiDeviceSyncServiceGetSyncResult:
    """Test MultiDeviceSyncService.get_sync_result() method."""

    def test_returns_running_status(self):
        """Should return running status when sync in progress."""
        MultiDeviceSyncService._sync_running = True

        result = MultiDeviceSyncService.get_sync_result()

        assert result["status"] == "running"

    def test_returns_idle_when_no_sync(self):
        """Should return idle when no sync has run."""
        result = MultiDeviceSyncService.get_sync_result()

        assert result["status"] == "idle"

    def test_returns_result_with_needs_refresh(self):
        """Should include needs_refresh flag in result."""
        MultiDeviceSyncService._sync_result = {"status": "ok"}
        MultiDeviceSyncService._needs_cache_refresh = True

        result = MultiDeviceSyncService.get_sync_result()

        assert result["needs_refresh"] is True


class TestMultiDeviceSyncServiceClearRefreshFlag:
    """Test MultiDeviceSyncService.clear_refresh_flag() method."""

    def test_clears_flag(self):
        """Should clear the cache refresh flag."""
        MultiDeviceSyncService._needs_cache_refresh = True

        MultiDeviceSyncService.clear_refresh_flag()

        assert MultiDeviceSyncService._needs_cache_refresh is False


class TestMultiDeviceSyncServiceSyncNow:
    """Test MultiDeviceSyncService.sync_now() async method."""

    @pytest.mark.asyncio
    async def test_returns_result_on_completion(self):
        """Should return result when sync completes."""

        def mock_start_sync():
            # Simulate quick sync
            MultiDeviceSyncService._sync_result = {"status": "ok"}
            MultiDeviceSyncService._sync_running = False
            return {"status": "ok"}

        with patch.object(
            MultiDeviceSyncService,
            "start_sync",
            side_effect=mock_start_sync,
        ):
            result = await MultiDeviceSyncService.sync_now()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_returns_error_on_start_failure(self):
        """Should return error if start_sync fails."""
        with patch.object(
            MultiDeviceSyncService,
            "start_sync",
            return_value={"status": "error", "error": "Already running"},
        ):
            result = await MultiDeviceSyncService.sync_now()

        assert result["status"] == "error"
