"""Tests for frago.init.runtime_state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.init import runtime_state
from frago.init.runtime_state import (
    LauncherInfo,
    RuntimeState,
    load_runtime_state,
    save_runtime_state,
    update_launcher,
)


@pytest.fixture(autouse=True)
def _tmp_runtime_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect RUNTIME_STATE_PATH to a temp file for every test."""
    target = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_state, "RUNTIME_STATE_PATH", target)
    return target


def test_load_missing_file_returns_empty_state(_tmp_runtime_path: Path) -> None:
    state = load_runtime_state()
    assert state.schema_version == "1.0"
    assert state.launcher is None


def test_save_and_reload_roundtrip(_tmp_runtime_path: Path) -> None:
    info = LauncherInfo(
        command=["frago"],
        mode="global",
        source={"argv0": "/usr/bin/frago"},
    )
    save_runtime_state(RuntimeState(launcher=info))

    reloaded = load_runtime_state()
    assert reloaded.launcher is not None
    assert reloaded.launcher.command == ["frago"]
    assert reloaded.launcher.mode == "global"
    assert reloaded.launcher.source == {"argv0": "/usr/bin/frago"}


def test_update_launcher_replaces_field(_tmp_runtime_path: Path) -> None:
    info1 = LauncherInfo(command=["frago"], mode="global")
    update_launcher(info1)

    info2 = LauncherInfo(
        command=["uv", "run", "--project", "/p", "frago"], mode="uv_run"
    )
    state = update_launcher(info2)

    assert state.launcher is not None
    assert state.launcher.mode == "uv_run"
    assert state.launcher.command == ["uv", "run", "--project", "/p", "frago"]

    reloaded = load_runtime_state()
    assert reloaded.launcher is not None
    assert reloaded.launcher.mode == "uv_run"


def test_corrupt_json_returns_empty_and_backs_up(_tmp_runtime_path: Path) -> None:
    _tmp_runtime_path.write_text("{not json", encoding="utf-8")

    state = load_runtime_state()
    assert state.launcher is None

    backups = list(_tmp_runtime_path.parent.glob("runtime.json.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


def test_missing_launcher_field_is_ok(_tmp_runtime_path: Path) -> None:
    _tmp_runtime_path.write_text(
        json.dumps({"schema_version": "1.0"}), encoding="utf-8"
    )
    state = load_runtime_state()
    assert state.launcher is None


def test_validation_error_resets_state(_tmp_runtime_path: Path) -> None:
    # launcher.command must be min_length=1; empty list fails validation
    _tmp_runtime_path.write_text(
        json.dumps({"launcher": {"command": [], "mode": "global"}}),
        encoding="utf-8",
    )
    state = load_runtime_state()
    assert state.launcher is None
    backups = list(_tmp_runtime_path.parent.glob("runtime.json.bak.*"))
    assert len(backups) == 1


def test_save_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nested = tmp_path / "nested" / "dir" / "runtime.json"
    monkeypatch.setattr(runtime_state, "RUNTIME_STATE_PATH", nested)
    save_runtime_state(RuntimeState(launcher=LauncherInfo(command=["frago"], mode="global")))
    assert nested.exists()


def test_unknown_fields_are_ignored_future_schema(_tmp_runtime_path: Path) -> None:
    _tmp_runtime_path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "launcher": {"command": ["frago"], "mode": "global"},
                "server_pid": 12345,
                "future_field": "whatever",
            }
        ),
        encoding="utf-8",
    )
    state = load_runtime_state()
    assert state.launcher is not None
    assert state.launcher.command == ["frago"]
