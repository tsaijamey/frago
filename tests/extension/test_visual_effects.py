"""Visual effects extension-backend RPC contract tests.

The actual JS injection is verified by the live e2e demo. These tests
pin the Python wrapper's RPC method names + parameter names, so a
typo in the SW dispatcher would surface as a parity failure.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from frago.chrome.backends.extension import ExtensionChromeBackend


def _be():
    be = ExtensionChromeBackend()
    be._rpc = MagicMock(return_value={"matched": 1})
    return be


def test_highlight_rpc_shape():
    be = _be()
    be.highlight("#btn", "g", color="red", border_width=2, lifetime=3000)
    be._rpc.assert_called_once_with("visual.highlight", {
        "selector": "#btn", "group": "g", "color": "red",
        "border_width": 2, "lifetime": 3000})


def test_pointer_rpc_shape():
    be = _be()
    be.pointer("#btn", "g", lifetime=2000)
    be._rpc.assert_called_once_with("visual.pointer", {
        "selector": "#btn", "group": "g", "lifetime": 2000})


def test_spotlight_rpc_shape():
    be = _be()
    be.spotlight("#btn", "g", lifetime=5000)
    be._rpc.assert_called_once_with("visual.spotlight", {
        "selector": "#btn", "group": "g", "lifetime": 5000})


def test_annotate_rpc_shape():
    be = _be()
    be.annotate("#btn", "click here", "g", position="bottom", lifetime=5000)
    be._rpc.assert_called_once_with("visual.annotate", {
        "selector": "#btn", "text": "click here", "group": "g",
        "position": "bottom", "lifetime": 5000})


def test_underline_rpc_shape():
    be = _be()
    be.underline("p", "g", color="blue", width=2, duration=800)
    be._rpc.assert_called_once_with("visual.underline", {
        "selector": "p", "group": "g", "color": "blue",
        "width": 2, "duration": 800})


def test_clear_effects_rpc_shape():
    be = _be()
    be.clear_effects("g")
    be._rpc.assert_called_once_with("visual.clear_effects", {"group": "g"})


def test_lifetime_zero_means_permanent():
    """``lifetime=0`` is the documented contract for 'permanent' effects."""
    be = _be()
    be.highlight("#btn", "g", lifetime=0)
    args = be._rpc.call_args[0]
    assert args[1]["lifetime"] == 0


def test_visual_commands_in_chrome_command_set():
    """Make sure VISUAL_COMMANDS includes everything we expose."""
    from frago.cli.chrome_commands import VISUAL_COMMANDS
    assert VISUAL_COMMANDS == {
        "highlight", "pointer", "spotlight", "annotate",
        "underline", "clear-effects",
    }
