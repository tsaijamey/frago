"""Tests for frago.server.services.github_service module.

Tests GitHub CLI integration.
"""
import platform
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.github_service import GitHubService


class TestGitHubServiceCheckGhCli:
    """Test GitHubService.check_gh_cli() method."""

    def test_returns_not_installed_when_gh_not_found(self):
        """Should return installed=False when gh not in PATH."""
        mock_result = MagicMock()
        mock_result.returncode = 127  # Command not found

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=FileNotFoundError,
        ):
            result = GitHubService.check_gh_cli()

        assert result["installed"] is False
        assert result["version"] is None
        assert result["authenticated"] is False
        assert result["username"] is None

    def test_returns_installed_with_version(self):
        """Should return installed=True with version number."""
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "gh version 2.40.1 (2023-12-13)"

        auth_result = MagicMock()
        auth_result.returncode = 1  # Not authenticated

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[version_result, auth_result],
        ):
            result = GitHubService.check_gh_cli()

        assert result["installed"] is True
        assert result["version"] == "2.40.1"
        assert result["authenticated"] is False

    def test_returns_authenticated_with_username(self):
        """Should return authenticated=True with username when logged in."""
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "gh version 2.40.1"

        auth_result = MagicMock()
        auth_result.returncode = 0
        auth_result.stdout = ""
        auth_result.stderr = "Logged in to github.com as testuser"

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[version_result, auth_result],
        ):
            result = GitHubService.check_gh_cli()

        assert result["installed"] is True
        assert result["authenticated"] is True
        assert result["username"] == "testuser"

    def test_handles_alternate_auth_format(self):
        """Should parse alternate auth output format."""
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "gh version 2.40.1"

        auth_result = MagicMock()
        auth_result.returncode = 0
        auth_result.stdout = "Logged in to github.com account anotheruser (keyring)"
        auth_result.stderr = ""

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[version_result, auth_result],
        ):
            result = GitHubService.check_gh_cli()

        assert result["authenticated"] is True
        assert result["username"] == "anotheruser"

    def test_handles_timeout(self):
        """Should handle timeout gracefully."""
        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=subprocess.TimeoutExpired("gh", 5),
        ):
            result = GitHubService.check_gh_cli()

        assert result["installed"] is False


class TestGitHubServiceAuthLogin:
    """Test GitHubService.auth_login() method."""

    def test_linux_tries_x_terminal_emulator(self):
        """Should try x-terminal-emulator first on Linux."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "ok"
        mock_popen.assert_called_once()
        assert "x-terminal-emulator" in mock_popen.call_args[0][0]

    def test_linux_falls_back_to_gnome_terminal(self):
        """Should fall back to gnome-terminal when x-terminal-emulator not found."""
        call_count = [0]

        def popen_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise FileNotFoundError
            return MagicMock()

        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.Popen", side_effect=popen_side_effect),
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "ok"

    def test_linux_returns_error_when_no_terminal(self):
        """Should return error when no terminal emulator found."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.Popen", side_effect=FileNotFoundError),
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "error"
        assert "terminal" in result["error"].lower()

    def test_macos_uses_osascript(self):
        """Should use osascript on macOS."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run") as mock_run,
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "ok"
        mock_run.assert_called_once()
        assert "osascript" in mock_run.call_args[0][0]

    @pytest.mark.skipif(
        platform.system() != "Windows",
        reason="Windows-specific test using creationflags",
    )
    def test_windows_tries_powershell(self):
        """Should try PowerShell first on Windows."""
        with (
            patch("platform.system", return_value="Windows"),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "ok"
        mock_popen.assert_called_once()
        assert "powershell" in mock_popen.call_args[0][0]

    @pytest.mark.skipif(
        platform.system() != "Windows",
        reason="Windows-specific test using creationflags",
    )
    def test_windows_falls_back_to_cmd(self):
        """Should fall back to cmd when PowerShell fails."""
        call_count = [0]

        def popen_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise FileNotFoundError
            return MagicMock()

        with (
            patch("platform.system", return_value="Windows"),
            patch("subprocess.Popen", side_effect=popen_side_effect),
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "ok"

    def test_unsupported_os_returns_error(self):
        """Should return error for unsupported operating system."""
        with patch("platform.system", return_value="Unknown"):
            result = GitHubService.auth_login()

        assert result["status"] == "error"
        assert "Unsupported" in result["error"]

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        with (
            patch("platform.system", side_effect=Exception("Test error")),
        ):
            result = GitHubService.auth_login()

        assert result["status"] == "error"


class TestOfflineAuthIsNotLogout:
    """网络不通时，`gh auth status` 会把一个登录着的账号报成 token 无效。

    照单全收的后果是：那条关不掉的横幅会在每次网络抖动时告诉用户「你的数据没有
    备份，去重新登录」。凭据明明还在本机躺着。所以这里按「有没有存着凭据」来判，
    而不是按「GitHub 这一秒答没答应」。
    """

    def _versions(self):
        version = MagicMock()
        version.returncode = 0
        version.stdout = "gh version 2.86.0 (2026-07-31)"
        return version

    def test_offline_with_a_stored_token_still_counts_as_logged_in(self):
        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = (
            "github.com\n  X Failed to log in to github.com account tsaijamey (keyring)\n"
            "  - The token in keyring is invalid.\n"
        )
        token = MagicMock()
        token.returncode = 0
        token.stdout = "gho_sometoken\n"

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[self._versions(), failed, token],
        ):
            result = GitHubService.check_gh_cli()

        assert result["authenticated"] is True
        # 但要说清楚：这次没核验过。
        assert result["verified"] is False
        assert result["verify_error"]
        # 名字 gh 在失败信息里照样给了，别丢。
        assert result["username"] == "tsaijamey"

    def test_no_stored_token_is_a_real_logout(self):
        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = "You are not logged into any GitHub hosts.\n"
        no_token = MagicMock()
        no_token.returncode = 1
        no_token.stdout = ""

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[self._versions(), failed, no_token],
        ):
            result = GitHubService.check_gh_cli()

        assert result["authenticated"] is False
        assert result["verified"] is False

    def test_a_timeout_is_treated_like_any_other_no_answer(self):
        """卡住和失败是同一种情况：GitHub 没回话，这不说明凭据没了。"""
        token = MagicMock()
        token.returncode = 0
        token.stdout = "gho_sometoken\n"

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[self._versions(), subprocess.TimeoutExpired("gh", 5), token],
        ):
            result = GitHubService.check_gh_cli()

        assert result["authenticated"] is True
        assert result["verified"] is False

    def test_a_successful_check_is_marked_verified(self):
        ok = MagicMock()
        ok.returncode = 0
        ok.stdout = ""
        ok.stderr = "Logged in to github.com account tsaijamey (keyring)"

        with patch(
            "frago.server.services.github_service.run_subprocess",
            side_effect=[self._versions(), ok],
        ):
            result = GitHubService.check_gh_cli()

        assert result["authenticated"] is True
        assert result["verified"] is True
        assert result["verify_error"] is None
        assert result["username"] == "tsaijamey"
