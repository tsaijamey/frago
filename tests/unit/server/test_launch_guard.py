"""Tests for frago.server.launch_guard (Gate 1 spawn env, Gate 2 system install)."""

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


class TestSanctionedSpawnEnv:
    """daemon 长过拉它起来的那场会话，不能带着那场的身份。"""

    def test_the_token_rides_along(self) -> None:
        env = launch_guard.sanctioned_spawn_env({"PATH": "/bin"})
        assert env[launch_guard.SPAWN_TOKEN_ENV] == launch_guard.SPAWN_TOKEN_VALUE
        assert env["PATH"] == "/bin"  # 其余照带，别把 VIRTUAL_ENV 这类丢了

    def test_session_identity_is_stripped(self) -> None:
        """2026-10-15：服务端继承了重启它那场的编号，随后 8 条子会话被错挂到那场名下。"""
        env = launch_guard.sanctioned_spawn_env(
            {
                "FRAGO_SESSION_ID": "core_6b8d623fe9bf436ba63064b6f4d9dfe8",
                "CLAUDE_CODE_SESSION_ID": "1b75fa7d-4bff-4817-b536-755ddcd2700d",
                "FRAGO_AGENT_ROLE": "worker",
            }
        )
        assert "FRAGO_SESSION_ID" not in env
        assert "CLAUDE_CODE_SESSION_ID" not in env
        assert "FRAGO_AGENT_ROLE" not in env

    def test_an_explicit_base_is_honoured_too(self) -> None:
        """两个调用点（start_daemon / restarter）都从这里走，清的是同一份。"""
        env = launch_guard.sanctioned_spawn_env({"FRAGO_SESSION_ID": "x"})
        assert "FRAGO_SESSION_ID" not in env
