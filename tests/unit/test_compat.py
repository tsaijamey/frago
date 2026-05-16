"""Tests for frago.compat module.

Tests cross-platform compatibility utilities.
"""
import platform
from unittest.mock import MagicMock, patch

import pytest

from frago.compat import (
    get_windows_subprocess_kwargs,
    prepare_command_for_windows,
)


class TestPrepareCommandForWindows:
    """Test prepare_command_for_windows() function."""

    def test_non_windows_returns_unchanged(self):
        """On non-Windows platforms, command should be returned unchanged."""
        with patch("platform.system", return_value="Linux"):
            cmd = ["claude", "-p", "test prompt"]
            result = prepare_command_for_windows(cmd)
            assert result == cmd

    def test_non_windows_darwin(self):
        """On macOS, command should be returned unchanged."""
        with patch("platform.system", return_value="Darwin"):
            cmd = ["frago", "recipe", "run", "test"]
            result = prepare_command_for_windows(cmd)
            assert result == cmd

    def test_empty_command_returns_empty(self):
        """Empty command list should return empty."""
        with patch("platform.system", return_value="Windows"):
            assert prepare_command_for_windows([]) == []

    def test_windows_resolves_path(self):
        """On Windows, command should be resolved to full path."""
        with (
            patch("platform.system", return_value="Windows"),
            patch("shutil.which", return_value="C:\\Users\\test\\AppData\\npm\\claude.CMD"),
        ):
            cmd = ["claude", "-p", "test"]
            result = prepare_command_for_windows(cmd)
            assert result == ["C:\\Users\\test\\AppData\\npm\\claude.CMD", "-p", "test"]

    def test_windows_command_not_found(self):
        """On Windows, if command not found, return unchanged."""
        with (
            patch("platform.system", return_value="Windows"),
            patch("shutil.which", return_value=None),
        ):
            cmd = ["nonexistent", "arg1"]
            result = prepare_command_for_windows(cmd)
            assert result == cmd


class TestGetWindowsSubprocessKwargs:
    """Test get_windows_subprocess_kwargs() function."""

    def test_non_windows_returns_empty(self):
        """On non-Windows platforms, should return empty dict."""
        with patch("platform.system", return_value="Linux"):
            result = get_windows_subprocess_kwargs()
            assert result == {}

    def test_non_windows_darwin_returns_empty(self):
        """On macOS, should return empty dict."""
        with patch("platform.system", return_value="Darwin"):
            result = get_windows_subprocess_kwargs(detach=True)
            assert result == {}

    @pytest.mark.skipif(
        platform.system() != "Windows",
        reason="Windows-specific test",
    )
    def test_windows_returns_kwargs(self):
        """On Windows, should return creationflags and startupinfo."""
        result = get_windows_subprocess_kwargs()
        assert "creationflags" in result
        assert "startupinfo" in result

    @pytest.mark.skipif(
        platform.system() != "Windows",
        reason="Windows-specific test",
    )
    def test_windows_detach_adds_flag(self):
        """On Windows with detach=True, should include DETACHED_PROCESS flag."""
        result_normal = get_windows_subprocess_kwargs(detach=False)
        result_detach = get_windows_subprocess_kwargs(detach=True)

        # Detach should have different (larger) creationflags
        assert result_detach["creationflags"] != result_normal["creationflags"]

    def test_windows_mocked_returns_kwargs(self):
        """Test Windows behavior with mocked platform."""
        # Create mock STARTUPINFO class
        mock_startupinfo_class = MagicMock()
        mock_startupinfo_instance = MagicMock()
        mock_startupinfo_instance.dwFlags = 0
        mock_startupinfo_class.return_value = mock_startupinfo_instance

        mock_subprocess = MagicMock()
        mock_subprocess.STARTUPINFO = mock_startupinfo_class
        mock_subprocess.STARTF_USESHOWWINDOW = 0x00000001
        mock_subprocess.SW_HIDE = 0

        with (
            patch("platform.system", return_value="Windows"),
            patch.dict("sys.modules", {"subprocess": mock_subprocess}),
        ):
            # Need to reimport to get fresh module with mocked subprocess
            import importlib

            import frago.compat

            importlib.reload(frago.compat)

            result = frago.compat.get_windows_subprocess_kwargs()

            # Should have creationflags with CREATE_NO_WINDOW
            assert "creationflags" in result
            assert result["creationflags"] == 0x08000000  # CREATE_NO_WINDOW

            # Restore original module
            with patch("platform.system", return_value="Linux"):
                importlib.reload(frago.compat)
