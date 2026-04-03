"""Telemetry client — fire-and-forget event capture.

All network I/O runs in daemon threads. Failures are silently swallowed.
Telemetry is always enabled once telemetry.json exists (created by server startup).
"""

import os
import platform
import threading

import requests

from frago.telemetry.config import TelemetryConfig, load_config

POSTHOG_API_KEY = "phc_m2TzpvRTrVTmxFTbud7TjJhZ8usSRwF4t9tkTyXFbudj"
POSTHOG_CAPTURE_URL = "https://us.i.posthog.com/capture/"


def _suppressed() -> bool:
    """Check if telemetry is suppressed by environment variables."""
    return os.environ.get("CI") == "true"


def is_enabled() -> bool:
    """Quick check: config exists, enabled, and not suppressed."""
    if _suppressed():
        return False
    config = load_config()
    return config is not None and config.enabled


def capture(event_name: str, properties: dict | None = None) -> None:
    """Send a telemetry event (fire-and-forget).

    Safe to call from anywhere — returns immediately.
    Does nothing if suppressed or config not yet created.
    """
    if _suppressed():
        return
    config = load_config()
    if not config or not config.enabled:
        return
    _fire_and_forget(_send_event, config, event_name, properties)


# --- internals ---


def _fire_and_forget(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def _send_event(
    config: TelemetryConfig, event_name: str, properties: dict | None
) -> None:
    try:
        from frago import __version__

        payload = {
            "api_key": POSTHOG_API_KEY,
            "event": event_name,
            "distinct_id": config.anonymous_id,
            "properties": {
                "frago_version": __version__,
                "os_name": platform.system(),
                "os_version": platform.release(),
                "arch": platform.machine(),
                "python_version": platform.python_version(),
                **(properties or {}),
            },
        }
        requests.post(POSTHOG_CAPTURE_URL, json=payload, timeout=5)
    except Exception:
        pass
