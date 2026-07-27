"""
opencode plugin deployment.

Copies the bundled frago-hook bridge plugin into opencode's global plugin
directory so opencode sessions get the same knowledge injections that
Claude Code gets from ~/.claude/settings.json hook registrations.

The plugin shells out to the frago-hook binary deployed by
frago.init.hook_binary, so this module only moves one JS file — there is no
second copy of the binary and no separate rule set.
"""

import filecmp
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

PLUGIN_FILENAME = "frago-hook.js"
TOOL_NAME_MAP_FILENAME = "tool-name-map.json"
INJECTION_MARKERS_FILENAME = "injection-markers.json"

# The plugin reads both data files from its own directory at load time, so all
# of them must land together.
PLUGIN_FILES = (PLUGIN_FILENAME, TOOL_NAME_MAP_FILENAME, INJECTION_MARKERS_FILENAME)


def get_opencode_config_dir() -> Path:
    """Return opencode's global config directory (not created here)."""
    return Path.home() / ".config" / "opencode"


def is_opencode_present() -> bool:
    """Report whether opencode looks installed on this machine.

    Deployment is skipped otherwise: creating an opencode config tree for a
    user who does not run opencode would be an unrequested side effect.
    """
    return get_opencode_config_dir().is_dir() or shutil.which("opencode") is not None


def get_bundled_resource_dir() -> Path:
    """Return the packaged opencode resource directory."""
    return Path(__file__).resolve().parent.parent / "resources" / "opencode"


def get_bundled_plugin_path(filename: str = PLUGIN_FILENAME) -> Path:
    """Return the path to a packaged opencode resource.

    Raises:
        FileNotFoundError: If the resource is missing from the install.
    """
    src = get_bundled_resource_dir() / filename
    if not src.exists():
        raise FileNotFoundError(f"Bundled opencode resource not found at: {src}")
    return src


def get_tool_name_map() -> dict[str, str]:
    """Return the opencode -> Claude Code tool name mapping.

    Shared with the bridge plugin so `frago hook-rules add` can normalise
    rules authored from an opencode session into the vocabulary the routing
    engine actually matches on.
    """
    raw = get_bundled_plugin_path(TOOL_NAME_MAP_FILENAME).read_text(encoding="utf-8")
    return json.loads(raw)["map"]


def get_injection_markers() -> tuple[str, str]:
    """Return the (begin, end) markers wrapping frago-hook injected context.

    The bridge plugin wraps every injection it appends to an opencode user
    message in this pair; the archive layer strips those spans back out so a
    session's detail view shows what the user actually typed. Both sides read
    this one file, so the markers can never drift apart.
    """
    raw = get_bundled_plugin_path(INJECTION_MARKERS_FILENAME).read_text(encoding="utf-8")
    data = json.loads(raw)
    return data["begin"], data["end"]


def deploy_opencode_plugin(force: bool = False) -> Path | None:
    """Install the frago-hook bridge into ~/.config/opencode/plugin/.

    Args:
        force: Copy even when the deployed file is already identical.

    Returns:
        Path to the deployed plugin, or None if opencode is not installed.

    Raises:
        FileNotFoundError: If the plugin resource is missing from the package.
    """
    if not is_opencode_present():
        logger.debug("opencode not detected, skipping plugin deployment")
        return None

    dst_dir = get_opencode_config_dir() / "plugin"
    dst_dir.mkdir(parents=True, exist_ok=True)

    for filename in PLUGIN_FILES:
        src = get_bundled_plugin_path(filename)
        dst = dst_dir / filename
        if dst.exists() and not force and filecmp.cmp(src, dst, shallow=False):
            continue
        shutil.copy2(src, dst)
        logger.info("opencode plugin file deployed: %s", dst)

    return dst_dir / PLUGIN_FILENAME
