"""Python API exposed to JavaScript for Frago GUI.

Implements the JS-Python bridge using pywebview's js_api protocol.
Extended for 011-gui-tasks-redesign: Tasks-related API methods.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

from frago.compat import prepare_command_for_windows as _prepare_command_for_windows

try:
    import webview
except ImportError:
    webview = None

from frago.gui_deprecated.config import load_config, save_config, update_config
from frago.gui_deprecated.exceptions import RecipeNotFoundError, TaskAlreadyRunningError
from frago.gui_deprecated.history import append_record, clear_history, get_history
from frago.gui_deprecated.models import (
    CommandRecord,
    CommandType,
    MessageType,
    RecipeItem,
    SkillItem,
    StreamMessage,
    TaskStatus,
    UserConfig,
    TaskItem,
    TaskDetail,
    TaskStep,
)
from frago.gui_deprecated.state import AppStateManager

# 011-gui-tasks-redesign: Import session module
from frago.session.storage import (
    list_sessions,
    read_metadata,
    read_steps,
    read_steps_paginated,
    read_summary,
)
from frago.session.models import AgentType


def _get_utf8_env() -> Dict[str, str]:
    """Get environment variables with UTF-8 encoding for Windows.

    Sets PYTHONIOENCODING to ensure Click outputs UTF-8 on Windows,
    where the default encoding is typically GBK.
    See: https://github.com/python/cpython/issues/105312
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class FragoGuiApi:
    """Python API class exposed to JavaScript via pywebview."""

    # Session sync interval (seconds)
    SYNC_INTERVAL_SECONDS = 5

    def __init__(self) -> None:
        """Initialize the GUI API."""
        self.window: Optional["webview.Window"] = None
        self.state = AppStateManager.get_instance()
        self._recipe_cache: List[RecipeItem] = []
        self._skill_cache: List[SkillItem] = []
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_stop_event = threading.Event()
        self._sync_result: Optional[Dict[str, Any]] = None  # Sync state for Settings page

        # Sync current project Claude sessions on GUI startup
        self._sync_sessions_on_startup()

    def _sync_sessions_on_startup(self) -> None:
        """Start periodic session sync on GUI startup

        Start a background thread to sync session data every SYNC_INTERVAL_SECONDS seconds.
        Sync all projects from ~/.claude/projects/ to ~/.frago/sessions/claude/
        """
        import logging

        logger = logging.getLogger(__name__)

        def sync_loop():
            from frago.session.sync import sync_all_projects

            while not self._sync_stop_event.is_set():
                try:
                    result = sync_all_projects()

                    if result.synced > 0 or result.updated > 0:
                        logger.debug(
                            f"Session sync: synced={result.synced}, updated={result.updated}"
                        )
                except Exception as e:
                    logger.warning(f"Session sync failed: {e}")

                # Wait for next sync, but can be interrupted
                self._sync_stop_event.wait(self.SYNC_INTERVAL_SECONDS)

        # Start background sync thread
        self._sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self._sync_thread.start()
        logger.info(f"Session sync thread started (interval: {self.SYNC_INTERVAL_SECONDS}s)")

    def stop_sync(self) -> None:
        """Stop session sync thread"""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_stop_event.set()
            self._sync_thread.join(timeout=2)
            import logging
            logging.getLogger(__name__).info("Session sync thread stopped")

    def set_window(self, window: "webview.Window") -> None:
        """Set the window reference for evaluate_js calls.

        Args:
            window: webview.Window instance.
        """
        self.window = window

    def get_recipes(self) -> List[Dict]:
        """Get list of available recipes.

        Returns:
            List of recipe dictionaries.
        """
        if not self._recipe_cache:
            self._recipe_cache = self._load_recipes()
        return [r.to_dict() for r in self._recipe_cache]

    def _load_recipes(self) -> List[RecipeItem]:
        """Load recipes from frago recipe list command.

        Returns:
            List of RecipeItem instances.
        """
        recipes = []
        try:
            result = subprocess.run(
                _prepare_command_for_windows(["frago", "recipe", "list", "--format", "json"]),
                capture_output=True,
                text=True,
                encoding='utf-8',
                env=_get_utf8_env(),
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for item in data:
                    recipes.append(
                        RecipeItem(
                            name=item.get("name", ""),
                            description=item.get("description"),
                            category=item.get("type", "atomic"),
                            tags=item.get("tags", []),
                            path=item.get("path"),
                            source=item.get("source"),
                            runtime=item.get("runtime"),
                        )
                    )
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        if not recipes:
            recipes = self._load_recipes_from_filesystem()

        return recipes

    def _load_recipes_from_filesystem(self) -> List[RecipeItem]:
        """Load recipes from filesystem as fallback.

        Returns:
            List of RecipeItem instances.
        """
        recipes = []
        recipe_dirs = [
            Path.home() / ".frago" / "recipes",
        ]

        for recipe_dir in recipe_dirs:
            if recipe_dir.exists():
                for path in recipe_dir.rglob("*.js"):
                    recipes.append(
                        RecipeItem(
                            name=path.stem,
                            description=None,
                            category="atomic" if "atomic" in str(path) else "workflow",
                        )
                    )
                for path in recipe_dir.rglob("*.py"):
                    if path.stem != "__init__":
                        recipes.append(
                            RecipeItem(
                                name=path.stem,
                                description=None,
                                category="atomic" if "atomic" in str(path) else "workflow",
                            )
                        )

        return recipes

    def get_skills(self) -> List[Dict]:
        """Get list of available skills.

        Returns:
            List of skill dictionaries.
        """
        if not self._skill_cache:
            self._skill_cache = self._load_skills()
        return [s.to_dict() for s in self._skill_cache]

    def _load_skills(self) -> List[SkillItem]:
        """Load skills from ~/.claude/skills/ directory.

        Skills are organized as directories with SKILL.md files containing
        YAML frontmatter for name and description.

        Returns:
            List of SkillItem instances.
        """
        skills = []
        skills_dir = Path.home() / ".claude" / "skills"

        if not skills_dir.exists():
            return skills

        for skill_path in skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_file = skill_path / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                post = frontmatter.load(skill_file)
                name = post.get("name", skill_path.name)
                description = post.get("description")

                skills.append(
                    SkillItem(
                        name=name,
                        description=description,
                        file_path=str(skill_file),
                    )
                )
            except Exception:
                # fallback: use directory name
                skills.append(
                    SkillItem(
                        name=skill_path.name,
                        description=None,
                        file_path=str(skill_file),
                    )
                )

        return skills

    def run_recipe(self, name: str, params: Optional[Dict] = None) -> Dict:
        """Execute a recipe.

        Args:
            name: Recipe name.
            params: Optional parameters.

        Returns:
            Result dictionary with status and output.
        """
        start_time = time.time()
        task_id = None

        try:
            task_id = self.state.start_task()

            cmd = ["frago", "recipe", "run", name]
            if params:
                cmd.extend(["--params", json.dumps(params)])

            result = subprocess.run(
                _prepare_command_for_windows(cmd),
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=300,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                self.state.complete_task()
                output = result.stdout.strip()

                record = CommandRecord(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    command_type=CommandType.RECIPE,
                    input_text=f"recipe run {name}",
                    status=TaskStatus.COMPLETED,
                    duration_ms=duration_ms,
                    output=output,
                )
                append_record(record)

                return {"status": "ok", "output": output, "error": None}
            else:
                error = result.stderr.strip() or "Recipe execution failed"
                self.state.error_task(error)

                record = CommandRecord(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    command_type=CommandType.RECIPE,
                    input_text=f"recipe run {name}",
                    status=TaskStatus.ERROR,
                    duration_ms=duration_ms,
                    error=error,
                )
                append_record(record)

                return {"status": "error", "output": None, "error": error}

        except subprocess.TimeoutExpired:
            self.state.error_task("Recipe execution timed out")
            return {"status": "error", "output": None, "error": "Execution timed out"}
        except TaskAlreadyRunningError as e:
            return {"status": "error", "output": None, "error": str(e)}
        except Exception as e:
            self.state.error_task(str(e))
            return {"status": "error", "output": None, "error": str(e)}

    def run_agent(self, prompt: str) -> str:
        """Start an agent task.

        Args:
            prompt: User prompt.

        Returns:
            Task ID.

        Raises:
            TaskAlreadyRunningError: If a task is already running.
        """
        if self.state.is_task_running():
            raise TaskAlreadyRunningError()

        task_id = self.state.start_task()

        thread = threading.Thread(
            target=self._run_agent_async,
            args=(task_id, prompt),
            daemon=True,
        )
        thread.start()

        return task_id

    def _run_agent_async(self, task_id: str, prompt: str) -> None:
        """Run agent asynchronously.

        Args:
            task_id: Task ID.
            prompt: User prompt.
        """
        start_time = time.time()

        try:
            process = subprocess.Popen(
                _prepare_command_for_windows(["frago", "agent", prompt]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                bufsize=1,
            )

            output_lines = []

            for line in process.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
                    self._push_stream_message(
                        StreamMessage(
                            type=MessageType.ASSISTANT,
                            content=line,
                            timestamp=datetime.now(),
                        )
                    )

            process.wait()
            duration_ms = int((time.time() - start_time) * 1000)

            if process.returncode == 0:
                self.state.complete_task()
                record = CommandRecord(
                    id=task_id,
                    timestamp=datetime.now(),
                    command_type=CommandType.AGENT,
                    input_text=prompt,
                    status=TaskStatus.COMPLETED,
                    duration_ms=duration_ms,
                    output="\n".join(output_lines),
                )
            else:
                error = process.stderr.read().strip()
                self.state.error_task(error)
                record = CommandRecord(
                    id=task_id,
                    timestamp=datetime.now(),
                    command_type=CommandType.AGENT,
                    input_text=prompt,
                    status=TaskStatus.ERROR,
                    duration_ms=duration_ms,
                    error=error,
                )

            append_record(record)

        except Exception as e:
            self.state.error_task(str(e))
            record = CommandRecord(
                id=task_id,
                timestamp=datetime.now(),
                command_type=CommandType.AGENT,
                input_text=prompt,
                status=TaskStatus.ERROR,
                error=str(e),
            )
            append_record(record)

    def cancel_agent(self) -> Dict:
        """Cancel the current running agent task.

        Returns:
            Result dictionary.
        """
        if self.state.cancel_task():
            return {"status": "ok", "message": "Task cancelled"}
        return {"status": "error", "message": "No task running"}

    def get_task_status(self) -> Dict:
        """Get current task status.

        Returns:
            Task status dictionary.
        """
        return self.state.get_task_status()

    def get_history(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get command history.

        Args:
            limit: Maximum records to return.
            offset: Number of records to skip.

        Returns:
            List of history record dictionaries.
        """
        records = get_history(limit=limit, offset=offset)
        return [r.to_dict() for r in records]

    def clear_history(self) -> Dict:
        """Clear all history records.

        Returns:
            Result dictionary with cleared count.
        """
        count = clear_history()
        return {"status": "ok", "cleared_count": count}

    def get_config(self) -> Dict:
        """Get user configuration.

        Returns:
            Configuration dictionary.
        """
        config = load_config()
        return asdict(config)

    def update_config(self, config: Dict) -> Dict:
        """Update user configuration.

        Args:
            config: Configuration updates.

        Returns:
            Result dictionary with updated configuration.
        """
        try:
            updated = update_config(config)
            return {"status": "ok", "config": asdict(updated)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_system_status(self) -> Dict:
        """Get system status information.

        Returns:
            System status dictionary.
        """
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
        except ImportError:
            cpu_percent = 0.0
            memory_percent = 0.0

        chrome_connected = self._check_chrome_connection()

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "chrome_connected": chrome_connected,
        }

    def _check_chrome_connection(self) -> bool:
        """Check if Chrome is connected.

        Directly request CDP endpoint to avoid subprocess CLI command logs.

        Returns:
            True if Chrome is connected.
        """
        try:
            import requests
            resp = requests.get("http://127.0.0.1:9222/json/version", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def check_connection(self) -> Dict:
        """Check connection status.

        Returns:
            Connection status dictionary.
        """
        connected = self._check_chrome_connection()
        return {
            "connected": connected,
            "message": "Connected to Chrome" if connected else "Chrome not connected",
        }

    def open_path(self, path: str, reveal: bool = False) -> Dict:
        """Open a file or directory in the system default application.

        Args:
            path: The file or directory path to open.
            reveal: If True, reveal in Finder instead of opening.

        Returns:
            Status dictionary with 'status' and optional 'error'.
        """
        import platform
        from pathlib import Path

        try:
            p = Path(path)
            if not p.exists():
                return {"status": "error", "error": f"Path does not exist: {path}"}

            system = platform.system()
            if system == "Darwin":  # macOS
                if reveal:
                    subprocess.run(["open", "-R", str(p)], check=True)
                else:
                    subprocess.run(["open", str(p)], check=True)
            elif system == "Linux":
                subprocess.run(["xdg-open", str(p)], check=True)
            elif system == "Windows":
                import os
                os.startfile(str(p))
            else:
                return {"status": "error", "error": f"Unsupported platform: {system}"}

            return {"status": "ok"}
        except subprocess.CalledProcessError as e:
            return {"status": "error", "error": str(e)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _push_stream_message(self, message: StreamMessage) -> None:
        """Push a stream message to the frontend.

        Args:
            message: StreamMessage to push.
        """
        if self.window:
            js_code = f"window.handleStreamMessage && window.handleStreamMessage({json.dumps(message.to_dict())})"
            self.window.evaluate_js(js_code)

    def update_progress(self, progress: float, step: str = "") -> None:
        """Update task progress.

        Args:
            progress: Progress value (0.0 - 1.0).
            step: Current step description.
        """
        self.state.update_progress(progress, step)
        if self.window:
            js_code = f"window.updateProgress && window.updateProgress({progress}, {json.dumps(step)})"
            self.window.evaluate_js(js_code)

    def show_toast(self, message: str, toast_type: str = "info") -> None:
        """Show a toast notification.

        Args:
            message: Toast message.
            toast_type: Toast type (info, success, warning, error).
        """
        if self.window:
            js_code = f"window.showToast && window.showToast({json.dumps(message)}, {json.dumps(toast_type)})"
            self.window.evaluate_js(js_code)

    def refresh_recipes(self) -> List[Dict]:
        """Refresh and return the recipe list.

        Returns:
            Updated list of recipe dictionaries.
        """
        self._recipe_cache = self._load_recipes()
        return [r.to_dict() for r in self._recipe_cache]

    def get_recipe_detail(self, name: str) -> Dict[str, Any]:
        """Get detailed information about a specific recipe.

        Args:
            name: Recipe name.

        Returns:
            Dictionary containing recipe details and metadata content.
        """
        # Find recipe in cache
        recipe = None
        for r in self._recipe_cache:
            if r.name == name:
                recipe = r
                break

        if not recipe:
            # Refresh cache and search again
            self._recipe_cache = self._load_recipes()
            for r in self._recipe_cache:
                if r.name == name:
                    recipe = r
                    break

        if not recipe:
            return {"error": f"Recipe '{name}' does not exist"}

        result = recipe.to_dict()

        # Read recipe.md content
        if recipe.path:
            recipe_path = Path(recipe.path)
            # path might be script path, need to find recipe.md
            if recipe_path.is_file():
                recipe_dir = recipe_path.parent
            else:
                recipe_dir = recipe_path

            metadata_path = recipe_dir / "recipe.md"
            if metadata_path.exists():
                try:
                    result["metadata_content"] = metadata_path.read_text(encoding="utf-8")
                except Exception:
                    result["metadata_content"] = None
            else:
                result["metadata_content"] = None

            result["recipe_dir"] = str(recipe_dir)
        else:
            result["metadata_content"] = None
            result["recipe_dir"] = None

        return result

    def delete_recipe(self, name: str) -> Dict[str, Any]:
        """Delete a recipe (only user-level recipes can be deleted).

        Args:
            name: Recipe name.

        Returns:
            Dictionary with status and message.
        """
        import shutil

        # Find recipe in cache
        recipe = None
        for r in self._recipe_cache:
            if r.name == name:
                recipe = r
                break

        if not recipe:
            return {"status": "error", "message": f"Recipe '{name}' does not exist"}

        # Only allow deletion of user-level recipes
        if recipe.source != "User":
            return {
                "status": "error",
                "message": f"Only user-level recipes can be deleted, '{name}' is from {recipe.source}",
            }

        if not recipe.path:
            return {"status": "error", "message": "Recipe path is unknown"}

        recipe_path = Path(recipe.path)
        if recipe_path.is_file():
            recipe_dir = recipe_path.parent
        else:
            recipe_dir = recipe_path

        # Ensure it's in user directory
        user_recipes_dir = Path.home() / ".frago" / "recipes"
        try:
            recipe_dir.relative_to(user_recipes_dir)
        except ValueError:
            return {
                "status": "error",
                "message": f"Recipe is not in user directory, cannot delete",
            }

        if not recipe_dir.exists():
            return {"status": "error", "message": "Recipe directory does not exist"}

        try:
            shutil.rmtree(recipe_dir)
            # Refresh cache
            self._recipe_cache = self._load_recipes()
            return {"status": "ok", "message": f"Recipe '{name}' has been deleted"}
        except Exception as e:
            return {"status": "error", "message": f"Deletion failed: {e}"}

    def refresh_skills(self) -> List[Dict]:
        """Refresh and return the skill list.

        Returns:
            Updated list of skill dictionaries.
        """
        self._skill_cache = self._load_skills()
        return [s.to_dict() for s in self._skill_cache]

    # ============================================================
    # 011-gui-tasks-redesign: Tasks-related API methods
    # ============================================================

    def get_tasks(self, limit: int = 50, status: Optional[str] = None) -> List[Dict]:
        """Get task list

        Prioritize reading session data from ~/.frago/sessions/, if empty
        read AGENT type records from GUI history as task list.

        Args:
            limit: Maximum number to return, range 1-100, default 50
            status: Status filter (optional), supports running/completed/error/cancelled

        Returns:
            Task list
        """
        try:
            from frago.session.models import SessionStatus

            # Parameter validation
            limit = max(1, min(100, limit))

            # Convert status filter parameter
            status_filter = None
            if status:
                try:
                    status_filter = SessionStatus(status)
                except ValueError:
                    pass  # Invalid status, ignore filter

            tasks = []
            session_ids = set()

            # 1. Get existing tasks from sessions directory
            # Request more sessions to compensate for filtering losses
            sessions = list_sessions(
                agent_type=AgentType.CLAUDE,
                limit=limit * 3,  # Request 3x amount, then trim after filtering
                status=status_filter,
            )

            for session in sessions:
                try:
                    # Apply filter rules: skip low-value sessions
                    if not TaskItem.should_display(session):
                        continue
                    task = TaskItem.from_session(session)
                    tasks.append(task.model_dump(mode="json"))
                    session_ids.add(session.session_id)
                except Exception:
                    continue

            # Note: Removed history fallback because history task_id doesn't match Claude session_id
            # Sync mechanism ensures all Claude sessions are imported

            # Sort by started_at descending
            tasks.sort(
                key=lambda t: t.get("started_at") or "",
                reverse=True
            )

            return tasks[:limit]

        except Exception:
            # Fallback to history
            return self._get_tasks_from_history(limit, status)

    def _get_tasks_from_history(
        self, limit: int = 50, status: Optional[str] = None
    ) -> List[Dict]:
        """Read AGENT type records from GUI history as task list

        Args:
            limit: Maximum number to return
            status: Status filter

        Returns:
            Task list
        """
        # Convert status filter
        task_status = None
        if status:
            try:
                task_status = TaskStatus(status)
            except ValueError:
                pass

        # Read AGENT type history records
        records = get_history(
            limit=limit,
            command_type=CommandType.AGENT,
            status=task_status,
        )

        tasks = []
        for record in records:
            # Convert CommandRecord to TaskItem-like format
            task = {
                "session_id": record.id,
                "name": record.input_text[:100] if record.input_text else "Unnamed task",
                "status": record.status.value if record.status else "completed",
                "started_at": record.timestamp.isoformat() if record.timestamp else None,
                "ended_at": None,
                "duration_ms": record.duration_ms or 0,
                "step_count": 0,
                "tool_call_count": 0,
                "last_activity": record.timestamp.isoformat() if record.timestamp else None,
                "project_path": None,
            }
            tasks.append(task)

        return tasks

    def _get_task_detail_from_history(self, session_id: str) -> Dict[str, Any]:
        """Get task details from history (for newly started tasks without session data yet)"""
        records = get_history(limit=100, command_type=CommandType.AGENT)

        for record in records:
            if record.id == session_id:
                return {
                    "session_id": session_id,
                    "name": record.input_text[:100] if record.input_text else f"Task {session_id[:8]}",
                    "status": record.status.value if record.status else "running",
                    "started_at": record.timestamp.isoformat() if record.timestamp else None,
                    "ended_at": None,
                    "duration_ms": record.duration_ms,
                    "project_path": None,
                    "step_count": 0,
                    "tool_call_count": 0,
                    "user_message_count": 0,
                    "assistant_message_count": 0,
                    "steps": [],
                    "steps_total": 0,
                    "steps_offset": 0,
                    "has_more_steps": False,
                    "summary": None,
                }

        return {"error": f"Session {session_id} does not exist or has been deleted"}

    def get_task_detail(
        self,
        session_id: str,
        steps_limit: int = 0,
        steps_offset: int = 0,
    ) -> Dict[str, Any]:
        """Get task details

        Read complete information for specified session, including metadata, step records, and summary.

        Args:
            session_id: Session ID (required)
            steps_limit: Step count limit, 0 means get all, default 0
            steps_offset: Step offset for pagination, default 0

        Returns:
            Task detail dictionary containing:
            - session_id, name, status, started_at, ended_at
            - duration_ms, project_path
            - step_count, tool_call_count, user_message_count, assistant_message_count
            - steps (step list)
            - steps_total, steps_offset, has_more_steps
            - summary (summary after completion)
            - error (if error occurred)
        """
        # Parameter validation
        if not session_id:
            return {"error": "Session ID cannot be empty"}

        # steps_limit = 0 or None means get all
        if not steps_limit:
            steps_limit = 10000  # Set a sufficiently large value
        else:
            steps_limit = max(1, min(10000, steps_limit))
        steps_offset = max(0, steps_offset or 0)

        try:
            # Read session metadata
            session = read_metadata(session_id, AgentType.CLAUDE)
            if not session:
                # Try to get from history (might be a newly started task)
                return self._get_task_detail_from_history(session_id)

            # Read steps with pagination
            steps_result = read_steps_paginated(
                session_id, AgentType.CLAUDE, steps_limit, steps_offset
            )
            steps = steps_result["steps"]
            total_steps = steps_result["total"]

            # Read summary (might not exist)
            summary = read_summary(session_id, AgentType.CLAUDE)

            # Build TaskDetail
            detail = TaskDetail.from_session_data(
                session=session,
                steps=steps,
                summary=summary,
                offset=steps_offset,
                limit=steps_limit,
                total_steps=total_steps,
            )

            return detail.model_dump(mode="json")
        except Exception as e:
            return {"error": f"Failed to load task details: {str(e)}"}

    def get_task_steps(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get task steps with pagination

        Used for "load more" functionality in task detail page, returns step records in specified range.

        Args:
            session_id: Session ID (required)
            offset: Offset, starting from which record, default 0
            limit: Count limit, range 1-100, default 50

        Returns:
            Dictionary containing:
            - steps: Step list
            - total: Total step count
            - offset: Current offset
            - has_more: Whether there are more
            - error: Error message (if error occurred)
        """
        # Parameter validation
        if not session_id:
            return {"error": "Session ID cannot be empty", "steps": [], "has_more": False}

        limit = max(1, min(100, limit))
        offset = max(0, offset)

        try:
            result = read_steps_paginated(session_id, AgentType.CLAUDE, limit, offset)

            # Convert step format to GUI required format
            gui_steps = [TaskStep.from_session_step(s) for s in result["steps"]]

            return {
                "steps": [s.model_dump(mode="json") for s in gui_steps],
                "total": result["total"],
                "offset": result["offset"],
                "has_more": result["has_more"],
            }
        except Exception as e:
            return {
                "error": f"Failed to load steps: {str(e)}",
                "steps": [],
                "has_more": False,
            }

    def start_agent_task(self, prompt: str) -> Dict[str, Any]:
        """Start agent task

        Execute `frago agent {prompt}` command in background.
        Returns immediately after task starts, does not wait for task completion.
        Also records a "running" entry in history.

        Args:
            prompt: Task description/prompt

        Returns:
            Dictionary containing:
            - status: "ok" or "error"
            - message: Status message
            - task_id: Task ID (returned on success)
            - error: Error message (if error occurred)
        """
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        task_id = str(uuid.uuid4())

        try:
            # First record a "running" history entry
            record = CommandRecord(
                id=task_id,
                timestamp=datetime.now(),
                command_type=CommandType.AGENT,
                input_text=prompt,
                status=TaskStatus.RUNNING,
                duration_ms=0,
            )
            append_record(record)

            # Start frago agent command in background
            # Use shutil.which to find full path, avoid environment variable issues
            import shutil
            frago_path = shutil.which("frago")
            if not frago_path:
                return {
                    "status": "error",
                    "error": "frago command not found, please ensure it's properly installed and in PATH",
                }

            # Use Popen to start process, don't wait for completion
            # Redirect output to log file for debugging
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-{task_id[:8]}.log"

            # Use temp file to pass prompt, avoid Windows command line truncating newlines
            prompt_file = log_dir / f"prompt-{task_id[:8]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            with open(log_file, "w", encoding="utf-8") as f:
                subprocess.Popen(
                    _prepare_command_for_windows([frago_path, "agent", "--yes", "--prompt-file", str(prompt_file)]),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # Detach process, prevent termination when GUI closes
                )

            return {
                "status": "ok",
                "task_id": task_id,
                "message": f"Task started: {prompt[:50]}{'...' if len(prompt) > 50 else ''}",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago command not found, please ensure it's properly installed",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to start task: {str(e)}",
            }

    def continue_agent_task(self, session_id: str, prompt: str) -> Dict[str, Any]:
        """Continue conversation in specified session

        Args:
            session_id: Session ID to continue
            prompt: User's new prompt

        Returns:
            Dictionary containing:
            - status: "ok" or "error"
            - message: Status message
            - error: Error message (if error occurred)
        """
        if not session_id:
            return {"status": "error", "error": "session_id cannot be empty"}
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()

        try:
            import shutil
            frago_path = shutil.which("frago")
            if not frago_path:
                return {
                    "status": "error",
                    "error": "frago command not found, please ensure it's properly installed and in PATH",
                }

            # Use Popen to start process, don't wait for completion
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-resume-{session_id[:8]}.log"

            # Use temp file to pass prompt, avoid Windows command line truncating newlines
            prompt_file = log_dir / f"prompt-resume-{session_id[:8]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            with open(log_file, "w", encoding="utf-8") as f:
                subprocess.Popen(
                    _prepare_command_for_windows([frago_path, "agent", "--resume", session_id, "--yes", "--prompt-file", str(prompt_file)]),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )

            return {
                "status": "ok",
                "message": f"Continued in session {session_id[:8]}...: {prompt[:50]}{'...' if len(prompt) > 50 else ''}",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago command not found, please ensure it's properly installed",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to continue task: {str(e)}",
            }

    # ============================================================
    # Settings page-related API methods: Main configuration management
    # ============================================================

    def get_main_config(self) -> Dict[str, Any]:
        """Get main configuration (~/.frago/config.json)

        Returns:
            Configuration dictionary containing all fields from Config model, plus additional working_directory_display
        """
        from frago.init.config_manager import load_config

        try:
            config = load_config()
            result = config.model_dump(mode='json')
            # Add working directory display path (fixed to ~/.frago/projects, but show actual path)
            result['working_directory_display'] = str(Path.home() / ".frago" / "projects")
            return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to load main config: {e}")
            # Return empty config
            from frago.init.models import Config
            result = Config().model_dump(mode='json')
            result['working_directory_display'] = str(Path.home() / ".frago" / "projects")
            return result

    def update_main_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update main configuration

        Args:
            updates: Partial update dictionary, e.g. {"sync_repo_url": "git@github.com:user/repo.git"}

        Returns:
            {"status": "ok", "config": {...}} or {"status": "error", "error": "..."}
        """
        from frago.init.config_manager import update_config
        from pydantic import ValidationError

        try:
            config = update_config(updates)
            return {
                "status": "ok",
                "config": config.model_dump(mode='json')
            }
        except ValidationError as e:
            return {
                "status": "error",
                "error": f"Config validation failed: {e}"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def update_auth_method(self, auth_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update authentication method and API endpoint

        Updates simultaneously:
        - ~/.frago/config.json (frago configuration)
        - ~/.claude/settings.json (Claude Code environment variables)
        - ~/.claude.json (skip official login)

        Args:
            auth_data: {
                "auth_method": "official" | "custom",
                "api_endpoint": {  # Only provided for custom
                    "type": "deepseek" | "aliyun" | "kimi" | "minimax" | "custom",
                    "url": "...",  # Only needed for type=custom
                    "api_key": "..."
                }
            }

        Returns:
            {"status": "ok", "config": {...}} or {"status": "error", "error": "..."}
        """
        from frago.init.config_manager import update_config
        from frago.init.configurator import (
            build_claude_env_config,
            save_claude_settings,
            delete_claude_settings,
            ensure_claude_json_for_custom_auth,
        )
        from pydantic import ValidationError
        import logging

        logger = logging.getLogger(__name__)

        try:
            # Build update dictionary
            updates: Dict[str, Any] = {
                "auth_method": auth_data["auth_method"]
            }

            # Handle api_endpoint
            if auth_data["auth_method"] == "custom":
                if "api_endpoint" not in auth_data:
                    return {
                        "status": "error",
                        "error": "Custom auth requires api_endpoint"
                    }
                updates["api_endpoint"] = auth_data["api_endpoint"]

                # Sync write to ~/.claude/settings.json
                endpoint = auth_data["api_endpoint"]
                endpoint_type = endpoint.get("type", "custom")
                api_key = endpoint.get("api_key", "")
                custom_url = endpoint.get("url") if endpoint_type == "custom" else None
                custom_model = endpoint.get("model") if endpoint_type == "custom" else None

                # Build Claude Code env config
                env_config = build_claude_env_config(
                    endpoint_type=endpoint_type,
                    api_key=api_key,
                    custom_url=custom_url,
                    custom_model=custom_model,
                )

                # Ensure ~/.claude.json exists (skip official login flow)
                ensure_claude_json_for_custom_auth()

                # Write to ~/.claude/settings.json
                save_claude_settings({"env": env_config})
                logger.info("Synced API config to ~/.claude/settings.json")
            else:
                # Official mode, remove api_endpoint and delete settings.json
                updates["api_endpoint"] = None

                # Delete ~/.claude/settings.json, let Claude Code use official config
                if delete_claude_settings():
                    logger.info("Deleted ~/.claude/settings.json, switched to official API")
                else:
                    logger.warning("Failed to delete ~/.claude/settings.json")

            # Update ~/.frago/config.json
            config = update_config(updates)

            # Mask returned config
            config_dict = config.model_dump(mode='json')
            if config_dict.get("api_endpoint") and config_dict["api_endpoint"].get("api_key"):
                config_dict["api_endpoint"]["api_key"] = self._mask_api_key(
                    config_dict["api_endpoint"]["api_key"]
                )

            # Add working directory display path
            config_dict['working_directory_display'] = str(Path.home() / ".frago" / "projects")

            return {
                "status": "ok",
                "config": config_dict
            }
        except ValidationError as e:
            return {
                "status": "error",
                "error": f"Config validation failed: {e}"
            }
        except Exception as e:
            logger.exception("Failed to update auth config")
            return {
                "status": "error",
                "error": str(e)
            }

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        """Mask API key (first 4 and last 4, fully mask if shorter than 8 chars)

        Args:
            api_key: Original API key

        Returns:
            Masked API key
        """
        if len(api_key) <= 8:
            return '••••••••'
        return api_key[:4] + '••••' + api_key[-4:]

    def open_working_directory(self) -> Dict[str, Any]:
        """Open working directory in file manager

        Working directory is fixed to ~/.frago/projects

        Returns:
            {"status": "ok"} or {"status": "error", "error": "..."}
        """
        import subprocess
        import sys

        try:
            # Working directory is fixed to ~/.frago/projects
            work_dir_path = Path.home() / ".frago" / "projects"

            # Ensure directory exists
            work_dir_path.mkdir(parents=True, exist_ok=True)

            # Open file manager according to OS
            if sys.platform == 'darwin':  # macOS
                subprocess.Popen(['open', str(work_dir_path)])
            elif sys.platform == 'win32':  # Windows
                subprocess.Popen(['explorer', str(work_dir_path)])
            else:  # Linux
                subprocess.Popen(['xdg-open', str(work_dir_path)])

            return {"status": "ok"}
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to open directory: {str(e)}"
            }

    # ============================================================
    # Settings page-related API methods: Environment variable management
    # ============================================================

    def get_env_vars(self) -> Dict[str, Any]:
        """Get user-level environment variables (~/.frago/.env)

        Returns:
            {"vars": {...}, "file_exists": bool}
        """
        from frago.recipes.env_loader import EnvLoader

        try:
            env_path = EnvLoader.USER_ENV_PATH
            loader = EnvLoader()

            # Load user-level .env file
            env_vars = loader.load_env_file(env_path)

            return {
                "vars": env_vars,
                "file_exists": env_path.exists()
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to load environment variables: {e}")
            return {
                "vars": {},
                "file_exists": False
            }

    def update_env_vars(self, updates: Dict[str, Optional[str]]) -> Dict[str, Any]:
        """Batch update environment variables

        Args:
            updates: {"KEY": "value", "DELETE_KEY": None} - value=None means delete

        Returns:
            {"status": "ok", "vars": {...}} or {"status": "error", "error": "..."}
        """
        from frago.recipes.env_loader import EnvLoader, update_env_file

        try:
            env_path = EnvLoader.USER_ENV_PATH

            # Update .env file
            update_env_file(env_path, updates)

            # Reload and return
            loader = EnvLoader()
            env_vars = loader.load_env_file(env_path)

            return {
                "status": "ok",
                "vars": env_vars
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def get_recipe_env_requirements(self) -> List[Dict]:
        """Scan all Recipe environment variable requirements

        Returns:
            [{
                "recipe_name": "...",
                "var_name": "GITHUB_TOKEN",
                "required": true,
                "description": "...",
                "configured": false
            }, ...]
        """
        try:
            import frontmatter
        except ImportError:
            import logging
            logging.getLogger(__name__).warning(
                "python-frontmatter not installed, unable to scan Recipe environment variable requirements"
            )
            return []

        from frago.recipes.env_loader import EnvLoader

        requirements = []
        recipe_dirs = [
            Path.home() / ".frago" / "recipes",
        ]

        # Load current environment variables
        try:
            current_env = EnvLoader().load_all()
        except Exception:
            current_env = {}

        # Scan Recipe directories
        for recipe_dir in recipe_dirs:
            if not recipe_dir.exists():
                continue

            for md_file in recipe_dir.rglob("recipe.md"):
                try:
                    # Parse frontmatter
                    post = frontmatter.load(md_file)
                    env_vars = post.metadata.get("env", {})

                    if not env_vars:
                        continue

                    recipe_name = post.metadata.get("name", md_file.parent.name)

                    for var_name, var_def in env_vars.items():
                        # var_def may be a dict or a simple default value
                        if isinstance(var_def, dict):
                            required = var_def.get("required", False)
                            description = var_def.get("description", "")
                        else:
                            required = False
                            description = ""

                        requirements.append({
                            "recipe_name": recipe_name,
                            "var_name": var_name,
                            "required": required,
                            "description": description,
                            "configured": var_name in current_env
                        })
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Failed to parse {md_file}: {e}"
                    )
                    continue

        # Deduplicate (same variable used by multiple Recipes)
        unique = {}
        for req in requirements:
            key = req["var_name"]
            if key not in unique:
                unique[key] = req
            else:
                # Merge recipe_name
                unique[key]["recipe_name"] += f", {req['recipe_name']}"
                # Keep higher priority attribute (if any required=True, set to True)
                if req["required"]:
                    unique[key]["required"] = True

        return list(unique.values())

    # ============================================================
    # Settings page-related API methods: GitHub integration
    # ============================================================

    def check_gh_cli(self) -> Dict[str, Any]:
        """Check gh CLI installation and login status

        Returns:
            {
                "installed": bool,
                "version": "2.40.1" or None,
                "authenticated": bool,
                "username": "..." or None
            }
        """
        result = {
            "installed": False,
            "version": None,
            "authenticated": False,
            "username": None
        }

        # Check if gh is installed
        try:
            version_result = subprocess.run(
                _prepare_command_for_windows(['gh', '--version']),
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=5
            )
            if version_result.returncode == 0:
                result["installed"] = True
                # Parse version number (format like "gh version 2.40.1 (2023-12-13)")
                import re
                match = re.search(r'gh version ([\d.]+)', version_result.stdout)
                if match:
                    result["version"] = match.group(1)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return result

        # Check login status
        if result["installed"]:
            try:
                auth_result = subprocess.run(
                    _prepare_command_for_windows(['gh', 'auth', 'status']),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=5
                )
                # gh auth status returns 0 if logged in
                if auth_result.returncode == 0:
                    result["authenticated"] = True
                    # Parse username (extract from output)
                    # Output format: "Logged in to github.com account USERNAME (keyring)"
                    import re
                    # Try both old format "as USERNAME" and new format "account USERNAME"
                    output = auth_result.stderr + auth_result.stdout
                    match = re.search(r'Logged in to github\.com (?:as|account) ([^\s(]+)', output)
                    if match:
                        result["username"] = match.group(1)
            except subprocess.TimeoutExpired:
                pass

        return result

    def gh_auth_login(self) -> Dict[str, Any]:
        """Execute gh auth login in external terminal

        Returns:
            {"status": "ok", "message": "..."} or {"status": "error", "error": "..."}
        """
        import platform

        try:
            system = platform.system()

            if system == 'Linux':
                # Try x-terminal-emulator
                try:
                    subprocess.Popen(
                        ['x-terminal-emulator', '-e', 'gh', 'auth', 'login']
                    )
                    return {"status": "ok", "message": "Terminal opened, please complete login in terminal"}
                except FileNotFoundError:
                    # Fall back to gnome-terminal
                    try:
                        subprocess.Popen(
                            ['gnome-terminal', '--', 'gh', 'auth', 'login']
                        )
                        return {"status": "ok", "message": "Terminal opened, please complete login in terminal"}
                    except FileNotFoundError:
                        return {
                            "status": "error",
                            "error": "No available terminal emulator found (x-terminal-emulator, gnome-terminal)"
                        }
            elif system == 'Darwin':
                # macOS
                script = 'tell application "Terminal" to do script "gh auth login; exit"'
                subprocess.run(['osascript', '-e', script])
                return {"status": "ok", "message": "Terminal opened, please complete login in terminal"}
            elif system == 'Windows':
                # Windows: Prefer PowerShell (default in Windows 10/11)
                try:
                    subprocess.Popen(
                        ['powershell', '-NoExit', '-Command', 'gh auth login'],
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    return {"status": "ok", "message": "PowerShell window opened, please complete login in window"}
                except FileNotFoundError:
                    # Fall back to cmd
                    try:
                        subprocess.Popen(
                            ['cmd', '/c', 'start', 'cmd', '/k', 'gh auth login'],
                            creationflags=subprocess.CREATE_NEW_CONSOLE
                        )
                        return {"status": "ok", "message": "Command Prompt window opened, please complete login in window"}
                    except Exception as e:
                        return {"status": "error", "error": f"Unable to open terminal window: {e}"}
            else:
                return {"status": "error", "error": f"Unsupported operating system: {system}"}

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def create_sync_repo(self, repo_name: str, private: bool = True) -> Dict[str, Any]:
        """Create GitHub repository and configure in config.json

        Args:
            repo_name: Repository name (without username prefix)
            private: Whether repository is private

        Returns:
            {"status": "ok", "repo_url": "..."} or {"status": "error", "error": "..."}
        """
        from frago.init.config_manager import update_config

        try:
            # Create repository
            cmd = ['gh', 'repo', 'create', repo_name]
            if private:
                cmd.append('--private')
            else:
                cmd.append('--public')

            # Add description
            cmd.extend(['--description', 'Frago resources sync repository'])

            # Retry mechanism
            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    result = subprocess.run(
                        _prepare_command_for_windows(cmd),
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        timeout=30
                    )

                    if result.returncode == 0:
                        # Successfully created, parse repository URL
                        # gh repo create output is like: ✓ Created repository user/repo on GitHub
                        # We need to get SSH URL
                        username_result = subprocess.run(
                            _prepare_command_for_windows(['gh', 'api', 'user', '--jq', '.login']),
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            timeout=5
                        )
                        username = username_result.stdout.strip()
                        # Use HTTPS URL, works with gh credential helper without SSH key
                        repo_url = f"https://github.com/{username}/{repo_name}.git"

                        # Update configuration
                        update_config({"sync_repo_url": repo_url})

                        return {
                            "status": "ok",
                            "repo_url": repo_url
                        }
                    else:
                        last_error = result.stderr.strip()
                        if "already exists" in last_error.lower():
                            # Repository already exists, no need to retry
                            return {
                                "status": "error",
                                "error": f"Repository {repo_name} already exists"
                            }
                        # Other errors, continue retrying
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue

                except subprocess.TimeoutExpired:
                    last_error = "Repository creation timed out"
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue

            return {
                "status": "error",
                "error": last_error or "Repository creation failed"
            }

        except FileNotFoundError:
            return {
                "status": "error",
                "error": "gh command not found, please ensure GitHub CLI is installed"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def list_user_repos(self, limit: int = 100) -> Dict[str, Any]:
        """List user's GitHub repositories

        Args:
            limit: Maximum number to return, default 100

        Returns:
            {
                "status": "ok",
                "repos": [
                    {
                        "name": "repo-name",
                        "full_name": "username/repo-name",
                        "private": true,
                        "ssh_url": "git@github.com:username/repo-name.git",
                        "description": "..."
                    },
                    ...
                ]
            }
        """
        import json

        try:
            # Use gh api to get user repository list
            result = subprocess.run(
                _prepare_command_for_windows([
                    'gh', 'api', 'user/repos',
                    '--paginate',
                    '-q', f'.[::{limit}] | .[] | {{name: .name, full_name: .full_name, private: .private, ssh_url: .ssh_url, description: .description}}'
                ]),
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30
            )

            if result.returncode != 0:
                return {
                    "status": "error",
                    "error": result.stderr.strip() or "Failed to get repository list"
                }

            # Parse JSON Lines output
            repos = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        repos.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            return {
                "status": "ok",
                "repos": repos[:limit]  # Ensure not exceeding limit
            }

        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Repository list retrieval timed out"}
        except FileNotFoundError:
            return {"status": "error", "error": "gh command not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def select_existing_repo(self, repo_url: str) -> Dict[str, Any]:
        """Select existing repository as sync repository

        Supports SSH and HTTPS URLs, but converts to HTTPS URL to work with gh credential helper.

        Args:
            repo_url: Repository URL (SSH or HTTPS format)

        Returns:
            {"status": "ok", "repo_url": "..."} or {"status": "error", "error": "..."}
        """
        from frago.init.config_manager import update_config
        import re

        try:
            # Convert SSH URL to HTTPS URL
            # SSH: git@github.com:user/repo.git -> HTTPS: https://github.com/user/repo.git
            ssh_match = re.match(r'git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$', repo_url)
            if ssh_match:
                owner, repo = ssh_match.group(1), ssh_match.group(2)
                repo_url = f"https://github.com/{owner}/{repo}.git"
            elif repo_url.startswith('https://github.com/'):
                # Already HTTPS URL, ensure it ends with .git
                if not repo_url.endswith('.git'):
                    repo_url = repo_url.rstrip('/') + '.git'
            else:
                return {
                    "status": "error",
                    "error": "Invalid repository URL format, please use GitHub repository address"
                }

            # Update configuration
            update_config({"sync_repo_url": repo_url})

            return {
                "status": "ok",
                "repo_url": repo_url
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def run_first_sync(self) -> Dict[str, Any]:
        """Execute frago sync (background thread)

        Returns:
            {"status": "ok", "message": "Sync started"}
        """
        # Check if sync is already running
        if self._sync_result and self._sync_result.get("status") == "running":
            return {
                "status": "error",
                "error": "Sync in progress, please try again later"
            }

        # Reset sync result
        self._sync_result = {"status": "running"}

        def sync_task():
            """Background sync task"""
            try:
                import shutil
                frago_path = shutil.which("frago")
                if not frago_path:
                    self._sync_result = {
                        "status": "error",
                        "error": "frago command not found"
                    }
                    return

                # Configure gh credential helper first, ensure git can use gh's OAuth token
                gh_path = shutil.which("gh")
                if gh_path:
                    try:
                        subprocess.run(
                            _prepare_command_for_windows([gh_path, 'auth', 'setup-git']),
                            capture_output=True,
                            timeout=10
                        )
                    except Exception:
                        pass  # Ignore errors, continue trying sync

                # Execute frago sync
                # Use errors='replace' to handle possible encoding issues on Windows
                process = subprocess.Popen(
                    _prepare_command_for_windows([frago_path, 'sync']),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )

                output_lines = []
                # Manually decode to handle encoding errors
                for line in process.stdout:
                    try:
                        decoded = line.decode('utf-8').strip()
                    except UnicodeDecodeError:
                        # Windows may output GBK encoding
                        try:
                            decoded = line.decode('gbk').strip()
                        except UnicodeDecodeError:
                            decoded = line.decode('utf-8', errors='replace').strip()
                    if decoded:
                        output_lines.append(decoded)

                process.wait()

                if process.returncode == 0:
                    self._sync_result = {
                        "status": "ok",
                        "output": "\n".join(output_lines)
                    }
                else:
                    self._sync_result = {
                        "status": "error",
                        "error": "\n".join(output_lines) or "Sync failed"
                    }

            except Exception as e:
                self._sync_result = {
                    "status": "error",
                    "error": str(e)
                }

        # Start background thread
        thread = threading.Thread(target=sync_task, daemon=True)
        thread.start()

        return {
            "status": "ok",
            "message": "Sync started"
        }

    def get_sync_result(self) -> Dict[str, Any]:
        """Get sync result (polling)

        Returns:
            {"status": "running"} or {"status": "ok", "output": "..."} or {"status": "error", "error": "..."}
        """
        if self._sync_result is None:
            return {"status": "error", "error": "No sync in progress"}

        return self._sync_result

    def check_sync_repo_visibility(self) -> Dict[str, Any]:
        """Check sync repository visibility

        Returns:
            {"status": "ok", "visibility": "public"/"private"} or
            {"status": "error", "error": "..."}
        """
        from frago.init.configurator import load_config
        from frago.tools.sync_repo import _check_repo_visibility

        try:
            config = load_config()
            repo_url = config.sync_repo_url

            if not repo_url:
                return {
                    "status": "error",
                    "error": "Sync repository not configured"
                }

            visibility = _check_repo_visibility(repo_url)

            if visibility is None:
                return {
                    "status": "error",
                    "error": "Unable to detect repository visibility (gh CLI may not be installed or not logged in)"
                }

            return {
                "status": "ok",
                "visibility": visibility,
                "is_public": visibility == "public"
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def open_tutorial(self, tutorial_id: str, lang: str = "auto", anchor: str = "") -> Dict[str, Any]:
        """Open tutorial presentation window

        Open specified tutorial presentation in new window.

        Args:
            tutorial_id: Tutorial ID, such as "intro", "guide", "best-practices", "videos"
            lang: Language, "auto" auto-detect, "zh" Chinese, "en" English
            anchor: Anchor ID for jumping to specific page position, such as "concepts"

        Returns:
            {"status": "ok", "tutorial_id": "..."} or {"status": "error", "error": "..."}
        """
        import locale

        # Language detection
        if lang == "auto":
            try:
                system_lang = locale.getdefaultlocale()[0] or ""
                lang = "zh" if system_lang.startswith("zh") else "en"
            except Exception:
                lang = "en"

        # Build path
        tips_dir = Path.home() / ".frago" / "tips" / "tutorials"
        filename = f"{tutorial_id}.zh-CN.html" if lang == "zh" else f"{tutorial_id}.html"
        tutorial_path = tips_dir / filename

        # Check if file exists
        if not tutorial_path.exists():
            # Try falling back to English version
            fallback_path = tips_dir / f"{tutorial_id}.html"
            if fallback_path.exists():
                tutorial_path = fallback_path
            else:
                return {
                    "status": "error",
                    "error": f"Tutorial file does not exist: {tutorial_path}"
                }

        # Open Viewer window in new thread to avoid blocking GUI
        def show_viewer():
            try:
                from frago.viewer import ViewerWindow

                viewer = ViewerWindow(
                    content=tutorial_path,
                    mode="doc",  # Document mode: full page, scrollable
                    theme="github-dark",
                    title=f"Frago Tutorial",
                    width=900,
                    height=700,
                    anchor=anchor if anchor else None,
                )
                viewer.show()
            except Exception as e:
                # Log error in background thread (cannot return directly to frontend)
                import logging
                logging.getLogger(__name__).error(f"Failed to open tutorial window: {e}")

        thread = threading.Thread(target=show_viewer, daemon=True)
        thread.start()

        return {
            "status": "ok",
            "tutorial_id": tutorial_id,
            "lang": lang
        }