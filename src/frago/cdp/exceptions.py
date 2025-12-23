"""
CDP exception definitions

Defines custom exceptions related to Chrome DevTools Protocol.
"""


class CDPError(Exception):
    """CDP base exception class"""
    pass


class ConnectionError(CDPError):
    """Connection related exception"""
    pass


class TimeoutError(CDPError):
    """Timeout exception"""
    pass


class ProtocolError(CDPError):
    """Protocol error exception"""
    pass


class CommandError(CDPError):
    """Command execution error exception"""
    pass


class RetryExhaustedError(CDPError):
    """Retry exhausted exception"""
    pass


class InvalidResponseError(CDPError):
    """Invalid response exception"""
    pass


class ProxyConnectionError(ConnectionError):
    """Proxy connection exception"""
    pass


class ProxyConfigError(CDPError):
    """Proxy configuration error exception"""
    pass