"""Recipe 执行器"""
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from .env_loader import EnvLoader, WorkflowContext
from .exceptions import RecipeExecutionError, RecipeValidationError
from .metadata import validate_params
from .registry import RecipeRegistry


class RecipeRunner:
    """Recipe 运行器，负责执行 Recipe"""

    def __init__(
        self,
        registry: Optional[RecipeRegistry] = None,
        project_root: Optional[Path] = None
    ):
        """
        初始化 RecipeRunner

        Args:
            registry: Recipe 注册表（不提供则自动创建并扫描）
            project_root: 项目根目录（用于加载项目级 .env）
        """
        if registry is None:
            registry = RecipeRegistry()
            registry.scan()

        self.registry = registry
        self.env_loader = EnvLoader(project_root=project_root)

    def run(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        output_target: str = 'stdout',
        output_options: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None
    ) -> dict[str, Any]:
        """
        执行指定的 Recipe

        Args:
            name: Recipe 名称
            params: 输入参数（JSON 字典）
            output_target: 输出目标 ('stdout' | 'file' | 'clipboard')
            output_options: 输出选项（如 file 需要 'path'）
            env_overrides: CLI --env 参数提供的环境变量覆盖
            workflow_context: Workflow 执行上下文（用于跨 Recipe 共享环境变量）

        Returns:
            执行结果字典，格式:
            {
                "success": bool,
                "data": dict | None,
                "error": dict | None,
                "execution_time": float,
                "recipe_name": str,
                "runtime": str
            }

        Raises:
            RecipeNotFoundError: Recipe 不存在
            RecipeValidationError: 参数验证失败
            RecipeExecutionError: 执行失败
        """
        params = params or {}
        output_options = output_options or {}

        # 查找 Recipe
        recipe = self.registry.find(name)

        # 验证参数
        self._validate_params(recipe.metadata, params)

        # 解析环境变量
        try:
            resolved_env = self.env_loader.resolve_for_recipe(
                env_definitions=recipe.metadata.env,
                cli_overrides=env_overrides,
                workflow_context=workflow_context
            )
        except ValueError as e:
            raise RecipeValidationError(name, [str(e)])

        # 记录开始时间
        start_time = time.time()

        try:
            # 根据运行时类型执行 Recipe
            if recipe.metadata.runtime == 'chrome-js':
                result_data = self._run_chrome_js(recipe.script_path, params, resolved_env)
            elif recipe.metadata.runtime == 'python':
                result_data = self._run_python(recipe.script_path, params, resolved_env)
            elif recipe.metadata.runtime == 'shell':
                result_data = self._run_shell(recipe.script_path, params, resolved_env)
            else:
                raise RecipeExecutionError(
                    recipe_name=name,
                    runtime=recipe.metadata.runtime,
                    exit_code=-1,
                    stderr=f"不支持的运行时类型: {recipe.metadata.runtime}"
                )

            # 计算执行时间
            execution_time = time.time() - start_time

            # 返回成功结果
            return {
                "success": True,
                "data": result_data,
                "error": None,
                "execution_time": execution_time,
                "recipe_name": name,
                "runtime": recipe.metadata.runtime
            }

        except RecipeExecutionError:
            # 直接重新抛出 RecipeExecutionError
            raise
        except Exception as e:
            # 其他异常转换为 RecipeExecutionError
            execution_time = time.time() - start_time
            raise RecipeExecutionError(
                recipe_name=name,
                runtime=recipe.metadata.runtime,
                exit_code=-1,
                stderr=str(e)
            )

    def _validate_params(self, metadata, params: dict[str, Any]) -> None:
        """
        验证参数是否符合元数据定义

        Args:
            metadata: Recipe 元数据
            params: 输入参数

        Raises:
            RecipeValidationError: 参数验证失败
        """
        # 使用统一的参数验证函数（包含必需参数和类型检查）
        validate_params(metadata, params)

    def _run_chrome_js(
        self,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str]
    ) -> dict[str, Any]:
        """
        执行 Chrome JavaScript Recipe

        Args:
            script_path: JS 脚本路径
            params: 输入参数
            env: 解析后的环境变量

        Returns:
            执行结果 JSON

        Raises:
            RecipeExecutionError: 执行失败
        """
        # 构建命令：uv run frago exec-js <script_path> --return-value
        cmd = [
            'uv', 'run', 'frago', 'exec-js',
            str(script_path),
            '--return-value'
        ]

        # 如果有参数，需要注入到脚本中（chrome-js 暂不支持参数传递）
        # 这里我们直接执行脚本，参数传递留给后续版本

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                check=False,
                env=env
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='chrome-js',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # 检查输出大小（10MB 限制）
            if len(result.stdout) > 10 * 1024 * 1024:  # 10MB
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='chrome-js',
                    exit_code=-1,
                    stderr=f"Recipe 输出过大: {len(result.stdout) / 1024 / 1024:.2f}MB (限制: 10MB)"
                )

            # 解析 JSON 输出
            try:
                # exec-js 的输出可能是纯文本或 JSON
                # 尝试解析为 JSON，失败则作为文本返回
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                # 返回文本结果
                return {"result": result.stdout.strip()}

        except subprocess.TimeoutExpired:
            raise RecipeExecutionError(
                recipe_name=script_path.stem,
                runtime='chrome-js',
                exit_code=-1,
                stderr="执行超时（5分钟）"
            )

    def _run_python(
        self,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str]
    ) -> dict[str, Any]:
        """
        执行 Python Recipe

        使用 `uv run` 执行脚本，支持 PEP 723 内联依赖声明。
        uv 会自动解析脚本头部的依赖并在隔离环境中执行。

        Args:
            script_path: Python 脚本路径
            params: 输入参数
            env: 解析后的环境变量

        Returns:
            执行结果 JSON

        Raises:
            RecipeExecutionError: 执行失败
        """
        # 构建命令：uv run <script_path> <params_json>
        # uv 会自动处理 PEP 723 内联依赖（# /// script ... # ///）
        params_json = json.dumps(params)
        cmd = ['uv', 'run', str(script_path), params_json]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                check=False,
                env=env
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='python',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # 检查输出大小（10MB 限制）
            if len(result.stdout) > 10 * 1024 * 1024:  # 10MB
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='python',
                    exit_code=-1,
                    stderr=f"Recipe 输出过大: {len(result.stdout) / 1024 / 1024:.2f}MB (限制: 10MB)"
                )

            # 解析 JSON 输出
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='python',
                    exit_code=-1,
                    stderr=f"JSON 解析失败: {e}\n输出: {result.stdout[:200]}"
                )

        except subprocess.TimeoutExpired:
            raise RecipeExecutionError(
                recipe_name=script_path.stem,
                runtime='python',
                exit_code=-1,
                stderr="执行超时（5分钟）"
            )

    def _run_shell(
        self,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str]
    ) -> dict[str, Any]:
        """
        执行 Shell Recipe

        Args:
            script_path: Shell 脚本路径
            params: 输入参数
            env: 解析后的环境变量

        Returns:
            执行结果 JSON

        Raises:
            RecipeExecutionError: 执行失败
        """
        # 检查执行权限
        if not script_path.stat().st_mode & 0o100:
            raise RecipeExecutionError(
                recipe_name=script_path.stem,
                runtime='shell',
                exit_code=-1,
                stderr=f"脚本没有执行权限: {script_path}"
            )

        # 构建命令：<script_path> <params_json>
        params_json = json.dumps(params)
        cmd = [str(script_path), params_json]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                check=False,
                env=env
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='shell',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # 检查输出大小（10MB 限制）
            if len(result.stdout) > 10 * 1024 * 1024:  # 10MB
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='shell',
                    exit_code=-1,
                    stderr=f"Recipe 输出过大: {len(result.stdout) / 1024 / 1024:.2f}MB (限制: 10MB)"
                )

            # 解析 JSON 输出
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                raise RecipeExecutionError(
                    recipe_name=script_path.stem,
                    runtime='shell',
                    exit_code=-1,
                    stderr=f"JSON 解析失败: {e}\n输出: {result.stdout[:200]}"
                )

        except subprocess.TimeoutExpired:
            raise RecipeExecutionError(
                recipe_name=script_path.stem,
                runtime='shell',
                exit_code=-1,
                stderr="执行超时（5分钟）"
            )
