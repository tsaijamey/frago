"""
frago - Automated visual management system CDP control library

Provides Python wrapper for Chrome DevTools Protocol,
for browser automation control and visual management.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("frago-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"  # Fallback value when not installed in development mode
__author__ = "Jamey Tsai"
__email__ = "caijia@frago.ai"

# Recommended to use explicit imports:
# from frago.recipes import RecipeRegistry, RecipeRunner
# from frago.run import RunInstance, RunManager
# from frago.cdp import CDPClient, CDPSession
# from frago.cli import cli

# Submodules accessed via path (avoid top-level namespace pollution)
# Example: import frago.recipes, import frago.run

__all__ = [
    "__version__",
    "__author__",
    "__email__",
]