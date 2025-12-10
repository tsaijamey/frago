"""Python API exposed to JavaScript for Frago GUI.

Implements the JS-Python bridge using pywebview's js_api protocol.
Extended for 011-gui-tasks-redesign: Tasks 相关 API 方法。
"""

import json
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def __init__(self) -> None:
        """Initialize the GUI API."""
        self.window: Optional["webview.Window"] = None
        self.state = AppStateManager.get_instance()
        self._recipe_cache: List[RecipeItem] = []
        self._skill_cache: List[SkillItem] = []

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
                ["frago", "recipe", "list", "--format", "json"],
                capture_output=True,
                text=True,
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
            Path.home() / ".frago" / "examples",
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

        Returns:
            List of SkillItem instances.
        """
        skills = []
        skills_dir = Path.home() / ".claude" / "skills"

        if not skills_dir.exists():
            return skills

        for path in skills_dir.glob("*.md"):
            name = path.stem
            description = None

            try:
                content = path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if line.startswith("# "):
                        name = line[2:].strip()
                    elif line.strip() and not line.startswith("#") and not line.startswith("---"):
                        description = line.strip()[:100]
                        break
            except Exception:
                pass

            skills.append(
                SkillItem(
                    name=name,
                    description=description,
                    file_path=str(path),
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
                cmd,
                capture_output=True,
                text=True,
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
                ["frago", "agent", prompt],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
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

        Returns:
            True if Chrome is connected.
        """
        try:
            result = subprocess.run(
                ["frago", "chrome", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
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
            sessions = list_sessions(
                agent_type=AgentType.CLAUDE,
                limit=limit,
                status=status_filter,
            )

            for session in sessions:
                try:
                    task = TaskItem.from_session(session)
                    tasks.append(task.model_dump(mode="json"))
                    session_ids.add(session.session_id)
                except Exception:
                    continue

            # 2. 从 history 获取运行中的任务（可能还没有 session 文件）
            running_from_history = self._get_tasks_from_history(
                limit=20,
                status="running"
            )
            for task in running_from_history:
                if task.get("session_id") not in session_ids:
                    tasks.insert(0, task)  # 新任务放在最前面

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
        history = CommandHistory()
        records = history.get_history(limit=100, command_type=CommandType.AGENT)

        for record in records:
            if record.id == session_id:
                return {
                    "session_id": session_id,
                    "name": record.command[:100] if record.command else f"Task {session_id[:8]}",
                    "status": record.status.value if record.status else "running",
                    "started_at": record.timestamp.isoformat() if record.timestamp else None,
                    "ended_at": None,
                    "duration_ms": None,
                    "project_path": str(record.cwd) if record.cwd else None,
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
        steps_limit: int = 50,
        steps_offset: int = 0,
    ) -> Dict[str, Any]:
        """获取任务详情

        读取指定会话的完整信息，包括元数据、步骤记录和摘要。
        步骤支持分页加载，默认返回前 50 条。

        Args:
            session_id: 会话 ID（必填）
            steps_limit: 步骤数量限制，范围 1-100，默认 50
            steps_offset: 步骤偏移量，用于分页，默认 0

        Returns:
            任务详情字典，包含：
            - session_id, name, status, started_at, ended_at
            - duration_ms, project_path
            - step_count, tool_call_count, user_message_count, assistant_message_count
            - steps (分页的步骤列表)
            - steps_total, steps_offset, has_more_steps
            - summary (完成后的摘要)
            - error (如果出错)
        """
        # 参数验证
        if not session_id:
            return {"error": "会话 ID 不能为空"}

        steps_limit = max(1, min(100, steps_limit or 50))
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
                    [frago_path, "agent", "--yes", prompt],
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
