"""Git helpers shared across CLI commands.

Hosts `_ensure_git_user_config` so `cli/recipe_commands.py` can ensure a
usable git identity for the community recipe PR flow. Keep this module
narrowly scoped to git-credential helpers; recipe implementations should
own their own git logic.
"""

import subprocess
from pathlib import Path
from typing import Any

from frago.compat import get_windows_subprocess_kwargs


def _get_subprocess_kwargs() -> dict[str, Any]:
    """Get subprocess kwargs with Windows hidden window support."""
    return get_windows_subprocess_kwargs()


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Execute git command."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=check,
        **_get_subprocess_kwargs(),
    )


def _ensure_git_user_config(repo_dir: Path) -> tuple[bool, str]:
    """Ensure git user.name and user.email are configured.

    If not configured, fetch from gh CLI and set locally.

    Args:
        repo_dir: Git repository directory

    Returns:
        (success, error_message) tuple
    """
    # Check if already configured (local or global)
    name_result = _run_git(["config", "user.name"], repo_dir, check=False)
    email_result = _run_git(["config", "user.email"], repo_dir, check=False)

    if name_result.returncode == 0 and email_result.returncode == 0 and name_result.stdout.strip() and email_result.stdout.strip():
        return True, ""

    # Fetch from gh api user
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login,.email"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=10,
            **_get_subprocess_kwargs(),
        )
        if result.returncode != 0:
            return False, "Failed to get user info from gh CLI. Run 'gh auth login' first."

        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return False, "Failed to parse user info from gh CLI"

        username = lines[0].strip()
        email = lines[1].strip()

        # Handle null/empty email (GitHub privacy setting)
        if not email or email == "null":
            email = f"{username}@users.noreply.github.com"

        # Set local git config (not global)
        _run_git(["config", "user.name", username], repo_dir)
        _run_git(["config", "user.email", email], repo_dir)

        return True, ""
    except FileNotFoundError:
        return False, "gh CLI not found. Please install GitHub CLI first."
    except subprocess.TimeoutExpired:
        return False, "gh CLI timed out"
