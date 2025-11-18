"""
CDP异常定义

定义Chrome DevTools Protocol相关的自定义异常。
"""


class CDPError(Exception):
    """CDP基础异常类"""
    pass


class ConnectionError(CDPError):
    """连接相关异常"""
    pass


class TimeoutError(CDPError):
    """超时异常"""
    pass


class ProtocolError(CDPError):
    """协议错误异常"""
    pass


class CommandError(CDPError):
    """命令执行错误异常"""
    pass


class RetryExhaustedError(CDPError):
    """重试耗尽异常"""
    pass


class InvalidResponseError(CDPError):
    """无效响应异常"""
    pass


class ProxyConnectionError(ConnectionError):
    """代理连接异常"""
    pass


class ProxyConfigError(CDPError):
    """代理配置错误异常"""
    pass