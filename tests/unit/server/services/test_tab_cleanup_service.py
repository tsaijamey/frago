"""Unit tests for TabCleanupService.

Covers task lifecycle (start/stop) and the _do_cleanup reconcile/close logic.
All Chrome/CDP/real IO is mocked. Service is instantiated directly, not via
the singleton.
"""
import asyncio
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.tab_cleanup_service import (
    TabCleanupService,
)


# ------------------------------------------------------------------
# Lifecycle: start / stop
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_task():
    svc = TabCleanupService()
    with patch.object(svc, "_cleanup_loop", new=_never_ending_loop):
        await svc.start()
        try:
            assert svc._task is not None
            assert not svc._task.done()
        finally:
            await svc.stop()


@pytest.mark.asyncio
async def test_repeat_start_does_not_recreate_task():
    svc = TabCleanupService()
    with patch.object(svc, "_cleanup_loop", new=_never_ending_loop):
        await svc.start()
        first_task = svc._task
        await svc.start()
        try:
            assert svc._task is first_task
        finally:
            await svc.stop()


@pytest.mark.asyncio
async def test_start_after_done_task_creates_new_task():
    svc = TabCleanupService()
    # A task that completes immediately.
    with patch.object(svc, "_cleanup_loop", new=_immediate_loop):
        await svc.start()
        first_task = svc._task
        await asyncio.sleep(0)  # let it finish
        assert first_task.done()
    with patch.object(svc, "_cleanup_loop", new=_never_ending_loop):
        await svc.start()
        try:
            assert svc._task is not first_task
            assert not svc._task.done()
        finally:
            await svc.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task():
    svc = TabCleanupService()
    with patch.object(svc, "_cleanup_loop", new=_never_ending_loop):
        await svc.start()
        task = svc._task
        await svc.stop()
    assert svc._task is None
    assert task.cancelled()
    assert svc._stop_event.is_set()


@pytest.mark.asyncio
async def test_stop_without_start_is_noop():
    svc = TabCleanupService()
    # Should not raise.
    await svc.stop()
    assert svc._task is None


async def _never_ending_loop():
    ev = asyncio.Event()
    await ev.wait()


async def _immediate_loop():
    return None


# ------------------------------------------------------------------
# _do_cleanup
# ------------------------------------------------------------------


def _install_fake_cdp_modules(tgm, tm):
    """Inject fake frago.chrome.cdp.* modules so the inner imports resolve."""
    tab_group_mod = types.ModuleType("frago.chrome.cdp.tab_group_manager")
    tab_group_mod.TabGroupManager = MagicMock(return_value=tgm)
    tab_mod = types.ModuleType("frago.chrome.cdp.tab_manager")
    tab_mod.TabManager = MagicMock(return_value=tm)
    return patch.dict(
        sys.modules,
        {
            "frago.chrome.cdp.tab_group_manager": tab_group_mod,
            "frago.chrome.cdp.tab_manager": tab_mod,
        },
    )


def _make_group(tab_ids):
    g = MagicMock()
    g.tabs = {tid: MagicMock() for tid in tab_ids}
    return g


def _make_tm(tracked_ids):
    tm = MagicMock()
    tm.get_tracked_tabs.return_value = [
        types.SimpleNamespace(tab_id=tid) for tid in tracked_ids
    ]
    return tm


def _resp(json_data=None, status_ok=True):
    r = MagicMock()
    r.json.return_value = json_data
    if not status_ok:
        r.raise_for_status.side_effect = Exception("bad status")
    return r


def test_do_cleanup_skips_when_chrome_down():
    svc = TabCleanupService()
    tgm = MagicMock()
    tm = MagicMock()
    with _install_fake_cdp_modules(tgm, tm):
        with patch(
            "frago.server.services.tab_cleanup_service.requests"
        ) as req:
            req.get.side_effect = Exception("connection refused")
            svc._do_cleanup()
    # Should bail before touching managers.
    tgm.reconcile.assert_not_called()


def test_do_cleanup_closes_only_orphans():
    svc = TabCleanupService()
    tgm = MagicMock()
    tgm.list_groups.return_value = {"g1": _make_group(["grouped1"])}
    tm = _make_tm(["managed1"])

    live_tabs = [
        {"type": "page", "id": "grouped1", "url": "http://a", "title": "A"},
        {"type": "page", "id": "managed1", "url": "http://b", "title": "B"},
        {"type": "page", "id": "landing",
         "url": "http://x/chrome/dashboard", "title": "dash"},
        {"type": "page", "id": "frago_title",
         "url": "http://y", "title": "frago"},
        {"type": "page", "id": "data_tab",
         "url": "data:text/html,foo", "title": "d"},
        {"type": "background_page", "id": "bg", "url": "http://z", "title": "z"},
        {"type": "page", "id": "orphan1", "url": "http://o1", "title": "O1"},
        {"type": "page", "id": "orphan2", "url": "http://o2", "title": "O2"},
    ]

    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if url.endswith("/json/version"):
            return _resp()
        if url.endswith("/json/list"):
            return _resp(json_data=live_tabs)
        # close calls
        return _resp()

    with _install_fake_cdp_modules(tgm, tm):
        with patch(
            "frago.server.services.tab_cleanup_service.requests"
        ) as req:
            req.get.side_effect = fake_get
            svc._do_cleanup()

    tgm.reconcile.assert_called_once()
    tm.reconcile.assert_called_once()

    close_calls = [c for c in calls if "/json/close/" in c]
    closed_ids = {c.rsplit("/", 1)[1] for c in close_calls}
    assert closed_ids == {"orphan1", "orphan2"}


def test_do_cleanup_returns_when_list_fails():
    svc = TabCleanupService()
    tgm = MagicMock()
    tgm.list_groups.return_value = {}
    tm = _make_tm([])

    def fake_get(url, timeout=None):
        if url.endswith("/json/version"):
            return _resp()
        if url.endswith("/json/list"):
            return _resp(json_data=None, status_ok=False)
        raise AssertionError("should not reach close on list failure")

    with _install_fake_cdp_modules(tgm, tm):
        with patch(
            "frago.server.services.tab_cleanup_service.requests"
        ) as req:
            req.get.side_effect = fake_get
            svc._do_cleanup()  # must not raise


def test_do_cleanup_swallows_close_errors():
    svc = TabCleanupService()
    tgm = MagicMock()
    tgm.list_groups.return_value = {}
    tm = _make_tm([])
    live_tabs = [
        {"type": "page", "id": "orphan1", "url": "http://o1", "title": "O1"},
    ]

    def fake_get(url, timeout=None):
        if url.endswith("/json/version"):
            return _resp()
        if url.endswith("/json/list"):
            return _resp(json_data=live_tabs)
        raise Exception("close failed")

    with _install_fake_cdp_modules(tgm, tm):
        with patch(
            "frago.server.services.tab_cleanup_service.requests"
        ) as req:
            req.get.side_effect = fake_get
            svc._do_cleanup()  # must not raise


# ------------------------------------------------------------------
# _cleanup_loop: exception in cleanup is swallowed; stop_event ends loop
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_loop_swallows_cleanup_exception_and_exits_on_stop():
    svc = TabCleanupService()

    def boom():
        raise RuntimeError("cleanup blew up")

    with patch.object(svc, "_do_cleanup", side_effect=boom):
        svc._stop_event.set()  # exit right after first cycle
        # Should run one cycle, swallow the exception, then break.
        await asyncio.wait_for(svc._cleanup_loop(), timeout=2)
