"""
CDP module - Chrome DevTools Protocol wrapper

Provides Python interface for browser automation control.
"""

from .client import CDPClient
from .config import CDPConfig
from .exceptions import CDPError, ConnectionError, TimeoutError
from .session import CDPSession

__all__ = [
    "CDPClient",
    "CDPSession",
    "CDPConfig",
    "CDPError",
    "ConnectionError",
    "TimeoutError",
]
