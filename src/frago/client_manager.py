"""Client Manager for frago desktop client.

Handles downloading, updating, and launching the Tauri desktop client.
The client binary is downloaded from GitHub Releases on first run.

Installation locations by platform:
- macOS: ~/Applications/frago.app
- Linux: ~/.local/bin/frago.AppImage + ~/.local/share/applications/frago.desktop
- Windows: %LOCALAPPDATA%\\Programs\\frago\\frago.exe
"""

import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, List

import requests

logger = logging.getLogger(__name__)

# frago user data directory (for version tracking)
FRAGO_HOME = Path.home() / ".frago"

# GitHub repository for releases
GITHUB_OWNER = "tsaijamey"
GITHUB_REPO = "frago"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

# Download mirror sources (tried in order, with fallback)
# Format: base URL that will be prefixed to the GitHub download URL
DOWNLOAD_MIRRORS = [
    # China-friendly mirrors (try first for better speed in mainland China)
    "https://mirror.ghproxy.com/",
    "https://ghproxy.net/",
    # Direct GitHub (fallback)
    "",
]


def _get_install_dir() -> Path:
    """Get the platform-specific installation directory.

    Returns:
        Path to the installation directory.
    """
    if sys.platform == "darwin":
        # macOS: ~/Applications/
        return Path.home() / "Applications"
    elif sys.platform == "linux":
        # Linux: ~/.local/bin/
        return Path.home() / ".local" / "bin"
    elif sys.platform == "win32":
        # Windows: %LOCALAPPDATA%\Programs\frago\
        local_app_data = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return Path(local_app_data) / "Programs" / "frago"
    else:
        # Fallback
        return FRAGO_HOME / "client"


def _get_desktop_entry_dir() -> Optional[Path]:
    """Get the directory for desktop entries (Linux only).

    Returns:
        Path to desktop entry directory, or None if not applicable.
    """
    if sys.platform == "linux":
        return Path.home() / ".local" / "share" / "applications"
    return None


# Platform-specific binary names and archive patterns
PLATFORM_CONFIG = {
    "darwin": {
        "arm64": {
            "archive_pattern": "frago_*_aarch64-apple-darwin.tar.gz",
            "binary_name": "frago.app",
            "is_app_bundle": True,
        },
        "x86_64": {
            "archive_pattern": "frago_*_x86_64-apple-darwin.tar.gz",
            "binary_name": "frago.app",
            "is_app_bundle": True,
        },
    },
    "linux": {
        "x86_64": {
            "archive_pattern": "frago_*_x86_64-unknown-linux-gnu.AppImage",
            "binary_name": "frago.AppImage",
            "is_app_bundle": False,
        },
        "aarch64": {
            "archive_pattern": "frago_*_aarch64-unknown-linux-gnu.AppImage",
            "binary_name": "frago.AppImage",
            "is_app_bundle": False,
        },
    },
    "win32": {
        "AMD64": {
            "archive_pattern": "frago_*_x86_64-pc-windows-msvc.zip",
            "binary_name": "frago.exe",
            "is_app_bundle": False,
        },
    },
}


def get_platform_config() -> Optional[dict]:
    """Get platform-specific configuration for the current system.

    Returns:
        Platform configuration dict or None if unsupported.
    """
    system = sys.platform
    machine = platform.machine()

    # Normalize machine architecture
    if machine == "AMD64":
        machine = "AMD64"  # Windows
    elif machine == "arm64":
        machine = "arm64"  # macOS Apple Silicon

    if system not in PLATFORM_CONFIG:
        logger.error(f"Unsupported operating system: {system}")
        return None

    if machine not in PLATFORM_CONFIG[system]:
        logger.error(f"Unsupported architecture: {machine} on {system}")
        return None

    return PLATFORM_CONFIG[system][machine]


def get_client_path() -> Path:
    """Get the path to the installed client binary.

    Returns:
        Path to the client binary/app bundle.
    """
    config = get_platform_config()
    if not config:
        return _get_install_dir() / "frago"

    return _get_install_dir() / config["binary_name"]


def is_installed() -> bool:
    """Check if the desktop client is installed.

    Returns:
        True if client is installed, False otherwise.
    """
    client_path = get_client_path()

    if sys.platform == "darwin":
        # macOS: check for app bundle
        return (client_path / "Contents" / "MacOS" / "frago").exists()
    else:
        return client_path.exists()


