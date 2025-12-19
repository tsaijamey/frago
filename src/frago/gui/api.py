"""Python API exposed to JavaScript for Frago GUI.

Implements the JS-Python bridge using pywebview's js_api protocol.
Extended for 011-gui-tasks-redesign: Tasks 相关 API 方法。
"""

import json
import platform
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter


def _prepare_command_for_windows(cmd: List[str]) -> List[str]:
    """
    为 Windows 平台调整命令格式

    Windows 上通过 pip/npm 安装的命令是 .CMD/.BAT 批处理文件，
    subprocess 直接执行会报 [WinError 2]。需要通过 cmd.exe /c 执行。
    """
    if platform.system() != "Windows":
        return cmd

    if not cmd:
        return cmd

    executable = shutil.which(cmd[0])
    if executable and executable.lower().endswith(('.cmd', '.bat')):
        return ["cmd.exe", "/c"] + cmd

    return cmd

try:
    import webview
except ImportError:
    webview = None

from frago.gui.config import load_config, save_config, update_config
from frago.gui.exceptions import RecipeNotFoundError, TaskAlreadyRunningError
from frago.gui.history import append_record, clear_history, get_history
from frago.gui.models import (
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
from frago.gui.state import AppStateManager

# 011-gui-tasks-redesign: 导入 session 模块
from frago.session.storage import (
    list_sessions,
    read_metadata,
    read_steps,
    read_steps_paginated,
    read_summary,
)
from frago.session.models import AgentType


class FragoGuiApi:
    """Python API class exposed to JavaScript via pywebview."""

    # 会话同步间隔（秒）
    SYNC_INTERVAL_SECONDS = 5

    def __init__(self) -> None:
        """Initialize the GUI API."""
        self.window: Optional["webview.Window"] = None
        self.state = AppStateManager.get_instance()
        self._recipe_cache: List[RecipeItem] = []
        self._skill_cache: List[SkillItem] = []
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_stop_event = threading.Event()
        self._sync_result: Optional[Dict[str, Any]] = None  # 用于 Settings 页面的 sync 状态

        # GUI 启动时同步当前项目的 Claude 会话
        self._sync_sessions_on_startup()

    def _sync_sessions_on_startup(self) -> None:
        """GUI 启动时启动定时会话同步

        启动一个后台线程，每隔 SYNC_INTERVAL_SECONDS 秒同步一次会话数据。
        从 ~/.claude/projects/ 同步所有项目到 ~/.frago/sessions/claude/
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
                            f"会话同步: synced={result.synced}, updated={result.updated}"
                        )
                except Exception as e:
                    logger.warning(f"会话同步失败: {e}")

                # 等待下一次同步，但可被中断
                self._sync_stop_event.wait(self.SYNC_INTERVAL_SECONDS)

        # 启动后台同步线程
        self._sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self._sync_thread.start()
        logger.info(f"会话同步线程已启动 (间隔: {self.SYNC_INTERVAL_SECONDS}s)")

    def stop_sync(self) -> None:
        """停止会话同步线程"""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_stop_event.set()
            self._sync_thread.join(timeout=2)
            import logging
            logging.getLogger(__name__).info("会话同步线程已停止")

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

        直接请求 CDP 端点，避免 subprocess 调用 CLI 命令产生日志。

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
        # 从缓存中查找配方
        recipe = None
        for r in self._recipe_cache:
            if r.name == name:
                recipe = r
                break

        if not recipe:
            # 刷新缓存后再找
            self._recipe_cache = self._load_recipes()
            for r in self._recipe_cache:
                if r.name == name:
                    recipe = r
                    break

        if not recipe:
            return {"error": f"配方 '{name}' 不存在"}

        result = recipe.to_dict()

        # 读取 recipe.md 内容
        if recipe.path:
            recipe_path = Path(recipe.path)
            # path 可能是脚本路径，需要找到 recipe.md
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

        # 从缓存中查找配方
        recipe = None
        for r in self._recipe_cache:
            if r.name == name:
                recipe = r
                break

        if not recipe:
            return {"status": "error", "message": f"配方 '{name}' 不存在"}

        # 只允许删除用户级配方
        if recipe.source != "User":
            return {
                "status": "error",
                "message": f"只能删除用户级配方，'{name}' 来源是 {recipe.source}",
            }

        if not recipe.path:
            return {"status": "error", "message": "配方路径未知"}

        recipe_path = Path(recipe.path)
        if recipe_path.is_file():
            recipe_dir = recipe_path.parent
        else:
            recipe_dir = recipe_path

        # 确保是在用户目录下
        user_recipes_dir = Path.home() / ".frago" / "recipes"
        try:
            recipe_dir.relative_to(user_recipes_dir)
        except ValueError:
            return {
                "status": "error",
                "message": f"配方不在用户目录下，无法删除",
            }

        if not recipe_dir.exists():
            return {"status": "error", "message": "配方目录不存在"}

        try:
            shutil.rmtree(recipe_dir)
            # 刷新缓存
            self._recipe_cache = self._load_recipes()
            return {"status": "ok", "message": f"配方 '{name}' 已删除"}
        except Exception as e:
            return {"status": "error", "message": f"删除失败: {e}"}

    def refresh_skills(self) -> List[Dict]:
        """Refresh and return the skill list.

        Returns:
            Updated list of skill dictionaries.
        """
        self._skill_cache = self._load_skills()
        return [s.to_dict() for s in self._skill_cache]

    # ============================================================
    # 011-gui-tasks-redesign: Tasks 相关 API 方法
    # ============================================================

    def get_tasks(self, limit: int = 50, status: Optional[str] = None) -> List[Dict]:
        """获取任务列表

        优先从 ~/.frago/sessions/ 读取会话数据，如果为空则从
        GUI history 中读取 AGENT 类型的记录作为任务列表。

        Args:
            limit: 最大返回数量，范围 1-100，默认 50
            status: 筛选状态（可选），支持 running/completed/error/cancelled

        Returns:
            任务列表
        """
        try:
            from frago.session.models import SessionStatus

            # 参数验证
            limit = max(1, min(100, limit))

            # 转换状态筛选参数
            status_filter = None
            if status:
                try:
                    status_filter = SessionStatus(status)
                except ValueError:
                    pass  # 无效状态，忽略筛选

            tasks = []
            session_ids = set()

            # 1. 从 sessions 目录获取已有任务
            # 请求更多会话以弥补过滤损失
            sessions = list_sessions(
                agent_type=AgentType.CLAUDE,
                limit=limit * 3,  # 请求 3 倍数量，过滤后再截取
                status=status_filter,
            )

            for session in sessions:
                try:
                    # 应用过滤规则：跳过低价值会话
                    if not TaskItem.should_display(session):
                        continue
                    task = TaskItem.from_session(session)
                    tasks.append(task.model_dump(mode="json"))
                    session_ids.add(session.session_id)
                except Exception:
                    continue

            # 注：移除 history fallback，因为 history 的 task_id 与 Claude session_id 不匹配
            # 同步机制会确保所有 Claude session 都被导入

            # 按 started_at 倒序排序
            tasks.sort(
                key=lambda t: t.get("started_at") or "",
                reverse=True
            )

            return tasks[:limit]

        except Exception:
            # 降级到 history
            return self._get_tasks_from_history(limit, status)

    def _get_tasks_from_history(
        self, limit: int = 50, status: Optional[str] = None
    ) -> List[Dict]:
        """从 GUI history 中读取 AGENT 类型记录作为任务列表

        Args:
            limit: 最大返回数量
            status: 筛选状态

        Returns:
            任务列表
        """
        # 转换状态筛选
        task_status = None
        if status:
            try:
                task_status = TaskStatus(status)
            except ValueError:
                pass

        # 读取 AGENT 类型的历史记录
        records = get_history(
            limit=limit,
            command_type=CommandType.AGENT,
            status=task_status,
        )

        tasks = []
        for record in records:
            # 将 CommandRecord 转换为类似 TaskItem 的格式
            task = {
                "session_id": record.id,
                "name": record.input_text[:100] if record.input_text else "未命名任务",
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
        """从 history 获取任务详情（用于刚启动尚未产生 session 数据的任务）"""
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

        return {"error": f"会话 {session_id} 不存在或已删除"}

    def get_task_detail(
        self,
        session_id: str,
        steps_limit: int = 0,
        steps_offset: int = 0,
    ) -> Dict[str, Any]:
        """获取任务详情

        读取指定会话的完整信息，包括元数据、步骤记录和摘要。

        Args:
            session_id: 会话 ID（必填）
            steps_limit: 步骤数量限制，0 表示获取全部，默认 0
            steps_offset: 步骤偏移量，用于分页，默认 0

        Returns:
            任务详情字典，包含：
            - session_id, name, status, started_at, ended_at
            - duration_ms, project_path
            - step_count, tool_call_count, user_message_count, assistant_message_count
            - steps (步骤列表)
            - steps_total, steps_offset, has_more_steps
            - summary (完成后的摘要)
            - error (如果出错)
        """
        # 参数验证
        if not session_id:
            return {"error": "会话 ID 不能为空"}

        # steps_limit = 0 或 None 表示获取全部
        if not steps_limit:
            steps_limit = 10000  # 设置一个足够大的值
        else:
            steps_limit = max(1, min(10000, steps_limit))
        steps_offset = max(0, steps_offset or 0)

        try:
            # 读取会话元数据
            session = read_metadata(session_id, AgentType.CLAUDE)
            if not session:
                # 尝试从 history 获取（可能是刚启动的任务）
                return self._get_task_detail_from_history(session_id)

            # 分页读取步骤
            steps_result = read_steps_paginated(
                session_id, AgentType.CLAUDE, steps_limit, steps_offset
            )
            steps = steps_result["steps"]
            total_steps = steps_result["total"]

            # 读取摘要（可能不存在）
            summary = read_summary(session_id, AgentType.CLAUDE)

            # 构建 TaskDetail
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
            return {"error": f"加载任务详情失败: {str(e)}"}

    def get_task_steps(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """分页获取任务步骤

        用于任务详情页的"加载更多"功能，返回指定范围的步骤记录。

        Args:
            session_id: 会话 ID（必填）
            offset: 偏移量，从第几条开始，默认 0
            limit: 数量限制，范围 1-100，默认 50

        Returns:
            字典包含：
            - steps: 步骤列表
            - total: 总步骤数
            - offset: 当前偏移量
            - has_more: 是否还有更多
            - error: 错误信息（如果出错）
        """
        # 参数验证
        if not session_id:
            return {"error": "会话 ID 不能为空", "steps": [], "has_more": False}

        limit = max(1, min(100, limit))
        offset = max(0, offset)

        try:
            result = read_steps_paginated(session_id, AgentType.CLAUDE, limit, offset)

            # 转换步骤格式为 GUI 所需格式
            gui_steps = [TaskStep.from_session_step(s) for s in result["steps"]]

            return {
                "steps": [s.model_dump(mode="json") for s in gui_steps],
                "total": result["total"],
                "offset": result["offset"],
                "has_more": result["has_more"],
            }
        except Exception as e:
            return {
                "error": f"加载步骤失败: {str(e)}",
                "steps": [],
                "has_more": False,
            }

    def start_agent_task(self, prompt: str) -> Dict[str, Any]:
        """启动 agent 任务

        在后台执行 `frago agent {prompt}` 命令。
        任务启动后立即返回，不等待任务完成。
        同时在 history 中记录一条"运行中"的记录。

        Args:
            prompt: 任务描述/提示词

        Returns:
            字典包含：
            - status: "ok" 或 "error"
            - message: 状态消息
            - task_id: 任务 ID（成功时返回）
            - error: 错误信息（如果出错）
        """
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "任务描述不能为空"}

        prompt = prompt.strip()
        task_id = str(uuid.uuid4())

        try:
            # 先记录一条"运行中"的 history 记录
            record = CommandRecord(
                id=task_id,
                timestamp=datetime.now(),
                command_type=CommandType.AGENT,
                input_text=prompt,
                status=TaskStatus.RUNNING,
                duration_ms=0,
            )
            append_record(record)

            # 在后台启动 frago agent 命令
            # 使用 shutil.which 查找完整路径，避免环境变量问题
            import shutil
            frago_path = shutil.which("frago")
            if not frago_path:
                return {
                    "status": "error",
                    "error": "frago 命令未找到，请确保已正确安装并在 PATH 中",
                }

            # 使用 Popen 启动进程，不等待完成
            # 重定向输出到日志文件以便调试
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-{task_id[:8]}.log"

            with open(log_file, "w") as f:
                subprocess.Popen(
                    _prepare_command_for_windows([frago_path, "agent", "--yes", prompt]),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # 分离进程，防止 GUI 关闭时终止任务
                )

            return {
                "status": "ok",
                "task_id": task_id,
                "message": f"任务已启动: {prompt[:50]}{'...' if len(prompt) > 50 else ''}",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago 命令未找到，请确保已正确安装",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"启动任务失败: {str(e)}",
            }

    def continue_agent_task(self, session_id: str, prompt: str) -> Dict[str, Any]:
        """在指定会话中继续对话

        Args:
            session_id: 要继续的会话 ID
            prompt: 用户输入的新提示词

        Returns:
            字典包含：
            - status: "ok" 或 "error"
            - message: 状态消息
            - error: 错误信息（如果出错）
        """
        if not session_id:
            return {"status": "error", "error": "session_id 不能为空"}
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "任务描述不能为空"}

        prompt = prompt.strip()

        try:
            import shutil
            frago_path = shutil.which("frago")
            if not frago_path:
                return {
                    "status": "error",
                    "error": "frago 命令未找到，请确保已正确安装并在 PATH 中",
                }

            # 使用 Popen 启动进程，不等待完成
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-resume-{session_id[:8]}.log"

            with open(log_file, "w") as f:
                subprocess.Popen(
                    _prepare_command_for_windows([frago_path, "agent", "--resume", session_id, "--yes", prompt]),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )

            return {
                "status": "ok",
                "message": f"已在会话 {session_id[:8]}... 中继续: {prompt[:50]}{'...' if len(prompt) > 50 else ''}",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago 命令未找到，请确保已正确安装",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"继续任务失败: {str(e)}",
            }

    # ============================================================
    # Settings 页面相关 API 方法：主配置管理
    # ============================================================

    def get_main_config(self) -> Dict[str, Any]:
        """获取主配置 (~/.frago/config.json)

        Returns:
            配置字典，包含 Config 模型的所有字段，以及额外的 working_directory_display
        """
        from frago.init.config_manager import load_config

        try:
            config = load_config()
            result = config.model_dump(mode='json')
            # 添加工作目录显示路径（固定为 ~/.frago/projects，但显示实际路径）
            result['working_directory_display'] = str(Path.home() / ".frago" / "projects")
            return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"加载主配置失败: {e}")
            # 返回空配置
            from frago.init.models import Config
            result = Config().model_dump(mode='json')
            result['working_directory_display'] = str(Path.home() / ".frago" / "projects")
            return result

    def update_main_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """更新主配置

        Args:
            updates: 部分更新字典，例如 {"sync_repo_url": "git@github.com:user/repo.git"}

        Returns:
            {"status": "ok", "config": {...}} 或 {"status": "error", "error": "..."}
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
                "error": f"配置验证失败: {e}"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def update_auth_method(self, auth_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新认证方式和 API 端点

        同时更新:
        - ~/.frago/config.json (frago 配置)
        - ~/.claude/settings.json (Claude Code 环境变量)
        - ~/.claude.json (跳过官方登录)

        Args:
            auth_data: {
                "auth_method": "official" | "custom",
                "api_endpoint": {  # 仅 custom 时提供
                    "type": "deepseek" | "aliyun" | "kimi" | "minimax" | "custom",
                    "url": "...",  # 仅 type=custom 时需要
                    "api_key": "..."
                }
            }

        Returns:
            {"status": "ok", "config": {...}} 或 {"status": "error", "error": "..."}
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
            # 构建更新字典
            updates: Dict[str, Any] = {
                "auth_method": auth_data["auth_method"]
            }

            # 处理 api_endpoint
            if auth_data["auth_method"] == "custom":
                if "api_endpoint" not in auth_data:
                    return {
                        "status": "error",
                        "error": "Custom auth requires api_endpoint"
                    }
                updates["api_endpoint"] = auth_data["api_endpoint"]

                # 同步写入 ~/.claude/settings.json
                endpoint = auth_data["api_endpoint"]
                endpoint_type = endpoint.get("type", "custom")
                api_key = endpoint.get("api_key", "")
                custom_url = endpoint.get("url") if endpoint_type == "custom" else None
                custom_model = endpoint.get("model") if endpoint_type == "custom" else None

                # 构建 Claude Code env 配置
                env_config = build_claude_env_config(
                    endpoint_type=endpoint_type,
                    api_key=api_key,
                    custom_url=custom_url,
                    custom_model=custom_model,
                )

                # 确保 ~/.claude.json 存在（跳过官方登录流程）
                ensure_claude_json_for_custom_auth()

                # 写入 ~/.claude/settings.json
                save_claude_settings({"env": env_config})
                logger.info("已同步 API 配置到 ~/.claude/settings.json")
            else:
                # official 模式，移除 api_endpoint 并删除 settings.json
                updates["api_endpoint"] = None

                # 删除 ~/.claude/settings.json，让 Claude Code 使用官方配置
                if delete_claude_settings():
                    logger.info("已删除 ~/.claude/settings.json，切换到官方 API")
                else:
                    logger.warning("删除 ~/.claude/settings.json 失败")

            # 更新 ~/.frago/config.json
            config = update_config(updates)

            # 对返回的配置进行掩码处理
            config_dict = config.model_dump(mode='json')
            if config_dict.get("api_endpoint") and config_dict["api_endpoint"].get("api_key"):
                config_dict["api_endpoint"]["api_key"] = self._mask_api_key(
                    config_dict["api_endpoint"]["api_key"]
                )

            # 添加工作目录显示路径
            config_dict['working_directory_display'] = str(Path.home() / ".frago" / "projects")

            return {
                "status": "ok",
                "config": config_dict
            }
        except ValidationError as e:
            return {
                "status": "error",
                "error": f"配置验证失败: {e}"
            }
        except Exception as e:
            logger.exception("更新认证配置失败")
            return {
                "status": "error",
                "error": str(e)
            }

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        """掩码 API key（前4后4，短于8位则完全掩码）

        Args:
            api_key: 原始 API key

        Returns:
            掩码后的 API key
        """
        if len(api_key) <= 8:
            return '••••••••'
        return api_key[:4] + '••••' + api_key[-4:]

    def open_working_directory(self) -> Dict[str, Any]:
        """在文件管理器中打开工作目录

        工作目录固定为 ~/.frago/projects

        Returns:
            {"status": "ok"} 或 {"status": "error", "error": "..."}
        """
        import subprocess
        import sys

        try:
            # 工作目录固定为 ~/.frago/projects
            work_dir_path = Path.home() / ".frago" / "projects"

            # 确保目录存在
            work_dir_path.mkdir(parents=True, exist_ok=True)

            # 根据操作系统打开文件管理器
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
                "error": f"打开目录失败: {str(e)}"
            }

    # ============================================================
    # Settings 页面相关 API 方法：环境变量管理
    # ============================================================

    def get_env_vars(self) -> Dict[str, Any]:
        """获取用户级环境变量 (~/.frago/.env)

        Returns:
            {"vars": {...}, "file_exists": bool}
        """
        from frago.recipes.env_loader import EnvLoader

        try:
            env_path = EnvLoader.USER_ENV_PATH
            loader = EnvLoader()

            # 加载用户级 .env 文件
            env_vars = loader.load_env_file(env_path)

            return {
                "vars": env_vars,
                "file_exists": env_path.exists()
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"加载环境变量失败: {e}")
            return {
                "vars": {},
                "file_exists": False
            }

    def update_env_vars(self, updates: Dict[str, Optional[str]]) -> Dict[str, Any]:
        """批量更新环境变量

        Args:
            updates: {"KEY": "value", "DELETE_KEY": None} - value=None 表示删除

        Returns:
            {"status": "ok", "vars": {...}} 或 {"status": "error", "error": "..."}
        """
        from frago.recipes.env_loader import EnvLoader, update_env_file

        try:
            env_path = EnvLoader.USER_ENV_PATH

            # 更新 .env 文件
            update_env_file(env_path, updates)

            # 重新加载并返回
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
        """扫描所有 Recipe 的环境变量需求

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
                "python-frontmatter 未安装，无法扫描 Recipe 环境变量需求"
            )
            return []

        from frago.recipes.env_loader import EnvLoader

        requirements = []
        recipe_dirs = [
            Path.home() / ".frago" / "recipes",
        ]

        # 加载当前环境变量
        try:
            current_env = EnvLoader().load_all()
        except Exception:
            current_env = {}

        # 扫描 Recipe 目录
        for recipe_dir in recipe_dirs:
            if not recipe_dir.exists():
                continue

            for md_file in recipe_dir.rglob("recipe.md"):
                try:
                    # 解析 frontmatter
                    post = frontmatter.load(md_file)
                    env_vars = post.metadata.get("env", {})

                    if not env_vars:
                        continue

                    recipe_name = post.metadata.get("name", md_file.parent.name)

                    for var_name, var_def in env_vars.items():
                        # var_def 可能是字典或简单的默认值
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
                        f"解析 {md_file} 失败: {e}"
                    )
                    continue

        # 去重（同一变量被多个 Recipe 使用）
        unique = {}
        for req in requirements:
            key = req["var_name"]
            if key not in unique:
                unique[key] = req
            else:
                # 合并 recipe_name
                unique[key]["recipe_name"] += f", {req['recipe_name']}"
                # 保留更高优先级的属性（任一 required=True 则为 True）
                if req["required"]:
                    unique[key]["required"] = True

        return list(unique.values())

    # ============================================================
    # Settings 页面相关 API 方法：GitHub 集成
    # ============================================================

    def check_gh_cli(self) -> Dict[str, Any]:
        """检查 gh CLI 安装和登录状态

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

        # 检查 gh 是否安装
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
                # 解析版本号（格式如 "gh version 2.40.1 (2023-12-13)"）
                import re
                match = re.search(r'gh version ([\d.]+)', version_result.stdout)
                if match:
                    result["version"] = match.group(1)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return result

        # 检查登录状态
        if result["installed"]:
            try:
                auth_result = subprocess.run(
                    _prepare_command_for_windows(['gh', 'auth', 'status']),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=5
                )
                # gh auth status 返回 0 表示已登录
                if auth_result.returncode == 0:
                    result["authenticated"] = True
                    # 解析用户名（从输出中提取）
                    import re
                    match = re.search(r'Logged in to github\.com as ([^\s]+)', auth_result.stderr)
                    if match:
                        result["username"] = match.group(1)
            except subprocess.TimeoutExpired:
                pass

        return result

    def gh_auth_login(self) -> Dict[str, Any]:
        """在外部终端执行 gh auth login

        Returns:
            {"status": "ok", "message": "..."} 或 {"status": "error", "error": "..."}
        """
        import platform

        try:
            system = platform.system()

            if system == 'Linux':
                # 尝试 x-terminal-emulator
                try:
                    subprocess.Popen(
                        ['x-terminal-emulator', '-e', 'gh', 'auth', 'login']
                    )
                    return {"status": "ok", "message": "已打开终端，请在终端中完成登录"}
                except FileNotFoundError:
                    # 降级到 gnome-terminal
                    try:
                        subprocess.Popen(
                            ['gnome-terminal', '--', 'gh', 'auth', 'login']
                        )
                        return {"status": "ok", "message": "已打开终端，请在终端中完成登录"}
                    except FileNotFoundError:
                        return {
                            "status": "error",
                            "error": "未找到可用的终端模拟器 (x-terminal-emulator, gnome-terminal)"
                        }
            elif system == 'Darwin':
                # macOS
                script = 'tell application "Terminal" to do script "gh auth login; exit"'
                subprocess.run(['osascript', '-e', script])
                return {"status": "ok", "message": "已打开终端，请在终端中完成登录"}
            elif system == 'Windows':
                # Windows: 优先使用 PowerShell (Windows 10/11 默认)
                try:
                    subprocess.Popen(
                        ['powershell', '-NoExit', '-Command', 'gh auth login'],
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    return {"status": "ok", "message": "已打开 PowerShell 窗口，请在窗口中完成登录"}
                except FileNotFoundError:
                    # 回退到 cmd
                    try:
                        subprocess.Popen(
                            ['cmd', '/c', 'start', 'cmd', '/k', 'gh auth login'],
                            creationflags=subprocess.CREATE_NEW_CONSOLE
                        )
                        return {"status": "ok", "message": "已打开命令提示符窗口，请在窗口中完成登录"}
                    except Exception as e:
                        return {"status": "error", "error": f"无法打开终端窗口: {e}"}
            else:
                return {"status": "error", "error": f"不支持的操作系统: {system}"}

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def create_sync_repo(self, repo_name: str, private: bool = True) -> Dict[str, Any]:
        """创建 GitHub 仓库并配置到 config.json

        Args:
            repo_name: 仓库名称（不含用户名前缀）
            private: 是否私有仓库

        Returns:
            {"status": "ok", "repo_url": "..."} 或 {"status": "error", "error": "..."}
        """
        from frago.init.config_manager import update_config

        try:
            # 创建仓库
            cmd = ['gh', 'repo', 'create', repo_name]
            if private:
                cmd.append('--private')
            else:
                cmd.append('--public')

            # 添加描述
            cmd.extend(['--description', 'Frago resources sync repository'])

            # 重试机制
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
                        # 成功创建，解析仓库 URL
                        # gh repo create 输出类似: ✓ Created repository user/repo on GitHub
                        # 我们需要获取 SSH URL
                        username_result = subprocess.run(
                            _prepare_command_for_windows(['gh', 'api', 'user', '--jq', '.login']),
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            timeout=5
                        )
                        username = username_result.stdout.strip()
                        repo_url = f"git@github.com:{username}/{repo_name}.git"

                        # 更新配置
                        update_config({"sync_repo_url": repo_url})

                        return {
                            "status": "ok",
                            "repo_url": repo_url
                        }
                    else:
                        last_error = result.stderr.strip()
                        if "already exists" in last_error.lower():
                            # 仓库已存在，不需要重试
                            return {
                                "status": "error",
                                "error": f"仓库 {repo_name} 已存在"
                            }
                        # 其他错误，继续重试
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue

                except subprocess.TimeoutExpired:
                    last_error = "创建仓库超时"
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue

            return {
                "status": "error",
                "error": last_error or "创建仓库失败"
            }

        except FileNotFoundError:
            return {
                "status": "error",
                "error": "gh 命令未找到，请确保已安装 GitHub CLI"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def list_user_repos(self, limit: int = 100) -> Dict[str, Any]:
        """列出用户的 GitHub 仓库

        Args:
            limit: 最大返回数量，默认 100

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
            # 使用 gh api 获取用户仓库列表
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
                    "error": result.stderr.strip() or "获取仓库列表失败"
                }

            # 解析 JSON Lines 输出
            repos = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        repos.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            return {
                "status": "ok",
                "repos": repos[:limit]  # 确保不超过 limit
            }

        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "获取仓库列表超时"}
        except FileNotFoundError:
            return {"status": "error", "error": "gh 命令未找到"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def select_existing_repo(self, ssh_url: str) -> Dict[str, Any]:
        """选择已有仓库作为同步仓库

        Args:
            ssh_url: 仓库的 SSH URL

        Returns:
            {"status": "ok", "repo_url": "..."} 或 {"status": "error", "error": "..."}
        """
        from frago.init.config_manager import update_config

        try:
            # 验证 URL 格式
            if not ssh_url.startswith('git@github.com:') or not ssh_url.endswith('.git'):
                return {
                    "status": "error",
                    "error": "无效的 SSH URL 格式，请使用 git@github.com:user/repo.git 格式"
                }

            # 更新配置
            update_config({"sync_repo_url": ssh_url})

            return {
                "status": "ok",
                "repo_url": ssh_url
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    def run_first_sync(self) -> Dict[str, Any]:
        """执行 frago sync（后台线程）

        Returns:
            {"status": "ok", "message": "同步已开始"}
        """
        # 检查是否有同步正在运行
        if self._sync_result and self._sync_result.get("status") == "running":
            return {
                "status": "error",
                "error": "同步正在进行中，请稍后再试"
            }

        # 重置同步结果
        self._sync_result = {"status": "running"}

        def sync_task():
            """后台同步任务"""
            try:
                import shutil
                frago_path = shutil.which("frago")
                if not frago_path:
                    self._sync_result = {
                        "status": "error",
                        "error": "frago 命令未找到"
                    }
                    return

                # 执行 frago sync
                process = subprocess.Popen(
                    [frago_path, 'sync'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8'
                )

                output_lines = []
                for line in process.stdout:
                    output_lines.append(line.strip())

                process.wait()

                if process.returncode == 0:
                    self._sync_result = {
                        "status": "ok",
                        "output": "\n".join(output_lines)
                    }
                else:
                    self._sync_result = {
                        "status": "error",
                        "error": "\n".join(output_lines) or "同步失败"
                    }

            except Exception as e:
                self._sync_result = {
                    "status": "error",
                    "error": str(e)
                }

        # 启动后台线程
        thread = threading.Thread(target=sync_task, daemon=True)
        thread.start()

        return {
            "status": "ok",
            "message": "同步已开始"
        }

    def get_sync_result(self) -> Dict[str, Any]:
        """获取 sync 结果（轮询）

        Returns:
            {"status": "running"} 或 {"status": "ok", "output": "..."} 或 {"status": "error", "error": "..."}
        """
        if self._sync_result is None:
            return {"status": "error", "error": "没有正在进行的同步"}

        return self._sync_result

    def check_sync_repo_visibility(self) -> Dict[str, Any]:
        """检查同步仓库的可见性

        Returns:
            {"status": "ok", "visibility": "public"/"private"} 或
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
                    "error": "未配置同步仓库"
                }

            visibility = _check_repo_visibility(repo_url)

            if visibility is None:
                return {
                    "status": "error",
                    "error": "无法检测仓库可见性（可能未安装 gh CLI 或未登录）"
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
        """打开教程演示窗口

        在新窗口中打开指定的教程演示文稿。

        Args:
            tutorial_id: 教程 ID，如 "intro", "guide", "best-practices", "videos"
            lang: 语言，"auto" 自动检测，"zh" 中文，"en" 英文
            anchor: 锚点 ID，用于跳转到页面特定位置，如 "concepts"

        Returns:
            {"status": "ok", "tutorial_id": "..."} 或 {"status": "error", "error": "..."}
        """
        import locale

        # 语言检测
        if lang == "auto":
            try:
                system_lang = locale.getdefaultlocale()[0] or ""
                lang = "zh" if system_lang.startswith("zh") else "en"
            except Exception:
                lang = "en"

        # 构建路径
        tips_dir = Path.home() / ".frago" / "tips" / "tutorials"
        filename = f"{tutorial_id}.zh-CN.html" if lang == "zh" else f"{tutorial_id}.html"
        tutorial_path = tips_dir / filename

        # 检查文件是否存在
        if not tutorial_path.exists():
            # 尝试回退到英文版
            fallback_path = tips_dir / f"{tutorial_id}.html"
            if fallback_path.exists():
                tutorial_path = fallback_path
            else:
                return {
                    "status": "error",
                    "error": f"教程文件不存在: {tutorial_path}"
                }

        # 在新线程中打开 Viewer 窗口，避免阻塞 GUI
        def show_viewer():
            try:
                from frago.viewer import ViewerWindow

                viewer = ViewerWindow(
                    content=tutorial_path,
                    mode="doc",  # 文档模式：完整页面，可滚动
                    theme="github-dark",
                    title=f"Frago Tutorial",
                    width=900,
                    height=700,
                    anchor=anchor if anchor else None,
                )
                viewer.show()
            except Exception as e:
                # 在后台线程中记录错误（无法直接返回给前端）
                import logging
                logging.getLogger(__name__).error(f"打开教程窗口失败: {e}")

        thread = threading.Thread(target=show_viewer, daemon=True)
        thread.start()

        return {
            "status": "ok",
            "tutorial_id": tutorial_id,
            "lang": lang
        }