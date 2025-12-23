"""Adapter for existing FragoGuiApi to HTTP endpoints.

This module wraps the existing pywebview API methods for use
with HTTP endpoints, maintaining 100% compatibility with
existing business logic.
"""

from typing import Any, Dict, List, Optional

from frago.gui.api import FragoGuiApi
from frago.gui.models import RecipeItem, TaskItem, TaskDetail, UserConfig


class FragoApiAdapter:
    """Adapter that wraps FragoGuiApi for HTTP endpoint use.

    This class provides a thread-safe interface to the existing
    GUI API methods, handling the conversion between HTTP request/response
    formats and the internal API format.
    """

    _instance: Optional["FragoApiAdapter"] = None
    _api: Optional[FragoGuiApi] = None

    @classmethod
    def get_instance(cls) -> "FragoApiAdapter":
        """Get singleton instance of the adapter.

        Returns:
            The adapter instance
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialize the adapter with a FragoGuiApi instance."""
        if FragoApiAdapter._api is None:
            FragoApiAdapter._api = FragoGuiApi()
        self._api = FragoApiAdapter._api

    # ============================================================
    # Recipe Methods
    # ============================================================

    def get_recipes(self) -> List[Dict[str, Any]]:
        """Get list of all recipes.

        Returns:
            List of recipe dictionaries
        """
        result = self._api.get_recipes()
        if isinstance(result, dict) and "recipes" in result:
            return result["recipes"]
        return result if isinstance(result, list) else []

    def get_recipe(self, name: str) -> Optional[Dict[str, Any]]:
        """Get recipe details by name.

        Args:
            name: Recipe name

        Returns:
            Recipe dictionary or None if not found
        """
        result = self._api.get_recipe_detail(name)
        if isinstance(result, dict) and result.get("error"):
            return None
        return result

    def run_recipe(
        self, name: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute a recipe.

        Args:
            name: Recipe name
            params: Recipe parameters
            timeout: Execution timeout in seconds

        Returns:
            Execution result dictionary
        """
        return self._api.run_recipe(name, params or {}, timeout or 120)

    # ============================================================
    # Skill Methods
    # ============================================================

    def get_skills(self) -> List[Dict[str, Any]]:
        """Get list of all skills.

        Returns:
            List of skill dictionaries
        """
        result = self._api.get_skills()
        return result if isinstance(result, list) else []

    # ============================================================
    # Task Methods
    # ============================================================

    def get_tasks(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> Dict[str, Any]:
        """Get list of tasks with pagination.

        Args:
            status: Filter by status (running, completed, error, cancelled)
            limit: Maximum number of tasks to return
            offset: Number of tasks to skip

        Returns:
            Dictionary with tasks list and total count
        """
        # FragoGuiApi.get_tasks() returns List[Dict] directly, and has no offset parameter
        # Request more items to handle offset in adapter
        result = self._api.get_tasks(limit=limit + offset, status=status)

        # Result is a list, not a dict
        if isinstance(result, list):
            total = len(result)
            # Apply offset by slicing
            tasks_slice = result[offset:offset + limit]
            # Map field names: session_id -> id, name -> title
            tasks = []
            for t in tasks_slice:
                tasks.append({
                    "id": t.get("session_id", ""),
                    "title": t.get("name", ""),
                    "status": t.get("status", "running"),
                    "project_path": t.get("project_path"),
                    "agent_type": "claude",
                    "started_at": t.get("started_at"),
                    "completed_at": t.get("ended_at"),
                    "duration_ms": t.get("duration_ms"),
                })
            return {"tasks": tasks, "total": total}
        return {"tasks": [], "total": 0}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task details by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task detail dictionary or None if not found
        """
        result = self._api.get_task_detail(task_id)
        if isinstance(result, dict) and result.get("error"):
            return None
        if result is None:
            return None

        # Map field names: session_id -> id, name -> title
        return {
            "id": result.get("session_id", task_id),
            "title": result.get("name", ""),
            "status": result.get("status", "running"),
            "steps": result.get("steps", []),
            "summary": result.get("summary"),
        }

    def get_task_steps(
        self, task_id: str, limit: int = 50, offset: int = 0
    ) -> Dict[str, Any]:
        """Get task steps with pagination.

        Args:
            task_id: Task identifier
            limit: Maximum number of steps to return
            offset: Number of steps to skip

        Returns:
            Dictionary with steps list, total count, and has_more flag
        """
        result = self._api.get_task_steps(task_id, limit=limit, offset=offset)
        if isinstance(result, dict):
            steps = result.get("steps", [])
            total = result.get("total", len(steps))
            return {
                "steps": steps,
                "total": total,
                "has_more": offset + len(steps) < total,
            }
        return {"steps": [], "total": 0, "has_more": False}

    # ============================================================
    # Agent Methods
    # ============================================================

    def start_agent(self, prompt: str, project_path: Optional[str] = None) -> Dict[str, Any]:
        """Start an agent task.

        Args:
            prompt: Task prompt
            project_path: Optional project path context

        Returns:
            Started task information
        """
        return self._api.submit_agent_task(prompt, project_path)

    # ============================================================
    # Config Methods
    # ============================================================

    def get_config(self) -> Dict[str, Any]:
        """Get user configuration.

        Returns:
            Configuration dictionary
        """
        return self._api.get_config()

    def update_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update user configuration.

        Args:
            config: Configuration updates

        Returns:
            Updated configuration dictionary
        """
        return self._api.update_config(config)

    # ============================================================
    # System Methods
    # ============================================================

    def get_status(self) -> Dict[str, Any]:
        """Get system status.

        Returns:
            Status dictionary with chrome_available, chrome_connected, etc.
        """
        # Use get_system_status() which returns chrome_connected status
        system_status = self._api.get_system_status()
        chrome_connected = system_status.get("chrome_connected", False)

        # Get running tasks count
        tasks_result = self._api.get_tasks(limit=100)
        running_count = 0
        if isinstance(tasks_result, list):
            running_count = sum(1 for t in tasks_result if t.get("status") == "running")

        # Count projects from sessions directory
        projects_count = 0
        try:
            from pathlib import Path
            sessions_dir = Path.home() / ".frago" / "sessions" / "claude"
            if sessions_dir.exists():
                # Count unique project directories
                project_dirs = set()
                for session_dir in sessions_dir.iterdir():
                    if session_dir.is_dir():
                        project_dirs.add(session_dir.name.split("_")[0] if "_" in session_dir.name else session_dir.name)
                projects_count = len(project_dirs)
        except Exception:
            pass

        return {
            "chrome_available": chrome_connected,  # If connected, it's available
            "chrome_connected": chrome_connected,
            "projects_count": projects_count,
            "tasks_running": running_count,
        }

    def get_info(self, host: str, port: int, started_at: str) -> Dict[str, Any]:
        """Get server information.

        Args:
            host: Server host
            port: Server port
            started_at: Server start time (ISO format)

        Returns:
            Server info dictionary
        """
        try:
            from frago import __version__

            version = __version__
        except ImportError:
            version = "0.0.0"

        return {
            "version": version,
            "host": host,
            "port": port,
            "started_at": started_at,
        }

    # ============================================================
    # Settings Methods - GitHub CLI
    # ============================================================

    def check_gh_cli(self) -> Dict[str, Any]:
        """Check GitHub CLI installation and authentication status.

        Returns:
            Dictionary with installed, authenticated, and username
        """
        result = self._api.check_gh_cli()
        return result if isinstance(result, dict) else {"installed": False, "authenticated": False}

    def gh_auth_login(self) -> Dict[str, Any]:
        """Initiate GitHub CLI authentication.

        Returns:
            Result dictionary with status and message/error
        """
        result = self._api.gh_auth_login()
        return result if isinstance(result, dict) else {"status": "error", "error": "Unknown error"}

    # ============================================================
    # Settings Methods - Main Config
    # ============================================================

    def get_main_config(self) -> Dict[str, Any]:
        """Get main configuration.

        Returns:
            Configuration dictionary
        """
        result = self._api.get_main_config()
        return result if isinstance(result, dict) else {}

    def update_main_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update main configuration.

        Args:
            updates: Configuration updates

        Returns:
            Updated configuration dictionary
        """
        result = self._api.update_main_config(updates)
        return result if isinstance(result, dict) else {"error": "Update failed"}

    # ============================================================
    # Settings Methods - Environment Variables
    # ============================================================

    def get_env_vars(self) -> Dict[str, Any]:
        """Get environment variables from .env file.

        Returns:
            Dictionary with vars and file_exists
        """
        result = self._api.get_env_vars()
        return result if isinstance(result, dict) else {"vars": {}, "file_exists": False}

    def update_env_vars(self, updates: Dict[str, Optional[str]]) -> Dict[str, Any]:
        """Update environment variables.

        Args:
            updates: Dictionary of variable updates (None to delete)

        Returns:
            Updated vars dictionary
        """
        result = self._api.update_env_vars(updates)
        return result if isinstance(result, dict) else {"error": "Update failed"}

    def get_recipe_env_requirements(self) -> List[Dict[str, Any]]:
        """Get environment variable requirements from recipes.

        Returns:
            List of requirement dictionaries
        """
        result = self._api.get_recipe_env_requirements()
        return result if isinstance(result, list) else []
