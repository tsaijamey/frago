"""
Hook binary deployment for Claude Code.

Detects the current OS/arch, locates the matching precompiled binary
shipped inside the frago package, and copies it to ~/.claude/hooks/frago/.
"""

import platform
import shutil
import stat
from pathlib import Path


def get_platform_key() -> str:
    """Return the platform directory name matching the current OS and architecture.

    Returns:
        One of: linux-x86_64, darwin-arm64, darwin-x86_64, windows-x86_64

    Raises:
        RuntimeError: If the current platform is not supported.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        ("linux", "x86_64"): "linux-x86_64",
        ("linux", "amd64"): "linux-x86_64",
        ("darwin", "arm64"): "darwin-arm64",
        ("darwin", "aarch64"): "darwin-arm64",
        ("darwin", "x86_64"): "darwin-x86_64",
        ("windows", "x86_64"): "windows-x86_64",
        ("windows", "amd64"): "windows-x86_64",
    }

    key = arch_map.get((system, machine))
    if not key:
        raise RuntimeError(f"Unsupported platform: {system}-{machine}")
    return key


def get_binary_name() -> str:
    """Return the binary filename for the current OS."""
    if platform.system().lower() == "windows":
        return "frago-hook.exe"
    return "frago-hook"


def get_bundled_binary_path() -> Path:
    """Return the path to the bundled binary for the current platform.

    Raises:
        FileNotFoundError: If the binary for this platform is not bundled.
    """
    pkg_bin = Path(__file__).resolve().parent.parent / "bin"
    platform_key = get_platform_key()
    binary = pkg_bin / platform_key / get_binary_name()

    if not binary.exists():
        raise FileNotFoundError(
            f"No precompiled binary for {platform_key}. "
            f"Expected at: {binary}"
        )
    return binary


def get_hook_deploy_dir() -> Path:
    """Return ~/.claude/hooks/frago/, creating it if needed."""
    deploy_dir = Path.home() / ".claude" / "hooks" / "frago"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    return deploy_dir


def deploy_hook_binary(force: bool = False) -> Path:
    """Copy the platform-appropriate binary to ~/.claude/hooks/frago/.

    Args:
        force: Overwrite even if the target already exists and has the same size.

    Returns:
        Path to the deployed binary.

    Raises:
        FileNotFoundError: If no binary is bundled for this platform.
        RuntimeError: If the platform is not supported.
    """
    src = get_bundled_binary_path()
    dst_dir = get_hook_deploy_dir()
    dst = dst_dir / get_binary_name()

    if dst.exists() and not force:
        if dst.stat().st_size == src.stat().st_size:
            return dst

    shutil.copy2(src, dst)

    # Ensure executable permission (no-op on Windows)
    if platform.system().lower() != "windows":
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return dst


def get_hook_binary_path() -> str:
    """Return the absolute path string to the deployed hook binary.

    Useful for generating settings.json hook commands.
    """
    deploy_dir = get_hook_deploy_dir()
    return str(deploy_dir / get_binary_name())
