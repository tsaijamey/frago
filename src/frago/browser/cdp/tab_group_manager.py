"""
Tab Group Manager — agent-isolated tab pools for the CDP backend.

Same contract as the extension backend's groups: a group owns up to
:data:`DEFAULT_MAX_TABS_PER_GROUP` tabs, ``navigate`` reuses the group's
current tab unless asked for a new one, tab commands only ever reach the
group's own tabs, and a group with nothing happening in it for
:data:`GROUP_TIMEOUT_SECONDS` closes itself.

One difference that cannot be papered over: CDP has no access to the
browser's tab-group UI (that API is extension-only), so here a group is
bookkeeping alone — the tabs are not visually banded together on the tab
strip. Isolation is identical; only the visible grouping is missing.
That is one more reason the extension backend is the default.
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .landing import LANDING_PAGE_URL as _LANDING_URL
from .landing import is_landing_page
from .logger import get_logger
from .tab_manager import TabManager
from .transport import cdp_get, cdp_ws_connect


class ChromeCommandError(Exception):
    """Structured error for chrome command failures."""

    def __init__(self, code: str, message: str, context: dict | None = None):
        self.code = code
        self.message = message
        self.context = context or {}
        super().__init__(f"{code}: {message}")


# Error code definitions
CHROME_ERRORS = {
    "NO_GROUP": "no group context — add --group <name> to this command (or set FRAGO_CURRENT_RUN env in recipe)",
    "BROWSER_NOT_RUNNING": "chrome is not running — start with: frago browser start",
    "TAB_NOT_IN_GROUP": "target tab does not belong to current group",
    "GROUP_TAB_LIMIT": "group is full — close a tab before opening another",
    "NO_TAB_IN_GROUP": "group has no open tab yet — navigate first",
    "GROUP_NOT_FOUND": "no group by that name is open",
    "NAVIGATION_TIMEOUT": "page load timed out",
    "LANDING_PAGE_PROTECTED": "landing page is protected, cannot be operated on",
}


STATE_FILE = Path.home() / ".frago" / "chrome" / "tab_groups.json"
LOCK_FILE = Path.home() / ".frago" / "chrome" / "tab_groups.lock"
SCHEMA_VERSION = "1.0"
# Kept in step with the extension backend's ceiling — an agent must not
# have to learn two different limits depending on which backend is up.
DEFAULT_MAX_TABS_PER_GROUP = 5
GROUP_TIMEOUT_SECONDS = 30 * 60  # 30 minutes of total silence


@dataclass
class GroupTabEntry:
    """A tab within a group."""

    target_id: str
    origin: str
    url: str
    title: str
    last_activity: float
    created_at: float

    def touch(self) -> None:
        self.last_activity = time.time()


@dataclass
class TabGroupState:
    """State of a single tab group."""

    title: str
    agent_session: str  # FRAGO_CURRENT_RUN value or group name
    created_at: float
    last_activity: float = 0.0  # Group-level last activity timestamp
    tabs: dict[str, GroupTabEntry] = field(default_factory=dict)
    max_tabs: int = DEFAULT_MAX_TABS_PER_GROUP
    current_target_id: str | None = None  # Last navigated tab in this group

    def touch(self) -> None:
        self.last_activity = time.time()


class TabGroupManager:
    """Manages tab groups for agent isolation.

    Group name resolution priority:
      1. Explicit --group flag
      2. FRAGO_CURRENT_RUN environment variable
      3. No group context → caller falls back to original TabManager
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.logger = get_logger()
        self._state: dict[str, TabGroupState] = {}
        self._dirty_groups: set[str] = set()  # Groups modified by this process
        self._deleted_groups: set[str] = set()  # Groups explicitly deleted by this process
        self._load_state()

    # ------------------------------------------------------------------
    # Group name resolution
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_group_name(explicit_group: str | None = None) -> str | None:
        """Resolve group name from explicit flag or environment.

        Returns None if no group context (caller should use original TabManager).
        """
        if explicit_group:
            return explicit_group
        return os.environ.get("FRAGO_CURRENT_RUN") or None

    # ------------------------------------------------------------------
    # Group lifecycle
    # ------------------------------------------------------------------

    def ensure_group(self, group_name: str) -> TabGroupState:
        """Ensure a group exists, creating it if necessary."""
        if group_name in self._state:
            self._dirty_groups.add(group_name)
            return self._state[group_name]

        now = time.time()
        group = TabGroupState(
            title=group_name,
            agent_session=group_name,
            created_at=now,
            last_activity=now,
        )
        self._state[group_name] = group
        self._dirty_groups.add(group_name)
        self._save_state()
        self.logger.info(f"Created group '{group_name}'")
        return group

    def get_or_create_tab(self, url: str, group_name: str, session, *,
                          new: bool = False) -> str:
        """Return the target_id ``url`` should be loaded into.

        Without ``new``: the group's current tab — the last one this
        group navigated or switched to. Not the browser's active tab: a
        person may be looking at their own page while the agent works.

        With ``new``: another tab joins the group, up to
        ``group.max_tabs``. At the ceiling this raises
        ``GROUP_TAB_LIMIT`` listing the tabs already open, rather than
        quietly closing the oldest — an agent that believes a page is
        still open and finds its next command on a different page has no
        way to notice anything went wrong.
        """
        group = self.ensure_group(group_name)
        self._prune_dead_tabs(group)

        if not new and group.current_target_id in group.tabs:
            tab = group.tabs[group.current_target_id]
            tab.origin = TabManager.extract_origin(url) or tab.origin
            tab.url = url
            tab.touch()
            group.touch()
            self._save_state()
            return tab.target_id

        self._assert_room(group_name, group)

        # Create tab via existing TargetCommands (background to avoid stealing focus)
        target_id = session.target.create_target(url, background=True)
        if not target_id:
            raise RuntimeError(f"Failed to create tab for {url}")

        now = time.time()
        group.tabs[target_id] = GroupTabEntry(
            target_id=target_id,
            origin=TabManager.extract_origin(url) or "",
            url=url,
            title="",
            last_activity=now,
            created_at=now,
        )
        group.current_target_id = target_id
        group.touch()
        self._save_state()
        return target_id

    def _assert_room(self, group_name: str, group: TabGroupState) -> None:
        """Raise GROUP_TAB_LIMIT when the group cannot hold another tab."""
        if len(group.tabs) < group.max_tabs:
            return
        raise ChromeCommandError(
            "GROUP_TAB_LIMIT",
            f"group '{group_name}' already holds {len(group.tabs)} tabs "
            f"(limit {group.max_tabs}). Close one you no longer need, or "
            f"navigate without --new to reuse the current tab.",
            {
                "group": group_name,
                "limit": group.max_tabs,
                "tabs": [
                    {"tab_id": t.target_id, "title": t.title, "url": t.url,
                     "current": t.target_id == group.current_target_id}
                    for t in self.get_group_tabs(group_name)
                ],
                "remedies": [
                    f"frago browser close-tab --group {group_name} <tab_id>",
                    f"frago browser navigate <url> --group {group_name}",
                    f"frago browser group-close {group_name}",
                ],
            },
        )

    def _prune_dead_tabs(self, group: TabGroupState) -> None:
        """Drop tabs the browser no longer has (person closed one, crash)."""
        live = self._get_live_target_ids()
        if not live:
            return
        dead = [tid for tid in group.tabs if tid not in live]
        if not dead:
            return
        for tid in dead:
            del group.tabs[tid]
        if group.current_target_id not in group.tabs:
            group.current_target_id = (
                max(group.tabs.values(), key=lambda t: t.last_activity).target_id
                if group.tabs else None
            )
        self._save_state()

    # ------------------------------------------------------------------
    # Group-scoped tab operations
    # ------------------------------------------------------------------

    def require_tab_in_group(self, group_name: str, tab_id: str) -> str:
        """Resolve ``tab_id`` (full or prefix) against one group's tabs.

        A group may only touch its own tabs — that is the whole point of
        the isolation. Raises TAB_NOT_IN_GROUP otherwise, listing what
        the group does hold.
        """
        group = self._state.get(group_name)
        if not group:
            raise ChromeCommandError(
                "NO_TAB_IN_GROUP",
                f"group '{group_name}' does not exist — navigate first",
                {"group": group_name},
            )
        self._prune_dead_tabs(group)
        matches = [tid for tid in group.tabs
                   if tid == tab_id or tid.startswith(tab_id)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ChromeCommandError(
                "TAB_NOT_IN_GROUP",
                f"tab {tab_id} is not in group '{group_name}' — a group may "
                f"only operate on its own tabs",
                {"group": group_name,
                 "tabs": [t.target_id for t in self.get_group_tabs(group_name)]},
            )
        raise ChromeCommandError(
            "TAB_NOT_IN_GROUP",
            f"tab id '{tab_id}' is ambiguous in group '{group_name}'",
            {"group": group_name, "matches": matches},
        )

    def switch_tab(self, group_name: str, tab_id: str) -> str:
        """Point the group at one of its own tabs. Returns the full id."""
        full = self.require_tab_in_group(group_name, tab_id)
        group = self._state[group_name]
        group.current_target_id = full
        group.tabs[full].touch()
        group.touch()
        self._dirty_groups.add(group_name)
        self._save_state()
        return full

    def close_tab(self, group_name: str, tab_id: str, session) -> str:
        """Close one of the group's own tabs. Returns the full id."""
        full = self.require_tab_in_group(group_name, tab_id)
        group = self._state[group_name]
        try:
            session.target.close_target(full)
        except Exception:
            self.logger.warning(f"Failed to close tab {full}", exc_info=True)
        del group.tabs[full]
        if group.current_target_id == full:
            group.current_target_id = (
                max(group.tabs.values(), key=lambda t: t.last_activity).target_id
                if group.tabs else None
            )
        group.touch()
        self._dirty_groups.add(group_name)
        self._save_state()
        return full

    def touch_group(self, group_name: str) -> None:
        """Reset a group's idle clock. Any command on it counts as use."""
        group = self._state.get(group_name)
        if not group:
            return
        group.touch()
        if group.current_target_id in group.tabs:
            group.tabs[group.current_target_id].touch()
        self._dirty_groups.add(group_name)
        self._save_state()

    def close_group(self, group_name: str, session) -> bool:
        """Close a group and all its tabs.

        Args:
            group_name: Group name to close.
            session: CDPSession instance.

        Returns:
            True if group was found and closed.
        """
        return self._remove_group_and_close(group_name, session.target.close_target)

    def close_group_http(self, group_name: str) -> bool:
        """Close a group and all its tabs via HTTP GET /json/close/<tid>.

        Same semantics as close_group(session) but needs no CDPSession.
        Used by the server periodic service and the CLI fallback sweep.

        Returns:
            True if group was found and closed.
        """
        def close_tab(target_id: str) -> None:
            cdp_get(
                f"http://{self.host}:{self.port}/json/close/{target_id}",
                timeout=5,
            )

        return self._remove_group_and_close(group_name, close_tab)

    def _remove_group_and_close(self, group_name: str, close_tab_fn) -> bool:
        """Remove a group from state and close its tabs via close_tab_fn."""
        group = self._state.pop(group_name, None)
        if not group:
            return False

        self._deleted_groups.add(group_name)
        self._dirty_groups.discard(group_name)

        tab_count = len(group.tabs)
        for target_id in list(group.tabs):
            try:
                close_tab_fn(target_id)
            except Exception:
                self.logger.warning(
                    f"Failed to close tab {target_id}", exc_info=True
                )

        self._save_state()
        self.logger.info(f"Closed group '{group_name}' ({tab_count} tabs)")
        return True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_groups(self) -> dict[str, TabGroupState]:
        """Get all groups."""
        return dict(self._state)

    def get_group(self, group_name: str) -> TabGroupState | None:
        """Get a specific group."""
        return self._state.get(group_name)

    def set_current_target(self, group_name: str, target_id: str) -> None:
        """Record the last navigated tab for a group."""
        group = self._state.get(group_name)
        if group:
            group.current_target_id = target_id
            self._dirty_groups.add(group_name)
            self._save_state()

    def get_current_target(self, group_name: str) -> str | None:
        """Get the last navigated tab for a group."""
        group = self._state.get(group_name)
        return group.current_target_id if group else None

    def get_group_tabs(self, group_name: str) -> list[GroupTabEntry]:
        """Get tabs in a group, sorted by last_activity descending."""
        group = self._state.get(group_name)
        if not group:
            return []
        return sorted(
            group.tabs.values(), key=lambda t: t.last_activity, reverse=True
        )

    # ------------------------------------------------------------------
    # Cleanup & reconciliation
    # ------------------------------------------------------------------

    def reconcile(self) -> None:
        """Sync persisted state with actual Chrome tabs.

        Removes entries for tabs that no longer exist.
        Removes groups that have no tabs left.
        """
        live_ids = self._get_live_target_ids()
        if not live_ids:
            return

        changed = False
        empty_groups = []

        for name, group in self._state.items():
            dead = [tid for tid in group.tabs if tid not in live_ids]
            for tid in dead:
                del group.tabs[tid]
                changed = True
            if dead and group.current_target_id not in group.tabs:
                group.current_target_id = (
                    max(group.tabs.values(),
                        key=lambda t: t.last_activity).target_id
                    if group.tabs else None
                )
            if not group.tabs:
                empty_groups.append(name)

        for name in empty_groups:
            del self._state[name]
            self._deleted_groups.add(name)
            self._dirty_groups.discard(name)
            changed = True

        if changed:
            self._save_state()

    def cleanup_stale_groups(self) -> int:
        """Remove groups whose tabs are all gone.

        Returns number of groups cleaned up.
        """
        self.reconcile()

        # After reconcile, any remaining empty groups are stale
        stale = [n for n, g in self._state.items() if not g.tabs]
        for name in stale:
            del self._state[name]

        if stale:
            self._save_state()
            self.logger.info(f"Cleaned up {len(stale)} stale groups")

        return len(stale)

    def cleanup_expired_groups(self, session) -> int:
        """Close groups that have been inactive for longer than GROUP_TIMEOUT_SECONDS.

        Args:
            session: CDPSession instance for closing tabs.

        Returns:
            Number of groups cleaned up.
        """
        expired = self._expired_group_names(time.time())
        for name in expired:
            self.close_group(name, session)
            self.logger.info(f"Expired group '{name}' (inactive > {GROUP_TIMEOUT_SECONDS}s)")
        return len(expired)

    def cleanup_expired_groups_http(self) -> int:
        """Close expired groups via HTTP, without a CDPSession.

        Same expiry predicate as cleanup_expired_groups(session); used by
        the server periodic service and the CLI end-of-process fallback.

        Returns:
            Number of groups cleaned up.
        """
        expired = self._expired_group_names(time.time())
        for name in expired:
            self.close_group_http(name)
            self.logger.info(f"Expired group '{name}' (inactive > {GROUP_TIMEOUT_SECONDS}s)")
        return len(expired)

    def _expired_group_names(self, now: float) -> list[str]:
        """Groups whose last_activity exceeded GROUP_TIMEOUT_SECONDS.

        Groups with last_activity == 0 (legacy never-touched state) are
        excluded — reconcile / cleanup_stale_groups handles those.
        """
        return [
            name for name, group in self._state.items()
            if group.last_activity > 0 and now - group.last_activity > GROUP_TIMEOUT_SECONDS
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_live_target_ids(self) -> set[str]:
        """Fetch current page target IDs from Chrome via HTTP."""
        try:
            resp = cdp_get(
                f"http://{self.host}:{self.port}/json/list", timeout=5
            )
            resp.raise_for_status()
            return {t["id"] for t in resp.json() if t.get("type") == "page"}
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _flock(f, exclusive: bool = True) -> None:
        """Acquire a file lock (cross-platform)."""
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        except ImportError:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK if exclusive else msvcrt.LK_NBRLCK, 1)

    @staticmethod
    def _funlock(f) -> None:
        """Release a file lock (cross-platform)."""
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            self._state = {}
            return
        try:
            self._state = self._read_disk_state()
        except Exception:
            self.logger.debug("Failed to load tab group state, starting fresh")
            self._state = {}

    def _read_disk_state(self) -> dict[str, "TabGroupState"]:
        """Read state file into a dict of TabGroupState (no lock — caller must hold lock if needed)."""
        if not STATE_FILE.exists():
            return {}
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if data.get("port") != self.port:
            return {}
        result: dict[str, TabGroupState] = {}
        for name, gdata in data.get("groups", {}).items():
            tabs_raw = gdata.pop("tabs", {})
            tabs = {tid: GroupTabEntry(**td) for tid, td in tabs_raw.items()}
            group = TabGroupState(tabs=tabs, **gdata)
            # State written before the ceiling dropped to 5 carries the old
            # number. Left alone, a group that survived the upgrade would
            # keep a different limit from every group created after it.
            group.max_tabs = min(group.max_tabs, DEFAULT_MAX_TABS_PER_GROUP)
            result[name] = group
        return result

    def _save_state(self) -> None:
        """Atomic read-merge-write under exclusive file lock.

        Merges in-memory groups with disk state so concurrent writers
        don't overwrite each other's groups.
        """
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(LOCK_FILE, "a+") as lock:
            self._flock(lock, exclusive=True)
            try:
                # Re-read latest disk state under lock
                disk_state = self._read_disk_state()

                # Merge strategy:
                # - For groups this process modified (_dirty_groups): use our version
                # - For groups this process deleted (_deleted_groups): remove them
                # - For all other groups: keep disk version (another process may have updated)
                merged = dict(disk_state)

                # Apply our dirty groups (overwrite disk version)
                for name in self._dirty_groups:
                    if name in self._state:
                        merged[name] = self._state[name]

                # Remove groups we explicitly deleted
                for name in self._deleted_groups:
                    merged.pop(name, None)

                self._state = merged

                data = {
                    "schema_version": SCHEMA_VERSION,
                    "port": self.port,
                    "groups": {
                        name: {
                            "title": g.title,
                            "agent_session": g.agent_session,
                            "created_at": g.created_at,
                            "last_activity": g.last_activity,
                            "max_tabs": g.max_tabs,
                            "current_target_id": g.current_target_id,
                            "tabs": {tid: asdict(t) for tid, t in g.tabs.items()},
                        }
                        for name, g in self._state.items()
                    },
                }
                STATE_FILE.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            finally:
                self._funlock(lock)

        self._push_to_landing_page(data)

    def _push_to_landing_page(self, data: dict) -> None:
        """Push group state to the landing page dashboard via CDP."""
        try:
            resp = cdp_get(
                f"http://{self.host}:{self.port}/json/list", timeout=2
            )
            targets = resp.json()

            # Find landing page target
            landing_ws = None
            for t in targets:
                if t.get("type") != "page":
                    continue
                url = t.get("url", "")
                title = t.get("title", "")
                if is_landing_page(url, title) or url.startswith("data:text/html"):
                    landing_ws = t.get("webSocketDebuggerUrl")
                    break

            if not landing_ws:
                return

            payload = json.dumps(data, ensure_ascii=False)
            js = f"window.__frago_update_dashboard__({payload})"

            ws = cdp_ws_connect(landing_ws, timeout=3)
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js},
            }))
            ws.recv()
            ws.close()
        except Exception:
            pass  # Best-effort, don't break normal operations

    LANDING_PAGE_URL = _LANDING_URL

    def ensure_landing_page(self) -> bool:
        """Check if landing page exists; recreate if missing. Best-effort."""
        try:
            # Check if server is running
            try:
                cdp_get(self.LANDING_PAGE_URL, timeout=1)
            except Exception:
                return False

            resp = cdp_get(
                f"http://{self.host}:{self.port}/json/list", timeout=2
            )
            targets = resp.json()

            # Already exists?
            for t in targets:
                if t.get("type") != "page":
                    continue
                url = t.get("url", "")
                title = t.get("title", "")
                if is_landing_page(url, title):
                    return True

            # Missing — create it
            ws_url = None
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    ws_url = t["webSocketDebuggerUrl"]
                    break
            if not ws_url:
                ver = cdp_get(
                    f"http://{self.host}:{self.port}/json/version", timeout=2
                ).json()
                ws_url = ver.get("webSocketDebuggerUrl")
            if not ws_url:
                return False

            ws = cdp_ws_connect(ws_url, timeout=5)
            ws.send(json.dumps({
                "id": 100,
                "method": "Target.createTarget",
                "params": {"url": self.LANDING_PAGE_URL},
            }))
            ws.recv()
            ws.close()

            get_logger().info("Landing page restored")
            return True
        except Exception:
            return False


