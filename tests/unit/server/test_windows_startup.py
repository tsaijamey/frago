"""Tests for Windows platform startup, import chain integrity, and POSIX module isolation."""

import sys
import unittest.mock as mock
import pytest


def test_cli_import_without_posix_modules():
    """Verify frago CLI and server modules import cleanly when POSIX modules are absent (Windows simulation)."""
    posix_modules = ["fcntl", "termios", "tty", "pty", "pwd", "grp", "resource", "syslog"]

    with mock.patch.dict(sys.modules, {mod: None for mod in posix_modules}):
        import frago.cli.main
        import frago.cli.server_command
        import frago.calendar.store
        import frago.server.daemon
        import frago.server.runner

        assert frago.cli.main.cli is not None
        assert frago.server.daemon.start_daemon is not None
        assert frago.calendar.store._IS_WINDOWS in (True, False)


def test_calendar_store_windows_lock_avoids_fcntl():
    """Verify that when _IS_WINDOWS is True, calendar store uses msvcrt and never imports fcntl."""
    from frago.calendar import store

    fake_msvcrt = mock.MagicMock()
    mock_file = mock.MagicMock()
    mock_open_context = mock.MagicMock()
    mock_open_context.__enter__.return_value = mock_file

    with mock.patch.object(store, "_IS_WINDOWS", True), \
         mock.patch("builtins.open", return_value=mock_open_context), \
         mock.patch.dict(sys.modules, {"msvcrt": fake_msvcrt, "fcntl": None}):

        with store._month_lock("2026-11"):
            pass

        assert fake_msvcrt.locking.called


def test_windows_subprocess_kwargs():
    """Verify Windows subprocess kwargs hide console windows."""
    from frago.compat import get_windows_subprocess_kwargs
    import subprocess

    fake_startupinfo = mock.MagicMock()
    with mock.patch("platform.system", return_value="Windows"), \
         mock.patch.object(subprocess, "STARTUPINFO", return_value=fake_startupinfo, create=True), \
         mock.patch.object(subprocess, "STARTF_USESHOWWINDOW", 1, create=True), \
         mock.patch.object(subprocess, "SW_HIDE", 0, create=True):
        kwargs = get_windows_subprocess_kwargs(detach=False)
        assert "creationflags" in kwargs
        assert kwargs["creationflags"] == 0x08000000  # CREATE_NO_WINDOW
        assert "startupinfo" in kwargs

        detach_kwargs = get_windows_subprocess_kwargs(detach=True)
        assert detach_kwargs["creationflags"] == (0x08000000 | 0x00000008)
