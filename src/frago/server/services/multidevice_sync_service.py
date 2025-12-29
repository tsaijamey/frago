"""Multi-device synchronization service.

Provides functionality for syncing Frago resources across multiple devices
using a GitHub repository.
"""

import asyncio
import logging
import re
import threading
from typing import Any, Dict, List, Optional

from frago.init.config_manager import load_config, save_config
from frago.server.services.base import run_subprocess

logger = logging.getLogger(__name__)


class MultiDeviceSyncService:
    """Service for multi-device sync operations via GitHub."""

    # Sync state management
    _sync_lock = threading.Lock()
    _sync_running = False
    _sync_result: Optional[Dict[str, Any]] = None

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
            config = load_config()
            repo_url = config.sync_repo_url

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
            from frago.tools.sync_repo import sync

            result = sync()

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
            Dictionary with sync status and result
        """
        with cls._sync_lock:
            if cls._sync_running:
                return {"status": "running"}

            if cls._sync_result is not None:
                return cls._sync_result

            return {"status": "idle", "message": "No sync has been run"}

    @classmethod
    async def sync_now(cls) -> Dict[str, Any]:
        """Execute sync synchronously and return result.

        This is a blocking operation that waits for sync to complete.

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
                return result
            await asyncio.sleep(0.5)
