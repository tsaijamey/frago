"""Multi-device synchronization service.

Provides functionality for syncing Frago resources across multiple devices
using a GitHub repository.
"""

import asyncio
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional

from frago.init.config_manager import load_config, save_config
from frago.server.services.base import get_gh_command, run_subprocess
from frago.server.services.github_service import DEFAULT_SYNC_REPO_NAME

logger = logging.getLogger(__name__)


class MultiDeviceSyncService:
    """Service for multi-device sync operations via GitHub."""

    # Sync state management
    _sync_lock = threading.Lock()
    _sync_running = False
    _sync_result: Optional[Dict[str, Any]] = None
    _needs_cache_refresh = False

    @classmethod
    def create_sync_repo(
        cls, repo_name: str, private: bool = True
    ) -> Dict[str, Any]:
        """Create a new GitHub repository for syncing.

        Args:
            repo_name: Name of the repository to create
            private: Whether the repository should be private

        Returns:
            Dictionary with status and repo_url or error
        """
        try:
            # Build gh repo create command
            visibility = "--private" if private else "--public"
            result = run_subprocess(
                ["gh", "repo", "create", repo_name, visibility, "--confirm"],
                timeout=30,
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return {"status": "error", "error": error_msg.strip()}

            # Get the created repo URL
            # Output format: "https://github.com/username/repo-name"
            output = result.stdout.strip()
            repo_url = None

            # Try to extract URL from output
            match = re.search(r"https://github\.com/[^\s]+", output)
            if match:
                repo_url = match.group(0)
            else:
                # Try to get repo info
                info_result = run_subprocess(
                    ["gh", "repo", "view", repo_name, "--json", "url", "-q", ".url"],
                    timeout=10,
                )
                if info_result.returncode == 0:
                    repo_url = info_result.stdout.strip()

            if repo_url:
                # Save to config
                config = load_config()
                config.sync_repo_url = repo_url
                save_config(config)

                return {"status": "ok", "repo_url": repo_url}
            else:
                return {
                    "status": "error",
                    "error": "Repository created but failed to get URL",
                }

        except Exception as e:
            logger.error("Failed to create sync repo: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def list_user_repos(cls, limit: int = 100) -> Dict[str, Any]:
        """List user's GitHub repositories.

        Args:
            limit: Maximum number of repositories to return

        Returns:
            Dictionary with status and repos list or error
        """
        try:
            result = run_subprocess(
                [
                    "gh",
                    "repo",
                    "list",
                    "--limit",
                    str(limit),
                    "--json",
                    "name,nameWithOwner,description,isPrivate,sshUrl,url",
                ],
                timeout=30,
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return {"status": "error", "error": error_msg.strip()}

            import json

            repos_data = json.loads(result.stdout)
            repos = [
                {
                    "name": repo.get("name", ""),
                    "full_name": repo.get("nameWithOwner", repo.get("name", "")),
                    "description": repo.get("description"),
                    "private": repo.get("isPrivate", True),
                    "ssh_url": repo.get("sshUrl", ""),
                    "url": repo.get("url", ""),
                }
                for repo in repos_data
            ]

            return {"status": "ok", "repos": repos}

        except Exception as e:
            logger.error("Failed to list repos: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def select_existing_repo(cls, repo_url: str) -> Dict[str, Any]:
        """Select an existing repository for syncing.

        Args:
            repo_url: Repository URL (SSH or HTTPS)

        Returns:
            Dictionary with status and repo_url or error
        """
        try:
            # Validate the URL format
            if not repo_url:
                return {"status": "error", "error": "Repository URL is required"}

            # Convert SSH URL to HTTPS if needed for display
            display_url = repo_url
            if repo_url.startswith("git@github.com:"):
                # git@github.com:user/repo.git -> https://github.com/user/repo
                match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", repo_url)
                if match:
                    display_url = f"https://github.com/{match.group(1)}"

            # Save to config
            config = load_config()
            config.sync_repo_url = display_url
            save_config(config)

            return {"status": "ok", "repo_url": display_url}

        except Exception as e:
            logger.error("Failed to select repo: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def check_repo_visibility(cls) -> Dict[str, Any]:
        """Check if the configured sync repository is public or private.

        Returns:
            Dictionary with status and is_public flag or error
        """
        try:
            from frago.tools.sync_repo import get_sync_repo_url

            repo_url = get_sync_repo_url()

            if not repo_url:
                return {"status": "error", "error": "No sync repository configured"}

            # Extract repo path from URL
            match = re.search(r"github\.com[/:]([^/]+/[^/\s.]+)", repo_url)
            if not match:
                return {"status": "error", "error": "Invalid repository URL"}

            repo_path = match.group(1)

            # Query repo visibility
            result = run_subprocess(
                ["gh", "repo", "view", repo_path, "--json", "isPrivate", "-q", ".isPrivate"],
                timeout=10,
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return {"status": "error", "error": error_msg.strip()}

            is_private = result.stdout.strip().lower() == "true"
            return {"status": "ok", "is_public": not is_private}

        except Exception as e:
            logger.error("Failed to check repo visibility: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def start_sync(cls) -> Dict[str, Any]:
        """Start a sync operation in the background.

        Returns:
            Dictionary with status indicating sync started or error
        """
        with cls._sync_lock:
            if cls._sync_running:
                return {"status": "error", "error": "Sync already in progress"}

            cls._sync_running = True
            cls._sync_result = None

        # Start sync in background thread
        thread = threading.Thread(target=cls._do_sync, daemon=True)
        thread.start()

        return {"status": "ok", "message": "Sync started"}

    @classmethod
    def _do_sync(cls) -> None:
        """Execute sync operation (runs in background thread)."""
        try:
            from frago.tools.sync_repo import get_sync_repo_url, sync

            # Load configured repo URL (config + git remote fallback)
            repo_url = get_sync_repo_url()

            result = sync(repo_url=repo_url)

            with cls._sync_lock:
                cls._sync_result = {
                    "status": "ok" if result.success else "error",
                    "success": result.success,
                    "local_changes": len(result.local_changes),
                    "remote_updates": len(result.remote_updates),
                    "pushed_to_remote": result.pushed_to_remote,
                    "conflicts": result.conflicts,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "is_public_repo": result.is_public_repo,
                    "output": cls._format_sync_output(result),
                }
                if not result.success and result.errors:
                    cls._sync_result["error"] = "; ".join(result.errors)
                # Mark that cache refresh is needed after successful sync
                if result.success:
                    cls._needs_cache_refresh = True

        except Exception as e:
            logger.error("Sync failed: %s", e)
            with cls._sync_lock:
                cls._sync_result = {"status": "error", "error": str(e)}
        finally:
            with cls._sync_lock:
                cls._sync_running = False

    @classmethod
    def _format_sync_output(cls, result) -> str:
        """Format sync result as human-readable output."""
        lines = []

        if result.local_changes:
            lines.append(f"Local changes: {len(result.local_changes)} files")
            for change in result.local_changes[:5]:
                lines.append(f"  - {change.name} ({change.operation})")
            if len(result.local_changes) > 5:
                lines.append(f"  ... and {len(result.local_changes) - 5} more")

        if result.remote_updates:
            lines.append(f"Remote updates: {len(result.remote_updates)} files")
            for update in result.remote_updates[:5]:
                lines.append(f"  - {update.name} ({update.operation})")
            if len(result.remote_updates) > 5:
                lines.append(f"  ... and {len(result.remote_updates) - 5} more")

        if result.pushed_to_remote:
            lines.append("Changes pushed to remote repository")

        if result.warnings:
            for warning in result.warnings:
                lines.append(f"Warning: {warning}")

        if result.errors:
            for error in result.errors:
                lines.append(f"Error: {error}")

        if not lines:
            lines.append("No changes to sync")

        return "\n".join(lines)

    @classmethod
    def get_sync_result(cls) -> Dict[str, Any]:
        """Get the result of the current or last sync operation.

        Returns:
            Dictionary with sync status and result, including needs_refresh flag
        """
        with cls._sync_lock:
            if cls._sync_running:
                return {"status": "running"}

            if cls._sync_result is not None:
                result = cls._sync_result.copy()
                result["needs_refresh"] = cls._needs_cache_refresh
                return result

            return {"status": "idle", "message": "No sync has been run"}

    @classmethod
    def clear_refresh_flag(cls) -> None:
        """Clear the cache refresh flag after refresh has been triggered."""
        with cls._sync_lock:
            cls._needs_cache_refresh = False

    @classmethod
    async def sync_now(cls, auto_refresh: bool = True) -> Dict[str, Any]:
        """Execute sync synchronously and return result.

        This is a blocking operation that waits for sync to complete.

        Args:
            auto_refresh: If True, automatically refresh caches after successful sync

        Returns:
            Dictionary with sync result
        """
        start_result = cls.start_sync()
        if start_result.get("status") == "error":
            return start_result

        # Poll for completion
        while True:
            result = cls.get_sync_result()
            if result.get("status") != "running":
                # Auto-refresh caches if enabled and sync was successful
                if auto_refresh and result.get("needs_refresh"):
                    await cls._refresh_caches()
                    cls.clear_refresh_flag()
                return result
            await asyncio.sleep(0.5)

    @classmethod
    async def _refresh_caches(cls) -> None:
        """Refresh state caches after successful sync."""
        try:
            from frago.server.state import StateManager

            state_manager = StateManager.get_instance()
            if state_manager.is_initialized():
                await state_manager.refresh_config(broadcast=True)
                await state_manager.refresh_recipes(broadcast=True)
                await state_manager.refresh_skills(broadcast=True)
                logger.info("Caches refreshed after sync")
        except Exception as e:
            logger.warning("Failed to refresh caches after sync: %s", e)

    # Setup state management
    _setup_lock = threading.Lock()
    _setup_running = False
    _setup_result: Optional[Dict[str, Any]] = None

    @classmethod
    def setup_sync_repo(cls) -> Dict[str, Any]:
        """Start automatic setup of the frago-working-dir repository.

        This method:
        1. Gets the current GitHub username
        2. Checks if frago-working-dir repo exists
        3. Creates it as private if it doesn't exist
        4. Saves the repo URL to config
        5. Starts first sync

        Returns:
            Dictionary with status indicating setup started or error
        """
        with cls._setup_lock:
            if cls._setup_running:
                return {"status": "error", "error": "Setup already in progress"}

            cls._setup_running = True
            cls._setup_result = None

        # Start setup in background thread
        thread = threading.Thread(target=cls._do_setup, daemon=True)
        thread.start()

        return {"status": "ok", "message": "Setup started"}

    @classmethod
    def _do_setup(cls) -> None:
        """Execute repository setup (runs in background thread)."""
        try:
            # Step 1: Get current username
            user_result = run_subprocess(
                get_gh_command() + ["api", "user", "--jq", ".login"],
                timeout=10,
            )
            if user_result.returncode != 0:
                with cls._setup_lock:
                    cls._setup_result = {
                        "status": "error",
                        "error": "Failed to get GitHub username. Please ensure you're logged in.",
                    }
                return

            username = user_result.stdout.strip()
            repo_full_name = f"{username}/{DEFAULT_SYNC_REPO_NAME}"

            # Step 2: Check if repository exists
            check_result = run_subprocess(
                get_gh_command() + ["repo", "view", repo_full_name, "--json", "url", "-q", ".url"],
                timeout=10,
            )

            repo_url = None
            repo_created = False

            if check_result.returncode == 0:
                # Repository exists
                repo_url = check_result.stdout.strip()
                logger.info("Found existing repository: %s", repo_url)
            else:
                # Step 3: Create private repository
                logger.info("Creating repository: %s", DEFAULT_SYNC_REPO_NAME)
                create_result = run_subprocess(
                    get_gh_command() + [
                        "repo", "create", DEFAULT_SYNC_REPO_NAME,
                        "--private",
                        "--description", "frago resources sync repository",
                    ],
                    timeout=30,
                )

                if create_result.returncode != 0:
                    error_msg = create_result.stderr or create_result.stdout or "Unknown error"
                    with cls._setup_lock:
                        cls._setup_result = {
                            "status": "error",
                            "error": f"Failed to create repository: {error_msg.strip()}",
                        }
                    return

                # Get the created repo URL
                repo_created = True
                # Try to extract URL from output or query again
                url_match = re.search(r"https://github\.com/[^\s]+", create_result.stdout)
                if url_match:
                    repo_url = url_match.group(0)
                else:
                    # Query for the URL
                    view_result = run_subprocess(
                        get_gh_command() + ["repo", "view", repo_full_name, "--json", "url", "-q", ".url"],
                        timeout=10,
                    )
                    if view_result.returncode == 0:
                        repo_url = view_result.stdout.strip()
                    else:
                        repo_url = f"https://github.com/{repo_full_name}"

            if not repo_url:
                with cls._setup_lock:
                    cls._setup_result = {
                        "status": "error",
                        "error": "Failed to get repository URL",
                    }
                return

            # Step 4: Save to config
            config = load_config()
            config.sync_repo_url = repo_url
            save_config(config)

            # Step 5: Start first sync
            with cls._setup_lock:
                cls._setup_result = {
                    "status": "syncing",
                    "repo_url": repo_url,
                    "username": username,
                    "created": repo_created,
                    "message": "Repository configured, starting sync...",
                }

            # Run sync
            from frago.tools.sync_repo import sync

            sync_result = sync(repo_url=repo_url)

            with cls._setup_lock:
                cls._setup_result = {
                    "status": "ok" if sync_result.success else "error",
                    "repo_url": repo_url,
                    "username": username,
                    "created": repo_created,
                    "sync_success": sync_result.success,
                    "local_changes": len(sync_result.local_changes),
                    "remote_updates": len(sync_result.remote_updates),
                    "pushed_to_remote": sync_result.pushed_to_remote,
                }
                if not sync_result.success and sync_result.errors:
                    cls._setup_result["error"] = "; ".join(sync_result.errors)
                if sync_result.warnings:
                    cls._setup_result["warnings"] = sync_result.warnings

                # Mark that cache refresh is needed
                if sync_result.success:
                    cls._needs_cache_refresh = True

        except Exception as e:
            logger.error("Setup failed: %s", e)
            with cls._setup_lock:
                cls._setup_result = {"status": "error", "error": str(e)}
        finally:
            with cls._setup_lock:
                cls._setup_running = False

    @classmethod
    def get_setup_result(cls) -> Dict[str, Any]:
        """Get the result of the current or last setup operation.

        Returns:
            Dictionary with setup status and result
        """
        with cls._setup_lock:
            if cls._setup_running:
                if cls._setup_result and cls._setup_result.get("status") == "syncing":
                    return cls._setup_result.copy()
                return {"status": "running", "message": "Setup in progress..."}

            if cls._setup_result is not None:
                result = cls._setup_result.copy()
                result["needs_refresh"] = cls._needs_cache_refresh
                return result

            return {"status": "idle", "message": "No setup has been run"}

    @classmethod
    def check_repo_exists(cls, repo_name: str = DEFAULT_SYNC_REPO_NAME) -> Dict[str, Any]:
        """Check if the sync repository exists for the current user.

        Args:
            repo_name: Repository name to check

        Returns:
            Dictionary with:
            - status: 'ok' or 'error'
            - exists: Whether the repository exists
            - repo_url: Repository URL if exists
            - username: Current GitHub username
            - error: Error message if any
        """
        try:
            # Get current username
            user_result = run_subprocess(
                get_gh_command() + ["api", "user", "--jq", ".login"],
                timeout=10,
            )
            if user_result.returncode != 0:
                return {
                    "status": "error",
                    "error": "Failed to get GitHub username",
                }

            username = user_result.stdout.strip()
            repo_full_name = f"{username}/{repo_name}"

            # Check if repository exists
            check_result = run_subprocess(
                get_gh_command() + ["repo", "view", repo_full_name, "--json", "url,isPrivate"],
                timeout=10,
            )

            if check_result.returncode == 0:
                try:
                    repo_info = json.loads(check_result.stdout)
                    return {
                        "status": "ok",
                        "exists": True,
                        "repo_url": repo_info.get("url"),
                        "is_private": repo_info.get("isPrivate", True),
                        "username": username,
                    }
                except json.JSONDecodeError:
                    return {
                        "status": "ok",
                        "exists": True,
                        "repo_url": f"https://github.com/{repo_full_name}",
                        "username": username,
                    }
            else:
                return {
                    "status": "ok",
                    "exists": False,
                    "username": username,
                }

        except Exception as e:
            logger.error("Failed to check repo: %s", e)
            return {
                "status": "error",
                "error": str(e),
            }
