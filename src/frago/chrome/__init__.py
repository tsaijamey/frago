"""frago.chrome — pluggable browser backends.

Adds a thin ``ChromeBackend`` abstraction over the legacy CDP implementation
and the new MV3-extension implementation. Existing recipes continue to use
:mod:`frago.chrome.cdp` directly; new code can opt into an explicit backend via
``frago chrome <cmd> --backend extension`` or env ``FRAGO_CHROME_BACKEND``.
"""
from .backends.base import ChromeBackend, NavigateResult, ExecResult, ContentResult, ClickResult, ScreenshotResult

__all__ = [
    "ChromeBackend",
    "NavigateResult",
    "ExecResult",
    "ContentResult",
    "ClickResult",
    "ScreenshotResult",
]
