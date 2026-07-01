"""
CDP session implementation

Implements CDP session management with WebSocket connections.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from frago.chrome.cdp.commands.dom import DOMCommands
    from frago.chrome.cdp.commands.input import InputCommands
    from frago.chrome.cdp.commands.page import PageCommands
    from frago.chrome.cdp.commands.runtime import RuntimeCommands
    from frago.chrome.cdp.commands.screenshot import ScreenshotCommands
    from frago.chrome.cdp.commands.scroll import ScrollCommands
    from frago.chrome.cdp.commands.status import StatusCommands
    from frago.chrome.cdp.commands.target import TargetCommands
    from frago.chrome.cdp.commands.visual_effects import VisualEffectsCommands
    from frago.chrome.cdp.commands.wait import WaitCommands
    from frago.chrome.cdp.commands.zoom import ZoomCommands

from .client import CDPClient
from .config import CDPConfig
from .exceptions import CDPError
from .transport import CDPTransport, cdp_get

# Lazy import to avoid circular imports
# from .commands import PageCommands, InputCommands, RuntimeCommands, DOMCommands


class CDPSession(CDPClient):
    """CDP session class.

    Facade over a :class:`CDPTransport` (WebSocket transport / request
    forwarding / event multiplexing) plus the lazy-loaded command wrappers.
    Transport-level operations (connect/disconnect/send_command/on_event) are
    delegated to the transport; the convenience CLI methods and lazy properties
    live here.
    """

    def __init__(self, config: Optional[CDPConfig] = None):
        """
        Initialize CDP session

        Args:
            config: CDP configuration, uses default config if None
        """
        super().__init__(config)
        self._transport = CDPTransport(self.config, self.logger)

        # Lazy initialization of command wrappers
        self._page: PageCommands | None = None
        self._input: InputCommands | None = None
        self._runtime: RuntimeCommands | None = None
        self._dom: DOMCommands | None = None
        self._screenshot: ScreenshotCommands | None = None
        self._scroll: ScrollCommands | None = None
        self._wait: WaitCommands | None = None
        self._zoom: ZoomCommands | None = None
        self._status: StatusCommands | None = None
        self._visual_effects: VisualEffectsCommands | None = None
        self._target: TargetCommands | None = None

        # Auto viewport border indicator
        self.auto_viewport_border = True

    # ── Transport delegation ──────────────────────────────────────────────
    @property
    def connected(self) -> bool:
        """Check if connected (delegated to transport)"""
        return self._transport.connected

    @property
    def ws(self):
        """Underlying WebSocket connection (delegated to transport)"""
        return self._transport.ws

    def connect(self) -> None:
        """Establish WebSocket connection (delegated to transport)"""
        self._transport.connect()

    def disconnect(self) -> None:
        """Disconnect WebSocket connection (delegated to transport)"""
        self._transport.disconnect()

    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send CDP command (delegated to transport)"""
        return self._transport.send_command(method, params)

    def on_event(self, event_name: str) -> Callable:
        """Register a CDP event handler (delegated to transport)"""
        return self._transport.on_event(event_name)

    def health_check(self) -> bool:
        """
        Perform connection health check

        Returns:
            bool: Whether connection is healthy
        """
        if not self.connected:
            return False

        try:
            # Send a simple ping command to check connection
            result = self.send_command("Runtime.evaluate", {
                "expression": "1",
                "returnByValue": True
            })
            return "result" in result
        except Exception as e:
            self.logger.warning(f"Health check failed: {e}")
            return False

    # Landing page detection
    def get_landing_page_target_id(self) -> Optional[str]:
        """Identify the landing page tab by URL or title.

        Returns target_id of the landing page, or None if not found.
        """
        try:
            response = cdp_get(
                f"{self.config.http_url}/json/list",
                timeout=5,
            )
            response.raise_for_status()
            for target in response.json():
                if target.get("type") != "page":
                    continue
                url = target.get("url", "")
                title = target.get("title", "")
                if "/chrome/dashboard" in url or title == "frago":
                    return target.get("id")
        except Exception:
            pass
        return None

    # CLI convenience methods
    def navigate(self, url: str) -> None:
        """Navigate to specified URL"""
        self.page.navigate(url)

    def click(self, selector: str, wait_timeout: int = 10) -> None:
        """JS-first click with automatic fallback to coordinate-based click.

        1. Inject document capture-phase listener
        2. Execute JS element.click()
        3. Check if listener received the event
        4. If not → fallback to dispatchMouseEvent via click_precise()
        """
        self.page.wait_for_selector(selector, timeout=wait_timeout)

        # JS click + capture-phase detection (single Runtime.evaluate call)
        result = self.evaluate("""
            (function(sel) {
                var el = document.querySelector(sel);
                if (!el) return 'not_found';
                var reached = false;
                document.addEventListener('click', function() { reached = true }, {capture: true, once: true});
                el.scrollIntoView({block: 'center', behavior: 'instant'});
                el.click();
                return reached ? 'ok' : 'blocked';
            })
        """ + f"({json.dumps(selector)})", return_by_value=True)

        if result == 'ok':
            return
        if result == 'not_found':
            raise CDPError(f"Element not found: {selector}")
        # 'blocked' → fallback to coordinate-based click
        self.click_precise(selector, wait_timeout=0)  # already waited

    def click_precise(self, selector: str, wait_timeout: int = 10) -> None:
        """Coordinate-based click via getBoxModel + dispatchMouseEvent.

        Use this for scenarios requiring pixel-level accuracy (canvas clicks, etc.).
        Note: dispatchMouseEvent does NOT generate DOM events on Wayland Native Chrome.
        """
        if wait_timeout > 0:
            self.page.wait_for_selector(selector, timeout=wait_timeout)

        result = self.dom.get_document()
        node_id = result.get("result", {}).get("root", {}).get("nodeId")

        if not node_id:
            raise CDPError("Unable to get document node")

        query_result = self.dom.query_selector(node_id, selector)
        element_node_id = query_result.get("result", {}).get("nodeId")

        if not element_node_id:
            raise CDPError(f"Element not found: {selector}")

        box_model = self.dom.get_box_model(element_node_id)
        content = box_model.get("result", {}).get("model", {}).get("content", [])

        if not content:
            raise CDPError(f"Cannot get element position: {selector}")

        x = (content[0] + content[2]) / 2
        y = (content[1] + content[5]) / 2

        self.input.click(x, y)

    def take_screenshot(self, output_file: str, full_page: bool = False, quality: int = 80) -> None:
        """Capture page screenshot and save to file (convenience method)"""
        # Delegate to screenshot commands
        self.screenshot.capture(output_file, full_page=full_page, quality=quality)

    def evaluate(self, script: str, return_by_value: bool = True) -> Any:
        """Execute JavaScript"""
        response = self.runtime.evaluate(script, return_by_value=return_by_value)
        # CDP return format: {'id': ..., 'result': {'result': {'value': ...}}}
        if return_by_value and response:
            result = response.get("result", {})
            if "result" in result:
                return result["result"].get("value")
        return response

    def get_title(self) -> str:
        """Get page title"""
        result = self.evaluate("document.title")
        return result or ""

    def scroll(self, distance: int) -> None:
        """Scroll page"""
        self.evaluate(f"window.scrollBy(0, {distance})")

    def wait(self, seconds: float) -> None:
        """Wait for specified seconds"""
        import time
        time.sleep(seconds)

    def zoom(self, factor: float) -> None:
        """Set page zoom factor"""
        self.evaluate(f"document.body.style.zoom = '{factor}'")

    def clear_effects(self) -> None:
        """Clear all visual effects"""
        self.evaluate("""
            // Clear element styles
            document.querySelectorAll('[data-frago-highlight], [style*="pointer"], [style*="spotlight"]').forEach(el => {
                el.style.removeProperty('background-color');
                el.style.removeProperty('border');
                el.style.removeProperty('outline');
                el.style.removeProperty('box-shadow');
                el.style.removeProperty('cursor');
                el.style.removeProperty('z-index');
                el.style.removeProperty('position');
                el.removeAttribute('data-frago-highlight');
            });
            // Remove frago-added DOM elements (annotate, underline, pointer, etc.)
            document.querySelectorAll('.frago-underline, .frago-annotation, #frago-pointer, #frago-underline-style').forEach(el => el.remove());
        """)

    def highlight(self, selector: str, color: str = "magenta", border_width: int = 3, lifetime: int = 5000) -> None:
        """
        Highlight specified element

        Args:
            selector: CSS selector
            color: Highlight color, default magenta
            border_width: Border width (pixels), default 3
            lifetime: Effect duration (milliseconds), 0 means permanent
        """
        self.evaluate(f"""
            (function() {{
                document.querySelectorAll('{selector}').forEach(el => {{
                    el.style.border = '{border_width}px solid {color}';
                    el.style.outline = '{border_width}px solid {color}';
                    el.setAttribute('data-frago-highlight', 'true');
                    if ({lifetime} > 0) {{
                        setTimeout(() => {{
                            el.style.removeProperty('border');
                            el.style.removeProperty('outline');
                            el.removeAttribute('data-frago-highlight');
                        }}, {lifetime});
                    }}
                }});
                return true;
            }})()
        """, return_by_value=True)

    def pointer(self, selector: str, lifetime: int = 5000) -> None:
        """Display mouse pointer on element"""
        self.evaluate(f"""
            document.querySelectorAll('{selector}').forEach(el => {{
                el.style.cursor = 'pointer';
                el.style.boxShadow = '0 0 10px magenta';
                el.setAttribute('data-frago-pointer', 'true');
                if ({lifetime} > 0) {{
                    setTimeout(() => {{
                        el.style.removeProperty('cursor');
                        el.style.removeProperty('boxShadow');
                        el.removeAttribute('data-frago-pointer');
                    }}, {lifetime});
                }}
            }});
        """)

    def spotlight(self, selector: str, lifetime: int = 5000) -> None:
        """Spotlight effect to highlight element, auto-fades using CSS animation"""
        lifetime_sec = lifetime / 1000
        # Hold time ratio: hold 90%, fade out in last 10%
        hold_percent = 90
        self.evaluate(f"""
            (function() {{
                // Inject keyframes animation
                if (!document.getElementById('frago-spotlight-style')) {{
                    const style = document.createElement('style');
                    style.id = 'frago-spotlight-style';
                    style.textContent = `
                        @keyframes frago-spotlight-fade {{
                            0% {{ box-shadow: 0 0 20px magenta; }}
                            {hold_percent}% {{ box-shadow: 0 0 20px magenta; }}
                            100% {{ box-shadow: none; }}
                        }}
                    `;
                    document.head.appendChild(style);
                }}

                document.querySelectorAll('{selector}').forEach(el => {{
                    el.style.zIndex = '9999';
                    el.style.position = 'relative';
                    el.setAttribute('data-frago-spotlight', 'true');

                    if ({lifetime} > 0) {{
                        el.style.animation = 'frago-spotlight-fade {lifetime_sec}s forwards';
                        el.addEventListener('animationend', function handler() {{
                            el.style.removeProperty('animation');
                            el.style.removeProperty('zIndex');
                            el.style.removeProperty('position');
                            el.removeAttribute('data-frago-spotlight');
                            el.removeEventListener('animationend', handler);
                        }});
                    }} else {{
                        el.style.boxShadow = '0 0 20px magenta';
                    }}
                }});
            }})();
        """)

    def annotate(self, selector: str, text: str, position: str = "top", lifetime: int = 5000) -> None:
        """Add annotation on element"""
        self.evaluate(f"""
            document.querySelectorAll('{selector}').forEach(el => {{
                const annotation = document.createElement('div');
                annotation.className = 'frago-annotation';
                annotation.textContent = '{text}';
                annotation.style.position = 'absolute';
                annotation.style.background = 'magenta';
                annotation.style.color = 'white';
                annotation.style.padding = '5px 8px';
                annotation.style.borderRadius = '3px';
                annotation.style.fontSize = '12px';
                annotation.style.fontWeight = 'bold';
                annotation.style.zIndex = '10000';

                const rect = el.getBoundingClientRect();
                switch('{position}') {{
                    case 'top':
                        annotation.style.top = (rect.top + window.scrollY - 30) + 'px';
                        annotation.style.left = rect.left + 'px';
                        break;
                    case 'bottom':
                        annotation.style.top = (rect.bottom + window.scrollY + 5) + 'px';
                        annotation.style.left = rect.left + 'px';
                        break;
                    case 'left':
                        annotation.style.top = rect.top + window.scrollY + 'px';
                        annotation.style.left = (rect.left - 150) + 'px';
                        break;
                    case 'right':
                        annotation.style.top = rect.top + window.scrollY + 'px';
                        annotation.style.left = (rect.right + 5) + 'px';
                        break;
                }}

                document.body.appendChild(annotation);
                if ({lifetime} > 0) {{
                    setTimeout(() => annotation.remove(), {lifetime});
                }}
            }});
        """)

    def underline(self, selector: str, color: str = "magenta", width: int = 3, duration: int = 1000) -> None:
        """
        Draw animated underlines under element text, line by line

        Args:
            selector: CSS selector
            color: Line color, default magenta
            width: Line width (pixels), default 3
            duration: Total animation duration (milliseconds), default 1000
        """
        self.evaluate(f"""
            (function() {{
                const elements = document.querySelectorAll('{selector}');
                elements.forEach(el => {{
                    // Use Range to get line positions
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    const allRects = Array.from(range.getClientRects());

                    // Merge rectangles on same line (by top value)
                    const lineMap = new Map();
                    allRects.forEach(rect => {{
                        if (rect.width <= 0 || rect.height <= 0) return;
                        const topKey = Math.round(rect.top);
                        if (lineMap.has(topKey)) {{
                            const existing = lineMap.get(topKey);
                            existing.left = Math.min(existing.left, rect.left);
                            existing.right = Math.max(existing.right, rect.right);
                            existing.bottom = Math.max(existing.bottom, rect.bottom);
                        }} else {{
                            lineMap.set(topKey, {{
                                left: rect.left,
                                right: rect.right,
                                bottom: rect.bottom,
                                top: rect.top
                            }});
                        }}
                    }});

                    // Convert to sorted array
                    const lines = Array.from(lineMap.values())
                        .map(l => ({{ left: l.left, top: l.bottom, width: l.right - l.left }}))
                        .sort((a, b) => a.top - b.top);

                    if (lines.length === 0) return;

                    // Calculate per-line animation duration
                    const perLineDuration = {duration} / lines.length;

                    // Create underline for each line (show full width immediately)
                    lines.forEach((line, index) => {{
                        const underline = document.createElement('div');
                        underline.className = 'frago-underline';
                        underline.style.position = 'fixed';
                        underline.style.left = line.left + 'px';
                        underline.style.top = line.top + 'px';
                        underline.style.width = line.width + 'px';
                        underline.style.height = '{width}px';
                        underline.style.backgroundColor = '{color}';
                        underline.style.zIndex = '999999';
                        underline.style.pointerEvents = 'none';
                        document.body.appendChild(underline);
                    }});
                }});
            }})();
        """)

    def viewport_border(self, color: str = "80, 200, 120", duration: float = 3.0) -> None:
        """
        Display a breathing gradient border around the viewport to indicate automation control.

        Args:
            color: RGB color values (e.g., "80, 200, 120" for green)
            duration: Breathing animation cycle duration in seconds
        """
        self.visual_effects.viewport_border(color=color, duration=duration)

    def clear_viewport_border(self) -> None:
        """Remove the viewport border indicator."""
        self.visual_effects.clear_viewport_border()

    def wait_for_selector(self, selector: str, timeout: Optional[float] = None) -> None:
        """Wait for element matching selector"""
        self.page.wait_for_selector(selector, timeout=timeout)

    def wait_for_load(self, timeout: float = 30) -> bool:
        """Wait for page to finish loading"""
        result = self.page.wait_for_load(timeout=timeout)
        # Auto-inject viewport border after page load if enabled
        if self.auto_viewport_border:
            self.viewport_border()
        return result

    # Lazy-loaded property accessors for command classes
    @property
    def page(self):
        if self._page is None:
            from .commands.page import PageCommands
            self._page = PageCommands(self)
        return self._page

    @property
    def input(self):
        if self._input is None:
            from .commands.input import InputCommands
            self._input = InputCommands(self)
        return self._input

    @property
    def runtime(self):
        if self._runtime is None:
            from .commands.runtime import RuntimeCommands
            self._runtime = RuntimeCommands(self)
        return self._runtime

    @property
    def dom(self):
        if self._dom is None:
            from .commands.dom import DOMCommands
            self._dom = DOMCommands(self)
        return self._dom
    
    @property
    def screenshot(self):
        if self._screenshot is None:
            from .commands.screenshot import ScreenshotCommands
            self._screenshot = ScreenshotCommands(self)
        return self._screenshot
    
    @property
    def scroll(self):
        if self._scroll is None:
            from .commands.scroll import ScrollCommands
            self._scroll = ScrollCommands(self)
        return self._scroll
    
    @property
    def wait(self):
        if self._wait is None:
            from .commands.wait import WaitCommands
            self._wait = WaitCommands(self)
        return self._wait
    
    @property
    def zoom(self):
        if self._zoom is None:
            from .commands.zoom import ZoomCommands
            self._zoom = ZoomCommands(self)
        return self._zoom
    
    @property
    def status(self):
        if self._status is None:
            from .commands.status import StatusCommands
            self._status = StatusCommands(self)
        return self._status
    
    @property
    def visual_effects(self):
        if self._visual_effects is None:
            from .commands.visual_effects import VisualEffectsCommands
            self._visual_effects = VisualEffectsCommands(self)
        return self._visual_effects

    @property
    def target(self):
        if self._target is None:
            from .commands.target import TargetCommands
            self._target = TargetCommands(self)
        return self._target