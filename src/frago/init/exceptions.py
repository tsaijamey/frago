"""
Custom exception classes

Defines all exceptions and error codes used by the frago init command.
"""

from enum import IntEnum
from typing import Optional


class InitErrorCode(IntEnum):
    """Init command error code enumeration"""

    SUCCESS = 0
    INSTALL_FAILED = 1
    USER_CANCELLED = 2
    CONFIG_ERROR = 3
    COMMAND_NOT_FOUND = 10
    VERSION_INSUFFICIENT = 11
    PERMISSION_ERROR = 12
    NETWORK_ERROR = 13
    INSTALL_ERROR = 14


class CommandError(Exception):
    """External command execution error"""

    def __init__(
        self,
        message: str,
        code: InitErrorCode,
        details: Optional[str] = None,
    ):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(message)

    def __str__(self) -> str:
        """String representation"""
        result = f"[{self.code.name}] {self.message}"
        if self.details:
            result += f"\nDetails:\n{self.details}"
        return result
