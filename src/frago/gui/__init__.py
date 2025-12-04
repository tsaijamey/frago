"""Frago GUI module.

Provides a desktop GUI interface for Frago using pywebview.
"""

__all__ = [
    "FragoGuiApp",
    "can_start_gui",
]


def _lazy_import():
    """Lazy import to avoid loading pywebview unless GUI is used."""
    try:
        from frago.gui.app import FragoGuiApp
        from frago.gui.utils import can_start_gui

        return FragoGuiApp, can_start_gui
    except ImportError as e:
        raise ImportError(
            "GUI dependencies not installed. Install with: pip install frago-cli[gui]"
        ) from e


def __getattr__(name):
    """Lazy load GUI components only when accessed."""
    if name == "FragoGuiApp":
        FragoGuiApp, _ = _lazy_import()
        return FragoGuiApp
    elif name == "can_start_gui":
        _, can_start_gui = _lazy_import()
        return can_start_gui
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
