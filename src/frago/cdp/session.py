"""
CDP session implementation

Implements CDP session management with WebSocket connections.
"""

import json
import uuid
import threading
import queue
import time
from typing import Dict, Any, Optional, Callable

import websocket

from .client import CDPClient
from .config import CDPConfig
from .logger import get_logger
from .exceptions import ConnectionError, TimeoutError, CDPError
from .types import CDPRequest, CDPResponse
# Lazy import to avoid circular imports
# from .commands import PageCommands, InputCommands, RuntimeCommands, DOMCommands


class CDPSession(CDPClient):
    """CDP session class"""

    def __init__(self, config: Optional[CDPConfig] = None):
        """
        Initialize CDP session

        Args:
            config: CDP configuration, uses default config if None
        """
        super().__init__(config)
        self.ws: Optional[websocket.WebSocket] = None
        self._request_id = 0
        self._pending_requests: Dict[int, Dict] = {}
        self._event_handlers: Dict[str, Callable] = {}
        self._message_queue = queue.Queue()
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.RLock()

        # Lazy initialization of command wrappers
        self._page = None
        self._input = None
        self._runtime = None
        self._dom = None
        self._screenshot = None
        self._scroll = None
        self._wait = None
        self._zoom = None
        self._status = None
        self._visual_effects = None
        self._target = None

        # Auto viewport border indicator
        self.auto_viewport_border = True

    def connect(self) -> None:
        """Establish WebSocket connection

        Performance optimizations:
        - Connection timeout defaults to 5 seconds (optimized for local connections)
        - Unnecessary handshake checks disabled to speed up connection
        - Supports fast-fail mechanism
        """
        try:
            start_time = time.time()

            # Dynamically get WebSocket URL
            ws_url = self._get_websocket_url()
            self.logger.info(f"Connecting to CDP at {ws_url}")

            # Prepare WebSocket connection options (performance optimization)
            ws_options = {
                "timeout": 1.0,  # Receive message timeout set to 1 second for periodic _running check
                "skip_utf8_validation": True,  # Skip UTF-8 validation for performance
                "enable_multithread": True      # Enable multithreading support
            }

            # Configure proxy parameters
            if self.config.proxy_host and self.config.proxy_port and not self.config.no_proxy:
                ws_options["http_proxy_host"] = self.config.proxy_host
                ws_options["http_proxy_port"] = self.config.proxy_port

                if self.config.proxy_username and self.config.proxy_password:
                    ws_options["http_proxy_auth"] = (
                        self.config.proxy_username,
                        self.config.proxy_password
                    )

                self.logger.debug(f"Using proxy: {self.config.proxy_host}:{self.config.proxy_port}")
            elif self.config.no_proxy:
                self.logger.debug("Proxy bypassed (no_proxy=True)")

            # Create WebSocket connection
            self.ws = websocket.create_connection(
                ws_url,
                **ws_options
            )

            self._connected = True
            self._running = True

            # Log connection time
            elapsed = (time.time() - start_time) * 1000  # Convert to milliseconds
            self.logger.info(f"CDP connection established in {elapsed:.2f}ms")

            # Start message listener thread
            self._start_message_listener()

        except Exception as e:
            self._connected = False
            self._running = False
            elapsed = (time.time() - start_time) * 1000
            self.logger.error(f"Connection failed after {elapsed:.2f}ms: {e}")
            raise ConnectionError(f"Failed to connect to CDP: {e}")

    def _get_websocket_url(self) -> str:
        """Dynamically get WebSocket debug URL

        If target_id is specified, connect to that tab; otherwise auto-select the first page-type tab.

        Returns:
            str: WebSocket URL
        """
        import requests
        try:
            # Get list of all targets
            # Disable proxy when no_proxy is set to avoid connection issues
            response = requests.get(
                f"{self.config.http_url}/json/list",
                timeout=self.config.connect_timeout,
                proxies={} if self.config.no_proxy else None
            )
            response.raise_for_status()
            targets = response.json()

            # If target_id specified, find the corresponding target
            if self.config.target_id:
                for target in targets:
                    if target.get('id') == self.config.target_id:
                        ws_url = target.get('webSocketDebuggerUrl')
                        if ws_url:
                            self.logger.debug(f"Using specified target: {target.get('title', 'Unknown')} (id: {self.config.target_id})")
                            return ws_url
                        else:
                            raise ConnectionError(f"Target {self.config.target_id} has no WebSocket URL available")

                # Specified target not found
                raise ConnectionError(f"Target not found: {self.config.target_id}")

            # No target_id specified, find first available page
            for target in targets:
                if target.get('type') == 'page' and target.get('webSocketDebuggerUrl'):
                    self.logger.debug(f"Using page: {target.get('title', 'Unknown')}")
                    return target['webSocketDebuggerUrl']

            # If no page available, use browser endpoint
            response = requests.get(
                f"{self.config.http_url}/json/version",
                timeout=self.config.connect_timeout,
                proxies={} if self.config.no_proxy else None
            )
            response.raise_for_status()
            version_info = response.json()
            return version_info['webSocketDebuggerUrl']
        except ConnectionError:
            # Re-raise ConnectionError, don't let it be caught by except below
            raise
        except Exception:
            # Fallback to static URL
            return self.config.websocket_url
    
    def disconnect(self) -> None:
        """Disconnect WebSocket connection"""
        # Stop message listener thread
        self._running = False

        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=5.0)

        if self.ws:
            try:
                self.ws.close()
                self.logger.info("CDP connection closed")
            except Exception as e:
                self.logger.warning(f"Error closing CDP connection: {e}")
            finally:
                self.ws = None
                self._connected = False

    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send CDP command

        Args:
            method: CDP method name
            params: Command parameters

        Returns:
            Dict[str, Any]: Command result

        Raises:
            CDPError: Command execution failed
        """
        if not self.connected:
            raise ConnectionError("CDP not connected")

        # Generate request ID
        with self._lock:
            request_id = self._request_id
            self._request_id += 1

        # Build request
        request: CDPRequest = {
            "id": request_id,
            "method": method,
            "params": params or {}
        }

        # Send request
        try:
            self.ws.send(json.dumps(request))
            self.logger.debug(f"Sent CDP command: {method} (id: {request_id})")
        except Exception as e:
            raise CDPError(f"Failed to send CDP command: {e}")

        # Wait for response
        return self._wait_for_response(request_id)
    
    def _validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate CDP response

        Args:
            response: CDP response

        Returns:
            Dict[str, Any]: Validated response

        Raises:
            CDPError: Response error
        """
        if "error" in response:
            error = response["error"]
            raise CDPError(f"CDP error: {error.get('message', 'Unknown error')} (code: {error.get('code')})")

        return response

    def _wait_for_response(self, request_id: int) -> Dict[str, Any]:
        """
        Wait for response with specified request ID

        Args:
            request_id: Request ID

        Returns:
            Dict[str, Any]: Response data

        Raises:
            TimeoutError: Timeout waiting
            CDPError: Response error
        """
        start_time = time.time()
        timeout = self.config.command_timeout

        # Register as pending request
        with self._lock:
            self._pending_requests[request_id] = {
                "start_time": start_time,
                "timeout": timeout
            }

        try:
            while time.time() - start_time < timeout:
                # Check if our response is in message queue
                try:
                    # Non-blocking get
                    message = self._message_queue.get_nowait()
                    response = json.loads(message)

                    # If this is the response we're waiting for
                    if response.get("id") == request_id:
                        return self._validate_response(response)

                    # If event, call event handler
                    elif "method" in response:
                        self._handle_event(response)

                except queue.Empty:
                    # Queue empty, sleep briefly and continue
                    time.sleep(0.01)
                    continue
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
                    continue

            raise TimeoutError(f"Command timeout after {timeout} seconds")

        finally:
            # Clean up pending request
            with self._lock:
                self._pending_requests.pop(request_id, None)
    
    def _start_message_listener(self) -> None:
        """Start message listener thread"""
        self._listener_thread = threading.Thread(
            target=self._message_listener,
            daemon=True,
            name="CDPMessageListener"
        )
        self._listener_thread.start()

    def _message_listener(self) -> None:
        """Message listener thread main loop"""
        while self._running and self.ws:
            try:
                # Receive message
                message = self.ws.recv()

                # Put into queue
                self._message_queue.put(message)

            except websocket.WebSocketConnectionClosedException:
                self.logger.warning("WebSocket connection closed")
                break
            except websocket.WebSocketTimeoutException:
                # Timeout is normal, used for periodic _running check, not an error
                continue
            except Exception as e:
                self.logger.error(f"Message listener error: {e}")
                # Brief sleep before continuing
                time.sleep(0.1)

    def _handle_event(self, event: Dict[str, Any]) -> None:
        """
        Handle CDP event

        Args:
            event: Event data
        """
        method = event.get("method")
        params = event.get("params", {})

        if method in self._event_handlers:
            try:
                self._event_handlers[method](params)
            except Exception as e:
                self.logger.error(f"Error in event handler for {method}: {e}")

    def on_event(self, event_name: str) -> Callable:
        """
        Event handler decorator

        Args:
            event_name: Event name

        Returns:
            Callable: Decorator function
        """
        def decorator(handler: Callable) -> Callable:
            self._event_handlers[event_name] = handler
            return handler
        return decorator

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

    # CLI convenience methods
    def navigate(self, url: str) -> None:
        """Navigate to specified URL"""
        self.page.navigate(url)

    def click(self, selector: str, wait_timeout: int = 10) -> None:
        """Click element matching selector"""
        # Wait for element first
        self.page.wait_for_selector(selector, timeout=wait_timeout)

        # Get element position and click
        result = self.dom.get_document()
        # CDP return format: {"id": ..., "result": {"root": {...}}}
        node_id = result.get("result", {}).get("root", {}).get("nodeId")

        if not node_id:
            raise CDPError("Unable to get document node")

        query_result = self.dom.query_selector(node_id, selector)
        # CDP return format: {"id": ..., "result": {"nodeId": ...}}
        element_node_id = query_result.get("result", {}).get("nodeId")

        if not element_node_id:
            raise CDPError(f"Element not found: {selector}")

        box_model = self.dom.get_box_model(element_node_id)
        # CDP return format: {"id": ..., "result": {"model": {"content": [...]}}}
        content = box_model.get("result", {}).get("model", {}).get("content", [])

        if not content:
            raise CDPError(f"Cannot get element position: {selector}")

        # Calculate element center
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

    def viewport_border(self, color: str = "255, 180, 0", duration: float = 3.0) -> None:
        """
        Display a breathing gradient border around the viewport to indicate automation control.

        Args:
            color: RGB color values (e.g., "255, 180, 0" for yellow)
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