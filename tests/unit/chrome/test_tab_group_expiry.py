"""Tests for expired tab-group reclamation (spec 20260717-chrome-group-expiry-server-sweep).

Covers the session-free close path in TabGroupManager (Phase 1), the
server-side periodic sweep in TabCleanupService (Phase 2), and the CLI
throttled fallback sweep (Phase 3). All Chrome IO is mocked.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import frago.chrome.cdp.tab_group_manager as tgm_mod
from frago.chrome.cdp.tab_group_manager import (
    GROUP_TIMEOUT_SECONDS,
    TabGroupManager,
)


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect group state/lock files to tmp and silence landing-page push."""
    state_file = tmp_path / "tab_groups.json"
    lock_file = tmp_path / "tab_groups.lock"
    monkeypatch.setattr(tgm_mod, "STATE_FILE", state_file)
    monkeypatch.setattr(tgm_mod, "LOCK_FILE", lock_file)
    monkeypatch.setattr(
        TabGroupManager, "_push_to_landing_page", lambda self, data: None
    )
    return state_file


def _write_state(state_file, groups, port=9222):
    state_file.write_text(json.dumps({
        "schema_version": "1.0",
        "port": port,
        "groups": groups,
    }), encoding="utf-8")


def _group_data(last_activity, tabs):
    now = time.time()
    return {
        "title": "t",
        "agent_session": "t",
        "created_at": now,
        "last_activity": last_activity,
        "max_tabs": 10,
        "current_target_id": None,
        "tabs": {
            tid: {
                "target_id": tid,
                "origin": "http://a",
                "url": "http://a/",
                "title": "",
                "last_activity": last_activity,
                "created_at": now,
            }
            for tid in tabs
        },
    }


# ------------------------------------------------------------------
# Phase 1 — expiry predicate
# ------------------------------------------------------------------


def test_expired_group_names_predicate(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["t1"]),
        "fresh": _group_data(now - 60, ["t2"]),
        "never": _group_data(0.0, ["t3"]),
    })
    tgm = TabGroupManager()
    assert tgm._expired_group_names(now) == ["expired"]


# ------------------------------------------------------------------
# Phase 1 — close_group_http
# ------------------------------------------------------------------


def test_close_group_http_closes_tabs_and_removes_state(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "g1": _group_data(now, ["tab_a", "tab_b"]),
    })
    tgm = TabGroupManager()
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        assert tgm.close_group_http("g1") is True

    closed = {c.args[0] for c in fake_get.call_args_list}
    assert closed == {
        "http://127.0.0.1:9222/json/close/tab_a",
        "http://127.0.0.1:9222/json/close/tab_b",
    }
    assert "g1" not in tgm.list_groups()
    on_disk = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert "g1" not in on_disk["groups"]


def test_close_group_http_missing_group_returns_false(isolated_state):
    tgm = TabGroupManager()
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        assert tgm.close_group_http("nope") is False
    fake_get.assert_not_called()


def test_close_group_http_failure_logs_warning_and_still_removes(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "g1": _group_data(now, ["dead_tab", "live_tab"]),
    })
    tgm = TabGroupManager()
    tgm.logger = MagicMock()

    def flaky_get(url, **kwargs):
        if "dead_tab" in url:
            raise Exception("tab already gone")
        return MagicMock()

    with patch.object(tgm_mod, "cdp_get", side_effect=flaky_get) as fake_get:
        assert tgm.close_group_http("g1") is True

    # Both tabs were attempted despite the first failure
    assert fake_get.call_count == 2
    tgm.logger.warning.assert_called_once()
    assert "dead_tab" in tgm.logger.warning.call_args.args[0]
    assert "g1" not in tgm.list_groups()


def test_close_group_session_path_behavior_aligned(isolated_state):
    """close_group(session) keeps its original semantics via the shared helper."""
    now = time.time()
    _write_state(isolated_state, {
        "g1": _group_data(now, ["tab_a"]),
    })
    tgm = TabGroupManager()
    session = MagicMock()
    assert tgm.close_group("g1", session) is True
    session.target.close_target.assert_called_once_with("tab_a")
    assert "g1" not in tgm.list_groups()
    assert tgm.close_group("g1", session) is False


# ------------------------------------------------------------------
# Phase 1 — cleanup_expired_groups_http
# ------------------------------------------------------------------


def test_cleanup_expired_groups_http_reclaims_only_expired(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
        "fresh": _group_data(now - 60, ["new_tab"]),
        "never": _group_data(0.0, ["legacy_tab"]),
    })
    tgm = TabGroupManager()
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        assert tgm.cleanup_expired_groups_http() == 1

    closed = {c.args[0] for c in fake_get.call_args_list}
    assert closed == {"http://127.0.0.1:9222/json/close/old_tab"}
    groups = tgm.list_groups()
    assert set(groups) == {"fresh", "never"}


# ------------------------------------------------------------------
# Phase 2 — server periodic sweep integration (real TabGroupManager)
# ------------------------------------------------------------------


