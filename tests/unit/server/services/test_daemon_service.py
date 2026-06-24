"""Tests for DaemonService — config-driven recipe daemon supervision.

These exercise spec resolution (metadata default vs config override, skip
rules, dedup) and the start/stop/status lifecycle, with a fake runner whose
registry returns controllable recipe metadata, and a stubbed RecipeSupervisor
so no real subprocess is spawned.
"""

import asyncio
from dataclasses import dataclass

import pytest

from frago.server.services.daemon_service import DaemonService


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


class _FakeRunner:
    def __init__(self, recipes: dict[str, _FakeRecipe]) -> None:
        self.registry = _FakeRegistry(recipes)


def _runner(**recipes: _FakeRecipe) -> _FakeRunner:
    return _FakeRunner(recipes)


def test_merges_metadata_default_and_config_override():
    runner = _runner(
        a=_FakeRecipe(_FakeMeta(daemon=True, restart_policy="on-failure")),
        b=_FakeRecipe(_FakeMeta(daemon=True, restart_policy="never")),
    )
    items = [
        {"recipe": "a", "restart_policy": "always"},  # override
        {"recipe": "b"},  # falls back to metadata default (never)
    ]
    specs = DaemonService._resolve_specs(items, runner)
    by_name = {s.recipe: s for s in specs}
    assert by_name["a"].restart_policy == "always"
    assert by_name["b"].restart_policy == "never"


def test_skips_disabled_unknown_and_non_daemon():
    runner = _runner(
        good=_FakeRecipe(_FakeMeta(daemon=True)),
        notdaemon=_FakeRecipe(_FakeMeta(daemon=False)),
    )
    items = [
        {"recipe": "good"},
        {"recipe": "good2", "enabled": False},
        {"recipe": "missing"},
        {"recipe": "notdaemon"},
    ]
    specs = DaemonService._resolve_specs(items, runner)
    assert [s.recipe for s in specs] == ["good"]


def test_dedups_by_recipe_name():
    runner = _runner(a=_FakeRecipe(_FakeMeta(daemon=True)))
    items = [{"recipe": "a"}, {"recipe": "a", "restart_policy": "always"}]
    specs = DaemonService._resolve_specs(items, runner)
    assert len(specs) == 1
    assert specs[0].restart_policy == "on-failure"  # first declaration wins


def test_invalid_policy_falls_back_to_on_failure():
    runner = _runner(a=_FakeRecipe(_FakeMeta(daemon=True)))
    specs = DaemonService._resolve_specs([{"recipe": "a", "restart_policy": "bogus"}], runner)
    assert specs[0].restart_policy == "on-failure"


def test_from_config_disabled_returns_none():
    assert DaemonService.from_config({}) is None
    assert DaemonService.from_config({"daemons": {"enabled": False}}) is None


@pytest.mark.asyncio
async def test_start_stop_lifecycle(monkeypatch):
    """start() launches one supervisor task per daemon; stop() collects them."""
    from frago.server.services import daemon_service as ds_mod
    from frago.server.services.recipe_supervisor import SupervisedRecipe

    run_calls: list[str] = []

    class _FakeSupervisor:
        def __init__(self, spec, sink=None, *, runner=None, stop_event=None):  # noqa: ARG002
            self._spec = spec
            self._stop_event = stop_event
            self._proc = None
            self._restarts = 0

        async def run(self):
            run_calls.append(self._spec.label)
            await self._stop_event.wait()

    monkeypatch.setattr(ds_mod, "RecipeSupervisor", _FakeSupervisor)

    specs = [
        SupervisedRecipe(recipe="a", startup_delay=0),
        SupervisedRecipe(recipe="b", startup_delay=0),
    ]
    service = DaemonService.__new__(DaemonService)
    service._daemons = specs
    service._tasks = {}
    service._supervisors = {}
    service._stop_event = asyncio.Event()
    service._runner = object()

    await service.start()
    await asyncio.sleep(0.01)
    assert sorted(run_calls) == ["a", "b"]

    status = service.status()
    assert {s["name"] for s in status} == {"a", "b"}
    assert all(s["running"] for s in status)

    await service.stop()
    assert service._tasks == {}
