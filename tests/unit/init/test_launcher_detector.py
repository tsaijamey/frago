"""Tests for frago.init.launcher_detector."""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.init.launcher_detector import detect_launcher


@pytest.fixture
def make_venv(tmp_path: Path) -> Path:
    """Create a fake <project>/.venv layout with pyproject.toml."""
    project = tmp_path / "myproject"
    venv = project / ".venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    (bin_dir / "frago").write_text("#!/bin/sh\n")
    (bin_dir / "frago").chmod(0o755)
    return project


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("VIRTUAL_ENV", "UV_PROJECT"):
        monkeypatch.delenv(key, raising=False)


def test_global_mode_uses_absolute_path_from_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch)
    fake_bin = tmp_path / "local_bin"
    fake_bin.mkdir()
    frago_path = fake_bin / "frago"
    frago_path.write_text("#!/bin/sh\n")
    frago_path.chmod(0o755)

    monkeypatch.setattr("sys.argv", [str(frago_path), "server"])
    monkeypatch.setattr(
        "shutil.which",
        lambda name: str(frago_path) if name == "frago" else None,
    )

    info = detect_launcher()
    assert info is not None
    assert info.mode == "global"
    assert info.command == [str(frago_path.resolve())]


def test_uv_run_mode_with_standard_venv(
    monkeypatch: pytest.MonkeyPatch, make_venv: Path
) -> None:
    _clean_env(monkeypatch)
    project = make_venv
    venv_bin_frago = project / ".venv" / "bin" / "frago"
    monkeypatch.setenv("VIRTUAL_ENV", str(project / ".venv"))
    monkeypatch.setattr("sys.argv", [str(venv_bin_frago), "server"])
    monkeypatch.setattr(
        "shutil.which", lambda name: str(venv_bin_frago) if name == "frago" else None
    )

    info = detect_launcher()
    assert info is not None
    assert info.mode == "uv_run"
    assert info.command == [
        "uv",
        "run",
        "--project",
        str(project.resolve()),
        "frago",
    ]


def test_uv_run_mode_with_uv_project_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # venv sits in a nonstandard place; UV_PROJECT points to the real project root
    venv = tmp_path / "venvs" / "myproj-abc"
    (venv / "bin").mkdir(parents=True)
    frago_path = venv / "bin" / "frago"
    frago_path.write_text("#!/bin/sh\n")
    frago_path.chmod(0o755)

    project = tmp_path / "projects" / "myproj"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    # venv must also have no ancestor pyproject.toml to force UV_PROJECT path

    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setenv("UV_PROJECT", str(project))
    monkeypatch.setattr("sys.argv", [str(frago_path), "server"])
    monkeypatch.setattr(
        "shutil.which", lambda name: str(frago_path) if name == "frago" else None
    )

    info = detect_launcher()
    assert info is not None
    assert info.mode == "uv_run"
    assert info.command[3] == str(project.resolve())


def test_returns_none_when_nothing_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setattr("sys.argv", ["-c"])
    monkeypatch.setattr("shutil.which", lambda name: None)

    info = detect_launcher()
    assert info is None


def test_python_dash_m_launch_still_finds_frago_via_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """systemd daemon case: argv[0] is runner.py, PATH-resolved frago is
    the venv binary. The venv shebang works fine via absolute path."""
    _clean_env(monkeypatch)
    fake_venv = tmp_path / "myproject" / ".venv" / "bin"
    fake_venv.mkdir(parents=True)
    frago_path = fake_venv / "frago"
    frago_path.write_text("#!/bin/sh\n")
    frago_path.chmod(0o755)

    # argv[0] is the runner module, not frago
    monkeypatch.setattr("sys.argv", [str(tmp_path / "myproject" / "src" / "runner.py")])
    monkeypatch.setattr(
        "shutil.which", lambda name: str(frago_path) if name == "frago" else None
    )

    info = detect_launcher()
    assert info is not None
    assert info.mode == "global"
    assert info.command == [str(frago_path.resolve())]


def test_venv_path_without_virtual_env_uses_absolute_path(
    monkeypatch: pytest.MonkeyPatch, make_venv: Path
) -> None:
    """If shutil.which returns a venv path and VIRTUAL_ENV is unset, we use
    the absolute venv path directly (shebang handles Python resolution)."""
    _clean_env(monkeypatch)
    project = make_venv
    venv_bin_frago = project / ".venv" / "bin" / "frago"
    monkeypatch.setattr("sys.argv", [str(venv_bin_frago), "server"])
    monkeypatch.setattr(
        "shutil.which", lambda name: str(venv_bin_frago) if name == "frago" else None
    )

    info = detect_launcher()
    assert info is not None
    assert info.mode == "global"
    assert info.command == [str(venv_bin_frago.resolve())]


def test_uv_run_argv_outside_venv_skips_branch2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """VIRTUAL_ENV set but argv[0] is not inside it → skip uv_run branch."""
    venv = tmp_path / "myproj" / ".venv"
    (venv / "bin").mkdir(parents=True)
    (tmp_path / "myproj" / "pyproject.toml").write_text("")

    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.delenv("UV_PROJECT", raising=False)
    # argv[0] is a totally unrelated path
    monkeypatch.setattr("sys.argv", ["/usr/bin/python3"])
    monkeypatch.setattr("shutil.which", lambda name: None)

    info = detect_launcher()
    assert info is None
