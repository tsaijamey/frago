"""Tests for the source-checkout reinstall handoff in frago.cli.server_command."""

from __future__ import annotations

import os
from pathlib import Path

import click
import pytest

from frago.cli import server_command
from frago.cli.server_command import (
    REINSTALL_SENTINEL_ENV,
    _bump_patch_version,
    _reinstall_and_exec_if_source_checkout,
    _system_frago_path,
)

PYPROJECT_TEMPLATE = """\
[project]
# a comment that must survive
name = "frago-cli"
version = "1.2.0"
description = "x"
"""


class TestBumpPatchVersion:
    def test_bumps_only_patch_segment(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_TEMPLATE, encoding="utf-8")

        new = _bump_patch_version(pyproject)

        assert new == "1.2.1"
        text = pyproject.read_text(encoding="utf-8")
        assert 'version = "1.2.1"' in text
        # rest of the file is byte-identical
        assert text == PYPROJECT_TEMPLATE.replace('"1.2.0"', '"1.2.1"')

    def test_rejects_non_xyz_version(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "1.2.0rc1"\n', encoding="utf-8")
        with pytest.raises(click.ClickException):
            _bump_patch_version(pyproject)

    def test_rejects_missing_version_line(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        with pytest.raises(click.ClickException):
            _bump_patch_version(pyproject)


class TestSystemFragoPath:
    def _make_frago(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        exe = directory / "frago"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        return exe

    def test_skips_repo_venv_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo_frago = self._make_frago(repo / ".venv" / "bin")
        system_frago = self._make_frago(tmp_path / "local_bin")
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(repo_frago.parent), str(system_frago.parent)])
        )

        assert _system_frago_path(repo) == str(system_frago)

    def test_none_when_only_repo_frago(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo_frago = self._make_frago(repo / ".venv" / "bin")
        monkeypatch.setenv("PATH", str(repo_frago.parent))

        assert _system_frago_path(repo) is None


class TestReinstallHandoff:
    def test_noop_outside_checkout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(REINSTALL_SENTINEL_ENV, raising=False)
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: None
        )
        called: list[str] = []
        monkeypatch.setattr(os, "execv", lambda *_a: called.append("execv"))

        _reinstall_and_exec_if_source_checkout()

        assert called == []

    def test_noop_when_sentinel_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(REINSTALL_SENTINEL_ENV, "1")
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: tmp_path
        )
        called: list[str] = []
        monkeypatch.setattr(os, "execv", lambda *_a: called.append("execv"))

        _reinstall_and_exec_if_source_checkout()

        assert called == []

    def test_full_handoff_flow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(PYPROJECT_TEMPLATE, encoding="utf-8")

        system_bin = tmp_path / "local_bin"
        system_bin.mkdir()
        system_frago = system_bin / "frago"
        system_frago.write_text("#!/bin/sh\n")
        system_frago.chmod(0o755)

        monkeypatch.delenv(REINSTALL_SENTINEL_ENV, raising=False)
        monkeypatch.setenv("PATH", str(system_bin))
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: repo
        )
        monkeypatch.setattr("sys.argv", ["frago", "server", "restart"])

        commands: list[list[str]] = []

        class FakeCompleted:
            returncode = 0
            stderr = ""

        def fake_run(cmd, **_kwargs):
            commands.append(list(cmd))
            if cmd[:2] == ["uv", "build"]:
                out_dir = Path(cmd[cmd.index("--out-dir") + 1])
                (out_dir / "frago_cli-1.2.1-py3-none-any.whl").write_bytes(b"")
            return FakeCompleted()

        monkeypatch.setattr(server_command.subprocess, "run", fake_run)

        execv_args: list = []
        monkeypatch.setattr(
            os, "execv", lambda path, args: execv_args.append((path, args))
        )

        _reinstall_and_exec_if_source_checkout()

        # version bumped in place
        assert 'version = "1.2.1"' in (repo / "pyproject.toml").read_text()
        # wheel built then installed with --force
        assert commands[0][:4] == ["uv", "build", "--wheel", "--out-dir"]
        assert commands[1][:4] == ["uv", "tool", "install", "--force"]
        assert commands[1][4].endswith(".whl")
        # temp wheel dir cleaned up
        assert not Path(commands[1][4]).exists()
        # handed over to the system frago with original argv and sentinel set
        assert execv_args == [
            (str(system_frago), [str(system_frago), "server", "restart"])
        ]
        assert os.environ[REINSTALL_SENTINEL_ENV] == "1"

    def test_build_failure_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(PYPROJECT_TEMPLATE, encoding="utf-8")
        monkeypatch.delenv(REINSTALL_SENTINEL_ENV, raising=False)
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: repo
        )

        class Failed:
            returncode = 1
            stderr = "boom"

        monkeypatch.setattr(
            server_command.subprocess, "run", lambda *_a, **_k: Failed()
        )
        with pytest.raises(click.ClickException, match="uv build failed"):
            _reinstall_and_exec_if_source_checkout()
