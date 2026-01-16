"""Cross-platform compatibility utilities"""
import os
import platform
import shutil
import sys
from typing import List, Optional


def _supports_unicode() -> bool:
    """Check if current terminal supports Unicode output"""
    if platform.system() != "Windows":
        return True

    # Must have UTF-8 stdout encoding to output Unicode
    try:
        encoding = sys.stdout.encoding or ""
        if encoding.lower() not in ("utf-8", "utf8"):
            return False
    except Exception:
        return False

    # Windows Terminal and modern consoles support Unicode
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
        return True

    return False


# Cross-platform symbols with fallback
_UNICODE_SUPPORTED = _supports_unicode()

SYMBOLS = {
    "clipboard": "📋" if _UNICODE_SUPPORTED else "[i]",
    "package": "📦" if _UNICODE_SUPPORTED else "[*]",
    "check": "✓" if _UNICODE_SUPPORTED else "[OK]",
    "cross": "✗" if _UNICODE_SUPPORTED else "[X]",
    "arrow": "→" if _UNICODE_SUPPORTED else "->",
    "info": "ℹ" if _UNICODE_SUPPORTED else "[i]",
}


def prepare_command_for_windows(cmd: List[str]) -> List[str]:
    """Adjust command format for Windows platform

    npm globally installed commands are .CMD batch files on Windows.
    Execute using full path directly instead of via cmd.exe /c (which truncates arguments at newlines).

    Args:
        cmd: Original command list

    Returns:
        Adjusted command list
    """
    if platform.system() != "Windows":
        return cmd

    if not cmd:
        return cmd

    # Find the full path to the executable
    executable = shutil.which(cmd[0])
    if executable:
        # Replace command name with full path
        # This allows subprocess to execute .CMD files directly without cmd.exe /c
        # Important: cmd.exe /c truncates arguments at newlines, losing multi-line prompts
        return [executable] + cmd[1:]

    return cmd


def _search_node_version_dirs(base_dir: str, subpath: str, executable: str) -> Optional[str]:
    """Search for executable in Node version manager directories.

    Args:
        base_dir: Base directory containing version subdirectories
        subpath: Path within each version directory (e.g., "bin", "installation/bin")
        executable: Name of the executable to find

    Returns:
        Full path to executable if found, None otherwise
    """
    if not os.path.isdir(base_dir):
        return None
    try:
        for version in os.listdir(base_dir):
            if version.startswith("."):
                continue
            candidate = os.path.join(base_dir, version, subpath, executable)
            if os.path.isfile(candidate):
                return candidate
    except OSError:
        pass
    return None


def find_claude_cli() -> Optional[str]:
    """Find claude CLI executable path.

    Returns full path to claude executable, or None if not found.
    Searches common npm global install locations if not in PATH,
    including Node version managers (nvm, fnm, volta, asdf) and pnpm.
    """
    # Try PATH first
    path = shutil.which("claude")
    if path:
        return path

    home = os.path.expanduser("~")

    # Windows: try common npm global locations and Node version managers
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")

        candidates = [
            # Standard npm global paths
            os.path.join(appdata, "npm", "claude.cmd"),
            os.path.join(localappdata, "npm", "claude.cmd"),
            # pnpm global path
            os.path.join(localappdata, "pnpm", "claude.cmd"),
        ]

        # Check environment variable hints for pnpm
        pnpm_home = os.environ.get("PNPM_HOME", "")
        if pnpm_home:
            candidates.append(os.path.join(pnpm_home, "claude.cmd"))

        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        # fnm: search in node-versions directory
        fnm_dir = os.environ.get("FNM_DIR", os.path.join(appdata, "fnm"))
        result = _search_node_version_dirs(
            os.path.join(fnm_dir, "node-versions"), "installation", "claude.cmd"
        )
        if result:
            return result

        # nvm-windows: search in nvm directory
        nvm_home = os.environ.get("NVM_HOME", os.path.join(appdata, "nvm"))
        if os.path.isdir(nvm_home):
            try:
                for version in os.listdir(nvm_home):
                    if version.startswith(".") or not version.startswith("v"):
                        continue
                    candidate = os.path.join(nvm_home, version, "claude.cmd")
                    if os.path.isfile(candidate):
                        return candidate
            except OSError:
                pass

        # volta: search in tools/image/node directory
        volta_home = os.environ.get("VOLTA_HOME", os.path.join(localappdata, "Volta"))
        volta_node_dir = os.path.join(volta_home, "tools", "image", "node")
        result = _search_node_version_dirs(volta_node_dir, "", "claude.cmd")
        if result:
            return result

    # macOS/Linux: try common npm global locations and Node version managers
    else:
        candidates = [
            # Standard system paths
            "/usr/local/bin/claude",
            "/usr/bin/claude",
            # Homebrew paths (macOS)
            "/opt/homebrew/bin/claude",  # Apple Silicon
            # pnpm global path
            os.path.join(home, ".local", "share", "pnpm", "claude"),
        ]

        # Check environment variable hints for pnpm
        pnpm_home = os.environ.get("PNPM_HOME", "")
        if pnpm_home:
            candidates.append(os.path.join(pnpm_home, "claude"))

        # volta shim (takes priority as it's a shim that handles version switching)
        volta_home = os.environ.get("VOLTA_HOME", os.path.join(home, ".volta"))
        candidates.append(os.path.join(volta_home, "bin", "claude"))

        # asdf shim
        asdf_dir = os.environ.get("ASDF_DATA_DIR", os.path.join(home, ".asdf"))
        candidates.append(os.path.join(asdf_dir, "shims", "claude"))

        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        # nvm: search in versions/node directory
        nvm_dir = os.environ.get("NVM_DIR", os.path.join(home, ".nvm"))
        result = _search_node_version_dirs(
            os.path.join(nvm_dir, "versions", "node"), "bin", "claude"
        )
        if result:
            return result

        # fnm: search in node-versions directory
        fnm_dir = os.environ.get("FNM_DIR", os.path.join(home, ".fnm"))
        result = _search_node_version_dirs(
            os.path.join(fnm_dir, "node-versions"), "installation/bin", "claude"
        )
        if result:
            return result

        # n: search in n/versions/node directory
        n_prefix = os.environ.get("N_PREFIX", "/usr/local")
        result = _search_node_version_dirs(
            os.path.join(n_prefix, "n", "versions", "node"), "bin", "claude"
        )
        if result:
            return result

    return None


def get_windows_subprocess_kwargs(detach: bool = False) -> dict:
    """Get Windows-specific subprocess kwargs to hide console window.

    On Windows, subprocess calls to .CMD files or console applications
    can flash a console window. This function returns kwargs that prevent
    the window from appearing.

    Args:
        detach: If True, also detach process from parent (for daemons/background tasks)

    Returns:
        dict with creationflags and startupinfo for subprocess calls.
        Empty dict on non-Windows platforms.

    Example:
        subprocess.run(cmd, **get_windows_subprocess_kwargs())
        subprocess.Popen(cmd, **get_windows_subprocess_kwargs(detach=True))
    """
    if platform.system() != "Windows":
        return {}

    import subprocess

    CREATE_NO_WINDOW = 0x08000000
    kwargs: dict = {}

    if detach:
        DETACHED_PROCESS = 0x00000008
        kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
    else:
        kwargs["creationflags"] = CREATE_NO_WINDOW

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startupinfo

    return kwargs
