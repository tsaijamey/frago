"""CDP-backed ChromeBackend.

Thin wrapper around :class:`frago.browser.cdp.session.CDPSession` + TabGroupManager.
Preserves existing behavior for callers that go through the adapter.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    MAX_TABS_PER_GROUP,
    ChromeBackend,
    ClickResult,
    ContentResult,
    ExecResult,
    NavigateResult,
    ScreenshotResult,
)


class CDPChromeBackend(ChromeBackend):
    name = "cdp"

    def __init__(self, *, host: str = "127.0.0.1", port: int = 9222,
                 timeout: float = 30.0, debug: bool = False) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.debug = debug

    # --- internals -----------------------------------------------------

    def _session(self, group: str) -> Any:
        from ..cdp.config import CDPConfig
        from ..cdp.session import CDPSession
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        target_id = tgm.get_current_target(group)
        cfg = CDPConfig(host=self.host, port=self.port,
                        timeout=self.timeout, debug=self.debug,
                        target_id=target_id)
        return CDPSession(cfg)

    # --- ChromeBackend -------------------------------------------------

    def start(self) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        return {"backend": "cdp", "host": self.host, "port": self.port,
                "groups": list(tgm.list_groups()) if hasattr(tgm, "list_groups") else []}

    def navigate(self, url: str, group: str, *,
                 timeout: float = 15.0,  # noqa: ARG002 — backend interface param
                 new: bool = False) -> NavigateResult:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.ensure_group(group)
        # A fresh session on the group's current tab; creating the tab
        # needs a session with TargetCommands, which _session() gives us.
        target_id = tgm.get_or_create_tab(url, group, self._session(group),
                                          new=new)
        cfg_session = self._session_from_target(target_id)
        cfg_session.navigate(url)
        title = cfg_session.get_title() if hasattr(cfg_session, "get_title") else ""
        state = tgm.get_group(group)
        return NavigateResult(
            tab_id=target_id, url=url, title=title, group=group,
            opened_new=bool(new),
            tabs_in_group=len(state.tabs) if state else None,
            tab_limit=state.max_tabs if state else MAX_TABS_PER_GROUP,
        )

    def _session_from_target(self, target_id: str) -> Any:
        from ..cdp.config import CDPConfig
        from ..cdp.session import CDPSession
        cfg = CDPConfig(host=self.host, port=self.port,
                        timeout=self.timeout, debug=self.debug,
                        target_id=target_id)
        return CDPSession(cfg)

    def exec_js(self, script: str, group: str) -> ExecResult:
        s = self._session(group)
        return ExecResult(value=s.evaluate(script, return_by_value=True))

    def get_content(self, group: str, *,
                    selector: str | None = None) -> ContentResult:
        s = self._session(group)
        if selector:
            js = (f"(() => {{ const el = document.querySelector({selector!r}); "
                  f"return el ? {{text: el.innerText, html: el.outerHTML}} : null; }})()")
        else:
            js = ("(() => ({text: document.body.innerText, "
                  "html: document.body.outerHTML}))()")
        raw = s.evaluate(js, return_by_value=True) or {}
        return ContentResult(
            text=raw.get("text", "") if isinstance(raw, dict) else "",
            html=raw.get("html", "") if isinstance(raw, dict) else "",
            title=s.get_title() if hasattr(s, "get_title") else "",
        )

    def click(self, selector: str, group: str) -> ClickResult:
        s = self._session(group)
        s.click(selector)
        return ClickResult(success=True)

    def screenshot(self, group: str, *,
                   output: str | None = None) -> ScreenshotResult:
        s = self._session(group)
        out = output or str(Path.cwd() / "screenshot.png")
        s.take_screenshot(out)
        return ScreenshotResult(path=out)

    # ─── Batch 1: tab management + simple element ops ─────────────────

    def stop(self) -> dict:
        from ..cdp.launcher import ChromeLauncher
        from ..cdp.process import kill_existing_chrome
        launcher = ChromeLauncher(port=self.port)
        killed = kill_existing_chrome(launcher.debugging_port)
        return {"backend": "cdp", "stopped": killed > 0,
                "processes_killed": killed}

    def status(self) -> dict:
        import requests
        try:
            resp = requests.get(f"http://{self.host}:{self.port}/json/version",
                                timeout=5)
            return {"backend": "cdp", "ok": resp.ok,
                    "chrome": resp.json() if resp.ok else None}
        except Exception as e:
            return {"backend": "cdp", "ok": False, "error": str(e)}

    def list_tabs(self, group: str) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.reconcile()
        g = tgm.get_group(group)
        if not g:
            raise RuntimeError(
                f"group '{group}' does not exist — navigate first")
        return {
            "group": group,
            "tabs": [{"tab_id": t.target_id, "title": t.title, "url": t.url,
                      "current": t.target_id == g.current_target_id}
                     for t in tgm.get_group_tabs(group)],
            "current": g.current_target_id,
            "count": len(g.tabs),
            "limit": g.max_tabs,
        }

    def switch_tab(self, group: str, tab_id: str, *,
                   activate: bool = False) -> dict:
        import json

        import requests
        import websocket

        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        full = tgm.switch_tab(group, str(tab_id))
        if activate:
            targets = requests.get(
                f"http://{self.host}:{self.port}/json/list", timeout=5).json()
            target = next((t for t in targets if t.get("id") == full), None)
            if target and target.get("webSocketDebuggerUrl"):
                ws = websocket.create_connection(
                    target["webSocketDebuggerUrl"])
                ws.send(json.dumps({"id": 1, "method": "Page.bringToFront",
                                    "params": {}}))
                ws.recv()
                ws.close()
        return {"group": group, "tab_id": full, "current": True,
                "activated": bool(activate)}

    def close_tab(self, group: str, tab_id: str) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        full = tgm.close_tab(group, str(tab_id), self._session(group))
        g = tgm.get_group(group)
        return {"group": group, "tab_id": full, "closed": True,
                "remaining": len(g.tabs) if g else 0,
                "current": g.current_target_id if g else None}

    def list_groups(self) -> dict:
        import time

        from ..cdp.tab_group_manager import (
            GROUP_TIMEOUT_SECONDS,
            TabGroupManager,
        )
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.reconcile()
        now = time.time()
        return {name: {"tabs": len(g.tabs),
                       "current": g.current_target_id,
                       "limit": g.max_tabs,
                       "created_at": g.created_at,
                       "last_activity": g.last_activity,
                       "idle_seconds": int(now - g.last_activity),
                       "expires_in_seconds": max(
                           0, int(g.last_activity + GROUP_TIMEOUT_SECONDS - now)),
                       "agent_session": g.agent_session}
                for name, g in tgm.list_groups().items()}

    def group_info(self, name: str) -> dict:
        import time

        from ..cdp.tab_group_manager import (
            GROUP_TIMEOUT_SECONDS,
            TabGroupManager,
        )
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.reconcile()
        g = tgm.get_group(name)
        if not g:
            return {}
        now = time.time()
        return {"name": name, "agent_session": g.agent_session,
                "created_at": g.created_at,
                "last_activity": g.last_activity,
                "idle_seconds": int(now - g.last_activity),
                "expires_in_seconds": max(
                    0, int(g.last_activity + GROUP_TIMEOUT_SECONDS - now)),
                "current": g.current_target_id,
                "count": len(g.tabs), "limit": g.max_tabs,
                "tabs": [{"tab_id": t.target_id, "title": t.title,
                          "url": t.url, "origin": t.origin,
                          "current": t.target_id == g.current_target_id}
                         for t in tgm.get_group_tabs(name)]}

    def group_close(self, name: str) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        ok = tgm.close_group(name, self._session(name)) \
            if tgm.get_group(name) else False
        return {"name": name, "closed": bool(ok)}

    def group_cleanup(self) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        removed = tgm.cleanup_stale_groups()
        return {"removed": removed}

    def reset(self, group: str | None = None) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        closed = []
        if group:
            if tgm.get_group(group):
                tgm.close_group(group, self._session(group))
                closed.append(group)
        else:
            for name in list(tgm.list_groups().keys()):
                tgm.close_group(name, self._session(name))
                closed.append(name)
        return {"group": group, "closed": closed}

    def scroll(self, distance: int, group: str, *,
               activate: bool = False) -> dict:
        """Scroll and report the measured movement, mirroring the
        extension backend's contract.

        ``activate`` is accepted for signature parity and ignored: a
        CDP-driven tab has no "active tab of its window" notion to fix
        up — see the visibility note in the extension backend.
        """
        del activate
        s = self._session(group)
        dist = int(distance)
        # 单趟往返里读前值、滚、等动画稳定、读后值。平滑滚动的站点
        # 滚完立刻读会读到中途值，这里轮询到位置不再变化为止。
        js = f"""
        (async () => {{
            const doc = document.documentElement;
            const read = () => ({{
                y: Math.round(window.scrollY),
                max: Math.round(Math.max(
                    0, doc.scrollHeight - window.innerHeight)),
            }});
            const y0 = read().y;
            window.scrollBy(0, {dist});
            let prev = -1, cur = read();
            for (let i = 0; i < 15 && cur.y !== prev; i++) {{
                prev = cur.y;
                await new Promise(r => setTimeout(r, 100));
                cur = read();
            }}
            return JSON.stringify({{y0, y: cur.y, max: cur.max,
                                    hidden: document.hidden}});
        }})()
        """
        # Runtime.evaluate 这一层已固定 awaitPromise=True，异步表达式
        # 会等 resolve 后再回值。
        raw = s.evaluate(js, return_by_value=True)
        try:
            import json as _json
            r = _json.loads(raw if isinstance(raw, str) else str(raw))
        except Exception:
            return {"requested": dist, "scrolled": None,
                    "note": f"unparsable evaluate result: {raw!r}"}
        return {"requested": dist, "scrolled": r["y"] - r["y0"],
                "y": r["y"], "max_y": r["max"],
                "at_bottom": r["max"] - r["y"] <= 2,
                "hidden": r["hidden"], "activated": False}

    def scroll_to(self, group: str, *, selector: str | None = None,
                  text: str | None = None, block: str = "center",
                  activate: bool = False) -> dict:
        del activate  # signature parity; see scroll()
        if not selector and not text:
            raise ValueError("scroll_to: selector or text required")
        import json
        s = self._session(group)
        if text:
            js = (f"(()=>{{const t={json.dumps(text)};"
                  "const w=document.createTreeWalker(document.body,"
                  "NodeFilter.SHOW_TEXT,{acceptNode:n=>"
                  "n.textContent.includes(t)?NodeFilter.FILTER_ACCEPT"
                  ":NodeFilter.FILTER_REJECT});const n=w.nextNode();"
                  "if(n&&n.parentElement){n.parentElement."
                  f"scrollIntoView({{behavior:'smooth',block:{json.dumps(block)}"
                  "});return 'success';}return 'element not found';})()")
        else:
            js = (f"(()=>{{const el=document.querySelector({json.dumps(selector)});"
                  f"if(el){{el.scrollIntoView({{behavior:'smooth',block:"
                  f"{json.dumps(block)}}});return 'success';}}"
                  "return 'element not found';})()")
        r = s.evaluate(js, return_by_value=True)
        if r != "success":
            raise RuntimeError(r or "scroll_to failed")
        return {"success": True}

    def zoom(self, factor: float, group: str) -> dict:
        s = self._session(group)
        s.evaluate(f"document.body.style.zoom = '{float(factor)}'",
                   return_by_value=True)
        return {"factor": float(factor)}

    def get_title(self, group: str) -> str:
        s = self._session(group)
        return s.get_title() if hasattr(s, "get_title") else ""
