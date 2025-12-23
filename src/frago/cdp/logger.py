"""
CDP logging configuration

Configures structured logger for CDP operations logging.
"""

import logging
import sys
from typing import Optional


class CDPLogger:
    """CDP logger manager"""

    def __init__(self, name: str = "frago.cdp", level: str = "INFO"):
        """
        Initialize logger manager

        Args:
            name: Logger name
            level: Log level
        """
        self.logger = logging.getLogger(name)
        self._setup_logger(level)

    def _setup_logger(self, level: str):
        """Set up logger configuration"""
        # Clear existing handlers
        self.logger.handlers.clear()

        # Set log level
        log_level = getattr(logging, level.upper(), logging.INFO)
        self.logger.setLevel(log_level)

        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Create console handler (output to stderr instead of stdout to avoid polluting command output)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        # Add handler
        self.logger.addHandler(console_handler)

        # Prevent log propagation to root logger
        self.logger.propagate = False

    def debug(self, message: str, *args, **kwargs):
        """Log debug message"""
        self.logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        """Log info message"""
        self.logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        """Log warning message"""
        self.logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        """Log error message"""
        self.logger.error(message, *args, **kwargs)

    def exception(self, message: str, *args, **kwargs):
        """Log exception message"""
        self.logger.exception(message, *args, **kwargs)

    # ========================================
    # T049: Proxy connection logging methods
    # ========================================

    def log_proxy_config(self, proxy_info: Optional[dict]):
        """
        Log proxy configuration information

        Args:
            proxy_info: Proxy configuration info dictionary, contains host, port, has_auth, etc.
        """
        if proxy_info is None:
            self.debug("Proxy configuration: Not using proxy")
            return

        host = proxy_info.get('host', 'unknown')
        port = proxy_info.get('port', 'unknown')
        has_auth = proxy_info.get('has_auth', False)

        auth_str = " (with auth)" if has_auth else ""
        self.info(f"Proxy configuration: {host}:{port}{auth_str}")

    def log_proxy_connection_attempt(self, proxy_host: str, proxy_port: int):
        """
        Log proxy connection attempt

        Args:
            proxy_host: Proxy host
            proxy_port: Proxy port
        """
        self.debug(f"Connecting through proxy: {proxy_host}:{proxy_port}")

    def log_proxy_connection_success(self, proxy_host: str, proxy_port: int):
        """
        Log proxy connection success

        Args:
            proxy_host: Proxy host
            proxy_port: Proxy port
        """
        self.info(f"Proxy connection successful: {proxy_host}:{proxy_port}")

    def log_proxy_connection_error(self, proxy_host: str, proxy_port: int, error: Exception):
        """
        Log proxy connection error

        Args:
            proxy_host: Proxy host
            proxy_port: Proxy port
            error: Error information
        """
        self.error(f"Proxy connection failed: {proxy_host}:{proxy_port} - {error}")

    def log_proxy_bypass(self, reason: str = "no_proxy setting"):
        """
        Log proxy bypass

        Args:
            reason: Bypass reason
        """
        self.debug(f"Bypassing proxy: {reason}")

    def log_proxy_auth(self, proxy_host: str, proxy_port: int, username: str):
        """
        Log proxy authentication (does not log password)

        Security note: This method only logs username, not password information

        Args:
            proxy_host: Proxy host
            proxy_port: Proxy port
            username: Username
        """
        # Security handling: only show first 3 characters of username, replace rest with *
        safe_username = username[:3] + '*' * max(0, len(username) - 3) if len(username) > 3 else username
        self.debug(f"Using proxy authentication: {proxy_host}:{proxy_port} (user: {safe_username})")

    def log_proxy_env_loaded(self, source: str, proxy_url: str):
        """
        Log loading proxy configuration from environment variable

        Security note: This method automatically hides username and password in URL

        Args:
            source: Environment variable name (e.g. HTTP_PROXY)
            proxy_url: Proxy URL (password will be hidden)
        """
        # Hide password and username parts
        safe_url = proxy_url
        if '@' in safe_url:
            # URL format: protocol://username:password@host:port
            parts = safe_url.split('@')
            protocol_and_auth = parts[0]
            host_and_port = '@'.join(parts[1:])  # Handle possible multiple @ symbols

            # Extract protocol part
            if '//' in protocol_and_auth:
                protocol = protocol_and_auth.split('//')[0]
                safe_url = f"{protocol}//***:***@{host_and_port}"
            else:
                safe_url = f"***:***@{host_and_port}"

        self.debug(f"Loaded proxy configuration from environment variable {source}: {safe_url}")


# Global logger instance
_logger: Optional[CDPLogger] = None


def get_logger(name: str = "frago.cdp", level: str = "WARNING") -> CDPLogger:
    """
    Get CDP logger

    Args:
        name: Logger name
        level: Log level (can be updated on each call)

    Returns:
        CDPLogger: Logger instance
    """
    global _logger
    if _logger is None:
        _logger = CDPLogger(name, level)
    else:
        # Update log level (if different)
        new_level = getattr(logging, level.upper(), logging.WARNING)
        if _logger.logger.level != new_level:
            _logger._setup_logger(level)
    return _logger