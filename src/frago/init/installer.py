"""
Installer Module

Provides functionality for installing Node.js and Claude Code.
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from frago.init.exceptions import CommandError, InitErrorCode


# ============================================================
# Windows Compatibility Helper Functions
# ============================================================


def check_npm_global_in_path() -> bool:
    """
    Check if npm global directory is in PATH

    Returns:
        True if in PATH or on non-Windows platform
    """
    if platform.system() != "Windows":
        return True

    npm_global = os.path.join(os.environ.get("APPDATA", ""), "npm")
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    return any(npm_global.lower() == p.lower() for p in path_dirs)


def get_windows_path_hint() -> str:
    """
    Get Windows PATH fix hint

    Returns:
        String containing fix suggestions
    """
    return (
        "\n[!]  npm global directory not in PATH, claude command may not work directly\n\n"
        "Please choose one of the following options:\n\n"
        "  1. Reopen PowerShell window (recommended)\n\n"
        "  2. Temporarily use npx to start:\n"
        "     npx @anthropic-ai/claude-code\n\n"
        "  3. Manually add to PATH (current session):\n"
        "     $env:PATH += \";$env:APPDATA\\npm\"\n\n"
        "  4. Permanently add to PATH:\n"
        "     [Environment]::SetEnvironmentVariable(\n"
        "       'PATH', $env:PATH + ';' + $env:APPDATA + '\\npm', 'User')\n"
    )


def get_platform_node_install_guide() -> str:
    """
    Return Node.js installation guide based on platform

    Returns:
        Platform-specific installation guide string
    """
    if platform.system() == "Windows":
        return (
            "Please install Node.js using one of the following methods:\n\n"
            "  1. winget (recommended):\n"
            "     winget install OpenJS.NodeJS.LTS\n\n"
            "  2. Official installer:\n"
            "     https://nodejs.org/\n\n"
            "  3. Chocolatey:\n"
            "     choco install nodejs-lts"
        )
    return (
        "Please install nvm first:\n"
        "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash\n"
        "or visit: https://github.com/nvm-sh/nvm"
    )


# ============================================================
# Command Execution Helper Functions
# ============================================================


def run_external_command(
    cmd: List[str],
    timeout: int = 120,
    check: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    Execute external command and handle errors

    Args:
        cmd: Command and argument list
        timeout: Timeout in seconds, default 120 seconds
        check: Whether to check return code, default True
        cwd: Working directory

    Returns:
        subprocess.CompletedProcess result

    Raises:
        CommandError: When command execution fails
    """
    # Check if command exists
    if not shutil.which(cmd[0]):
        raise CommandError(
            f"Command not found: {cmd[0]}",
            InitErrorCode.COMMAND_NOT_FOUND,
            f"Please ensure {cmd[0]} is installed and in PATH",
        )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout,
            cwd=cwd,
            check=False,
        )

        if check and result.returncode != 0:
            stderr_lower = result.stderr.lower()

            # Analyze error type
            if "permission denied" in stderr_lower or "eacces" in stderr_lower:
                raise CommandError(
                    f"Insufficient permissions: {' '.join(cmd)}",
                    InitErrorCode.PERMISSION_ERROR,
                    "Try using sudo or configure npm prefix:\n"
                    "  npm config set prefix ~/.npm-global\n"
                    "  export PATH=~/.npm-global/bin:$PATH",
                )
            elif "timeout" in stderr_lower or "etimedout" in stderr_lower:
                raise CommandError(
                    f"Network timeout: {' '.join(cmd)}",
                    InitErrorCode.NETWORK_ERROR,
                    "Please check network connection or configure proxy:\n"
                    "  export HTTP_PROXY=http://proxy:port\n"
                    "  export HTTPS_PROXY=http://proxy:port",
                )
            else:
                raise CommandError(
                    f"Command execution failed: {' '.join(cmd)}",
                    InitErrorCode.INSTALL_ERROR,
                    f"Return code: {result.returncode}\nError output:\n{result.stderr}",
                )

        return result

    except subprocess.TimeoutExpired as e:
        raise CommandError(
            f"Command execution timeout ({timeout}s): {' '.join(cmd)}",
            InitErrorCode.NETWORK_ERROR,
            "Please check network connection or increase timeout",
        ) from e


