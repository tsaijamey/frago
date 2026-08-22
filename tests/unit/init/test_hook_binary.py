"""Tests for hook binary deployment and the cleanup of superseded copies."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from frago.init import hook_binary


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point both hook directories somewhere disposable."""
    legacy = tmp_path / "claude-hooks"
    deploy = tmp_path / "frago-bin"
    legacy.mkdir()
    deploy.mkdir()
    monkeypatch.setattr(hook_binary, "get_legacy_hook_dir", lambda: legacy)
    monkeypatch.setattr(hook_binary, "get_hook_deploy_dir", lambda: deploy)
    return legacy, deploy


def as_platform(monkeypatch: pytest.MonkeyPatch, system: str) -> None:
    monkeypatch.setattr(hook_binary.platform, "system", lambda: system)


class TestCleanupLegacyHookCopy:
    def test_removes_the_windows_binary(
        self, dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The suffix is part of the name on Windows.

        Looking only for an extensionless ``frago-hook`` made this a no-op
        there, so the pre-rename binary survived every deploy — and a
        settings.json still pointing at it kept running indefinitely.
        """
        as_platform(monkeypatch, "Windows")
        legacy, deploy = dirs
        stale_legacy = legacy / "frago-hook.exe"
        stale_deploy = deploy / "frago-hook.exe"
        stale_legacy.write_bytes(b"old")
        stale_deploy.write_bytes(b"old")

        hook_binary.cleanup_legacy_hook_copy()

        assert not stale_legacy.exists()
        assert not stale_deploy.exists()

    def test_removes_the_posix_binary(
        self, dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_platform(monkeypatch, "Linux")
        legacy, deploy = dirs
        stale = legacy / "frago-hook"
        stale.write_bytes(b"old")

        hook_binary.cleanup_legacy_hook_copy()

        assert not stale.exists()

    def test_leaves_the_current_binary_and_scripts_alone(
        self, dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the superseded binary name goes.

        A script is registered in settings.json, so deleting it here — before
        anything unregisters it — would leave Claude Code invoking a file that
        is gone. Scripts are retired by ``retired_artifacts``.
        """
        as_platform(monkeypatch, "Windows")
        legacy, deploy = dirs
        script = legacy / "session-start-book.sh"
        current = deploy / "frago-core.exe"
        script.write_text("#!/bin/sh\n")
        current.write_bytes(b"new")

        hook_binary.cleanup_legacy_hook_copy()

        assert script.exists()
        assert current.exists()

    def test_missing_copies_are_normal(
        self, dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_platform(monkeypatch, "Linux")

        hook_binary.cleanup_legacy_hook_copy()  # a fresh install has none


class TestEventRegistrationRecognisesADrift:
    """What counts as "already registered the way we want it".

    The comparison used to look at the matcher and the command only. On a machine
    where the hook was already registered, a timeout changed in frago's code
    therefore never arrived: the command was identical, the entry was left alone,
    and nothing reported that the new value had not been applied. The timeout is
    what keeps the runtime from killing a long-running hook — and when it does,
    the agent loses every injection the hook had already computed — so a change
    to it has to be treated as drift.
    """

    @staticmethod
    def registered(timeout: int) -> dict[str, list[dict[str, object]]]:
        return {
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/x/frago-core --engine",
                            "timeout": timeout,
                        }
                    ],
                }
            ]
        }

    def wanted(self, timeout: int) -> dict[str, object]:
        return {"type": "command", "command": "/x/frago-core --engine", "timeout": timeout}

    def test_same_command_and_timeout_is_in_sync(self) -> None:
        assert hook_binary._has_frago_hook_with_matching_entry(
            self.registered(20), "UserPromptSubmit", "", self.wanted(20)
        )

    def test_a_changed_timeout_counts_as_drift(self) -> None:
        assert not hook_binary._has_frago_hook_with_matching_entry(
            self.registered(10), "UserPromptSubmit", "", self.wanted(20)
        )

    def test_a_changed_command_still_counts_as_drift(self) -> None:
        assert not hook_binary._has_frago_hook_with_matching_entry(
            self.registered(20), "UserPromptSubmit", "", {
                "type": "command",
                "command": "/elsewhere/frago-core --engine",
                "timeout": 20,
            }
        )

    def test_a_different_matcher_is_not_the_same_registration(self) -> None:
        assert not hook_binary._has_frago_hook_with_matching_entry(
            self.registered(20), "UserPromptSubmit", "Bash", self.wanted(20)
        )

    def test_an_unregistered_event_is_drift(self) -> None:
        assert not hook_binary._has_frago_hook_with_matching_entry(
            {}, "UserPromptSubmit", "", self.wanted(20)
        )


class TestDeployAnnouncesAppControl:
    def test_blocked_binary_gets_a_reason_in_the_log(
        self,
        dirs: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Deploy succeeds even when the binary will never load.

        Smart App Control blocks it at load time, not at copy time, so without
        this line the log records a clean deploy and nothing else — and the
        missing routing looks like a frago bug.
        """
        as_platform(monkeypatch, "Windows")
        bundled = tmp_path / "frago-core.exe"
        bundled.write_bytes(b"binary")
        monkeypatch.setattr(hook_binary, "get_bundled_binary_path", lambda: bundled)
        monkeypatch.setattr(
            hook_binary, "smart_app_control_warning", lambda: "SAC is on"
        )

        with caplog.at_level(logging.WARNING, logger=hook_binary.logger.name):
            hook_binary.deploy_hook_binary()

        assert "SAC is on" in caplog.text

    def test_nothing_said_when_the_platform_is_fine(
        self,
        dirs: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        as_platform(monkeypatch, "Linux")
        bundled = tmp_path / "frago-core"
        bundled.write_bytes(b"binary")
        monkeypatch.setattr(hook_binary, "get_bundled_binary_path", lambda: bundled)
        monkeypatch.setattr(hook_binary, "smart_app_control_warning", lambda: None)

        with caplog.at_level(logging.WARNING, logger=hook_binary.logger.name):
            deployed = hook_binary.deploy_hook_binary()

        assert caplog.text == ""
        assert deployed.read_bytes() == b"binary"
