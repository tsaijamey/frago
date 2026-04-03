"""Telemetry configuration — read/write ~/.frago/telemetry.json.

The config file is shared by CLI, server, and hook (Rust reads it too).
Schema is intentionally flat and simple for cross-language compatibility.
"""

import contextlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class TelemetryConfig:
    enabled: bool = False
    anonymous_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompted: bool = False
    last_heartbeat: str | None = None


def _config_path() -> Path:
    return Path.home() / ".frago" / "telemetry.json"


def load_config() -> TelemetryConfig | None:
    """Load config from disk. Returns None if file doesn't exist."""
    path = _config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TelemetryConfig(
            enabled=data.get("enabled", False),
            anonymous_id=data.get("anonymous_id", str(uuid.uuid4())),
            prompted=data.get("prompted", False),
            last_heartbeat=data.get("last_heartbeat"),
        )
    except (json.JSONDecodeError, OSError):
        # Corrupted file — reset
        return None


def save_config(config: TelemetryConfig) -> None:
    """Atomic write config to disk. Creates parent dir if needed."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = json.dumps(asdict(config), indent=2, ensure_ascii=False)

    # Atomic write: write to temp file then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".telemetry-", suffix=".tmp"
    )
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, str(path))
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def ensure_config() -> TelemetryConfig:
    """Ensure telemetry.json exists with telemetry enabled.

    Called on server startup. If the file doesn't exist or is corrupted,
    creates it with enabled=True and a fresh anonymous_id.
    """
    config = load_config()
    if config is None:
        config = TelemetryConfig(enabled=True, prompted=True)
        save_config(config)
    return config


def update_last_heartbeat(config: TelemetryConfig) -> None:
    """Update heartbeat timestamp and persist."""
    config.last_heartbeat = datetime.now().isoformat()
    save_config(config)
