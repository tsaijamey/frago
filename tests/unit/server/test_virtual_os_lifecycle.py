"""Keeping the virtual desktop up without overriding the person at the keyboard.

The whole point of this service is one distinction: a desktop that is gone
because it crashed should come back, and a desktop that is gone because someone
shut it down should stay gone. Getting it wrong in either direction is bad in a
way that hides itself — either the stop command lies, or nothing supervises
anything and the failure only surfaces on the next command.
"""

import asyncio

import pytest

from frago.server.services import virtual_os_lifecycle as vol


@pytest.fixture
def service(monkeypatch):
    svc = vol.VirtualOsLifecycleService(scan_interval_s=0.01)
    starts = []
    monkeypatch.setattr(svc, "_start_desktop", lambda: starts.append(1), raising=False)
    monkeypatch.setattr(
        vol.VirtualOsLifecycleService, "_start_desktop",
        staticmethod(lambda: starts.append(1)),
    )
    return svc, starts


def _state(monkeypatch, wanted, alive):
    monkeypatch.setattr(
        vol.VirtualOsLifecycleService, "_read_state",
        staticmethod(lambda: (wanted, alive)),
    )


class TestWhenToStart:
    @pytest.mark.asyncio
    async def test_wanted_and_missing_gets_started(self, service, monkeypatch):
        svc, starts = service
        _state(monkeypatch, wanted=True, alive=False)
        await svc._scan_once()
        assert starts == [1]

    @pytest.mark.asyncio
    async def test_shut_down_on_purpose_stays_down(self, service, monkeypatch):
        """The stop command's promise: it stays stopped until someone says otherwise."""
        svc, starts = service
        _state(monkeypatch, wanted=False, alive=False)
        await svc._scan_once()
        assert starts == []

    @pytest.mark.asyncio
    async def test_already_running_is_left_alone(self, service, monkeypatch):
        svc, starts = service
        _state(monkeypatch, wanted=True, alive=True)
        await svc._scan_once()
        assert starts == []

    @pytest.mark.asyncio
    async def test_never_created_is_not_conjured_into_existence(self, service, monkeypatch):
        """A machine that never had a desktop should not suddenly grow one."""
        svc, starts = service
        monkeypatch.setattr(
            vol.VirtualOsLifecycleService, "_read_state", staticmethod(lambda: None)
        )
        await svc._scan_once()
        assert starts == []


class TestNotStartingSeveralAtOnce:
    @pytest.mark.asyncio
    async def test_second_scan_during_startup_does_not_start_another(
        self, service, monkeypatch
    ):
        """Starting takes seconds; scans keep coming. Without the cooldown each
        scan would launch another desktop while the first is still coming up."""
        svc, starts = service
        _state(monkeypatch, wanted=True, alive=False)
        await svc._scan_once()
        await svc._scan_once()
        await svc._scan_once()
        assert starts == [1]

    @pytest.mark.asyncio
    async def test_cooldown_expiry_allows_another_attempt(self, service, monkeypatch):
        svc, starts = service
        _state(monkeypatch, wanted=True, alive=False)
        await svc._scan_once()
        svc._last_start_at -= vol._START_COOLDOWN_S + 1
        await svc._scan_once()
        assert starts == [1, 1]


class TestLoopSurvival:
    @pytest.mark.asyncio
    async def test_one_bad_scan_does_not_kill_the_service(self, service, monkeypatch):
        """A registry that is briefly unreadable must not silently end supervision."""
        svc, starts = service
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("registry unreadable")
            return (True, False)

        monkeypatch.setattr(
            vol.VirtualOsLifecycleService, "_read_state", staticmethod(flaky)
        )
        task = asyncio.create_task(svc._loop())
        await asyncio.sleep(0.08)
        task.cancel()
        assert calls["n"] > 1
        assert starts == [1]

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, service, monkeypatch):
        svc, _ = service
        # 指向一个确实存在的文件即可——start 只用它判断配方装没装。
        monkeypatch.setattr(vol, "_REGISTRY", vol.Path(__file__))
        await svc.start()
        first = svc._task
        await svc.start()
        assert svc._task is first
        await svc.stop()

    @pytest.mark.asyncio
    async def test_uninstalled_recipe_means_no_supervision(self, service, monkeypatch):
        """No stage recipe on this machine — the service must not spin a loop."""
        svc, _ = service
        monkeypatch.setattr(vol, "_REGISTRY", vol.Path("/nonexistent/registry.py"))
        await svc.start()
        assert svc._task is None
