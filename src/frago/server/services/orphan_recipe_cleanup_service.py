"""Hourly reaper for orphaned recipe daemon processes.

Why this exists
---------------
``RecipeSupervisor`` spawns each server-owned recipe daemon into its own
session (``start_new_session=True``) and tears down the whole process group on
exit, so the normal path leaks nothing. But any layer can fail outside that
path: the server gets ``SIGKILL``\\ ed, the machine loses power mid-restart, or
a recipe was once launched by hand from its own directory. What survives is a
recipe process reparented to init that no supervisor knows about — a second
voice HUD floating on the desktop, a stale stream holding the microphone.

Since the reaping is silent (no confirmation prompt, no user-visible event), a
false positive is unacceptable: killing a process the user deliberately started
would look like a random crash. The scan is therefore built to under-report.

Orphan definition (ALL must hold — plus a second sighting an hour later)
------------------------------------------------------------------------
1. POSIX only. On Windows there is no ``ppid == 1`` reparenting contract, so
   the service no-ops rather than guess.
2. The command line contains the absolute script path of a recipe this server
   declares as its own (``daemons.items[]`` + stream-mode channels). A recipe
   the server never owns is never touched, however old it looks.
3. ``ppid == 1`` — reparented to init, i.e. whoever spawned it is gone. A live
   supervisor's child always has the server (or its ``uv run`` shell) as parent.
4. No controlling terminal. Anything started from a shell keeps its tty, which
   rules out ``frago recipe run`` in a terminal the user is still watching.
5. Not a descendant of this server process, and not a pid any live supervisor
   currently reports — a redundant check against (3), kept deliberately.
6. Started at least ``MIN_ORPHAN_AGE_SECONDS`` before this server process
   started. A leftover from a previous server generation always predates the
   current one; a child of the current server can never satisfy this.
7. Seen with the same identity (pid + process start time) in the previous
   hourly scan. A single transient reparenting blip can never trigger a kill,
   and pid reuse cannot inherit a previous candidate's confirmation.

If a single scan somehow nominates more than ``MAX_KILLS_PER_CYCLE``
candidates, the cycle kills nothing and logs an error: at that point the more
likely explanation is a bug in the scan than a real pile of orphans.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# A leftover must predate the current server process by at least this much.
MIN_ORPHAN_AGE_SECONDS = 300

# Sanity ceiling: more candidates than this in one scan means "distrust the
# scan", not "reap them all".
MAX_KILLS_PER_CYCLE = 10

# Grace period between SIGTERM and SIGKILL of an orphan tree.
TERM_GRACE_SECONDS = 5.0

_LEDGER_PATH = Path.home() / ".frago" / "state" / "orphan_recipe_candidates.json"


@dataclass(frozen=True)
class ProcInfo:
    """The process facts the scan needs, decoupled from psutil for testing."""

    pid: int
    ppid: int
    create_time: float
    terminal: str | None
    cmdline: tuple[str, ...]

    @property
    def key(self) -> str:
        """Identity that survives a scan gap but not pid reuse."""
        return f"{self.pid}:{int(self.create_time)}"


@dataclass(frozen=True)
class OrphanCandidate:
    proc: ProcInfo
    recipe: str

    @property
    def key(self) -> str:
        return self.proc.key


def collect_owned_recipes(raw_config: dict, runner: object) -> dict[str, Path]:
    """Map recipe name → absolute script path for every server-owned daemon.

    Owned means "this server is the only thing that should ever have it
    running": a ``daemons.items[]`` entry or a stream-mode ingestion channel.
    Disabled entries stay in the map on purpose — a daemon switched off in
    config should not still be running, while an entry the server has never
    heard of must remain untouchable.
    """
    names: list[str] = []

    for item in (raw_config.get("daemons") or {}).get("items", []) or []:
        name = item.get("recipe")
        if name:
            names.append(name)

    for ch in (raw_config.get("task_ingestion") or {}).get("channels", []) or []:
        if ch.get("mode") == "stream" and ch.get("poll_recipe"):
            names.append(ch["poll_recipe"])

    owned: dict[str, Path] = {}
    for name in names:
        if name in owned:
            continue
        try:
            recipe = runner.registry.find(name)
        except Exception as e:
            logger.debug("Orphan scan: recipe %s not resolvable (%s), skipping", name, e)
            continue
        script = getattr(recipe, "script_path", None)
        if script:
            owned[name] = Path(str(script)).resolve()
    return owned


def find_orphan_candidates(
    procs: list[ProcInfo],
    owned_scripts: dict[str, Path],
    *,
    server_pid: int,
    server_create_time: float,
    protected_pids: frozenset[int],
    min_age_seconds: float = MIN_ORPHAN_AGE_SECONDS,
) -> list[OrphanCandidate]:
    """Apply rules 2–6 (see module docstring). Pure — no signals, no psutil."""
    if not owned_scripts:
        return []

    script_to_recipe = {str(path): name for name, path in owned_scripts.items()}
    candidates: list[OrphanCandidate] = []

    for proc in procs:
        if proc.pid <= 1 or proc.pid == server_pid:
            continue
        if proc.pid in protected_pids:
            continue
        if proc.ppid != 1:
            continue
        if proc.terminal:
            continue
        if proc.create_time > server_create_time - min_age_seconds:
            continue

        recipe = _match_owned_script(proc.cmdline, script_to_recipe)
        if recipe is None:
            continue
        candidates.append(OrphanCandidate(proc=proc, recipe=recipe))

    return candidates


def _match_owned_script(
    cmdline: tuple[str, ...], script_to_recipe: dict[str, str]
) -> str | None:
    """Return the owned recipe whose script path appears in ``cmdline``.

    Matching is on a full argument being the script path (``uv run … <script>``
    and the ``python <script>`` grandchild both look like this), so a substring
    of an unrelated path cannot produce a hit.
    """
    for arg in cmdline:
        if not arg:
            continue
        recipe = script_to_recipe.get(arg)
        if recipe is not None:
            return recipe
        # Tolerate symlinked / non-normalized spellings of the same file.
        with contextlib.suppress(OSError, ValueError):
            resolved = str(Path(arg).resolve())
            recipe = script_to_recipe.get(resolved)
            if recipe is not None:
                return recipe
    return None


def load_ledger(path: Path = _LEDGER_PATH) -> dict[str, dict]:
    """Read the previous scan's candidates (identity key → record)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    entries = data.get("candidates")
    return entries if isinstance(entries, dict) else {}


