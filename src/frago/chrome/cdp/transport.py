"""CDP transport primitives: proxy-bypassed HTTP/WebSocket for local CDP endpoints.

CDP endpoints live on localhost. If HTTP_PROXY / HTTPS_PROXY is set (common
with v2rayA / clash / ssh -D setups), Python's requests and websocket-client
route even localhost through the proxy and fail with opaque 404/502/handshake
errors. Every CDP caller MUST go through this module so the proxy-bypass
policy lives in one place.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, Optional

import requests
import websocket

if TYPE_CHECKING:
    from .config import CDPConfig

from .exceptions import CDPError, ConnectionError, TimeoutError
from .types import CDPRequest

# trust_env=False skips HTTP_PROXY / HTTPS_PROXY / NO_PROXY entirely,
# so a shared Session is safe regardless of the user's shell env.
_session = requests.Session()
_session.trust_env = False

# websocket-client ≤1.9 reads HTTP_PROXY/HTTPS_PROXY from env unconditionally:
# http_no_proxy=["*"] and http_proxy_host=None at the parameter level do NOT
# override it. The only reliable bypass is to remove those env vars for the
# duration of the handshake. _WS_ENV_LOCK keeps concurrent callers from
# racing on os.environ mutation.
_WS_ENV_LOCK = threading.Lock()
_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "WS_PROXY", "ws_proxy",
)


@contextmanager
def _scrub_proxy_env():
    with _WS_ENV_LOCK:
        saved = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
        try:
            yield
        finally:
            os.environ.update(saved)


def cdp_get(url: str, *, timeout: float = 5.0, **kwargs: Any) -> requests.Response:
    """GET a CDP HTTP endpoint. Proxy env vars are always bypassed."""
    return _session.get(url, timeout=timeout, **kwargs)


def cdp_ws_connect(ws_url: str, *, timeout: float = 5.0, **options: Any) -> websocket.WebSocket:
    """Open a CDP WebSocket. Proxy env vars are always bypassed."""
    options.setdefault("timeout", timeout)
    with _scrub_proxy_env():
        return websocket.create_connection(ws_url, **options)


class CDPTransport:
    """Session-level CDP transport: WebSocket lifecycle, request forwarding, and
    event multiplexing.

    Owns the WebSocket connection plus the listener thread that drains incoming
    frames into a queue. Command responses are matched by request id; everything
    else is dispatched to registered event handlers. CDPSession composes one of
    these and delegates connect/disconnect/send_command/on_event to it, keeping
    the lazy-property facade for itself.
    """

    def __init__(self, config: "CDPConfig", logger: Any):
        self.config = config
        self.logger = logger
        self.ws: websocket.WebSocket | None = None
        self._connected = False
        self._request_id = 0
        self._pending_requests: dict[int, dict] = {}
        self._event_handlers: dict[str, Callable] = {}
        self._message_queue: queue.Queue = queue.Queue()
        self._listener_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()

        # WebSocket URL used for the current connection
        self._ws_url: Optional[str] = None

    @property
    def connected(self) -> bool:
        """Check if connected"""
        return self._connected

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

            # Create WebSocket connection (cdp_ws_connect always bypasses proxy)
            self.ws = cdp_ws_connect(ws_url, **ws_options)
            self._ws_url = ws_url

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
        try:
            # Get list of all targets
            response = cdp_get(
                f"{self.config.http_url}/json/list",
                timeout=self.config.connect_timeout,
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

            # No target_id specified, find first available page (skip landing page)
            fallback_ws_url = None
            for target in targets:
                if target.get('type') != 'page' or not target.get('webSocketDebuggerUrl'):
                    continue
                target_url = target.get('url', '')
                target_title = target.get('title', '')
                # Skip landing page — identified by dashboard URL, data: URI, or title "frago"
                if '/chrome/dashboard' in target_url or target_url.startswith('data:text/html') or target_title == 'frago':
                    if fallback_ws_url is None:
                        fallback_ws_url = target['webSocketDebuggerUrl']
                    continue
                self.logger.debug(f"Using page: {target.get('title', 'Unknown')}")
                return target['webSocketDebuggerUrl']

            # All pages are landing pages — use it as fallback
            if fallback_ws_url:
                self.logger.debug("Only landing page available, using it as fallback")
                return fallback_ws_url

            # If no page available, use browser endpoint
            response = cdp_get(
                f"{self.config.http_url}/json/version",
                timeout=self.config.connect_timeout,
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
