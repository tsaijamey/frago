"""
自定义异常类

定义 frago init 命令使用的所有异常和错误码。
"""

from enum import IntEnum
from typing import Optional


class InitErrorCode(IntEnum):
    """Init 命令错误码枚举"""

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
    """外部命令执行错误"""

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
        """字符串表示"""
        result = f"[{self.code.name}] {self.message}"
        if self.details:
            result += f"\n详细信息:\n{self.details}"
        return result
