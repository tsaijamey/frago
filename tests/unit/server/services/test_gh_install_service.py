"""Tests for frago.server.services.gh_install_service.

Covers how the machine is sized up before an install runs, and the archive
path, which is the one that has to work on machines with no package manager.
"""
import io
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services import gh_install_service
from frago.server.services.gh_install_service import (
    GhInstallService,
    detect_install_plan,
)


class TestDetectInstallPlan:
    """Which install route this machine gets."""

    def test_prefers_brew_on_macos_when_present(self):
        with patch("platform.system", return_value="Darwin"), patch.object(
            gh_install_service, "_brew_command", return_value=["/opt/homebrew/bin/brew"]
        ):
            plan = detect_install_plan()

        assert plan["method"] == "brew"
        assert plan["command"] == "brew install gh"
        assert plan["needs_path_hint"] is False

    def test_prefers_winget_on_windows_when_present(self):
        with patch("platform.system", return_value="Windows"), patch.object(
            gh_install_service, "_winget_command", return_value=["winget"]
        ):
            plan = detect_install_plan()

        assert plan["method"] == "winget"
        assert plan["needs_path_hint"] is False

    def test_falls_back_to_archive_without_a_package_manager(self):
        """No brew, no winget — download the release rather than give up."""
        with patch("platform.system", return_value="Linux"), patch.object(
            gh_install_service, "_brew_command", return_value=None
        ):
            plan = detect_install_plan()

        assert plan["method"] == "binary"
        # The archive lands outside the shell PATH, so the user has to be told.
        assert plan["needs_path_hint"] is True
        assert plan["manual_url"]


class TestReleaseAssetPattern:
    """The (os, arch) fragment used to pick an asset out of the release."""

    @pytest.mark.parametrize(
        "system,machine,expected",
        [
            ("Darwin", "arm64", ("macOS", "arm64")),
            ("Darwin", "x86_64", ("macOS", "amd64")),
            ("Linux", "aarch64", ("linux", "arm64")),
            ("Linux", "x86_64", ("linux", "amd64")),
            ("Windows", "AMD64", ("windows", "amd64")),
        ],
    )
    def test_maps_known_platforms(self, system, machine, expected):
        with patch("platform.system", return_value=system), patch(
            "platform.machine", return_value=machine
        ):
            assert gh_install_service._release_asset_pattern() == expected

    def test_returns_none_for_a_platform_gh_does_not_ship(self):
        """Better to stop than to download something that cannot run."""
        with patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="mips64"
        ):
            assert gh_install_service._release_asset_pattern() is None


class TestExtractBinary:
    """Only the one wanted member comes out, and only where we put it."""

    def test_pulls_gh_out_of_a_tarball(self, tmp_path: Path):
        archive = tmp_path / "gh_2.0.0_linux_amd64.tar.gz"
        payload = b"#!/bin/sh\necho gh\n"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("gh_2.0.0_linux_amd64/bin/gh")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        target = tmp_path / "out" / "gh"
        target.parent.mkdir()
        GhInstallService._extract_binary(archive, "gh", target)

        assert target.read_bytes() == payload

    def test_pulls_gh_out_of_a_zip(self, tmp_path: Path):
        archive = tmp_path / "gh_2.0.0_macOS_arm64.zip"
        payload = b"binary"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("gh_2.0.0_macOS_arm64/bin/gh", payload)

        target = tmp_path / "gh"
        GhInstallService._extract_binary(archive, "gh", target)

        assert target.read_bytes() == payload

    def test_says_so_when_the_archive_has_no_binary(self, tmp_path: Path):
        archive = tmp_path / "empty.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("README.md", "nothing here")

        with pytest.raises(RuntimeError, match="bin/gh"):
            GhInstallService._extract_binary(archive, "gh", tmp_path / "gh")


class TestInstallViaCommand:
    """The package-manager path: stream the output, fail loudly on non-zero."""

    def _fake_process(self, lines, returncode):
        process = MagicMock()
        process.stdout = iter(lines)
        process.wait.return_value = returncode
        return process

    def test_captures_output_and_succeeds(self):
        GhInstallService._set(status="running", log=[])
        with patch(
            "subprocess.Popen",
            return_value=self._fake_process(["==> Downloading\n", "==> Pouring\n"], 0),
        ):
            GhInstallService._install_via_command(["brew", "install", "gh"])

        log = GhInstallService.get_status()["log"]
        assert "$ brew install gh" in log
        assert "==> Pouring" in log

    def test_raises_when_the_command_fails(self):
        GhInstallService._set(status="running", log=[])
        with patch(
            "subprocess.Popen",
            return_value=self._fake_process(["Error: no formula\n"], 1),
        ):
            with pytest.raises(RuntimeError, match="exited with code 1"):
                GhInstallService._install_via_command(["brew", "install", "gh"])


class TestStatusReporting:
    """The UI polls this; it must not hand out its own mutable state."""

    def test_log_is_a_copy(self):
        GhInstallService._set(status="running", log=[])
        GhInstallService._log("first")
        snapshot = GhInstallService.get_status()
        GhInstallService._log("second")

        assert snapshot["log"] == ["first"]

    def test_log_stays_bounded(self):
        GhInstallService._set(status="running", log=[])
        for i in range(gh_install_service._MAX_LOG_LINES + 50):
            GhInstallService._log(f"line {i}")

        log = GhInstallService.get_status()["log"]
        assert len(log) == gh_install_service._MAX_LOG_LINES
        # It is the tail that is kept — that is where a failure shows up.
        assert log[-1] == f"line {gh_install_service._MAX_LOG_LINES + 49}"

    def test_second_start_does_not_launch_a_second_install(self):
        GhInstallService._set(status="running", method="brew")
        try:
            result = GhInstallService.start()
        finally:
            GhInstallService._set(status="idle", method=None, log=[])

        assert result["already_running"] is True


class TestPathHint:
    """The line handed to users whose gh landed outside the shell PATH."""

    def test_zsh_users_get_zshrc(self, tmp_path: Path):
        with patch("platform.system", return_value="Darwin"), patch.dict(
            "os.environ", {"SHELL": "/bin/zsh"}
        ):
            hint = GhInstallService._path_hint(tmp_path)

        assert ".zshrc" in hint
        assert str(tmp_path) in hint

    def test_windows_users_get_setx(self, tmp_path: Path):
        with patch("platform.system", return_value="Windows"):
            hint = GhInstallService._path_hint(tmp_path)

        assert hint.startswith("setx PATH")
