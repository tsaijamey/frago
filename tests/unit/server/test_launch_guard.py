"""Tests for frago.server.launch_guard Gate 2 (system-install assertion)."""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.server import launch_guard


def test_assert_system_install_noop_for_global_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launch_guard, "source_checkout_root", lambda: None)
    launch_guard.assert_system_install()  # must not raise / exit


def test_assert_system_install_refuses_repo_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(launch_guard, "source_checkout_root", lambda: tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        launch_guard.assert_system_install()
    assert excinfo.value.code == 1


def test_source_checkout_root_none_outside_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launch_guard.sys, "prefix", "/usr")
    monkeypatch.setattr(launch_guard.sys, "base_prefix", "/usr")
    assert launch_guard.source_checkout_root() is None


def test_source_checkout_root_detects_repo_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "frago"
    (repo / "src" / "frago").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("")
    venv = repo / ".venv"
    venv.mkdir()
    monkeypatch.setattr(launch_guard.sys, "prefix", str(venv))
    monkeypatch.setattr(launch_guard.sys, "base_prefix", "/usr")
    assert launch_guard.source_checkout_root() == repo
