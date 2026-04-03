"""frago telemetry — anonymous usage tracking.

Public API:
    capture(event_name, properties=None)  — send an event (fire-and-forget)
    is_enabled()  — quick check: config exists and enabled
    load_config()  — read TelemetryConfig from disk
    ensure_config()  — create config if missing (called by server startup)
"""

from frago.telemetry.client import capture, is_enabled
from frago.telemetry.config import ensure_config, load_config

__all__ = [
    "capture",
    "ensure_config",
    "is_enabled",
    "load_config",
]
