"""Run Command System Custom Exceptions

Defines all run system related exception types
"""


class RunException(Exception):
    """Run system base exception"""

    pass


class RunNotFoundError(RunException):
    """Run instance does not exist"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"Run '{run_id}' not found")


class InvalidRunIDError(RunException):
    """Run ID format is invalid"""

    def __init__(self, run_id: str, reason: str = ""):
        self.run_id = run_id
        self.reason = reason
        message = f"Invalid run_id '{run_id}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class ContextNotSetError(RunException):
    """Current Run context not set"""

    def __init__(self):
        super().__init__(
            "Current run context not set. "
            "Run 'uv run frago run set-context <run_id>' first."
        )


class ContextAlreadySetError(RunException):
    """Run context already running (mutex lock)"""

    def __init__(self, existing_run_id: str):
        self.existing_run_id = existing_run_id
        super().__init__(
            f"Another run '{existing_run_id}' is currently active. "
            f"Run 'uv run frago run release' to release it first, "
            f"or 'uv run frago run set-context {existing_run_id}' to continue it."
        )


class CorruptedLogError(RunException):
    """JSONL log file corrupted"""

    def __init__(self, file_path: str, line_number: int, reason: str = ""):
        self.file_path = file_path
        self.line_number = line_number
        self.reason = reason
        message = f"Corrupted log entry at {file_path}:{line_number}"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class FileSystemError(RunException):
    """File system operation failed"""

    def __init__(self, operation: str, path: str, reason: str = ""):
        self.operation = operation
        self.path = path
        self.reason = reason
        message = f"Failed to {operation} '{path}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)
