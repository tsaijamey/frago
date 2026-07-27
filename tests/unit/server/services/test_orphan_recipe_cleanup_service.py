"""Unit tests for OrphanRecipeCleanupService.

The scan is deliberately paranoid — the reaping is silent, so a false positive
would look like a random crash to the user. Most of these tests therefore pin
the *negative* side: each safety rule on its own must be enough to spare a
process.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.orphan_recipe_cleanup_service import (
    MAX_KILLS_PER_CYCLE,
    MIN_ORPHAN_AGE_SECONDS,
    OrphanRecipeCleanupService,
    ProcInfo,
    collect_owned_recipes,
    find_orphan_candidates,
    load_ledger,
    save_ledger,
    seconds_until_next_hour,
)

SERVER_PID = 500
SERVER_START = 10_000.0
OLD = SERVER_START - MIN_ORPHAN_AGE_SECONDS - 60  # safely older than the server

HUD_SCRIPT = Path("/recipes/voice_desktop_hud/recipe.py")
STREAM_SCRIPT = Path("/recipes/voice_duplex_stream/recipe.py")
OWNED = {"voice_desktop_hud": HUD_SCRIPT, "voice_duplex_stream": STREAM_SCRIPT}


def _proc(
    pid=900,
    ppid=1,
    create_time=OLD,
    terminal=None,
    cmdline=("uv", "run", "--quiet", str(HUD_SCRIPT), "{}"),
):
    return ProcInfo(
        pid=pid,
        ppid=ppid,
        create_time=create_time,
        terminal=terminal,
        cmdline=cmdline,
    )


def _scan(procs, owned=None, protected=frozenset()):
    return find_orphan_candidates(
        procs,
        OWNED if owned is None else owned,
        server_pid=SERVER_PID,
        server_create_time=SERVER_START,
        protected_pids=protected,
    )


# ------------------------------------------------------------------
# The one positive case
# ------------------------------------------------------------------


def test_reparented_old_untethered_owned_recipe_is_a_candidate():
    found = _scan([_proc()])
    assert [(c.recipe, c.proc.pid) for c in found] == [("voice_desktop_hud", 900)]


def test_grandchild_python_process_also_matches_by_script_path():
    found = _scan([_proc(cmdline=("/uv/env/bin/python3", str(STREAM_SCRIPT), "{}"))])
    assert [c.recipe for c in found] == ["voice_duplex_stream"]


# ------------------------------------------------------------------
# Each safety rule, alone, spares the process
# ------------------------------------------------------------------


def test_recipe_not_owned_by_server_is_never_touched():
    other = ("uv", "run", "/recipes/meeting_copilot/recipe.py", '{"_daemon": true}')
    assert _scan([_proc(cmdline=other)]) == []


def test_live_parent_spares_process():
    """A supervised child has the server (or its uv shell) as parent."""
    assert _scan([_proc(ppid=SERVER_PID)]) == []


def test_controlling_terminal_spares_process():
    """`frago recipe run` in a terminal the user is watching keeps its tty."""
    assert _scan([_proc(terminal="/dev/ttys003")]) == []


def test_process_younger_than_server_spares_process():
    assert _scan([_proc(create_time=SERVER_START + 5)]) == []


def test_process_inside_age_margin_spares_process():
    just_inside = SERVER_START - MIN_ORPHAN_AGE_SECONDS + 1
    assert _scan([_proc(create_time=just_inside)]) == []


def test_protected_pid_spares_process():
    assert _scan([_proc(pid=900)], protected=frozenset({900})) == []


def test_server_itself_and_init_are_never_candidates():
    procs = [
        _proc(pid=SERVER_PID, ppid=1),
        _proc(pid=1, ppid=0),
    ]
    assert _scan(procs) == []


def test_no_owned_recipes_means_no_candidates():
    assert _scan([_proc()], owned={}) == []


def test_script_path_must_be_a_whole_argument():
    """A path that merely contains the script path as a substring is not a hit."""
    lookalike = ("uv", "run", f"{HUD_SCRIPT}.bak", "{}")
    assert _scan([_proc(cmdline=lookalike)]) == []


# ------------------------------------------------------------------
# collect_owned_recipes
# ------------------------------------------------------------------


def _runner_with(paths: dict[str, str]):
    runner = MagicMock()

    def find(name):
        if name not in paths:
            raise ValueError(f"unknown recipe {name}")
        return MagicMock(script_path=paths[name])

    runner.registry.find.side_effect = find
    return runner


def test_collect_owned_recipes_takes_daemons_and_stream_channels_only():
    config = {
        "daemons": {"enabled": True, "items": [{"recipe": "hud", "enabled": True}]},
        "task_ingestion": {
            "channels": [
                {"name": "voice", "poll_recipe": "stream_r", "mode": "stream"},
                {"name": "email", "poll_recipe": "poll_r", "mode": "poll"},
            ]
        },
    }
    runner = _runner_with({
        "hud": "/r/hud.py", "stream_r": "/r/stream.py", "poll_r": "/r/poll.py",
    })
    owned = collect_owned_recipes(config, runner)
    assert set(owned) == {"hud", "stream_r"}


def test_collect_owned_recipes_keeps_disabled_daemon_items():
    """A daemon switched off in config should not still be running."""
    config = {"daemons": {"items": [{"recipe": "hud", "enabled": False}]}}
    owned = collect_owned_recipes(config, _runner_with({"hud": "/r/hud.py"}))
    assert set(owned) == {"hud"}


def test_collect_owned_recipes_skips_unresolvable_recipe():
    config = {"daemons": {"items": [{"recipe": "gone"}]}}
    assert collect_owned_recipes(config, _runner_with({})) == {}


def test_collect_owned_recipes_tolerates_empty_config():
    assert collect_owned_recipes({}, _runner_with({})) == {}


# ------------------------------------------------------------------
# Ledger: two-strike confirmation
# ------------------------------------------------------------------


def test_ledger_roundtrip(tmp_path):
    path = tmp_path / "ledger.json"
    save_ledger({"900:9000": {"recipe": "hud", "pid": 900}}, path)
    assert load_ledger(path) == {"900:9000": {"recipe": "hud", "pid": 900}}


def test_load_ledger_tolerates_missing_and_corrupt_file(tmp_path):
    missing = tmp_path / "nope.json"
    assert load_ledger(missing) == {}
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_ledger(corrupt) == {}
    wrong_shape = tmp_path / "shape.json"
    wrong_shape.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_ledger(wrong_shape) == {}


def test_proc_key_binds_pid_to_start_time():
    """Pid reuse cannot inherit a previous candidate's confirmation."""
    assert _proc(pid=900, create_time=1000.0).key != _proc(pid=900, create_time=2000.0).key


