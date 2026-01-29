"""GitHub CLI integration service.

Provides functionality for checking gh CLI status and initiating authentication.
"""

import logging
import platform
import re
import subprocess
import threading
from typing import Any, Dict, Optional

from frago.server.services.base import get_gh_command, run_subprocess

logger = logging.getLogger(__name__)

# Default sync repository name
DEFAULT_SYNC_REPO_NAME = "frago-working-dir"


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
            version_result = run_subprocess(get_gh_command() + ["--version"], timeout=5)
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
                auth_result = run_subprocess(get_gh_command() + ["auth", "status"], timeout=5)
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

    # Repository to star
    FRAGO_REPO = "tsaijamey/frago"

    @staticmethod
    def check_starred() -> Dict[str, Any]:
        """Check if user has starred the frago repository.

        Returns:
            Dictionary with:
            - status: 'ok' or 'error'
            - is_starred: True/False/None (None if not authenticated)
            - gh_configured: Whether gh CLI is authenticated
            - error: Error message if any
        """
        # First check if gh is authenticated
        cli_status = GitHubService.check_gh_cli()
        if not cli_status["authenticated"]:
            return {
                "status": "ok",
                "is_starred": None,
                "gh_configured": False,
            }

        # Check if starred using gh api
        # Returns 204 if starred, 404 if not starred
        try:
            result = run_subprocess(
                get_gh_command() + ["api", f"/user/starred/{GitHubService.FRAGO_REPO}"],
                timeout=10,
            )
            # gh api returns 0 for 204 (starred), non-zero for 404 (not starred)
            is_starred = result.returncode == 0
            return {
                "status": "ok",
                "is_starred": is_starred,
                "gh_configured": True,
            }
        except subprocess.TimeoutExpired:
            logger.debug("gh api starred check timed out")
            return {
                "status": "error",
                "error": "Request timed out",
                "gh_configured": True,
            }
        except Exception as e:
            logger.warning("Failed to check starred status: %s", e)
            return {
                "status": "error",
                "error": str(e),
                "gh_configured": True,
            }

    @staticmethod
    def toggle_star(star: bool) -> Dict[str, Any]:
        """Star or unstar the frago repository.

        Args:
            star: True to star, False to unstar

        Returns:
            Dictionary with:
            - status: 'ok' or 'error'
            - is_starred: Current star status after operation
            - error: Error message if any
        """
        method = "PUT" if star else "DELETE"
        try:
            result = run_subprocess(
                get_gh_command() + ["api", "-X", method, f"/user/starred/{GitHubService.FRAGO_REPO}"],
                timeout=10,
            )
            if result.returncode == 0:
                return {
                    "status": "ok",
                    "is_starred": star,
                }
            else:
                return {
                    "status": "error",
                    "is_starred": not star,
                    "error": result.stderr or "Failed to update star status",
                }
        except subprocess.TimeoutExpired:
            logger.debug("gh api star toggle timed out")
            return {
                "status": "error",
                "error": "Request timed out",
            }
        except Exception as e:
            logger.warning("Failed to toggle star: %s", e)
            return {
                "status": "error",
                "error": str(e),
            }

    # Cached token to avoid repeated subprocess calls
    _cached_token: str | None = None
    _token_checked: bool = False

    @classmethod
    def get_auth_token(cls) -> str | None:
        """Get GitHub auth token from gh CLI.

        Returns:
            Token string or None if not authenticated.
        """
        # Return cached result if already checked
        if cls._token_checked:
            return cls._cached_token

        cls._token_checked = True

        try:
            result = run_subprocess(
                get_gh_command() + ["auth", "token"],
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                cls._cached_token = result.stdout.strip()
                logger.debug("GitHub token obtained from gh CLI")
                return cls._cached_token
        except subprocess.TimeoutExpired:
            logger.debug("gh auth token timed out")
        except FileNotFoundError:
            logger.debug("gh CLI not found")
        except Exception as e:
            logger.debug("Failed to get gh token: %s", e)

        return None

    @classmethod
    def clear_token_cache(cls) -> None:
        """Clear cached token (call after auth state changes)."""
        cls._cached_token = None
        cls._token_checked = False

    @classmethod
    def get_auth_headers(cls) -> Dict[str, str]:
        """Get HTTP headers with GitHub authentication if available.

        Returns:
            Headers dict with Authorization if token available.
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "frago",
        }
        token = cls.get_auth_token()
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    # Web login state management
    _login_process: Optional[subprocess.Popen] = None
    _login_code: Optional[str] = None
    _login_url: Optional[str] = None
    _login_lock = threading.Lock()

    @classmethod
    def auth_login_web(cls) -> Dict[str, Any]:
        """Start web-based GitHub authentication and capture the device code.

        Executes `gh auth login --web --git-protocol https` and captures
        the one-time code from stdout for display in the web UI.

        The output format is:
        "First copy your one-time code: XXXX-XXXX"
        "Open this URL to continue in your web browser: https://github.com/login/device"

        Returns:
            Dictionary with:
            - status: 'ok' or 'error'
            - code: The one-time device code (e.g., "2741-EE59")
            - url: The GitHub device login URL
            - error: Error message if any
        """
        with cls._login_lock:
            # Terminate any existing login process
            if cls._login_process is not None:
                try:
                    if cls._login_process.poll() is None:
                        cls._login_process.terminate()
                        cls._login_process.wait(timeout=2)
                except Exception:
                    pass
                cls._login_process = None
                cls._login_code = None
                cls._login_url = None

        try:
            # Start gh auth login in web mode
            # Note: We need to read output line by line to capture the code
            # before the process blocks waiting for user to complete auth
            process = subprocess.Popen(
                get_gh_command() + ["auth", "login", "--web", "--git-protocol", "https"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,  # Line buffered
            )

            code = None
            url = None
            output_lines = []

            # Read output until we find both code and URL, or process ends
            # The gh CLI outputs the code and URL before blocking for auth
            import select
            import time

            start_time = time.time()
            timeout = 30  # seconds

            while time.time() - start_time < timeout:
                # Check if there's data to read (non-blocking on Unix)
                if process.stdout is None:
                    break

                line = process.stdout.readline()
                if not line:
                    # Check if process has ended
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                output_lines.append(line)
                logger.debug("gh auth output: %s", line.strip())

                # Parse one-time code
                code_match = re.search(
                    r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})",
                    line,
                    re.IGNORECASE,
                )
                if code_match:
                    code = code_match.group(1).upper()

                # Parse URL
                url_match = re.search(
                    r"(https://github\.com/login/device)",
                    line,
                )
                if url_match:
                    url = url_match.group(1)

                # If we have both, we're done reading
                if code and url:
                    break

            if not code:
                # Process might have failed
                remaining = process.stdout.read() if process.stdout else ""
                output_lines.append(remaining)
                full_output = "".join(output_lines)
                logger.warning("Failed to capture device code. Output: %s", full_output)

                # Check if there's an error
                if process.poll() is not None and process.returncode != 0:
                    return {
                        "status": "error",
                        "error": f"gh auth login failed: {full_output.strip()}",
                    }

                return {
                    "status": "error",
                    "error": "Failed to capture device code from gh CLI",
                }

            # Store state for later status checks
            with cls._login_lock:
                cls._login_process = process
                cls._login_code = code
                cls._login_url = url or "https://github.com/login/device"

            # Clear token cache since auth state is changing
            cls.clear_token_cache()

            # Manually open browser since subprocess may not trigger it
            import webbrowser
            try:
                webbrowser.open(cls._login_url)
                logger.info("Opened browser for GitHub device login: %s", cls._login_url)
            except Exception as e:
                logger.warning("Failed to open browser: %s", e)

            return {
                "status": "ok",
                "code": code,
                "url": cls._login_url,
            }

        except FileNotFoundError:
            return {
                "status": "error",
                "error": "gh CLI not found. Please install GitHub CLI first.",
            }
        except Exception as e:
            logger.error("Failed to start web login: %s", e)
            return {
                "status": "error",
                "error": str(e),
            }

    @classmethod
    def check_auth_login_complete(cls) -> Dict[str, Any]:
        """Check if the web login process has completed.

        Returns:
            Dictionary with:
            - status: 'ok' or 'error'
            - completed: Whether the login process has finished
            - authenticated: Whether user is now authenticated
            - username: GitHub username if authenticated
            - error: Error message if login failed
        """
        with cls._login_lock:
            if cls._login_process is None:
                # No login in progress, check current auth status
                cli_status = cls.check_gh_cli()
                return {
                    "status": "ok",
                    "completed": True,
                    "authenticated": cli_status.get("authenticated", False),
                    "username": cli_status.get("username"),
                }

            # Check if process has completed
            returncode = cls._login_process.poll()

            if returncode is None:
                # Still running, waiting for user to complete auth in browser
                return {
                    "status": "ok",
                    "completed": False,
                    "authenticated": False,
                    "username": None,
                }

            # Process completed
            process = cls._login_process
            cls._login_process = None
            cls._login_code = None
            cls._login_url = None

        # Clear token cache
        cls.clear_token_cache()

        if returncode == 0:
            # Login successful, get user info
            cli_status = cls.check_gh_cli()
            return {
                "status": "ok",
                "completed": True,
                "authenticated": cli_status.get("authenticated", False),
                "username": cli_status.get("username"),
            }
        else:
            # Login failed or was cancelled
            # Try to get error message
            error_msg = "Login was cancelled or failed"
            try:
                if process.stdout:
                    remaining = process.stdout.read()
                    if remaining:
                        error_msg = remaining.strip()
            except Exception:
                pass

            return {
                "status": "error",
                "completed": True,
                "authenticated": False,
                "username": None,
                "error": error_msg,
            }

    @classmethod
    def cancel_auth_login(cls) -> Dict[str, Any]:
        """Cancel any ongoing web login process.

        Returns:
            Dictionary with status.
        """
        with cls._login_lock:
            if cls._login_process is not None:
                try:
                    if cls._login_process.poll() is None:
                        cls._login_process.terminate()
                        cls._login_process.wait(timeout=2)
                except Exception as e:
                    logger.warning("Error terminating login process: %s", e)
                finally:
                    cls._login_process = None
                    cls._login_code = None
                    cls._login_url = None

        return {"status": "ok"}

    @classmethod
    def get_current_user(cls) -> Dict[str, Any]:
        """Get the currently authenticated GitHub username.

        Returns:
            Dictionary with:
            - status: 'ok' or 'error'
            - username: GitHub username or None
            - error: Error message if any
        """
        try:
            result = run_subprocess(
                get_gh_command() + ["api", "user", "--jq", ".login"],
                timeout=10,
            )
            if result.returncode == 0:
                username = result.stdout.strip()
                return {
                    "status": "ok",
                    "username": username,
                }
            else:
                return {
                    "status": "error",
                    "error": result.stderr or "Failed to get username",
                }
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": "Request timed out",
            }
        except Exception as e:
            logger.error("Failed to get current user: %s", e)
            return {
                "status": "error",
                "error": str(e),
            }
