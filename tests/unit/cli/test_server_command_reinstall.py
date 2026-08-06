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

# What the installed console script is actually called, and where a venv keeps
# it. Windows has no extensionless `frago` and no `.venv/bin`.
IS_WINDOWS = os.name == "nt"
FRAGO_EXE = "frago.exe" if IS_WINDOWS else "frago"
VENV_BIN = "Scripts" if IS_WINDOWS else "bin"


def same_path(a: str, b: str) -> bool:
    """Compare paths the way the platform does — Windows ignores case.

    ``shutil.which`` builds the hit from PATHEXT, which is conventionally
    upper-case, so it reports ``frago.EXE`` for a file stored as ``frago.exe``.
    Both name the same file.
    """
    return os.path.normcase(a) == os.path.normcase(b)


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


def _make_frago(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / FRAGO_EXE
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


class TestSystemFragoPath:
    def test_skips_repo_venv_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo_frago = _make_frago(repo / ".venv" / VENV_BIN)
        system_frago = _make_frago(tmp_path / "local_bin")
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(repo_frago.parent), str(system_frago.parent)])
        )

        found = _system_frago_path(repo)
        assert found is not None and same_path(found, str(system_frago))

    def test_none_when_only_repo_frago(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo_frago = _make_frago(repo / ".venv" / VENV_BIN)
        monkeypatch.setenv("PATH", str(repo_frago.parent))

        assert _system_frago_path(repo) is None

    def test_finds_the_platform_executable_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The lookup must not assume an extensionless ``frago``.

        uv installs ``frago.exe`` on Windows, so probing for a bare ``frago``
        file found nothing and the handoff aborted with "System frago not found
        on PATH" even though the install had just succeeded.
        """
        system_frago = _make_frago(tmp_path / "local_bin")
        monkeypatch.setenv("PATH", str(system_frago.parent))

        found = _system_frago_path(tmp_path / "repo")

        assert found is not None
        assert same_path(Path(found).name, FRAGO_EXE)

    @pytest.mark.skipif(not IS_WINDOWS, reason="POSIX paths are case-sensitive")
    def test_differently_cased_checkout_entry_is_still_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An upper-cased PATH entry names the same directory on Windows."""
        repo = tmp_path / "repo"
        repo_frago = _make_frago(repo / ".venv" / VENV_BIN)
        monkeypatch.setenv("PATH", str(repo_frago.parent).upper())

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

        system_frago = _make_frago(tmp_path / "local_bin")
        system_bin = system_frago.parent

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

        if IS_WINDOWS:
            # No exec on Windows: the handover runs as a child and the caller
            # exits with its status.
            with pytest.raises(SystemExit) as exit_info:
                _reinstall_and_exec_if_source_checkout()
            assert exit_info.value.code == 0
            assert execv_args == []
            handed_over = commands[2]
        else:
            _reinstall_and_exec_if_source_checkout()
            assert len(execv_args) == 1
            target, handed_over = execv_args[0]
            assert same_path(target, str(system_frago))

        # original argv preserved behind the system frago
        assert same_path(handed_over[0], str(system_frago))
        assert handed_over[1:] == ["server", "restart"]

        # version bumped in place
        assert 'version = "1.2.1"' in (repo / "pyproject.toml").read_text()
        # wheel built then installed with --force
        assert commands[0][:4] == ["uv", "build", "--wheel", "--out-dir"]
        assert commands[1][:4] == ["uv", "tool", "install", "--force"]
        assert commands[1][4].endswith(".whl")
        # temp wheel dir cleaned up
        assert not Path(commands[1][4]).exists()
        assert os.environ[REINSTALL_SENTINEL_ENV] == "1"

    def test_blocked_handover_explains_itself(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A refused launch must not surface as a raw OSError traceback.

        Windows Smart App Control rejects the freshly built launcher with
        WinError 4551. The install has already succeeded at that point, so the
        message has to say what is done and what to change — a traceback tells
        the reader neither.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(PYPROJECT_TEMPLATE, encoding="utf-8")
        system_frago = _make_frago(tmp_path / "local_bin")

        monkeypatch.delenv(REINSTALL_SENTINEL_ENV, raising=False)
        monkeypatch.setenv("PATH", str(system_frago.parent))
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: repo
        )
        monkeypatch.setattr("sys.argv", ["frago", "server", "restart"])

        blocked = OSError("blocked by application control policy")
        blocked.winerror = server_command.WINDOWS_APP_CONTROL_ERROR  # type: ignore[attr-defined]

        class FakeCompleted:
            returncode = 0
            stderr = ""

        def fake_run(cmd, **_kwargs):
            if cmd[:2] == ["uv", "build"]:
                out_dir = Path(cmd[cmd.index("--out-dir") + 1])
                (out_dir / "frago_cli-1.2.1-py3-none-any.whl").write_bytes(b"")
                return FakeCompleted()
            if cmd[:3] == ["uv", "tool", "install"]:
                return FakeCompleted()
            raise blocked  # the handover

        monkeypatch.setattr(server_command.subprocess, "run", fake_run)
        monkeypatch.setattr(os, "execv", lambda *_a: (_ for _ in ()).throw(blocked))

        with pytest.raises(click.ClickException) as exc_info:
            _reinstall_and_exec_if_source_checkout()

        message = str(exc_info.value)
        assert "Smart App Control" in message
        # the install already happened — say so, or the reader retries for nothing
        assert "1.2.1 is installed" in message

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


class TestDropCheckoutVenvFromPath:
    """The checkout's virtualenv must not follow the server into its lifetime.

    ``uv run frago server start`` puts it first on PATH so the build step works.
    Replacing the process keeps the environment, so without this cleanup the
    server — and every recipe it spawns — resolves plain ``frago`` to the
    checkout copy, which refuses to run anything but ``server``. The recipe then
    fails with a message about source checkouts while the server looks healthy.
    """

    def test_checkout_venv_entry_is_removed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        venv_bin = tmp_path / ".venv" / VENV_BIN
        venv_bin.mkdir(parents=True)
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(venv_bin), "/usr/bin", "/bin"])
        )
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert str(venv_bin) not in os.environ["PATH"].split(os.pathsep)

    def test_both_venv_layouts_are_recognised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``bin`` on POSIX, ``Scripts`` on Windows — neither may be assumed.

        Hard-coding ``.venv/bin`` made this a silent no-op on Windows: the
        checkout venv stayed on PATH, so the server and every recipe it spawned
        resolved plain ``frago`` back to the checkout copy.
        """
        for name in ("bin", "Scripts"):
            (tmp_path / ".venv" / name).mkdir(parents=True, exist_ok=True)
        entries = [str(tmp_path / ".venv" / n) for n in ("bin", "Scripts")]
        monkeypatch.setenv("PATH", os.pathsep.join([*entries, "/usr/bin"]))
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert os.environ["PATH"] == "/usr/bin"

    def test_everything_else_survives_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        venv_bin = tmp_path / ".venv" / VENV_BIN
        venv_bin.mkdir(parents=True)
        monkeypatch.setenv(
            "PATH",
            os.pathsep.join([str(venv_bin), "/usr/local/bin", "/usr/bin", "/bin"]),
        )
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert os.environ["PATH"].split(os.pathsep) == [
            "/usr/local/bin", "/usr/bin", "/bin",
        ]

    def test_other_virtualenvs_are_left_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only this checkout's venv goes. A user's own active venv is theirs."""
        (tmp_path / ".venv" / VENV_BIN).mkdir(parents=True)
        other = tmp_path / "other-project" / ".venv" / VENV_BIN
        other.mkdir(parents=True)
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(other), str(tmp_path / ".venv" / VENV_BIN)])
        )
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert os.environ["PATH"] == str(other)

    def test_stale_virtual_env_pointer_is_cleared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Leaving it set points readers at an environment no longer on PATH."""
        (tmp_path / ".venv" / VENV_BIN).mkdir(parents=True)
        monkeypatch.setenv("PATH", str(tmp_path / ".venv" / VENV_BIN))
        monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / ".venv"))
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert "VIRTUAL_ENV" not in os.environ

    def test_unrelated_virtual_env_pointer_is_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".venv" / VENV_BIN).mkdir(parents=True)
        monkeypatch.setenv("PATH", str(tmp_path / ".venv" / VENV_BIN))
        monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else/.venv")
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert os.environ["VIRTUAL_ENV"] == "/somewhere/else/.venv"

    def test_no_checkout_venv_on_path_is_a_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
        server_command._drop_checkout_venv_from_path(tmp_path)
        assert os.environ["PATH"] == os.pathsep.join(["/usr/bin", "/bin"])
