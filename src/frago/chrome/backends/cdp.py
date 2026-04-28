"""CDP-backed ChromeBackend.

Thin wrapper around :class:`frago.chrome.cdp.session.CDPSession` + TabGroupManager.
Preserves existing behavior for callers that go through the adapter.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional

from .base import (
    ChromeBackend, ClickResult, ContentResult, ExecResult,
    NavigateResult, ScreenshotResult,
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
        from ..cdp.session import CDPSession
        from ..cdp.config import CDPConfig
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
                 timeout: float = 15.0) -> NavigateResult:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.ensure_group(group)
        target_id = tgm.get_or_create_tab(url, group, group)
        cfg_session = self._session_from_target(target_id)
        cfg_session.navigate(url)
        title = cfg_session.get_title() if hasattr(cfg_session, "get_title") else ""
        return NavigateResult(tab_id=target_id, url=url, title=title)

    def _session_from_target(self, target_id: str) -> Any:
        from ..cdp.session import CDPSession
        from ..cdp.config import CDPConfig
        cfg = CDPConfig(host=self.host, port=self.port,
                        timeout=self.timeout, debug=self.debug,
                        target_id=target_id)
        return CDPSession(cfg)

    def exec_js(self, script: str, group: str) -> ExecResult:
        s = self._session(group)
        return ExecResult(value=s.evaluate(script, return_by_value=True))

    def get_content(self, group: str, *,
                    selector: Optional[str] = None) -> ContentResult:
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
                   output: Optional[str] = None) -> ScreenshotResult:
        s = self._session(group)
        out = output or str(Path.cwd() / "screenshot.png")
        s.take_screenshot(out)
        return ScreenshotResult(path=out)

    # ─── Batch 1: tab management + simple element ops ─────────────────

    def stop(self) -> dict:
        from ..cdp.commands.chrome import ChromeLauncher
        launcher = ChromeLauncher(port=self.port)
        killed = launcher.kill_existing_chrome()
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

    def list_tabs(self) -> list[dict]:
        import requests
        resp = requests.get(f"http://{self.host}:{self.port}/json/list",
                            timeout=5)
        pages = [t for t in resp.json() if t.get("type") == "page"]
        return [{"index": i, "id": p.get("id", ""),
                 "title": p.get("title", ""), "url": p.get("url", "")}
                for i, p in enumerate(pages)]

    def switch_tab(self, tab_id: str) -> dict:
        import json
        import requests
        import websocket
        targets = requests.get(f"http://{self.host}:{self.port}/json/list",
                               timeout=5).json()
        target = next((t for t in targets
                       if t.get("type") == "page"
                       and (t.get("id") == tab_id
                            or t.get("id", "").startswith(str(tab_id)))), None)
        if not target:
            raise RuntimeError(f"no matching tab: {tab_id}")
        ws = websocket.create_connection(target["webSocketDebuggerUrl"])
        ws.send(json.dumps({"id": 1, "method": "Page.bringToFront",
                            "params": {}}))
        ws.recv(); ws.close()
        return {"tab_id": target["id"], "title": target.get("title", ""),
                "url": target.get("url", "")}

    def close_tab(self, tab_id: str) -> dict:
        import requests
        # Match list-tabs CLI behavior (prefix match).
        targets = requests.get(f"http://{self.host}:{self.port}/json/list",
                               timeout=5).json()
        target = next((t for t in targets
                       if t.get("type") == "page"
                       and (t.get("id") == tab_id
                            or t.get("id", "").startswith(str(tab_id)))), None)
        if not target:
            raise RuntimeError(f"no matching tab: {tab_id}")
        requests.get(
            f"http://{self.host}:{self.port}/json/close/{target['id']}",
            timeout=5)
        return {"tab_id": target["id"], "closed": True}

    def list_groups(self) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.reconcile()
        return {name: {"tabs": len(g.tabs),
                       "created_at": g.created_at,
                       "agent_session": g.agent_session}
                for name, g in tgm.list_groups().items()}

    def group_info(self, name: str) -> dict:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=self.host, port=self.port)
        tgm.reconcile()
        g = tgm.get_group(name)
        if not g:
            return {}
        return {"name": name, "agent_session": g.agent_session,
                "created_at": g.created_at,
                "tabs": [{"id": t.target_id, "title": t.title,
                          "url": t.url, "origin": t.origin}
                         for t in g.tabs.values()]}

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

    def reset(self, group: Optional[str] = None) -> dict:
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

    def scroll(self, distance: int, group: str) -> dict:
        s = self._session(group)
        if hasattr(s, "scroll"):
            s.scroll.scroll(int(distance)) if hasattr(s.scroll, "scroll") \
                else s.scroll(int(distance))
        else:
            s.evaluate(f"window.scrollBy(0, {int(distance)})",
                       return_by_value=True)
        return {"scrolled": int(distance)}

    def scroll_to(self, group: str, *, selector: Optional[str] = None,
                  text: Optional[str] = None, block: str = "center") -> dict:
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
