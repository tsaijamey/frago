"""Recipe 系统专用异常类"""


class RecipeError(Exception):
    """Recipe 基础异常类"""
    pass


class RecipeNotFoundError(RecipeError):
    """Recipe 未找到异常"""
    def __init__(self, name: str, searched_paths: list[str] | None = None):
        self.name = name
        self.searched_paths = searched_paths or []
        message = f"Recipe '{name}' 未找到"
        if self.searched_paths:
            paths_str = '\n  - '.join(self.searched_paths)
            message += f"\n\n已搜索路径:\n  - {paths_str}"
        super().__init__(message)


class RecipeExecutionError(RecipeError):
    """Recipe 执行失败异常"""
    def __init__(
        self,
        recipe_name: str,
        runtime: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ):
        self.recipe_name = recipe_name
        self.runtime = runtime
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        message = f"Recipe '{recipe_name}' 执行失败 (exit code: {exit_code})"
        if stderr:
            message += f"\nError: {stderr[:200]}"
        super().__init__(message)


class RecipeValidationError(RecipeError):
    """Recipe 验证失败异常"""
    def __init__(self, recipe_name: str, errors: list[str]):
        self.recipe_name = recipe_name
        self.errors = errors
        errors_str = '\n  - '.join(errors)
        message = f"Recipe '{recipe_name}' 验证失败:\n  - {errors_str}"
        super().__init__(message)


class MetadataParseError(RecipeError):
    """元数据解析失败异常"""
    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        message = f"元数据文件解析失败: {file_path}\n原因: {reason}"
        super().__init__(message)
