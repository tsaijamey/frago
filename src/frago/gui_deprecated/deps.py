"""Linux GUI dependency detection and automatic installation.

Provides Linux distribution detection, WebKit/GTK dependency checking and automatic installation.
"""

import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DistroInfo:
    """Linux distribution information."""

    id: str  # e.g. 'ubuntu', 'fedora', 'arch'
    name: str  # e.g. 'Ubuntu 24.04 LTS'
    version_id: str  # e.g. '24.04'
    id_like: list[str]  # Parent distribution list
    supported: bool  # Whether automatic installation is supported
    packages: list[str]  # List of packages to install
    install_cmd: str  # Installation command


# Distribution package mapping
# Includes WebKit runtime dependencies + PyGObject/pycairo compilation development libraries
#
# Note: PyGObject 3.51.0+ requires girepository-2.0
# - Ubuntu 24.04+: libgirepository-2.0-dev
# - Ubuntu 22.04 and earlier: libgirepository1.0-dev
# - Debian 12 (bookworm): libgirepository1.0-dev
# - Debian 13 (trixie)+: libgirepository-2.0-dev
DISTRO_PACKAGES = {
    # Ubuntu/Debian family
    # Note: Ubuntu 24.04+ requires libgirepository-2.0-dev
    # Dynamically select correct package via _get_girepository_package()
    "ubuntu": {
        "pkg_manager": "apt",
        "packages": [
            # WebKit runtime
            "gir1.2-webkit2-4.1",
            # PyGObject/pycairo compilation dependencies
            "libcairo2-dev",
            # libgirepository package dynamically added via _get_girepository_package()
            "pkg-config",
            "python3-dev",
        ],
        "install_prefix": "apt install -y",
    },
    "debian": {
        "pkg_manager": "apt",
        "packages": [
            "gir1.2-webkit2-4.1",
            "libcairo2-dev",
            # libgirepository package dynamically added via _get_girepository_package()
            "pkg-config",
            "python3-dev",
        ],
        "install_prefix": "apt install -y",
    },
    # Fedora/RHEL family
    "fedora": {
        "pkg_manager": "dnf",
        "packages": [
            "webkit2gtk4.1",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "dnf install -y",
    },
    "rhel": {
        "pkg_manager": "dnf",
        "packages": [
            "webkit2gtk4.1",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "dnf install -y",
    },
    "centos": {
        "pkg_manager": "dnf",
        "packages": [
            "webkit2gtk4.1",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "dnf install -y",
    },
    # Arch family
    "arch": {
        "pkg_manager": "pacman",
        "packages": [
            "webkit2gtk-4.1",
            "cairo",
            "gobject-introspection",
            "pkg-config",
            "python",
        ],
        "install_prefix": "pacman -S --noconfirm",
    },
    "manjaro": {
        "pkg_manager": "pacman",
        "packages": [
            "webkit2gtk-4.1",
            "cairo",
            "gobject-introspection",
            "pkg-config",
            "python",
        ],
        "install_prefix": "pacman -S --noconfirm",
    },
    # openSUSE
    "opensuse": {
        "pkg_manager": "zypper",
        "packages": [
            "webkit2gtk3",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "zypper install -y",
    },
    "opensuse-leap": {
        "pkg_manager": "zypper",
        "packages": [
            "webkit2gtk3",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "zypper install -y",
    },
    "opensuse-tumbleweed": {
        "pkg_manager": "zypper",
        "packages": [
            "webkit2gtk3",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "zypper install -y",
    },
}


def _get_girepository_package(distro_id: str, version_id: str, id_like: list[str] = None) -> str:
    """Return correct girepository development package name based on distro and version.

    PyGObject 3.51.0+ requires girepository-2.0.
    Determined by detecting which version is actually available on the system via pkg-config.

    Args:
        distro_id: Distribution ID (e.g. 'ubuntu', 'debian', 'linuxmint')
        version_id: Version number (e.g. '24.04', '12', '22.2')
        id_like: Parent distribution list (e.g. ['ubuntu', 'debian'])

    Returns:
        Correct package name.
    """
    # Most reliable method: check which package is available in apt repository
    if shutil.which("apt-cache"):
        # Check if 2.0 version is available first
        try:
            result = subprocess.run(
                ["apt-cache", "show", "libgirepository-2.0-dev"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return "libgirepository-2.0-dev"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fall back to 1.0 version
        try:
            result = subprocess.run(
                ["apt-cache", "show", "libgirepository1.0-dev"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return "libgirepository1.0-dev"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # If apt-cache unavailable, use default value
    return "libgirepository1.0-dev"


def _check_apt_package_available(pkg: str) -> bool:
    """Check if apt package is available in repository.

    Args:
        pkg: Package name.

    Returns:
        True if package is available.
    """
    if not shutil.which("apt-cache"):
        return False
    try:
        result = subprocess.run(
            ["apt-cache", "show", pkg],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def detect_distro() -> Optional[DistroInfo]:
    """Detect current Linux distribution.

    Retrieve distribution information by parsing /etc/os-release file.

    Returns:
        DistroInfo object, or None if not Linux or cannot detect.
    """
    if platform.system() != "Linux":
        return None

    os_release_path = Path("/etc/os-release")
    if not os_release_path.exists():
        return None

    # Parse os-release file
    info: dict[str, str] = {}
    try:
        with open(os_release_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    # Remove quotes
                    info[key] = value.strip('"').strip("'")
    except OSError:
        return None

    distro_id = info.get("ID", "").lower()
    name = info.get("NAME", distro_id or "Unknown")
    version_id = info.get("VERSION_ID", "")
    id_like = info.get("ID_LIKE", "").split()

    # Find matching distribution configuration
    config = None
    matched_id = distro_id

    # Try exact match first
    if distro_id in DISTRO_PACKAGES:
        config = DISTRO_PACKAGES[distro_id]
    else:
        # Try to match parent distribution
        for parent_id in id_like:
            if parent_id in DISTRO_PACKAGES:
                config = DISTRO_PACKAGES[parent_id]
                matched_id = parent_id
                break

    if config:
        packages = list(config["packages"])  # Copy list to avoid modifying original config

        # For apt-based distributions, dynamically add correct girepository package
        if config["pkg_manager"] == "apt":
            gi_pkg = _get_girepository_package(distro_id, version_id, id_like)
            packages.append(gi_pkg)

        install_cmd = f"{config['install_prefix']} {' '.join(packages)}"
        return DistroInfo(
            id=distro_id,
            name=name,
            version_id=version_id,
            id_like=id_like,
            supported=True,
            packages=packages,
            install_cmd=install_cmd,
        )

    # Unsupported distribution
    return DistroInfo(
        id=distro_id,
        name=name,
        version_id=version_id,
        id_like=id_like,
        supported=False,
        packages=[],
        install_cmd="",
    )


def _check_pkg_installed_dpkg(pkg: str) -> bool:
    """Check if package is installed using dpkg (Debian/Ubuntu)."""
    if not shutil.which("dpkg"):
        return False
    try:
        # Use dpkg-query for exact matching, avoiding fuzzy matching issues with dpkg -l
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", pkg],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Only consider installed if status is "install ok installed"
        installed = result.returncode == 0 and "install ok installed" in result.stdout
        logger.debug(f"dpkg check {pkg}: returncode={result.returncode}, status='{result.stdout.strip()}', installed={installed}")
        return installed
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _check_pkg_installed_rpm(pkg: str) -> bool:
    """Check if package is installed using rpm (Fedora/RHEL)."""
    if not shutil.which("rpm"):
        return False
    try:
        result = subprocess.run(
            ["rpm", "-q", pkg],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _check_pkg_installed_pacman(pkg: str) -> bool:
    """Check if package is installed using pacman (Arch/Manjaro)."""
    if not shutil.which("pacman"):
        return False
    try:
        result = subprocess.run(
            ["pacman", "-Q", pkg],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _check_pkg_config(lib: str) -> bool:
    """Check if library is available using pkg-config."""
    if not shutil.which("pkg-config"):
        return False
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", lib],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_all_system_deps(distro: Optional[DistroInfo]) -> tuple[bool, list[str]]:
    """Check all required system dependencies.

    Args:
        distro: Distribution information (including dynamically processed package list).

    Returns:
        Tuple of (all satisfied, list of missing packages).
    """
    if not distro or not distro.supported:
        return False, []

    missing = []
    pkg_manager = None

    # Get package manager configuration
    for distro_id in [distro.id] + distro.id_like:
        if distro_id in DISTRO_PACKAGES:
            pkg_manager = DISTRO_PACKAGES[distro_id]["pkg_manager"]
            break

    if not pkg_manager:
        return False, []

    # Use distro.packages (already includes dynamically added girepository package)
    packages = distro.packages
    logger.debug(f"Checking packages for {distro.id} {distro.version_id}: {packages}")

    # Check each package based on package manager
    for pkg in packages:
        installed = False

        if pkg_manager == "apt":
            installed = _check_pkg_installed_dpkg(pkg)
        elif pkg_manager in ("dnf", "zypper"):
            installed = _check_pkg_installed_rpm(pkg)
        elif pkg_manager == "pacman":
            installed = _check_pkg_installed_pacman(pkg)

        if not installed:
            missing.append(pkg)
            logger.debug(f"Package {pkg} is missing")

    logger.debug(f"Missing packages: {missing}")
    return len(missing) == 0, missing


def check_webkit_available() -> bool:
    """Check if WebKit2GTK system package is installed.

    Uses pkg-config for detection, the most reliable cross-distribution method.

    Returns:
        True if WebKit2GTK system package is installed.
    """
    for lib in ["webkit2gtk-4.1", "webkit2gtk-4.0", "webkit2gtk-3.0"]:
        if _check_pkg_config(lib):
            return True
    return False


def check_cairo_dev_available() -> bool:
    """Check if cairo development library is installed.

    Required for PyGObject/pycairo compilation.

    Returns:
        True if cairo development library is installed.
    """
    return _check_pkg_config("cairo")


def check_girepository_dev_available() -> bool:
    """Check if girepository development library is installed.

    Required for PyGObject compilation.
    - PyGObject 3.51.0+ requires girepository-2.0
    - Older versions require gobject-introspection-1.0

    Returns:
        True if girepository development library is installed.
    """
    # Check 2.0 version first (required by newer PyGObject)
    if _check_pkg_config("girepository-2.0"):
        return True
    # Fall back to 1.0 version
    if _check_pkg_config("gobject-introspection-1.0"):
        return True
    return False


def check_pywebview_available() -> bool:
    """Check if pywebview is available.

    Returns:
        True if pywebview can be imported.
    """
    try:
        import webview

        return True
    except ImportError:
        return False


def check_gi_importable() -> bool:
    """Check if gi (PyGObject) can be imported in current Python environment.

    Returns:
        True if gi can be imported.
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        return True
    except (ImportError, ValueError):
        return False


def install_pygobject_to_venv() -> tuple[bool, str]:
    """Install PyGObject to current virtual environment.

    Prefer uv pip, fall back to pip.

    Returns:
        Tuple of (success, message).
    """
    print("\nSystem WebKit dependencies installed, but current Python environment is missing PyGObject.")
    print("Installing PyGObject to frago environment...")
    print()

    # Prefer uv pip (frago installed via uv tool, needs --python specified)
    if shutil.which("uv"):
        cmd = ["uv", "pip", "install", "--python", sys.executable, "--quiet", "PyGObject"]
    elif shutil.which("pip"):
        cmd = ["pip", "install", "--quiet", "PyGObject"]
    elif shutil.which("pip3"):
        cmd = ["pip3", "install", "--quiet", "PyGObject"]
    else:
        # Fall back to python -m pip
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "PyGObject"]

    print(f"Executing: {' '.join(cmd)}\n")

    try:
        returncode = subprocess.call(cmd, timeout=120)

        if returncode == 0:
            return True, "PyGObject installed successfully"
        else:
            return False, f"PyGObject installation failed (exit code: {returncode})"

    except subprocess.TimeoutExpired:
        return False, "Installation timed out"
    except FileNotFoundError:
        return False, "Cannot find pip or uv, please install PyGObject manually"
    except Exception as e:
        return False, f"Installation error: {e}"


def has_sudo() -> bool:
    """Check if sudo is available.

    Returns:
        True if sudo exists.
    """
    return shutil.which("sudo") is not None


def auto_install_deps(distro: DistroInfo) -> tuple[bool, str]:
    """Install dependencies interactively in terminal using sudo.

    Args:
        distro: Distribution information.

    Returns:
        Tuple of (success, message).
    """
    if not distro.supported:
        return False, f"Automatic installation not supported: {distro.name}"

    if not has_sudo():
        return False, "sudo not available, cannot obtain administrator privileges"

    # Get package manager type
    pkg_manager = None
    for distro_id in [distro.id] + distro.id_like:
        if distro_id in DISTRO_PACKAGES:
            pkg_manager = DISTRO_PACKAGES[distro_id]["pkg_manager"]
            break

    if not pkg_manager:
        return False, f"Package configuration not found for {distro.id}"

    # Use distro.packages (already includes dynamically added girepository package)
    packages = distro.packages

    # Build complete command (using sudo, interactive password input in terminal)
    if pkg_manager == "apt":
        cmd = ["sudo", "apt", "install", "-y"] + packages
    elif pkg_manager == "dnf":
        cmd = ["sudo", "dnf", "install", "-y"] + packages
    elif pkg_manager == "pacman":
        cmd = ["sudo", "pacman", "-S", "--noconfirm"] + packages
    elif pkg_manager == "zypper":
        cmd = ["sudo", "zypper", "install", "-y"] + packages
    else:
        return False, f"Unsupported package manager: {pkg_manager}"

    print(f"\nExecuting: {' '.join(cmd)}\n")

    try:
        # Use subprocess.call to let sudo interact directly with terminal
        # Don't capture output, let user see installation process
        returncode = subprocess.call(cmd, timeout=300)

        if returncode == 0:
            return True, "Dependencies installed successfully"
        else:
            return False, f"Installation failed (exit code: {returncode})"

    except subprocess.TimeoutExpired:
        return False, "Installation timed out (over 5 minutes)"
    except FileNotFoundError:
        return False, "Package manager not found"
    except KeyboardInterrupt:
        print("\n")
        return False, "User cancelled installation"
    except Exception as e:
        return False, f"Installation error: {e}"


def get_manual_install_guide(distro: Optional[DistroInfo]) -> str:
    """Get manual installation guide.

    Args:
        distro: Distribution information, can be None.

    Returns:
        Manual installation guide text.
    """
    if distro and distro.supported:
        return f"""
Please manually run the following command to install GUI dependencies:

    sudo {distro.install_cmd}

After installation, run frago gui again.
"""

    if distro:
        return f"""
Unable to recognize your distribution ({distro.name}), please manually install the following dependencies:

    - Python GObject bindings (python3-gi or python-gobject)
    - WebKit2GTK library (webkit2gtk or similar package)
    - pywebview: pip install pywebview

Installation commands for common distributions:

    # Ubuntu/Debian
    sudo apt install -y python3-gi gir1.2-webkit2-4.1

    # Fedora/RHEL
    sudo dnf install -y python3-gobject webkit2gtk4.1

    # Arch
    sudo pacman -S python-gobject webkit2gtk-4.1

    # openSUSE
    sudo zypper install -y python3-gobject webkit2gtk3

After installation, run frago gui again.
"""

    return """
Please install GUI dependencies and retry:

    pip install pywebview

On Linux, system packages are also required:
    - Python GObject bindings
    - WebKit2GTK library

For details, see: https://pywebview.flowrl.com/guide/installation.html
"""


def prompt_auto_install() -> bool:
    """Prompt user whether to automatically install dependencies.

    Returns:
        True if user confirms installation.
    """
    print("\nMissing GUI system dependencies detected.")
    print("Install automatically? (requires administrator privileges)")
    print()

    while True:
        try:
            response = input("[Y/n] ").strip().lower()
            if response in ("", "y", "yes"):
                return True
            elif response in ("n", "no"):
                return False
            else:
                print("Please enter y or n")
        except (KeyboardInterrupt, EOFError):
            print()
            return False


def ensure_gui_deps() -> tuple[bool, str]:
    """Ensure GUI dependencies are available.

    Check process:
    1. Detect distribution
    2. Check all required system dependencies (WebKit + cairo-dev + gi-dev etc.)
    3. If missing, prompt user to install all system packages at once
    4. After all system packages installed, check if gi can be imported
    5. If gi cannot be imported, try pip install PyGObject

    Returns:
        Tuple of (can start GUI, message).
    """
    # Non-Linux systems, skip
    if platform.system() != "Linux":
        return True, ""

    # Step 1: Detect distribution
    distro = detect_distro()

    if not distro or not distro.supported:
        guide = get_manual_install_guide(distro)
        print(guide)
        return False, "Unsupported distribution"

    # Step 2: Check all system dependencies
    all_installed, missing_pkgs = check_all_system_deps(distro)

    if not all_installed:
        print(f"Detected distribution: {distro.name} ({distro.id} {distro.version_id})")
        print(f"\nMissing the following system dependencies:")
        for pkg in missing_pkgs:
            print(f"  - {pkg}")
        print()

        if not has_sudo():
            print("sudo not available, please install manually:")
            print(f"\n    sudo {distro.install_cmd}\n")
            return False, "sudo not available, please install dependencies manually"

        # Prompt user for installation
        if prompt_auto_install():
            success, msg = auto_install_deps(distro)
            if not success:
                print(f"\n{msg}")
                guide = get_manual_install_guide(distro)
                print(guide)
                return False, msg
            print(f"\n{msg}")
        else:
            guide = get_manual_install_guide(distro)
            print(guide)
            return False, "User cancelled installation"

    # Step 3: Check if gi can be imported
    if check_gi_importable():
        return True, ""

    # Step 4: System packages installed but gi cannot be imported, try pip install PyGObject
    # First confirm compilation dependencies are ready
    if not check_cairo_dev_available():
        print("\nError: cairo development library not properly installed, cannot compile PyGObject")
        print("Please ensure all system dependencies are installed and retry")
        return False, "cairo development library missing"

    if not check_girepository_dev_available():
        print("\nError: girepository development library not properly installed, cannot compile PyGObject")
        print()
        print("Please install girepository development library:")
        print("  Ubuntu 24.04+:  sudo apt install libgirepository-2.0-dev")
        print("  Ubuntu 22.04:   sudo apt install libgirepository1.0-dev")
        print("  Fedora/RHEL:    sudo dnf install gobject-introspection-devel")
        print()
        return False, "girepository development library missing"

    success, msg = install_pygobject_to_venv()
    if success:
        print(f"\n{msg}")
        print("Restarting GUI...")
        return True, "restart"
    else:
        print(f"\n{msg}")
        print("\nTry installing PyGObject manually:")
        print(f"    {sys.executable} -m pip install PyGObject")
        return False, msg