def get_installed_version() -> Optional[str]:
    """Get the version of the installed client.

    Returns:
        Version string or None if not installed.
    """
    version_file = FRAGO_HOME / "client_version"
    if version_file.exists():
        return version_file.read_text().strip()
    return None


def _save_installed_version(version: str) -> None:
    """Save the installed version to tracking file."""
    FRAGO_HOME.mkdir(parents=True, exist_ok=True)
    (FRAGO_HOME / "client_version").write_text(version)


def get_latest_release() -> Optional[dict]:
    """Fetch the latest release info from GitHub.

    Returns:
        Release info dict or None on error.
    """
    try:
        response = requests.get(
            f"{GITHUB_API_URL}/latest",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch latest release: {e}")
        return None


def find_asset_for_platform(release: dict) -> Optional[dict]:
    """Find the download asset for the current platform.

    Args:
        release: GitHub release info dict.

    Returns:
        Asset info dict or None if not found.
    """
    config = get_platform_config()
    if not config:
        return None

    pattern = config["archive_pattern"]
    # Convert glob pattern to a simple match
    pattern_prefix = pattern.split("*")[0]
    pattern_suffix = pattern.split("*")[-1]

    for asset in release.get("assets", []):
        name = asset["name"]
        if name.startswith(pattern_prefix) and name.endswith(pattern_suffix):
            return asset

    logger.error(f"No asset found matching pattern: {pattern}")
    return None


def _download_with_mirrors(url: str, dest_path: Path, mirrors: List[str]) -> bool:
    """Download a file trying multiple mirror sources.

    Args:
        url: Original GitHub download URL.
        dest_path: Destination file path.
        mirrors: List of mirror prefixes to try.

    Returns:
        True on success, False if all mirrors failed.
    """
    for i, mirror in enumerate(mirrors):
        # Construct the full URL
        if mirror:
            # Mirror: prefix the GitHub URL
            full_url = mirror + url
        else:
            # Direct GitHub
            full_url = url

        mirror_name = mirror.split("/")[2] if mirror else "github.com"
        logger.info(f"Trying {mirror_name}... ({i + 1}/{len(mirrors)})")

        try:
            response = requests.get(full_url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        progress = (downloaded / total_size) * 100
                        print(f"\rDownloading... {progress:.1f}%", end="", flush=True)

            print()  # Newline after progress
            logger.info(f"Download successful from {mirror_name}")
            return True

        except requests.RequestException as e:
            logger.warning(f"Mirror {mirror_name} failed: {e}")
            continue

    logger.error("All download sources failed")
    return False


def _create_linux_desktop_entry(app_path: Path) -> None:
    """Create a .desktop entry for Linux.

    Args:
        app_path: Path to the AppImage.
    """
    desktop_dir = _get_desktop_entry_dir()
    if not desktop_dir:
        return

    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = desktop_dir / "frago.desktop"

    # Get icon path (extract from AppImage or use a default)
    icon_path = FRAGO_HOME / "frago-icon.png"

    content = f"""[Desktop Entry]
Name=frago
Comment=AI-driven browser automation
Exec={app_path}
Icon={icon_path if icon_path.exists() else "application-x-executable"}
Terminal=false
Type=Application
Categories=Development;Utility;
StartupWMClass=frago
"""

    desktop_file.write_text(content)
    desktop_file.chmod(desktop_file.stat().st_mode | stat.S_IXUSR)
    logger.info(f"Created desktop entry: {desktop_file}")


def _remove_linux_desktop_entry() -> None:
    """Remove the .desktop entry for Linux."""
    desktop_dir = _get_desktop_entry_dir()
    if not desktop_dir:
        return

    desktop_file = desktop_dir / "frago.desktop"
    if desktop_file.exists():
        desktop_file.unlink()
        logger.info("Removed desktop entry")


def download_client(version: Optional[str] = None) -> bool:
    """Download and install the desktop client.

    Args:
        version: Specific version to download, or None for latest.

    Returns:
        True on success, False on error.
    """
    # Get release info
    if version:
        url = f"{GITHUB_API_URL}/tags/v{version}"
        try:
            response = requests.get(
                url,
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=30,
            )
            response.raise_for_status()
            release = response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch release v{version}: {e}")
            return False
    else:
        release = get_latest_release()
        if not release:
            return False

    release_version = release["tag_name"].lstrip("v")
    logger.info(f"Downloading frago client v{release_version}...")

    # Find asset for current platform
    asset = find_asset_for_platform(release)
    if not asset:
        return False

    download_url = asset["browser_download_url"]
    asset_name = asset["name"]

    # Create temp directory for download
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / asset_name

        # Download with mirror fallback
        logger.info(f"Downloading {asset_name}...")
        if not _download_with_mirrors(download_url, archive_path, DOWNLOAD_MIRRORS):
            return False

        # Extract and install
        logger.info("Installing client...")
        install_dir = _get_install_dir()
        install_dir.mkdir(parents=True, exist_ok=True)

        config = get_platform_config()
        if not config:
            return False

        try:
            if asset_name.endswith(".tar.gz"):
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(temp_path)

                # Find and move the app/binary
                if config["is_app_bundle"]:
                    # macOS: find .app bundle
                    for item in temp_path.iterdir():
                        if item.suffix == ".app":
                            dest = install_dir / config["binary_name"]
                            if dest.exists():
                                shutil.rmtree(dest)
                            shutil.move(str(item), str(dest))
                            break
                else:
                    # Linux/Windows: find binary
                    for item in temp_path.iterdir():
                        if item.name == config["binary_name"]:
                            dest = install_dir / config["binary_name"]
                            if dest.exists():
                                dest.unlink()
                            shutil.move(str(item), str(dest))
                            # Make executable
                            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                            break

            elif asset_name.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(temp_path)

                # Find and move the binary
                for item in temp_path.iterdir():
                    if item.name == config["binary_name"] or item.suffix == ".exe":
                        dest = install_dir / config["binary_name"]
                        if dest.exists():
                            dest.unlink()
                        shutil.move(str(item), str(dest))
                        break

            elif asset_name.endswith(".AppImage"):
                # AppImage: just copy directly
                dest = install_dir / config["binary_name"]
                if dest.exists():
                    dest.unlink()
                shutil.copy2(archive_path, dest)
                dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

                # Create desktop entry for Linux
                _create_linux_desktop_entry(dest)

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            return False

        # Save version info
        _save_installed_version(release_version)

        logger.info(f"frago client v{release_version} installed successfully!")
        logger.info(f"Location: {get_client_path()}")
        return True


def launch() -> bool:
    """Launch the desktop client.

    Returns:
        True on success, False on error.
    """
    if not is_installed():
        logger.error("Client not installed. Run 'frago client start' to install.")
        return False

    client_path = get_client_path()

    try:
        if sys.platform == "darwin":
            # macOS: use 'open' command for app bundles
            subprocess.Popen(["open", str(client_path)])
        elif sys.platform == "linux":
            # Linux: run AppImage directly
            subprocess.Popen([str(client_path)], start_new_session=True)
        elif sys.platform == "win32":
            # Windows: run exe directly
            subprocess.Popen([str(client_path)], creationflags=subprocess.DETACHED_PROCESS)
        else:
            logger.error(f"Unsupported platform: {sys.platform}")
            return False

        logger.info("frago client launched!")
        return True

    except Exception as e:
        logger.error(f"Failed to launch client: {e}")
        return False


def uninstall() -> bool:
    """Remove the installed desktop client.

    Returns:
        True on success, False on error.
    """
    client_path = get_client_path()

    if not client_path.exists():
        logger.info("Client not installed.")
        return True

    try:
        # Remove the client
        if client_path.is_dir():
            shutil.rmtree(client_path)
        else:
            client_path.unlink()

        # Remove desktop entry on Linux
        if sys.platform == "linux":
            _remove_linux_desktop_entry()

        # Remove version file
        version_file = FRAGO_HOME / "client_version"
        if version_file.exists():
            version_file.unlink()

        logger.info("frago client uninstalled.")
        return True

    except Exception as e:
        logger.error(f"Failed to uninstall: {e}")
        return False


def get_status() -> dict:
    """Get the current client status.

    Returns:
        Status dict with installation info.
    """
    config = get_platform_config()
    installed = is_installed()
    installed_version = get_installed_version() if installed else None

    # Try to get latest version
    latest_version = None
    try:
        release = get_latest_release()
        if release:
            latest_version = release["tag_name"].lstrip("v")
    except Exception:
        pass

    return {
        "installed": installed,
        "installed_version": installed_version,
        "latest_version": latest_version,
        "update_available": (
            installed_version and latest_version and installed_version != latest_version
        ),
        "client_path": str(get_client_path()) if installed else None,
        "install_dir": str(_get_install_dir()),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "supported": config is not None,
    }