# ------------------------------------------------------------------
# run_once: confirmation, dry run, sanity ceiling
# ------------------------------------------------------------------


def _patch_cycle(svc, candidates, *, procs=None):
    """Patch run_once's collaborators: owned set, psutil server, scan result."""
    server = MagicMock()
    server.pid = SERVER_PID
    server.create_time.return_value = SERVER_START
    server.children.return_value = []
    psutil = MagicMock()
    psutil.Process.return_value = server

    return (
        patch.object(svc, "_owned_scripts", return_value=OWNED),
        patch.dict("sys.modules", {"psutil": psutil}),
        patch(
            "frago.server.services.orphan_recipe_cleanup_service.snapshot_processes",
            return_value=procs or [],
        ),
        patch(
            "frago.server.services.orphan_recipe_cleanup_service.find_orphan_candidates",
            return_value=candidates,
        ),
        patch.object(svc, "_protected_pids", return_value=frozenset()),
    )


def _run_cycle(svc, candidates, **kwargs):
    patches = _patch_cycle(svc, candidates)
    for p in patches:
        p.start()
    try:
        return svc.run_once(**kwargs)
    finally:
        for p in reversed(patches):
            p.stop()


def _candidate(pid=900, recipe="voice_desktop_hud", create_time=OLD):
    from frago.server.services.orphan_recipe_cleanup_service import OrphanCandidate

    return OrphanCandidate(proc=_proc(pid=pid, create_time=create_time), recipe=recipe)


def test_first_sighting_records_but_does_not_kill(tmp_path):
    svc = OrphanRecipeCleanupService(ledger_path=tmp_path / "l.json")
    with patch.object(svc, "_reap") as reap:
        reaped = _run_cycle(svc, [_candidate()])
    reap.assert_not_called()
    assert reaped == []
    assert list(load_ledger(tmp_path / "l.json")) == [_candidate().key]


def test_second_sighting_of_same_identity_kills(tmp_path):
    ledger = tmp_path / "l.json"
    svc = OrphanRecipeCleanupService(ledger_path=ledger)
    c = _candidate()
    save_ledger({c.key: {"recipe": c.recipe, "pid": c.proc.pid}}, ledger)

    with patch.object(svc, "_reap", return_value=True) as reap:
        reaped = _run_cycle(svc, [c])
    reap.assert_called_once_with(c)
    assert reaped == [c]
    # Reaped entries leave the ledger.
    assert load_ledger(ledger) == {}
    assert svc.status()["reaped_total"] == 1


def test_recycled_pid_is_not_confirmed_by_old_ledger_entry(tmp_path):
    ledger = tmp_path / "l.json"
    svc = OrphanRecipeCleanupService(ledger_path=ledger)
    old = _candidate(pid=900, create_time=OLD)
    save_ledger({old.key: {"recipe": old.recipe, "pid": 900}}, ledger)

    reused = _candidate(pid=900, create_time=OLD - 999)  # same pid, other process
    with patch.object(svc, "_reap") as reap:
        _run_cycle(svc, [reused])
    reap.assert_not_called()


