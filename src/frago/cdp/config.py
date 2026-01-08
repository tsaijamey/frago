"""
CDP configuration management

Manages Chrome DevTools Protocol connection configuration and parameters.
"""

import fnmatch
import os
from typing import Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator


class CDPConfig(BaseModel):
    """CDP configuration class"""

    host: str = Field(default="127.0.0.1", description="CDP service host address")
    port: int = Field(default=9222, description="CDP service port")

    connect_timeout: float = Field(default=5.0, description="Connection timeout (seconds), optimized to 5 seconds for local connections")
    command_timeout: float = Field(default=30.0, description="Command execution timeout (seconds)")

    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_delay: float = Field(default=1.0, description="Retry delay time (seconds)")

    log_level: str = Field(default="INFO", description="Log level")
    debug: bool = Field(default=False, description="Whether to enable debug mode")
    timeout: int = Field(default=30, description="Operation timeout (seconds)")

    proxy_host: Optional[str] = Field(default=None, description="Proxy server host address")
    proxy_port: Optional[int] = Field(default=None, description="Proxy server port")
    proxy_username: Optional[str] = Field(default=None, description="Proxy authentication username", repr=False)
    proxy_password: Optional[str] = Field(default=None, description="Proxy authentication password", repr=False)
    no_proxy: bool = Field(default=False, description="Whether to bypass proxy")

    target_id: Optional[str] = Field(default=None, description="Specified target tab ID, auto-select first page if not specified")
    
    @model_validator(mode='after')
    def load_proxy_from_env(self):
        """Load proxy configuration from environment variables (if not specified via parameters)

        Supported environment variables:
        - HTTP_PROXY / http_proxy: HTTP proxy URL
        - HTTPS_PROXY / https_proxy: HTTPS proxy URL
        - NO_PROXY / no_proxy: List of hosts that should not use proxy

        Proxy URL format: http://[username:password@]host:port
        """
        # If no_proxy is already specified via parameters, skip environment variable reading
        if self.no_proxy:
            return self

        # If proxy parameters are already specified via command line, don't read from environment
        if self.proxy_host and self.proxy_port:
            return self

        # Try to read proxy configuration from environment variables
        proxy_url = None
        for env_var in ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy']:
            proxy_url = os.environ.get(env_var)
            if proxy_url:
                break

        if proxy_url:
            try:
                parsed = urlparse(proxy_url)

                # Extract host and port
                if parsed.hostname:
                    self.proxy_host = parsed.hostname
                if parsed.port:
                    self.proxy_port = parsed.port

                # Extract authentication information
                if parsed.username:
                    self.proxy_username = parsed.username
                if parsed.password:
                    self.proxy_password = parsed.password

            except Exception:
                # If parsing fails, ignore environment variable
                pass

        # Check NO_PROXY environment variable
        no_proxy_env = os.environ.get('NO_PROXY') or os.environ.get('no_proxy')
        if no_proxy_env:
            # Check if current CDP host matches any pattern in NO_PROXY list
            # Supports exact match, wildcard '*', and glob patterns like '127.*'
            no_proxy_hosts = [h.strip() for h in no_proxy_env.split(',')]
            for pattern in no_proxy_hosts:
                if pattern == '*' or self.host == pattern or fnmatch.fnmatch(self.host, pattern):
                    self.no_proxy = True
                    break

        return self

    @property
    def websocket_url(self) -> str:
        """Get WebSocket connection URL"""
        return f"ws://{self.host}:{self.port}/devtools/browser"

    @property
    def http_url(self) -> str:
        """Get HTTP debug URL"""
        return f"http://{self.host}:{self.port}"

    def validate_proxy_config(self) -> tuple[bool, Optional[str]]:
        """Validate proxy configuration validity

        Returns:
            tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        # If proxy is disabled, no validation needed
        if self.no_proxy:
            return True, None

        # If proxy is not configured, it's also valid (means not using proxy)
        if not self.proxy_host and not self.proxy_port:
            return True, None

        # If proxy is configured, host and port must both be specified
        if self.proxy_host and not self.proxy_port:
            return False, "Proxy host specified but proxy port is missing"

        if self.proxy_port and not self.proxy_host:
            return False, "Proxy port specified but proxy host is missing"

        # Validate port range
        if self.proxy_port and not (1 <= self.proxy_port <= 65535):
            return False, f"Invalid proxy port: {self.proxy_port}, must be between 1-65535"

        # Validate authentication configuration (username and password must both exist or both not exist)
        if (self.proxy_username and not self.proxy_password) or \
           (self.proxy_password and not self.proxy_username):
            return False, "Proxy authentication username and password must be specified together"

        return True, None

    def get_proxy_info(self) -> Optional[dict]:
        """Get proxy configuration information (for logging)

        Note: This method does not return authentication information (username and password), only host, port and authentication status

        Returns:
            Optional[dict]: Proxy configuration information dictionary, None if proxy is not configured
        """
        if self.no_proxy or not self.proxy_host or not self.proxy_port:
            return None

        return {
            "host": self.proxy_host,
            "port": self.proxy_port,
            "has_auth": bool(self.proxy_username and self.proxy_password),
            "url": f"{self.proxy_host}:{self.proxy_port}"
        }

    def safe_repr(self) -> str:
        """Return safe configuration representation (hiding sensitive information)

        Returns:
            str: Safe configuration string representation
        """
        config_dict = self.model_dump(exclude={'proxy_username', 'proxy_password'})
        if self.proxy_username:
            config_dict['proxy_username'] = '***'
        if self.proxy_password:
            config_dict['proxy_password'] = '***'
        return f"CDPConfig({config_dict})"


def load_config(config_file: Optional[str] = None) -> CDPConfig:
    """
    Load CDP configuration

    Args:
        config_file: Configuration file path, uses default configuration if None

    Returns:
        CDPConfig: Configuration instance
    """
    # Simplified configuration loading, directly return default configuration
    return CDPConfig()