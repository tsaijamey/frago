"""Tests for the source-checkout reinstall handoff in frago.cli.server_command."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import click
import pytest

from frago.cli import server_command
from frago.cli.server_command import (
    REINSTALL_SENTINEL_ENV,
    _local_build_version,
    _reinstall_and_exec_if_source_checkout,
    _system_frago_path,
    _wheel_source_files,
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


def _init_git_repo(repo: Path) -> str:
    """Make ``repo`` a git repo with one commit. Returns its short HEAD sha."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.test",
    }

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, env=env
        )
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "init")
    return git("rev-parse", "--short=12", "HEAD")


def _repo_with_pyproject(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(PYPROJECT_TEMPLATE, encoding="utf-8")
    return repo


class TestLocalBuildVersion:
    """本机构建报的号 = 发布号 + 一段本地标识，发布号一个字不动。

    从前这里是给发布号的补丁位加一、写回 pyproject.toml，于是同一个号有了两个写者：
    发布照仓库现状发，本机每部署一次把号往上推一格，两边迟早对不上——发出去的是 a，
    本机跑的是 a+1，代码其实是同一份。
    """

    def test_release_number_is_left_alone(self, tmp_path: Path) -> None:
        repo = _repo_with_pyproject(tmp_path)
        _init_git_repo(repo)

        version = _local_build_version(repo)

        assert version.startswith("1.2.0+local.")
        # 仓库那份一个字节都没动
        assert (repo / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT_TEMPLATE

    def test_stamp_names_the_commit_it_came_from(self, tmp_path: Path) -> None:
        """认得出是哪个提交，发布那边才能回答「本机跑的是不是要发的这一份」。"""
        repo = _repo_with_pyproject(tmp_path)
        sha = _init_git_repo(repo)

        assert f"g{sha}" in _local_build_version(repo)

    def test_uncommitted_work_is_marked(self, tmp_path: Path) -> None:
        """带未提交改动的构建不是任何一个提交，得看得出来。"""
        repo = _repo_with_pyproject(tmp_path)
        _init_git_repo(repo)
        (repo / "untracked.py").write_text("x = 1\n", encoding="utf-8")

        assert ".dirty" in _local_build_version(repo)

    def test_without_git_it_still_reports_something(self, tmp_path: Path) -> None:
        """认不出提交也不能变成空段——这一段的作用是让两次构建分得开。"""
        repo = _repo_with_pyproject(tmp_path)

        assert re.fullmatch(r"1\.2\.0\+local\.\d{8}T\d{6}", _local_build_version(repo))

    def test_missing_version_line_still_raises(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        with pytest.raises(click.ClickException):
            _local_build_version(tmp_path)


class TestWheelSourceFiles:
    """构建要从仓库里搬哪些文件。

    这份名单从前是手写的跳过列表，而列表只是规则的近似：它跳掉了
    node_modules 和缓存，却漏掉被 gitignore 的 *.log，于是那些文件进了
    本机构建的 wheel，而真正的发布构建不要它们——本机装的那份因此不是
    同一件东西。现在问 git 自己，跟 hatchling 构建时用的是同一套规则。
    """

    def test_gitignored_files_stay_out(self, tmp_path: Path) -> None:
        repo = _repo_with_pyproject(tmp_path)
        package = repo / "src" / "frago"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (repo / ".gitignore").write_text("*.log\njunk/\n", encoding="utf-8")
        (package / "process.log").write_text("noise\n", encoding="utf-8")
        (package / "junk").mkdir()
        (package / "junk" / "big.bin").write_bytes(b"x" * 32)
        _init_git_repo(repo)

        files = _wheel_source_files(repo)

        assert "src/frago/__init__.py" in files
        assert "src/frago/process.log" not in files
        assert not any(f.startswith("src/frago/junk/") for f in files)

    def test_untracked_work_still_ships(self, tmp_path: Path) -> None:
        """没提交的改动要跟着走——本机构建的意义就是部署手头这一份。"""
        repo = _repo_with_pyproject(tmp_path)
        package = repo / "src" / "frago"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        _init_git_repo(repo)
        (package / "brand_new.py").write_text("x = 1\n", encoding="utf-8")

        assert "src/frago/brand_new.py" in _wheel_source_files(repo)

    def test_without_git_it_says_nothing(self, tmp_path: Path) -> None:
        """git 答不出来就交白卷，让调用方退回照抄整棵树。"""
        repo = _repo_with_pyproject(tmp_path)

        assert _wheel_source_files(repo) == []


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

    def test_sentinel_does_not_outlive_the_handed_over_process(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The server must not inherit the sentinel.

        It used to stay set, so the server carried it, tmux took it from the
        server, and every agent session in tmux took it from tmux. A
        ``uv run frago server restart`` run there skipped the reinstall and
        restarted the old installed code while printing nothing wrong.
        """
        monkeypatch.setenv(REINSTALL_SENTINEL_ENV, "1")
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: tmp_path
        )
        monkeypatch.setattr(os, "execv", lambda *_a: None)

        _reinstall_and_exec_if_source_checkout()

        assert REINSTALL_SENTINEL_ENV not in os.environ

    def test_full_handoff_flow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo = _repo_with_pyproject(tmp_path)
        (repo / "src" / "frago").mkdir(parents=True)
        (repo / "src" / "frago" / "__init__.py").write_text("", encoding="utf-8")
        _init_git_repo(repo)

        system_frago = _make_frago(tmp_path / "local_bin")
        system_bin = system_frago.parent
        git_exe = shutil.which("git")

        monkeypatch.delenv(REINSTALL_SENTINEL_ENV, raising=False)
        monkeypatch.setenv("PATH", str(system_bin))
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: repo
        )
        monkeypatch.setattr("sys.argv", ["frago", "server", "restart"])

        commands: list[list[str]] = []
        built_from: list[Path] = []
        real_run = subprocess.run

        class FakeCompleted:
            returncode = 0
            stderr = ""
            stdout = ""

        def fake_run(cmd, **kwargs):
            # Patching server_command.subprocess.run patches subprocess.run
            # itself, so the version stamp's git lookups land here too. Let
            # them through to the real thing, by absolute path — the narrowed
            # PATH above hides git, and stubbing these out would only exercise
            # the no-git fallback.
            if cmd[:1] == ["git"]:
                return real_run([git_exe, *cmd[1:]], **kwargs)
            commands.append(list(cmd))
            if cmd[:2] == ["uv", "build"]:
                # the source is the last positional; it must not be the checkout
                source = Path(cmd[-1])
                built_from.append(source)
                out_dir = Path(cmd[cmd.index("--out-dir") + 1])
                (out_dir / "frago_cli-1.2.0+local.test-py3-none-any.whl").write_bytes(b"")
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

        # the checkout is left exactly as it was found
        assert (repo / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT_TEMPLATE
        # built from a throwaway copy, not from the checkout
        assert len(built_from) == 1
        assert built_from[0] != repo
        # wheel built then installed with --force
        assert commands[0][:4] == ["uv", "build", "--wheel", "--out-dir"]
        assert commands[1][:4] == ["uv", "tool", "install", "--force"]
        assert commands[1][4].endswith(".whl")
        # temp wheel dir cleaned up
        assert not Path(commands[1][4]).exists()
        assert os.environ[REINSTALL_SENTINEL_ENV] == "1"

    def test_built_copy_carries_the_local_version(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The version the wheel is built under is the release number plus the
        local segment — and the release number in the copy is what moved, not
        the one in the checkout."""
        repo = _repo_with_pyproject(tmp_path)
        (repo / "src" / "frago").mkdir(parents=True)
        (repo / "src" / "frago" / "__init__.py").write_text("", encoding="utf-8")
        sha = _init_git_repo(repo)
        git_exe = shutil.which("git")

        monkeypatch.delenv(REINSTALL_SENTINEL_ENV, raising=False)
        monkeypatch.setattr(
            "frago.server.launch_guard.source_checkout_root", lambda: repo
        )
        monkeypatch.setenv("PATH", str(_make_frago(tmp_path / "local_bin").parent))
        monkeypatch.setattr("sys.argv", ["frago", "server", "restart"])

        seen: list[str] = []
        real_run = subprocess.run

        class FakeCompleted:
            returncode = 0
            stderr = ""
            stdout = ""

        def fake_run(cmd, **kwargs):
            # by absolute path: the narrowed PATH above hides git
            if cmd[:1] == ["git"]:
                return real_run([git_exe, *cmd[1:]], **kwargs)
            if cmd[:2] == ["uv", "build"]:
                source = Path(cmd[-1])
                text = (source / "pyproject.toml").read_text(encoding="utf-8")
                seen.append(text)
                out_dir = Path(cmd[cmd.index("--out-dir") + 1])
                (out_dir / "frago_cli-1.2.0+local.test-py3-none-any.whl").write_bytes(b"")
            return FakeCompleted()

        monkeypatch.setattr(server_command.subprocess, "run", fake_run)
        monkeypatch.setattr(os, "execv", lambda *_a: None)

        _reinstall_and_exec_if_source_checkout()

        assert len(seen) == 1
        # the built copy names the commit it came from, so the publish side can
        # answer "is the running copy the one about to go out"
        assert f"1.2.0+local.g{sha}." in seen[0]
        # the release number in the checkout survived untouched
        assert 'version = "1.2.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")

    def test_blocked_handover_explains_itself(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A refused launch must not surface as a raw OSError traceback.

        Windows Smart App Control rejects the freshly built launcher with
        WinError 4551. The install has already succeeded at that point, so the
        message has to say what is done and what to change — a traceback tells
        the reader neither.
        """
        repo = _repo_with_pyproject(tmp_path)
        (repo / "src" / "frago").mkdir(parents=True)
        (repo / "src" / "frago" / "__init__.py").write_text("", encoding="utf-8")
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
            stdout = ""

        def fake_run(cmd, **_kwargs):
            if cmd[:2] == ["uv", "build"]:
                out_dir = Path(cmd[cmd.index("--out-dir") + 1])
                (out_dir / "frago_cli-1.2.0+local.test-py3-none-any.whl").write_bytes(b"")
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
        assert "1.2.0+local." in message and "is installed" in message

    def test_build_failure_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo = _repo_with_pyproject(tmp_path)
        (repo / "src" / "frago").mkdir(parents=True)
        (repo / "src" / "frago" / "__init__.py").write_text("", encoding="utf-8")
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
