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

STATE_FILE = Path.home() / ".frago" / "chrome" / "tab_groups.json"
SCHEMA_VERSION = "1.0"
DEFAULT_MAX_TABS_PER_GROUP = 10


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
    tabs: dict[str, GroupTabEntry] = field(default_factory=dict)
    max_tabs: int = DEFAULT_MAX_TABS_PER_GROUP


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
            return self._state[group_name]

        now = time.time()
        group = TabGroupState(
            title=group_name,
            agent_session=group_name,
            created_at=now,
        )
        self._state[group_name] = group
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
            self._save_state()
            return tab.target_id

        # Find existing tab with same origin in this group
        if origin:
            candidates = [t for t in group.tabs.values() if t.origin == origin]
            if candidates:
                tab = max(candidates, key=lambda t: t.last_activity)
                tab.touch()
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

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            self._state = {}
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if data.get("port") != self.port:
                self._state = {}
                return
            groups = data.get("groups", {})
            self._state = {}
            for name, gdata in groups.items():
                tabs_raw = gdata.pop("tabs", {})
                tabs = {tid: GroupTabEntry(**td) for tid, td in tabs_raw.items()}
                self._state[name] = TabGroupState(tabs=tabs, **gdata)
        except Exception:
            self.logger.debug("Failed to load tab group state, starting fresh")
            self._state = {}

    def _save_state(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": SCHEMA_VERSION,
            "port": self.port,
            "groups": {
                name: {
                    "title": g.title,
                    "agent_session": g.agent_session,
                    "created_at": g.created_at,
                    "max_tabs": g.max_tabs,
                    "tabs": {tid: asdict(t) for tid, t in g.tabs.items()},
                }
                for name, g in self._state.items()
            },
        }
        STATE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
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
