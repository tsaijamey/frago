"""Official resource synchronization service.

Provides functionality for syncing official frago resources (commands, skills)
from the GitHub repository to the user's local ~/.claude/ directory.
"""

import fnmatch
import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from frago.init.config_manager import load_config, save_config

logger = logging.getLogger(__name__)


class OfficialResourceSyncService:
    """Service for syncing official resources from GitHub."""

    REPO_OWNER = "tsaijamey"
    REPO_NAME = "frago"
    BRANCH = "main"
    REQUEST_TIMEOUT = 60

    # Mapping from GitHub paths to local paths
    RESOURCE_MAPPINGS = {
        "commands": {
            "source": "src/frago/resources/commands",
            "target": Path.home() / ".claude" / "commands",
            "patterns": ["frago.*.md", "frago"],  # files and directory
        },
        "skills": {
            "source": "src/frago/resources/skills",
            "target": Path.home() / ".claude" / "skills",
            "patterns": ["frago-*"],  # directories matching pattern
        },
    }

    # Sync state management
    _sync_lock = threading.Lock()
    _sync_running = False
    _sync_result: Optional[Dict[str, Any]] = None

    @classmethod
    def get_github_api_url(cls, path: str) -> str:
        """Get GitHub API URL for a path."""
        return f"https://api.github.com/repos/{cls.REPO_OWNER}/{cls.REPO_NAME}/contents/{path}?ref={cls.BRANCH}"

    @classmethod
    def get_raw_url(cls, path: str) -> str:
        """Get raw content URL for a file."""
        return f"https://raw.githubusercontent.com/{cls.REPO_OWNER}/{cls.REPO_NAME}/{cls.BRANCH}/{path}"

    @classmethod
    def _fetch_directory_contents(cls, path: str) -> List[Dict[str, Any]]:
        """Fetch directory contents from GitHub API."""
        url = cls.get_github_api_url(path)
        response = requests.get(url, timeout=cls.REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @classmethod
    def _download_file(cls, github_path: str, local_path: Path) -> None:
        """Download a file from GitHub raw content."""
        url = cls.get_raw_url(github_path)
        response = requests.get(url, timeout=cls.REQUEST_TIMEOUT)
        response.raise_for_status()

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(response.content)
        logger.debug("Downloaded: %s -> %s", github_path, local_path)

    @classmethod
    def _sync_directory(cls, github_path: str, local_path: Path) -> Dict[str, int]:
        """Recursively sync a directory from GitHub to local."""
        stats = {"files": 0, "dirs": 0}

        contents = cls._fetch_directory_contents(github_path)

        for item in contents:
            item_name = item["name"]
            item_path = item["path"]
            item_type = item["type"]

            if item_type == "file":
                cls._download_file(item_path, local_path / item_name)
                stats["files"] += 1
            elif item_type == "dir":
                sub_stats = cls._sync_directory(item_path, local_path / item_name)
                stats["files"] += sub_stats["files"]
                stats["dirs"] += sub_stats["dirs"] + 1

        return stats

    @classmethod
    def _sync_resource_type(
        cls, resource_type: str, mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Sync a specific resource type (commands or skills)."""
        source_path = mapping["source"]
        target_path = mapping["target"]
        patterns = mapping["patterns"]

        result = {
            "type": resource_type,
            "files_synced": 0,
            "dirs_synced": 0,
            "items": [],
        }

        try:
            contents = cls._fetch_directory_contents(source_path)

            for item in contents:
                item_name = item["name"]
                item_path = item["path"]
                item_type = item["type"]

                # Check if item matches any pattern
                matches = any(fnmatch.fnmatch(item_name, p) for p in patterns)
                if not matches:
                    continue

                local_item_path = target_path / item_name

                if item_type == "file":
                    cls._download_file(item_path, local_item_path)
                    result["files_synced"] += 1
                    result["items"].append(item_name)
                elif item_type == "dir":
                    # Remove existing directory to ensure clean sync
                    if local_item_path.exists():
                        shutil.rmtree(local_item_path)

                    stats = cls._sync_directory(item_path, local_item_path)
                    result["files_synced"] += stats["files"]
                    result["dirs_synced"] += stats["dirs"] + 1
                    result["items"].append(f"{item_name}/")

        except Exception as e:
            logger.error("Failed to sync %s: %s", resource_type, e)
            result["error"] = str(e)

        return result

    @classmethod
    def _get_latest_commit(cls) -> Optional[str]:
        """Get the latest commit SHA for the branch."""
        url = f"https://api.github.com/repos/{cls.REPO_OWNER}/{cls.REPO_NAME}/commits/{cls.BRANCH}"
        try:
            response = requests.get(url, timeout=cls.REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json().get("sha")
        except Exception as e:
            logger.error("Failed to get latest commit: %s", e)
            return None

    @classmethod
    def _do_sync(cls) -> Dict[str, Any]:
        """Perform the actual sync operation."""
        result = {
            "status": "ok",
            "started_at": datetime.now().isoformat(),
            "commands": None,
            "skills": None,
            "commit": None,
        }

        # Get latest commit SHA
        commit_sha = cls._get_latest_commit()
        result["commit"] = commit_sha

        # Sync each resource type
        for resource_type, mapping in cls.RESOURCE_MAPPINGS.items():
            sync_result = cls._sync_resource_type(resource_type, mapping)
            result[resource_type] = sync_result

            if sync_result.get("error"):
                result["status"] = "partial"

        result["completed_at"] = datetime.now().isoformat()

        # Update config with sync info
        try:
            config = load_config()
            config.official_resource_last_sync = datetime.now()
            config.official_resource_last_commit = commit_sha
            save_config(config)
        except Exception as e:
            logger.error("Failed to save sync config: %s", e)

        return result

    @classmethod
    def start_sync(cls) -> Dict[str, Any]:
        """Start a sync operation in background.

        Returns immediately with status. Use get_sync_result() to poll for completion.
        """
        with cls._sync_lock:
            if cls._sync_running:
                return {"status": "running", "message": "Sync already in progress"}

            cls._sync_running = True
            cls._sync_result = None

        def run_sync():
            try:
                result = cls._do_sync()
                with cls._sync_lock:
                    cls._sync_result = result
            except Exception as e:
                logger.error("Sync failed: %s", e)
                with cls._sync_lock:
                    cls._sync_result = {"status": "error", "error": str(e)}
            finally:
                with cls._sync_lock:
                    cls._sync_running = False

        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()

        return {"status": "started", "message": "Sync started"}

    @classmethod
    def get_sync_result(cls) -> Dict[str, Any]:
        """Get the status/result of the current or last sync operation."""
        with cls._sync_lock:
            if cls._sync_running:
                return {"status": "running"}

            if cls._sync_result:
                return cls._sync_result

            return {"status": "idle"}

    @classmethod
    def get_sync_status(cls) -> Dict[str, Any]:
        """Get the current sync configuration and status."""
        config = load_config()

        return {
            "enabled": config.official_resource_sync_enabled,
            "last_sync": (
                config.official_resource_last_sync.isoformat()
                if config.official_resource_last_sync
                else None
            ),
            "last_commit": config.official_resource_last_commit,
            "repo": f"{cls.REPO_OWNER}/{cls.REPO_NAME}",
            "branch": cls.BRANCH,
        }

    @classmethod
    def set_sync_enabled(cls, enabled: bool) -> Dict[str, Any]:
        """Enable or disable auto-sync on startup."""
        config = load_config()
        config.official_resource_sync_enabled = enabled
        save_config(config)

        return {"status": "ok", "enabled": enabled}

    @classmethod
    def check_for_updates(cls) -> Dict[str, Any]:
        """Check if there are updates available without syncing."""
        config = load_config()
        current_commit = config.official_resource_last_commit

        latest_commit = cls._get_latest_commit()

        has_updates = latest_commit and latest_commit != current_commit

        return {
            "has_updates": has_updates,
            "current_commit": current_commit,
            "latest_commit": latest_commit,
        }
