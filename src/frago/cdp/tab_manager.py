"""
Tab Manager - Intelligent tab lifecycle management for CDP automation

Provides:
- Origin-based routing: reuse existing tab for same origin, create new for different
- LRU eviction: maintain max tabs, close least recently used when limit reached
- State persistence: track tab state across CLI invocations via JSON file
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from .logger import get_logger

MAX_TABS = 20
STATE_FILE = Path.home() / ".frago" / "chrome" / "tab_state.json"
SCHEMA_VERSION = "1.0"

UNROUTABLE_SCHEMES = frozenset({
    "about", "chrome", "chrome-extension", "data", "blob", "javascript",
})

# Standard ports omitted from origin string
_STANDARD_PORTS = {"http": 80, "https": 443}


@dataclass
class TabEntry:
    """Represents a tracked tab."""
    tab_id: str
    origin: str
    url: str
    title: str
    last_activity: float
    created_at: float

    def touch(self) -> None:
        self.last_activity = time.time()


class TabManager:
    """Manages tab lifecycle with origin routing and LRU eviction."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.logger = get_logger()
        self._state: Dict[str, TabEntry] = {}
        self._load_state()

    # --- Origin Extraction ---

    @staticmethod
    def extract_origin(url: str) -> Optional[str]:
        """Extract origin from URL.

        Returns None for unroutable URLs (about:blank, chrome://, data:, etc.).
        Returns "scheme://host[:port]" for routable URLs.
        Port is included only when non-standard.
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return None

        scheme = (parsed.scheme or "").lower()
        if not scheme or scheme in UNROUTABLE_SCHEMES:
            return None

        hostname = parsed.hostname
        if not hostname:
            return None

        port = parsed.port
        standard = _STANDARD_PORTS.get(scheme)
        if port and port != standard:
            return f"{scheme}://{hostname}:{port}"
        return f"{scheme}://{hostname}"

    @staticmethod
    def is_routable_url(url: str) -> bool:
        return TabManager.extract_origin(url) is not None

    # --- State Persistence ---

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            self._state = {}
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # Discard state from a different port (different Chrome instance)
            if data.get("port") != self.port:
                self._state = {}
                return
            tabs = data.get("tabs", {})
            self._state = {
                tid: TabEntry(**entry) for tid, entry in tabs.items()
            }
        except Exception:
            self.logger.debug("Failed to load tab state, starting fresh")
            self._state = {}

    def _save_state(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": SCHEMA_VERSION,
            "port": self.port,
            "tabs": {tid: asdict(entry) for tid, entry in self._state.items()},
        }
        STATE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # --- Live Tab Reconciliation ---

    def _get_live_tabs(self) -> List[Dict]:
        """Fetch current page tabs from Chrome via HTTP /json/list."""
        try:
            resp = requests.get(
                f"http://{self.host}:{self.port}/json/list",
                timeout=5,
            )
            resp.raise_for_status()
            return [t for t in resp.json() if t.get("type") == "page"]
        except Exception:
            return []

    def reconcile(self) -> None:
        """Sync persisted state with actual Chrome tabs.

        Removes entries for tabs that no longer exist.
        Adds entries for live tabs not yet tracked.
        Updates URL/title for tabs that changed.
        """
        live_tabs = self._get_live_tabs()
        if not live_tabs:
            return

        live_ids = {t["id"] for t in live_tabs}

        # Remove stale entries
        stale = [tid for tid in self._state if tid not in live_ids]
        for tid in stale:
            del self._state[tid]

        # Add/update live tabs
        now = time.time()
        for tab in live_tabs:
            tid = tab["id"]
            url = tab.get("url", "")
            title = tab.get("title", "")
            origin = self.extract_origin(url) or ""

            if tid in self._state:
                entry = self._state[tid]
                entry.url = url
                entry.title = title
                if origin:
                    entry.origin = origin
            else:
                self._state[tid] = TabEntry(
                    tab_id=tid,
                    origin=origin,
                    url=url,
                    title=title,
                    last_activity=now,
                    created_at=now,
                )

        self._save_state()

    # --- Core Routing Logic ---

    def find_tab_by_origin(self, origin: str) -> Optional[TabEntry]:
        """Find the most recently used tab matching the given origin."""
        candidates = [
            e for e in self._state.values() if e.origin == origin
        ]
        if not candidates:
            return None
        # Return most recently active
        return max(candidates, key=lambda e: e.last_activity)

    def get_or_create_tab(self, url: str, session) -> str:
        """Main routing method: return target_id for the given URL.

        1. Extract origin from URL
        2. If unroutable, return current/first tab (no routing)
        3. Find existing tab with same origin → activate & return
        4. If at capacity, evict LRU tab
        5. Create new tab → return new target_id
        """
        origin = self.extract_origin(url)

        if origin is None:
            # Unroutable URL — use whatever tab is currently connected
            live = self._get_live_tabs()
            return live[0]["id"] if live else ""

        existing = self.find_tab_by_origin(origin)
        if existing:
            existing.touch()
            try:
                session.target.activate_target(existing.tab_id)
            except Exception:
                pass
            self._save_state()
            return existing.tab_id

        # Need a new tab — evict if at capacity
        if len(self._state) >= MAX_TABS:
            self._evict_lru_tab(session)

        target_id = session.target.create_target(url)
        now = time.time()
        self._state[target_id] = TabEntry(
            tab_id=target_id,
            origin=origin,
            url=url,
            title="",
            last_activity=now,
            created_at=now,
        )
        self._save_state()
        return target_id

    # --- LRU Eviction ---

    def _evict_lru_tab(self, session) -> Optional[str]:
        """Close and remove the least recently used tab."""
        if not self._state:
            return None

        lru = min(self._state.values(), key=lambda e: e.last_activity)
        try:
            session.target.close_target(lru.tab_id)
        except Exception:
            self.logger.debug(f"Failed to close LRU tab {lru.tab_id}")
        del self._state[lru.tab_id]
        self._save_state()
        return lru.tab_id

    # --- Tab Tracking ---

    def track_tab(self, tab_id: str, url: str, title: str = "") -> None:
        origin = self.extract_origin(url) or ""
        now = time.time()
        if tab_id in self._state:
            entry = self._state[tab_id]
            entry.url = url
            entry.title = title or entry.title
            if origin:
                entry.origin = origin
            entry.touch()
        else:
            self._state[tab_id] = TabEntry(
                tab_id=tab_id,
                origin=origin,
                url=url,
                title=title,
                last_activity=now,
                created_at=now,
            )

    def touch_tab(self, tab_id: str) -> None:
        if tab_id in self._state:
            self._state[tab_id].touch()

    def untrack_tab(self, tab_id: str) -> None:
        self._state.pop(tab_id, None)

    # --- Query ---

    def get_tracked_tabs(self) -> List[TabEntry]:
        """All tracked tabs sorted by last_activity descending."""
        return sorted(
            self._state.values(),
            key=lambda e: e.last_activity,
            reverse=True,
        )

    def get_tab_count(self) -> int:
        return len(self._state)

    def clear_state(self) -> None:
        """Delete all tracked state."""
        self._state.clear()
        if STATE_FILE.exists():
            STATE_FILE.unlink()
