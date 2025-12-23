"""Utility functions for Frago Web Service.

Provides helper functions for port discovery, URL handling,
and other server-related utilities.
"""

import socket
from typing import Optional, Tuple

# Global server state (shared across modules)
_server_started_at: Optional[str] = None
_server_host: str = "127.0.0.1"
_server_port: int = 8080


def set_server_state(host: str, port: int, started_at: str) -> None:
    """Set server state variables.

    Args:
        host: Server host
        port: Server port
        started_at: ISO timestamp when server started
    """
    global _server_started_at, _server_host, _server_port
    _server_host = host
    _server_port = port
    _server_started_at = started_at


def get_server_info() -> dict:
    """Get current server information.

    Returns:
        Dictionary with host, port, and started_at
    """
    return {
        "host": _server_host,
        "port": _server_port,
        "started_at": _server_started_at,
    }


def find_available_port(start_port: int = 8080, max_attempts: int = 100) -> int:
    """Find an available port starting from the given port.

    Attempts to bind to ports sequentially until one is available.

    Args:
        start_port: Port to start searching from
        max_attempts: Maximum number of ports to try

    Returns:
        An available port number

    Raises:
        RuntimeError: If no available port found within max_attempts
    """
    for offset in range(max_attempts):
        port = start_port + offset
        if is_port_available(port):
            return port

    raise RuntimeError(
        f"No available port found between {start_port} and {start_port + max_attempts - 1}"
    )


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is available for binding.

    Args:
        port: Port number to check
        host: Host to bind to

    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.bind((host, port))
            return True
    except (socket.error, OSError):
        return False


def get_server_url(host: str = "127.0.0.1", port: int = 8080) -> str:
    """Get the full server URL.

    Args:
        host: Server host
        port: Server port

    Returns:
        Full URL string (e.g., "http://127.0.0.1:8080")
    """
    return f"http://{host}:{port}"


def parse_host_port(address: str, default_port: int = 8080) -> Tuple[str, int]:
    """Parse a host:port string.

    Args:
        address: Address string (e.g., "127.0.0.1:8080" or "localhost")
        default_port: Default port if not specified

    Returns:
        Tuple of (host, port)
    """
    if ":" in address:
        host, port_str = address.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = default_port
    else:
        host = address
        port = default_port

    return host, port


def validate_port(port: int) -> bool:
    """Validate that a port number is in the valid range.

    Args:
        port: Port number to validate

    Returns:
        True if port is valid (1024-65535), False otherwise
    """
    return 1024 <= port <= 65535