def save_ledger(candidates: dict[str, dict], path: Path = _LEDGER_PATH) -> None:
    """Persist this scan's candidates so the next scan can confirm them."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"candidates": candidates}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Orphan scan: failed to persist ledger: %s", e)


class OrphanRecipeCleanupService:
    """Reap orphaned recipe daemon processes once per hour, on the hour."""

    _instance: Optional["OrphanRecipeCleanupService"] = None
    _lock = threading.Lock()

    def __init__(self, ledger_path: Path = _LEDGER_PATH) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._ledger_path = ledger_path
        self._reaped_total = 0
        self._last_scan_at: float | None = None

    @classmethod
    def get_instance(cls) -> "OrphanRecipeCleanupService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if sys.platform == "win32":
            logger.info("Orphan recipe cleanup disabled on Windows")
            return
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="orphan-recipe-cleanup")
        logger.info("Orphan recipe cleanup service started (hourly, on the hour)")

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Orphan recipe cleanup service stopped")

    def status(self) -> dict:
        return {
            "running": self._task is not None and not self._task.done(),
            "reaped_total": self._reaped_total,
            "last_scan_at": self._last_scan_at,
        }

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            delay = seconds_until_next_hour()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                return  # stop requested during the wait
            except TimeoutError:
                pass
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                logger.exception("Orphan recipe cleanup cycle failed")

    # -- one cycle (runs in a worker thread; psutil calls are blocking) --

    def run_once(self, *, dry_run: bool = False) -> list[OrphanCandidate]:
        """Scan, confirm against the previous scan, reap. Returns what was reaped.

        With ``dry_run=True`` nothing is signalled and the ledger is left alone,
        which is what an operator-facing inspection command wants.
        """
        import psutil

        self._last_scan_at = time.time()

        owned = self._owned_scripts()
        if not owned:
            return []

        server = psutil.Process(os.getpid())
        protected = self._protected_pids(server)
        procs = snapshot_processes()

        candidates = find_orphan_candidates(
            procs,
            owned,
            server_pid=server.pid,
            server_create_time=server.create_time(),
            protected_pids=protected,
        )
        if not candidates:
            if not dry_run:
                save_ledger({}, self._ledger_path)
            return []

        if len(candidates) > MAX_KILLS_PER_CYCLE:
            logger.error(
                "Orphan scan nominated %d candidates (> %d) — distrusting the scan, "
                "killing nothing. Recipes: %s",
                len(candidates), MAX_KILLS_PER_CYCLE,
                sorted({c.recipe for c in candidates}),
            )
            return []

        previous = load_ledger(self._ledger_path)
        confirmed = [c for c in candidates if c.key in previous]
        pending = [c for c in candidates if c.key not in previous]

        for c in pending:
            logger.info(
                "Orphan recipe candidate (first sighting, no action): %s pid=%s "
                "started=%s",
                c.recipe, c.proc.pid,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(c.proc.create_time)),
            )

        if dry_run:
            for c in confirmed:
                logger.info(
                    "Orphan recipe confirmed (dry run, not killed): %s pid=%s",
                    c.recipe, c.proc.pid,
                )
            return confirmed

        reaped: list[OrphanCandidate] = []
        for c in confirmed:
            if self._reap(c):
                reaped.append(c)

        # Carry unconfirmed sightings forward; a reaped entry is done with.
        still_pending = {
            c.key: {
                "recipe": c.recipe,
                "pid": c.proc.pid,
                "create_time": c.proc.create_time,
                "first_seen": previous.get(c.key, {}).get("first_seen", time.time()),
            }
            for c in candidates
            if c not in reaped
        }
        save_ledger(still_pending, self._ledger_path)

        if reaped:
            self._reaped_total += len(reaped)
            logger.info(
                "Orphan recipe cleanup: reaped %d process tree(s): %s",
                len(reaped),
                ", ".join(f"{c.recipe}(pid={c.proc.pid})" for c in reaped),
            )
        return reaped

    def _owned_scripts(self) -> dict[str, Path]:
        config_file = Path.home() / ".frago" / "config.json"
        try:
            raw_config = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Orphan scan: config unreadable (%s), skipping cycle", e)
            return {}
        from frago.recipes.runner import RecipeRunner

        return collect_owned_recipes(raw_config, RecipeRunner())

    @staticmethod
    def _protected_pids(server: object) -> frozenset[int]:
        """Pids that must never be candidates: server descendants + live daemons."""
        pids: set[int] = set()
        with contextlib.suppress(Exception):
            pids.update(child.pid for child in server.children(recursive=True))

        from frago.server.services.daemon_service import DaemonService

        instance = DaemonService.get_instance()
        if instance is not None:
            with contextlib.suppress(Exception):
                pids.update(
                    entry["pid"] for entry in instance.status() if entry.get("pid")
                )
        return frozenset(pids)

    def _reap(self, candidate: OrphanCandidate) -> bool:
        """SIGTERM the orphan's process tree, SIGKILL what survives the grace.

        The tree (``uv run`` shell + the recipe's python grandchild) is captured
        before any signal is sent, so a child that reparents mid-teardown is
        still accounted for.
        """
        import psutil

        pid = candidate.proc.pid
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return False

        # Re-verify identity at the moment of the kill: between scan and signal
        # the pid could have been recycled into an unrelated process.
        if int(proc.create_time()) != int(candidate.proc.create_time):
            logger.warning(
                "Orphan reap aborted: pid %s no longer the process we scanned", pid
            )
            return False

        targets = [proc]
        with contextlib.suppress(Exception):
            targets.extend(proc.children(recursive=True))

        _signal_group_or_procs(pid, targets, signal.SIGTERM)
        _, alive = psutil.wait_procs(targets, timeout=TERM_GRACE_SECONDS)
        if alive:
            _signal_group_or_procs(pid, alive, signal.SIGKILL)
            psutil.wait_procs(alive, timeout=TERM_GRACE_SECONDS)

        logger.info(
            "Orphan recipe reaped: %s pid=%s (started %s, %d process(es))",
            candidate.recipe, pid,
            time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(candidate.proc.create_time)
            ),
            len(targets),
        )
        return True


def _signal_group_or_procs(root_pid: int, procs: list, sig: int) -> None:
    """Signal the root's process group when it owns one, else each process.

    Supervised recipes are spawned with ``start_new_session=True``, so the
    orphan root leads its own group and one ``killpg`` reaches the whole tree.
    The per-process fallback covers hand-launched leftovers that share a group
    with other processes — there, signalling the group could hit a bystander.
    """
    with contextlib.suppress(OSError):
        if os.getpgid(root_pid) == root_pid:
            os.killpg(root_pid, sig)
            return
    for p in procs:
        with contextlib.suppress(Exception):
            p.send_signal(sig)


def snapshot_processes() -> list[ProcInfo]:
    """Snapshot every visible process as :class:`ProcInfo`."""
    import psutil

    out: list[ProcInfo] = []
    for p in psutil.process_iter(["pid", "ppid", "create_time", "terminal", "cmdline"]):
        info = p.info
        cmdline = info.get("cmdline") or []
        if not cmdline:
            continue
        out.append(
            ProcInfo(
                pid=info["pid"],
                ppid=info.get("ppid") or 0,
                create_time=info.get("create_time") or 0.0,
                terminal=info.get("terminal"),
                cmdline=tuple(cmdline),
            )
        )
    return out


def seconds_until_next_hour(now: float | None = None) -> float:
    """Seconds from ``now`` to the next wall-clock hour boundary."""
    now = time.time() if now is None else now
    return 3600.0 - (now % 3600.0)
