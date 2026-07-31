"""frago.browser — pluggable browser backends.

Adds a thin ``ChromeBackend`` abstraction over the legacy CDP implementation
and the new MV3-extension implementation. Existing recipes continue to use
:mod:`frago.browser.cdp` directly; new code can opt into an explicit backend via
``frago browser <cmd> --backend extension`` or env ``FRAGO_BROWSER_BACKEND``.
"""
from .backends.base import (
    ChromeBackend,
    ClickResult,
    ContentResult,
    ExecResult,
    NavigateResult,
    ScreenshotResult,
)

__all__ = [
    "ChromeBackend",
    "NavigateResult",
    "ExecResult",
    "ContentResult",
    "ClickResult",
    "ScreenshotResult",
]