def test_empty_scan_clears_the_ledger(tmp_path):
    ledger = tmp_path / "l.json"
    svc = OrphanRecipeCleanupService(ledger_path=ledger)
    save_ledger({"900:1": {"recipe": "hud", "pid": 900}}, ledger)
    with patch.object(svc, "_reap") as reap:
        assert _run_cycle(svc, []) == []
    reap.assert_not_called()
    assert load_ledger(ledger) == {}


def test_dry_run_kills_nothing_and_leaves_ledger_untouched(tmp_path):
    ledger = tmp_path / "l.json"
    svc = OrphanRecipeCleanupService(ledger_path=ledger)
    c = _candidate()
    save_ledger({c.key: {"recipe": c.recipe, "pid": c.proc.pid}}, ledger)

    with patch.object(svc, "_reap") as reap:
        confirmed = _run_cycle(svc, [c], dry_run=True)
    reap.assert_not_called()
    assert confirmed == [c]
    assert list(load_ledger(ledger)) == [c.key]


def test_too_many_candidates_aborts_the_cycle(tmp_path):
    ledger = tmp_path / "l.json"
    svc = OrphanRecipeCleanupService(ledger_path=ledger)
    many = [_candidate(pid=1000 + i) for i in range(MAX_KILLS_PER_CYCLE + 1)]
    save_ledger({c.key: {"recipe": c.recipe, "pid": c.proc.pid} for c in many}, ledger)

    with patch.object(svc, "_reap") as reap:
        assert _run_cycle(svc, many) == []
    reap.assert_not_called()


def test_no_owned_recipes_short_circuits_before_scanning(tmp_path):
    svc = OrphanRecipeCleanupService(ledger_path=tmp_path / "l.json")
    with patch.object(svc, "_owned_scripts", return_value={}), \
         patch.object(svc, "_reap") as reap:
        assert svc.run_once() == []
    reap.assert_not_called()


# ------------------------------------------------------------------
# _reap: identity re-check at signal time
# ------------------------------------------------------------------


def test_reap_aborts_when_pid_was_recycled_between_scan_and_signal():
    svc = OrphanRecipeCleanupService()
    c = _candidate(create_time=OLD)

    proc = MagicMock()
    proc.create_time.return_value = OLD + 5_000  # a different process now
    psutil = MagicMock()
    psutil.Process.return_value = proc
    psutil.NoSuchProcess = RuntimeError

    with patch.dict("sys.modules", {"psutil": psutil}):
        assert svc._reap(c) is False
    proc.children.assert_not_called()


def test_reap_signals_group_then_kills_survivors():
    svc = OrphanRecipeCleanupService()
    c = _candidate(pid=900, create_time=OLD)

    proc = MagicMock()
    proc.create_time.return_value = OLD
    child = MagicMock()
    proc.children.return_value = [child]
    psutil = MagicMock()
    psutil.Process.return_value = proc
    psutil.NoSuchProcess = RuntimeError
    # First wait: child survives SIGTERM; second wait: nothing left.
    psutil.wait_procs.side_effect = [([], [child]), ([child], [])]

    signals = []
    with patch.dict("sys.modules", {"psutil": psutil}), \
         patch(
             "frago.server.services.orphan_recipe_cleanup_service._signal_group_or_procs",
             side_effect=lambda pid, _procs, sig: signals.append((pid, sig)),
         ):
        assert svc._reap(c) is True

    import signal as _signal

    assert signals == [(900, _signal.SIGTERM), (900, _signal.SIGKILL)]


# ------------------------------------------------------------------
# Scheduling + lifecycle
# ------------------------------------------------------------------


def test_seconds_until_next_hour_lands_on_the_hour():
    assert seconds_until_next_hour(3600.0) == 3600.0
    assert seconds_until_next_hour(3600.0 + 1200.0) == 2400.0
    assert 0 < seconds_until_next_hour() <= 3600.0


@pytest.mark.asyncio
async def test_start_stop_lifecycle():
    svc = OrphanRecipeCleanupService()
    with patch.object(svc, "run_once"):
        await svc.start()
        assert svc.status()["running"] is True
        first = svc._task
        await svc.start()  # idempotent
        assert svc._task is first
        await svc.stop()
    assert svc._task is None
    assert svc.status()["running"] is False


@pytest.mark.asyncio
async def test_stop_without_start_is_noop():
    svc = OrphanRecipeCleanupService()
    await svc.stop()
    assert svc._task is None


@pytest.mark.asyncio
async def test_loop_swallows_cycle_exception_and_keeps_running():
    svc = OrphanRecipeCleanupService()
    calls = []

    def boom():
        calls.append(1)
        if len(calls) >= 2:
            svc._stop_event.set()
        raise RuntimeError("scan blew up")

    with patch.object(svc, "run_once", side_effect=boom), \
         patch(
             "frago.server.services.orphan_recipe_cleanup_service.seconds_until_next_hour",
             return_value=0.01,
         ):
        await asyncio.wait_for(svc._loop(), timeout=5)

    assert len(calls) >= 2
