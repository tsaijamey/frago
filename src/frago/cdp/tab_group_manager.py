"""
Tab Group Manager - Agent-isolated tab routing in shared Chrome browser

Adds a group dimension on top of TabManager's origin-based routing.
Each group has its own tab pool — agents in different groups never
share or collide on tabs, even for the same origin.

No Chrome extension. No browser-level WebSocket. Pure logical isolation
backed by a JSON state file, using existing CDPSession + TargetCommands.
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests
import websocket as _ws

from .logger import get_logger
from .tab_manager import TabManager

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
    "BROWSER_NOT_RUNNING": "chrome is not running — start with: uv run frago chrome start",
    "TAB_NOT_IN_GROUP": "target tab does not belong to current group",
    "NAVIGATION_TIMEOUT": "page load timed out",
    "LANDING_PAGE_PROTECTED": "landing page is protected, cannot be operated on",
}


STATE_FILE = Path.home() / ".frago" / "chrome" / "tab_groups.json"
LOCK_FILE = Path.home() / ".frago" / "chrome" / "tab_groups.lock"
SCHEMA_VERSION = "1.0"
DEFAULT_MAX_TABS_PER_GROUP = 10
GROUP_TIMEOUT_SECONDS = 30 * 60  # 30 minutes


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

    def get_or_create_tab(self, url: str, group_name: str, session) -> str:
        """Get or create a tab within a group for the given URL.

        Uses origin-based routing scoped to the group.

        Args:
            url: URL to navigate to.
            group_name: Group name.
            session: CDPSession instance (for TargetCommands).

        Returns:
            target_id of the tab to use.
        """
        group = self.ensure_group(group_name)
        origin = TabManager.extract_origin(url)

        if origin is None and group.tabs:
            # Unroutable URL — use most recent tab in group
            tab = max(group.tabs.values(), key=lambda t: t.last_activity)
            tab.touch()
            group.touch()
            self._save_state()
            return tab.target_id

        # Find existing tab with same origin in this group
        if origin:
            candidates = [t for t in group.tabs.values() if t.origin == origin]
            if candidates:
                tab = max(candidates, key=lambda t: t.last_activity)
                tab.touch()
                group.touch()
                self._save_state()
                return tab.target_id

        # Need new tab — evict if at capacity
        if len(group.tabs) >= group.max_tabs:
            self._evict_lru_tab(group, session)

        # Create tab via existing TargetCommands (background to avoid stealing focus)
        target_id = session.target.create_target(url, background=True)
        if not target_id:
            raise RuntimeError(f"Failed to create tab for {url}")

        now = time.time()
        group.tabs[target_id] = GroupTabEntry(
            target_id=target_id,
            origin=origin or "",
            url=url,
            title="",
            last_activity=now,
            created_at=now,
        )
        group.touch()
        self._save_state()
        return target_id

    def close_group(self, group_name: str, session) -> bool:
        """Close a group and all its tabs.

        Args:
            group_name: Group name to close.
            session: CDPSession instance.

        Returns:
            True if group was found and closed.
        """
        group = self._state.pop(group_name, None)
        if not group:
            return False

        self._deleted_groups.add(group_name)
        self._dirty_groups.discard(group_name)

        tab_count = len(group.tabs)
        for target_id in list(group.tabs):
            try:
                session.target.close_target(target_id)
            except Exception:
                self.logger.debug(f"Failed to close tab {target_id}")

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

        Called lazily during chrome command execution (no background thread needed).

        Args:
            session: CDPSession instance for closing tabs.

        Returns:
            Number of groups cleaned up.
        """
        now = time.time()
        expired = [
            name for name, group in self._state.items()
            if group.last_activity > 0 and now - group.last_activity > GROUP_TIMEOUT_SECONDS
        ]
        for name in expired:
            self.close_group(name, session)
            self.logger.info(f"Expired group '{name}' (inactive > {GROUP_TIMEOUT_SECONDS}s)")
        return len(expired)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_lru_tab(self, group: TabGroupState, session) -> None:
        """Evict the least recently used tab from a group."""
        if not group.tabs:
            return
        lru = min(group.tabs.values(), key=lambda t: t.last_activity)
        try:
            session.target.close_target(lru.target_id)
        except Exception:
            self.logger.debug(f"Failed to close LRU tab {lru.target_id}")
        del group.tabs[lru.target_id]

    def _get_live_target_ids(self) -> set[str]:
        """Fetch current page target IDs from Chrome via HTTP."""
        try:
            resp = requests.get(
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
            result[name] = TabGroupState(tabs=tabs, **gdata)
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
            resp = requests.get(
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
                if "/chrome/dashboard" in url or url.startswith("data:text/html") or title == "frago":
                    landing_ws = t.get("webSocketDebuggerUrl")
                    break

            if not landing_ws:
                return

            payload = json.dumps(data, ensure_ascii=False)
            js = f"window.__frago_update_dashboard__({payload})"

            ws = _ws.create_connection(landing_ws, timeout=3)
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js},
            }))
            ws.recv()
            ws.close()
        except Exception:
            pass  # Best-effort, don't break normal operations

    LANDING_PAGE_URL = "http://127.0.0.1:8093/chrome/dashboard"

    def ensure_landing_page(self) -> bool:
        """Check if landing page exists; recreate if missing. Best-effort."""
        try:
            import websocket as _ws

            # Check if server is running
            try:
                requests.get(self.LANDING_PAGE_URL, timeout=1)
            except Exception:
                return False

            resp = requests.get(
                f"http://{self.host}:{self.port}/json/list", timeout=2
            )
            targets = resp.json()

            # Already exists?
            for t in targets:
                if t.get("type") != "page":
                    continue
                url = t.get("url", "")
                title = t.get("title", "")
                if "/chrome/dashboard" in url or title == "frago":
                    return True

            # Missing — create it
            ws_url = None
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    ws_url = t["webSocketDebuggerUrl"]
                    break
            if not ws_url:
                ver = requests.get(
                    f"http://{self.host}:{self.port}/json/version", timeout=2
                ).json()
                ws_url = ver.get("webSocketDebuggerUrl")
            if not ws_url:
                return False

            ws = _ws.create_connection(ws_url, timeout=5)
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
