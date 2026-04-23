"""Claude Code one-shot installer.

Invoked by `frago init`. Detects whether Anthropic's official install script
(`https://claude.ai/install.sh`) is reachable. If reachable and the host has
the prerequisites (bash + curl on Unix; Windows is unsupported by the official
script), streams the script through bash. Otherwise prints manual install
guidance and returns control to init so the rest of initialization continues.

The function set here is intentionally small and side-effect-isolated — all
three callables operate without touching init state.
"""

import platform
import shutil
import subprocess
import urllib.error
import urllib.request

import click

CLAUDE_INSTALL_URL = "https://claude.ai/install.sh"

# Anthropic's CDN rejects requests without a User-Agent (HTTP 403). Any
# non-empty UA works in practice; we identify as frago-init so requests are
# attributable if Anthropic ever looks at their logs.
_PROBE_USER_AGENT = "frago-init (https://github.com/tsaijamey/frago)"


def is_claude_official_reachable(timeout: float = 5.0) -> bool:
    """Return True if the Claude Code official installer endpoint responds.

    A HEAD request with a short timeout; any exception or non-success status
    returns False. We don't try to distinguish DNS failure, TLS failure, and
    HTTP 5xx — any of them means "skip the auto path".
    """
    req = urllib.request.Request(
        CLAUDE_INSTALL_URL,
        method="HEAD",
        headers={"User-Agent": _PROBE_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


def install_claude_code_via_official() -> tuple[bool, str]:
    """Run `curl -fsSL https://claude.ai/install.sh | bash`.

    Returns (success, message). Pre-checks:
    - Windows is unsupported by the upstream script (it installs into
      POSIX-style paths). Caller should fall back to manual hint.
    - bash and curl must be on PATH.
    """
    if platform.system() == "Windows":
        return (False, "Windows is not supported by the official install script")

    if not shutil.which("bash"):
        return (False, "bash not found on PATH")
    if not shutil.which("curl"):
        return (False, "curl not found on PATH")

    cmd = ["bash", "-c", f"curl -fsSL {CLAUDE_INSTALL_URL} | bash"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return (False, "Installation timed out after 300 seconds")
    except OSError as e:
        return (False, f"Failed to spawn bash: {e}")

    if result.returncode == 0:
        return (True, "installed")

    tail = (result.stderr or result.stdout or "").strip()[-400:]
    return (False, f"Installer exited with code {result.returncode}\n{tail}")


def print_manual_install_hint() -> None:
    """Print platform-specific manual install guidance.

    Shown when the official script is unreachable or unsupported. Guidance is
    intentionally npm-based because that's the universal fallback — users who
    can't reach claude.ai still usually have access to nodejs.org or their
    distro's package manager.
    """
    system = platform.system()
    click.echo()
    click.secho(
        "Unable to use the official Claude Code installer. Please install manually:",
        fg="yellow",
    )
    click.echo()
    if system == "Windows":
        click.echo("  1. Install Node.js (LTS):")
        click.echo("       winget install OpenJS.NodeJS.LTS")
        click.echo("     or download from https://nodejs.org/")
        click.echo()
        click.echo("  2. Install Claude Code via npm:")
        click.echo("       npm install -g @anthropic-ai/claude-code")
    else:
        click.echo("  1. Install Node.js (ships with npm), e.g.:")
        click.echo("       macOS:   brew install node")
        click.echo("       Ubuntu:  sudo apt install nodejs npm")
        click.echo("     or install nvm: https://github.com/nvm-sh/nvm")
        click.echo()
        click.echo("  2. Install Claude Code via npm:")
        click.echo("       npm install -g @anthropic-ai/claude-code")
    click.echo()
    click.echo("Then re-run:")
    click.secho("    frago init", fg="cyan")
    click.echo()
