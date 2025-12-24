"""GitHub CLI integration service.

Provides functionality for checking gh CLI status and initiating authentication.
"""

import logging
import platform
import re
import subprocess
from typing import Any, Dict

from frago.server.services.base import run_subprocess

logger = logging.getLogger(__name__)


class GitHubService:
    """Service for GitHub CLI operations."""

    @staticmethod
    def check_gh_cli() -> Dict[str, Any]:
        """Check gh CLI installation and login status.

        Returns:
            Dictionary with:
            - installed: Whether gh CLI is installed
            - version: Version string or None
            - authenticated: Whether user is logged in
            - username: GitHub username or None
        """
        result = {
            "installed": False,
            "version": None,
            "authenticated": False,
            "username": None,
        }

        # Check if gh is installed
        try:
            version_result = run_subprocess(["gh", "--version"], timeout=5)
            if version_result.returncode == 0:
                result["installed"] = True
                # Parse version number (format: "gh version 2.40.1 (2023-12-13)")
                match = re.search(r"gh version ([\d.]+)", version_result.stdout)
                if match:
                    result["version"] = match.group(1)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("gh CLI not found: %s", e)
            return result
        except Exception as e:
            logger.warning("Failed to check gh version: %s", e)
            return result

        # Check login status
        if result["installed"]:
            try:
                auth_result = run_subprocess(["gh", "auth", "status"], timeout=5)
                # gh auth status returns 0 if logged in
                if auth_result.returncode == 0:
                    result["authenticated"] = True
                    # Parse username from output
                    # Format: "Logged in to github.com account USERNAME (keyring)"
                    # Or: "Logged in to github.com as USERNAME"
                    output = auth_result.stderr + auth_result.stdout
                    match = re.search(
                        r"Logged in to github\.com (?:as|account) ([^\s(]+)",
                        output,
                    )
                    if match:
                        result["username"] = match.group(1)
            except subprocess.TimeoutExpired:
                logger.debug("gh auth status timed out")
            except Exception as e:
                logger.warning("Failed to check gh auth status: %s", e)

        return result

    @staticmethod
    def auth_login() -> Dict[str, Any]:
        """Execute gh auth login in external terminal.

        Opens a terminal window for the user to complete authentication.

        Returns:
            Dictionary with 'status' and 'message' or 'error'.
        """
        try:
            system = platform.system()

            if system == "Linux":
                return GitHubService._auth_login_linux()
            elif system == "Darwin":
                return GitHubService._auth_login_macos()
            elif system == "Windows":
                return GitHubService._auth_login_windows()
            else:
                return {
                    "status": "error",
                    "error": f"Unsupported operating system: {system}",
                }

        except Exception as e:
            logger.error("Failed to initiate gh auth login: %s", e)
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _auth_login_linux() -> Dict[str, Any]:
        """Open gh auth login on Linux."""
        # Try x-terminal-emulator first
        try:
            subprocess.Popen(["x-terminal-emulator", "-e", "gh", "auth", "login"])
            return {
                "status": "ok",
                "message": "Terminal opened, please complete login in terminal",
            }
        except FileNotFoundError:
            pass

        # Fall back to gnome-terminal
        try:
            subprocess.Popen(["gnome-terminal", "--", "gh", "auth", "login"])
            return {
                "status": "ok",
                "message": "Terminal opened, please complete login in terminal",
            }
        except FileNotFoundError:
            pass

        return {
            "status": "error",
            "error": "No available terminal emulator found (x-terminal-emulator, gnome-terminal)",
        }

    @staticmethod
    def _auth_login_macos() -> Dict[str, Any]:
        """Open gh auth login on macOS."""
        script = 'tell application "Terminal" to do script "gh auth login; exit"'
        subprocess.run(["osascript", "-e", script], check=False)
        return {
            "status": "ok",
            "message": "Terminal opened, please complete login in terminal",
        }

    @staticmethod
    def _auth_login_windows() -> Dict[str, Any]:
        """Open gh auth login on Windows."""
        # Prefer PowerShell (default in Windows 10/11)
        try:
            subprocess.Popen(
                ["powershell", "-NoExit", "-Command", "gh auth login"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return {
                "status": "ok",
                "message": "PowerShell window opened, please complete login in window",
            }
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug("PowerShell failed: %s, trying cmd", e)

        # Fall back to cmd
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "cmd", "/k", "gh auth login"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return {
                "status": "ok",
                "message": "Command Prompt window opened, please complete login in window",
            }
        except Exception as e:
            return {"status": "error", "error": f"Unable to open terminal window: {e}"}
