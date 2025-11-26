"""Run命令系统自定义异常

定义所有run系统相关的异常类型
"""


class RunException(Exception):
    """Run系统基础异常"""

    pass


class RunNotFoundError(RunException):
    """Run实例不存在"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"Run '{run_id}' not found")


class InvalidRunIDError(RunException):
    """Run ID格式不合法"""

    def __init__(self, run_id: str, reason: str = ""):
        self.run_id = run_id
        self.reason = reason
        message = f"Invalid run_id '{run_id}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class ContextNotSetError(RunException):
    """当前Run上下文未设置"""

    def __init__(self):
        super().__init__(
            "Current run context not set. "
            "Run 'uv run frago run set-context <run_id>' first."
        )


class ContextAlreadySetError(RunException):
    """已有Run上下文正在运行（互斥锁）"""

    def __init__(self, existing_run_id: str):
        self.existing_run_id = existing_run_id
        super().__init__(
            f"Another run '{existing_run_id}' is currently active. "
            f"Run 'uv run frago run release' to release it first, "
            f"or 'uv run frago run set-context {existing_run_id}' to continue it."
        )


class CorruptedLogError(RunException):
    """JSONL日志文件损坏"""

    def __init__(self, file_path: str, line_number: int, reason: str = ""):
        self.file_path = file_path
        self.line_number = line_number
        self.reason = reason
        message = f"Corrupted log entry at {file_path}:{line_number}"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class FileSystemError(RunException):
    """文件系统操作失败"""

    def __init__(self, operation: str, path: str, reason: str = ""):
        self.operation = operation
        self.path = path
        self.reason = reason
        message = f"Failed to {operation} '{path}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)
