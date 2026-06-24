"""Tests for `frago daemon` CLI (spec 20260624-recipe-daemon-supervisor, Phase 3).

Exercises the activation declaration round-trip (enable writes config.json
daemons.items, validating the recipe's daemon:true flag; disable removes it),
the negative feedback when enabling a non-daemon recipe, and the ls/status
happy paths. Config is redirected to a tmp file; the recipe registry and the
in-process DaemonService instance are faked so no real recipes or subprocesses
are needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from click.testing import CliRunner

import frago.init.config_manager as cm
import frago.recipes.registry as registry_mod
from frago.cli.daemon_commands import daemon_group


@dataclass
class _FakeMeta:
    daemon: bool = True
    restart_policy: str = "on-failure"


@dataclass
class _FakeRecipe:
    metadata: _FakeMeta


class _FakeRegistry:
    def __init__(self, recipes: dict[str, _FakeRecipe]) -> None:
        self._recipes = recipes

    def find(self, name: str) -> _FakeRecipe:
        if name not in self._recipes:
            raise ValueError(f"recipe not found: {name}")
        return self._recipes[name]


@pytest.fixture(autouse=True)
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(cm, "CONFIG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    recipes = {
        "voice_desktop_hud": _FakeRecipe(_FakeMeta(daemon=True, restart_policy="on-failure")),
        "one_shot": _FakeRecipe(_FakeMeta(daemon=False)),
    }
    monkeypatch.setattr(registry_mod, "get_registry", lambda: _FakeRegistry(recipes))
    return recipes


def _read() -> dict:
    return json.loads(cm.CONFIG_PATH.read_text(encoding="utf-8"))


def test_enable_writes_config_and_validates_daemon_flag():
    runner = CliRunner()
    result = runner.invoke(
        daemon_group, ["enable", "voice_desktop_hud", "--restart-policy", "always"]
    )
    assert result.exit_code == 0, result.output

    data = _read()
    section = data["daemons"]
    assert section["enabled"] is True
    items = section["items"]
    assert len(items) == 1
    assert items[0]["recipe"] == "voice_desktop_hud"
    assert items[0]["enabled"] is True
    assert items[0]["restart_policy"] == "always"


def test_enable_non_daemon_recipe_gives_negative_feedback():
    runner = CliRunner()
    result = runner.invoke(daemon_group, ["enable", "one_shot"])
    assert result.exit_code != 0
    assert "daemon: true" in result.output
    # Config must not have been written for a rejected recipe.
    assert not cm.CONFIG_PATH.exists()


def test_enable_unknown_recipe_gives_negative_feedback():
    runner = CliRunner()
    result = runner.invoke(daemon_group, ["enable", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_ls_happy_path():
    runner = CliRunner()
    runner.invoke(daemon_group, ["enable", "voice_desktop_hud"])

    result = runner.invoke(daemon_group, ["ls"])
    assert result.exit_code == 0, result.output
    assert "voice_desktop_hud" in result.output
    assert "enabled" in result.output


def test_ls_empty():
    runner = CliRunner()
    result = runner.invoke(daemon_group, ["ls"])
    assert result.exit_code == 0, result.output
    assert "No daemons declared" in result.output


def test_disable_removes_item():
    runner = CliRunner()
    runner.invoke(daemon_group, ["enable", "voice_desktop_hud"])
    assert len(_read()["daemons"]["items"]) == 1

    result = runner.invoke(daemon_group, ["disable", "voice_desktop_hud"])
    assert result.exit_code == 0, result.output
    assert _read()["daemons"]["items"] == []


def test_disable_unknown_errors():
    runner = CliRunner()
    result = runner.invoke(daemon_group, ["disable", "voice_desktop_hud"])
    assert result.exit_code != 0
    assert "not declared" in result.output


def test_status_happy_path_with_inprocess_instance(monkeypatch):
    from frago.server.services.daemon_service import DaemonService

    class _FakeService:
        def status(self):
            return [
                {
                    "name": "voice_desktop_hud",
                    "recipe": "voice_desktop_hud",
                    "restart_policy": "always",
                    "pid": 4242,
                    "alive": True,
                    "restarts": 1,
                    "running": True,
                }
            ]

    monkeypatch.setattr(DaemonService, "get_instance", classmethod(lambda _cls: _FakeService()))

    runner = CliRunner()
    result = runner.invoke(daemon_group, ["status"])
    assert result.exit_code == 0, result.output
    assert "voice_desktop_hud" in result.output
    assert "4242" in result.output
    assert "yes" in result.output


def test_status_no_instance_server_down(monkeypatch):
    from frago.server.services.daemon_service import DaemonService

    monkeypatch.setattr(DaemonService, "get_instance", classmethod(lambda _cls: None))
    import frago.server.daemon as server_daemon

    monkeypatch.setattr(server_daemon, "is_server_running", lambda: (False, None))

    runner = CliRunner()
    runner.invoke(daemon_group, ["enable", "voice_desktop_hud"])
    result = runner.invoke(daemon_group, ["status"])
    assert result.exit_code == 0, result.output
    assert "Server is not running" in result.output
    assert "voice_desktop_hud" in result.output


def test_restart_requires_declaration():
    runner = CliRunner()
    result = runner.invoke(daemon_group, ["restart", "voice_desktop_hud"])
    assert result.exit_code != 0
    assert "not declared" in result.output

    runner.invoke(daemon_group, ["enable", "voice_desktop_hud"])
    result = runner.invoke(daemon_group, ["restart", "voice_desktop_hud"])
    assert result.exit_code == 0, result.output
    assert "server restart" in result.output