# =============================================================================
# CLI session / routing helpers (relocated from cli/commands.py)
#
# These build CDP sessions and route tabs within a group.  They take the
# click ctx (whose ctx.obj is a plain config dict) but contain no output or
# formatting — that stays in the CLI layer.
# =============================================================================

def create_session(ctx, *, group: str | None = None, require_group: bool = True):
    """
    Create CDP session.

    When require_group=True (default), resolves target from the group's
    current_target_id.  Raises ChromeCommandError("NO_GROUP") if no
    group context is available.

    Management commands (status, reset, group-close) pass require_group=False
    to skip group enforcement — they don't operate on a specific tab.
    """
    from .config import CDPConfig
    from .session import CDPSession

    target_id = ctx.obj.get('TARGET_ID')

    # Auto-resolve target from tab group when no explicit target_id
    if not target_id and require_group:
        group_name = TabGroupManager.resolve_group_name(group)
        if not group_name:
            raise ChromeCommandError("NO_GROUP", CHROME_ERRORS["NO_GROUP"])
        tgm = TabGroupManager(
            host=ctx.obj['HOST'],
            port=ctx.obj['PORT'],
        )
        target_id = tgm.get_current_target(group_name)
        if not target_id:
            raise ChromeCommandError(
                "NO_TAB_IN_GROUP",
                f"group '{group_name}' has no open tab — navigate first: "
                f"frago browser navigate <url> --group {group_name}",
                {"group": group_name},
            )
        # Any command on a group is proof it is in use; restart its clock.
        tgm.touch_group(group_name)
        # Store resolved group in ctx for downstream use
        ctx.obj['_RESOLVED_GROUP'] = group_name

    config = CDPConfig(
        host=ctx.obj['HOST'],
        port=ctx.obj['PORT'],
        timeout=ctx.obj['TIMEOUT'],
        debug=ctx.obj['DEBUG'],
        proxy_host=ctx.obj.get('PROXY_HOST'),
        proxy_port=ctx.obj.get('PROXY_PORT'),
        proxy_username=ctx.obj.get('PROXY_USERNAME'),
        proxy_password=ctx.obj.get('PROXY_PASSWORD'),
        no_proxy=ctx.obj.get('NO_PROXY', False),
        target_id=target_id,
    )
    return CDPSession(config)


