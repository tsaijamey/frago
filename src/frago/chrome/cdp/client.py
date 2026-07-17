"""
CDP client base class

Provides basic functionality for Chrome DevTools Protocol clients.
"""

from abc import ABC, abstractmethod
from typing import Any

from .config import CDPConfig
from .exceptions import CDPError
from .logger import get_logger


class CDPClient(ABC):
    """CDP client base class"""

    def __init__(self, config: CDPConfig | None = None):
        """
        Initialize CDP client

        Args:
            config: CDP configuration, uses default config if None
        """
        self.config = config or CDPConfig()
        # Set log level based on debug mode
        log_level = "INFO" if self.config.debug else "WARNING"
        self.logger = get_logger(level=log_level)
        self._connected = False

    @property
    def connected(self) -> bool:
        """Check if connected"""
        return self._connected

    @abstractmethod
    def connect(self) -> None:
        """Establish connection"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect"""
        pass

    @abstractmethod
    def send_command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Send CDP command

        Args:
            method: CDP method name
            params: Command parameters

        Returns:
            Dict[str, Any]: Command result

        Raises:
            CDPError: Command execution failed
        """
        pass

    def _validate_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """
        Validate CDP response

        Args:
            response: CDP response

        Returns:
            Dict[str, Any]: Validated response

        Raises:
            CDPError: Invalid response
        """
        if not isinstance(response, dict):
            raise CDPError(f"Invalid response type: {type(response)}")

        if "error" in response:
            error = response["error"]
            error_msg = error.get("message", "Unknown error")
            error_code = error.get("code", -1)
            raise CDPError(f"CDP error {error_code}: {error_msg}")

        return response

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
