"""
CDP command wrappers

Provides Python wrappers for Chrome DevTools Protocol commands.
"""

from .dom import DOMCommands
from .input import InputCommands
from .page import PageCommands
from .runtime import RuntimeCommands
from .screenshot import ScreenshotCommands
from .scroll import ScrollCommands
from .status import StatusCommands
from .visual_effects import VisualEffectsCommands
from .wait import WaitCommands
from .zoom import ZoomCommands

__all__ = [
    "PageCommands",
    "InputCommands",
    "RuntimeCommands",
    "DOMCommands",
    "ScreenshotCommands",
    "ScrollCommands",
    "WaitCommands",
    "ZoomCommands",
    "StatusCommands",
    "VisualEffectsCommands",
]