def build_group_index(host: str = "127.0.0.1", port: int = 9222) -> dict[str, str]:
    """Build tab_id → group_name mapping for all groups. Returns empty dict on failure."""
    try:
        tgm = TabGroupManager(host=host, port=port)
        index: dict[str, str] = {}
        for name, group in tgm.list_groups().items():
            for tid in group.tabs:
                index[tid] = name
        return index
    except Exception:
        return {}


def route_tab_for_navigate(ctx, session, url: str, group=None, *,
                           new: bool = False):
    """Route to the correct tab for a URL within a group.

    Group context is mandatory — resolved from explicit --group or
    FRAGO_CURRENT_RUN env var.  Raises ChromeCommandError if missing.

    ``new`` opens another tab inside the group instead of reusing its
    current one; at the group's ceiling it raises GROUP_TAB_LIMIT.

    Returns (target_id, resolved_group_name) tuple.
    """
    group_name = TabGroupManager.resolve_group_name(group)
    if not group_name:
        raise ChromeCommandError("NO_GROUP", CHROME_ERRORS["NO_GROUP"])

    tgm = TabGroupManager(
        host=ctx.obj['HOST'],
        port=ctx.obj['PORT'],
    )
    tgm.reconcile()
    tid = tgm.get_or_create_tab(url, group_name, session, new=new) or None
    return tid, group_name