def test_tab_cleanup_service_reclaims_expired_group(isolated_state):
    from frago.server.services.tab_cleanup_service import TabCleanupService

    now = time.time()
    _write_state(isolated_state, {
        "expiry-test": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
    })

    def fake_requests_get(url, timeout=None):
        r = MagicMock()
        if url.endswith("/json/list"):
            r.json.return_value = []
        return r

    fake_tm = MagicMock()
    fake_tm.get_tracked_tabs.return_value = []
    with patch.object(tgm_mod, "cdp_get") as fake_cdp_get, patch(
        "frago.server.services.tab_cleanup_service.requests"
    ) as req, patch(
        "frago.chrome.cdp.tab_manager.TabManager", return_value=fake_tm
    ):
        fake_cdp_get.return_value.json.return_value = []
        req.get.side_effect = fake_requests_get
        TabCleanupService()._do_cleanup()

    close_urls = [
        c.args[0] for c in fake_cdp_get.call_args_list
        if "/json/close/" in c.args[0]
    ]
    assert close_urls == ["http://127.0.0.1:9222/json/close/old_tab"]

    on_disk = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert "expiry-test" not in on_disk["groups"]


def test_cleanup_expired_groups_http_noop_when_nothing_expired(isolated_state):
    now = time.time()
    _write_state(isolated_state, {"fresh": _group_data(now, ["t1"])})
    tgm = TabGroupManager()
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        assert tgm.cleanup_expired_groups_http() == 0
    fake_get.assert_not_called()


# ------------------------------------------------------------------
# Phase 3 — CLI throttled fallback sweep
# ------------------------------------------------------------------


def _sweep(isolated_state):
    from frago.cli import commands as cmd_mod

    marker = isolated_state.parent / "last_expiry_sweep"
    return cmd_mod, marker


def test_maybe_sweep_runs_when_no_marker(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
    })
    cmd_mod, marker = _sweep(isolated_state)
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        cmd_mod._maybe_sweep_expired_groups("127.0.0.1", 9222)

    assert marker.exists()
    close_urls = [c.args[0] for c in fake_get.call_args_list if "/json/close/" in c.args[0]]
    assert close_urls == ["http://127.0.0.1:9222/json/close/old_tab"]


def test_maybe_sweep_throttled_within_window(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
    })
    cmd_mod, marker = _sweep(isolated_state)
    marker.touch()  # fresh marker → within throttle window
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        cmd_mod._maybe_sweep_expired_groups("127.0.0.1", 9222)
    fake_get.assert_not_called()


def test_maybe_sweep_runs_when_marker_stale(isolated_state):
    import os

    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
    })
    cmd_mod, marker = _sweep(isolated_state)
    marker.touch()
    stale = now - cmd_mod.EXPIRY_SWEEP_THROTTLE_SECONDS - 5
    os.utime(marker, (stale, stale))
    with patch.object(tgm_mod, "cdp_get") as fake_get:
        cmd_mod._maybe_sweep_expired_groups("127.0.0.1", 9222)
    assert any("/json/close/old_tab" in c.args[0] for c in fake_get.call_args_list)
    assert marker.stat().st_mtime > stale


def test_maybe_sweep_marker_unwritable_still_sweeps_and_warns(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
    })
    cmd_mod, marker = _sweep(isolated_state)
    fake_logger = MagicMock()
    with patch.object(tgm_mod, "cdp_get") as fake_get, patch.object(
        cmd_mod, "get_logger", return_value=fake_logger
    ), patch("pathlib.Path.touch", side_effect=OSError("disk full")):
        cmd_mod._maybe_sweep_expired_groups("127.0.0.1", 9222)

    fake_logger.warning.assert_called_once()
    assert any("/json/close/old_tab" in c.args[0] for c in fake_get.call_args_list)


def test_maybe_sweep_failure_logs_warning(isolated_state):
    now = time.time()
    _write_state(isolated_state, {
        "expired": _group_data(now - GROUP_TIMEOUT_SECONDS - 60, ["old_tab"]),
    })
    cmd_mod, _ = _sweep(isolated_state)
    fake_logger = MagicMock()
    with patch.object(
        tgm_mod.TabGroupManager,
        "cleanup_expired_groups_http",
        side_effect=Exception("boom"),
    ), patch.object(cmd_mod, "get_logger", return_value=fake_logger):
        cmd_mod._maybe_sweep_expired_groups("127.0.0.1", 9222)
    fake_logger.warning.assert_called_once()


def test_register_expiry_sweep_registers_atexit_once(monkeypatch):
    from frago.cli import commands as cmd_mod

    monkeypatch.setattr(cmd_mod, "_expiry_sweep_registered", False)
    with patch.object(cmd_mod, "atexit") as fake_atexit:
        cmd_mod._register_expiry_sweep("127.0.0.1", 9222)
        cmd_mod._register_expiry_sweep("127.0.0.1", 9222)

    fake_atexit.register.assert_called_once_with(
        cmd_mod._maybe_sweep_expired_groups, "127.0.0.1", 9222
    )