def _find_nvm() -> Optional[str]:
    """
    Find nvm installation location

    Returns:
        nvm.sh path or None
    """
    # Common nvm installation locations
    possible_paths = [
        Path.home() / ".nvm" / "nvm.sh",
        Path("/usr/local/opt/nvm/nvm.sh"),
        Path("/opt/homebrew/opt/nvm/nvm.sh"),
    ]

    for path in possible_paths:
        if path.exists():
            return str(path)

    # Check environment variable
    nvm_dir = os.environ.get("NVM_DIR")
    if nvm_dir:
        nvm_sh = Path(nvm_dir) / "nvm.sh"
        if nvm_sh.exists():
            return str(nvm_sh)

    return None


def _install_nvm() -> str:
    """
    Automatically install nvm

    Returns:
        nvm.sh path

    Raises:
        CommandError: When installation fails
    """
    import click

    click.echo("📦 nvm not installed, installing automatically...")

    # Download and install nvm
    install_script = "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"

    try:
        # Use curl or wget to download installation script
        if shutil.which("curl"):
            cmd = ["bash", "-c", f"curl -fsSL {install_script} | bash"]
        elif shutil.which("wget"):
            cmd = ["bash", "-c", f"wget -qO- {install_script} | bash"]
        else:
            raise CommandError(
                "Cannot download nvm installation script",
                InitErrorCode.COMMAND_NOT_FOUND,
                "Please install curl or wget first",
            )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=120,
        )

        if result.returncode != 0:
            raise CommandError(
                "nvm installation failed",
                InitErrorCode.INSTALL_ERROR,
                f"Error output:\n{result.stderr}",
            )

        click.echo("[OK] nvm installed successfully")

        # Return newly installed nvm path
        nvm_path = Path.home() / ".nvm" / "nvm.sh"
        if nvm_path.exists():
            return str(nvm_path)

        raise CommandError(
            "nvm not found after installation",
            InitErrorCode.INSTALL_ERROR,
            "Please manually check if ~/.nvm/nvm.sh exists",
        )

    except subprocess.TimeoutExpired:
        raise CommandError(
            "nvm installation timeout",
            InitErrorCode.NETWORK_ERROR,
            "Please check network connection",
        )


def _get_shell_config_file() -> Optional[Path]:
    """
    Get current shell's configuration file path

    Returns:
        Configuration file path or None
    """
    shell = os.environ.get("SHELL", "")

    if "zsh" in shell:
        return Path.home() / ".zshrc"
    elif "bash" in shell:
        # Prefer .bashrc, then .bash_profile
        bashrc = Path.home() / ".bashrc"
        if bashrc.exists():
            return bashrc
        return Path.home() / ".bash_profile"

    return None


def install_node(version: str = "20") -> Tuple[bool, bool]:
    """
    Install Node.js (via nvm, macOS/Linux only)

    Args:
        version: Node.js version (default 20)

    Returns:
        (success, requires_restart): Whether installation succeeded, whether terminal restart is required

    Raises:
        CommandError: When installation fails or Windows platform does not support automatic installation
    """
    import click

    # Windows does not support automatic installation via nvm
    if platform.system() == "Windows":
        raise CommandError(
            "Windows does not support automatic Node.js installation",
            InitErrorCode.COMMAND_NOT_FOUND,
            get_platform_node_install_guide(),
        )

    nvm_path = _find_nvm()

    # If nvm is not installed, install it automatically
    if not nvm_path:
        nvm_path = _install_nvm()

    # Call nvm via bash: install, use, and set as default
    install_cmd = (
        f'source "{nvm_path}" && '
        f'nvm install {version} && '
        f'nvm use {version} && '
        f'nvm alias default {version}'
    )

    try:
        result = subprocess.run(
            ["bash", "-c", install_cmd],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=300,  # Installation may take a while
        )

        if result.returncode != 0:
            raise CommandError(
                f"Node.js {version} installation failed",
                InitErrorCode.INSTALL_ERROR,
                f"Error output:\n{result.stderr}",
            )

        # Check if npm is available in current PATH
        if shutil.which("npm"):
            # npm is available, no restart needed
            return True, False

        # npm not available, terminal restart required
        return True, True

    except subprocess.TimeoutExpired:
        raise CommandError(
            "Node.js installation timeout",
            InitErrorCode.NETWORK_ERROR,
            "Please check network connection",
        )


def _install_claude_code_via_nvm() -> Tuple[bool, Optional[str]]:
    """
    Install Claude Code via nvm environment (used when npm is not in PATH)

    Execute npm install after sourcing nvm.sh in subprocess.
    This allows installation via nvm-managed npm even if current terminal hasn't activated nvm.

    Returns:
        (True, warning) Installation successful, warning is warning message (if any) or None

    Raises:
        CommandError: When installation fails
    """
    import click

    nvm_path = _find_nvm()
    if not nvm_path:
        raise CommandError(
            "nvm not found",
            InitErrorCode.COMMAND_NOT_FOUND,
            "Please install Node.js or nvm first",
        )

    click.echo("  (Installing via nvm environment)")

    # Activate nvm in subshell and install claude-code
    install_cmd = (
        f'source "{nvm_path}" && '
        f'npm install -g @anthropic-ai/claude-code'
    )

    try:
        result = subprocess.run(
            ["bash", "-c", install_cmd],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=300,
        )

        if result.returncode != 0:
            stderr_lower = result.stderr.lower()

            if "permission denied" in stderr_lower or "eacces" in stderr_lower:
                raise CommandError(
                    "Insufficient permissions",
                    InitErrorCode.PERMISSION_ERROR,
                    "Try configuring npm prefix:\n"
                    "  npm config set prefix ~/.npm-global\n"
                    "  export PATH=~/.npm-global/bin:$PATH",
                )
            elif "timeout" in stderr_lower or "etimedout" in stderr_lower:
                raise CommandError(
                    "Network timeout",
                    InitErrorCode.NETWORK_ERROR,
                    "Please check network connection or configure proxy",
                )
            else:
                raise CommandError(
                    "Claude Code installation failed",
                    InitErrorCode.INSTALL_ERROR,
                    f"Error output:\n{result.stderr}",
                )

        return True, None

    except subprocess.TimeoutExpired:
        raise CommandError(
            "Installation timeout",
            InitErrorCode.NETWORK_ERROR,
            "Please check network connection",
        )


def install_claude_code(use_nvm_fallback: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Install Claude Code (via npm)

    Args:
        use_nvm_fallback: Whether to try installing via nvm environment when npm is not in PATH

    Returns:
        (True, warning) Installation successful, warning is PATH warning (if any) or None

    Raises:
        CommandError: When installation fails
    """
    # Check if npm exists
    if not shutil.which("npm"):
        # Option 2: Try installing via nvm environment
        if use_nvm_fallback and platform.system() != "Windows":
            return _install_claude_code_via_nvm()

        raise CommandError(
            "npm not installed",
            InitErrorCode.COMMAND_NOT_FOUND,
            "Please install Node.js (includes npm) first",
        )

    # Install Claude Code
    cmd = ["npm", "install", "-g", "@anthropic-ai/claude-code"]

    run_external_command(cmd, timeout=300)

    # Check PATH on Windows platform
    warning = None
    if platform.system() == "Windows" and not check_npm_global_in_path():
        warning = get_windows_path_hint()

    return True, warning


def get_installation_order(
    node_needed: bool,
    claude_code_needed: bool,
) -> List[str]:
    """
    Get installation order

    Node.js must be installed before Claude Code (because Claude Code depends on npm).

    Args:
        node_needed: Whether Node.js installation is needed
        claude_code_needed: Whether Claude Code installation is needed

    Returns:
        Installation list sorted by dependency order
    """
    order = []

    if node_needed:
        order.append("node")

    if claude_code_needed:
        order.append("claude-code")

    return order


def install_dependency(
    name: str,
    use_nvm_fallback: bool = False,
) -> Tuple[bool, Optional[str], bool]:
    """
    Install specified dependency

    Args:
        name: Dependency name ("node" or "claude-code")
        use_nvm_fallback: For claude-code, whether to use nvm environment when npm is unavailable

    Returns:
        (success, warning, requires_restart):
        - success: Whether installation succeeded
        - warning: Warning message (if any) or None
        - requires_restart: Whether terminal restart is required to continue

    Raises:
        CommandError: When installation fails
        ValueError: Unknown dependency name
    """
    if name == "node":
        success, requires_restart = install_node()
        return success, None, requires_restart
    elif name == "claude-code":
        success, warning = install_claude_code(use_nvm_fallback=use_nvm_fallback)
        return success, warning, False
    else:
        raise ValueError(f"Unknown dependency: {name}")
