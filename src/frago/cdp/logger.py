"""
CDP日志配置

配置结构化日志记录器，用于CDP操作日志。
"""

import logging
import sys
from typing import Optional


class CDPLogger:
    """CDP日志管理器"""
    
    def __init__(self, name: str = "frago.cdp", level: str = "INFO"):
        """
        初始化日志管理器
        
        Args:
            name: 日志器名称
            level: 日志级别
        """
        self.logger = logging.getLogger(name)
        self._setup_logger(level)
    
    def _setup_logger(self, level: str):
        """设置日志器配置"""
        # 清除已有的处理器
        self.logger.handlers.clear()
        
        # 设置日志级别
        log_level = getattr(logging, level.upper(), logging.INFO)
        self.logger.setLevel(log_level)
        
        # 创建格式化器
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 创建控制台处理器（输出到stderr而不是stdout，避免污染命令输出）
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        
        # 添加处理器
        self.logger.addHandler(console_handler)
        
        # 防止日志传播到根日志器
        self.logger.propagate = False
    
    def debug(self, message: str, *args, **kwargs):
        """记录调试日志"""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """记录信息日志"""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """记录警告日志"""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """记录错误日志"""
        self.logger.error(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """记录异常日志"""
        self.logger.exception(message, *args, **kwargs)

    # ========================================
    # T049: 代理连接相关日志记录方法
    # ========================================

    def log_proxy_config(self, proxy_info: Optional[dict]):
        """
        记录代理配置信息

        Args:
            proxy_info: 代理配置信息字典，包含host、port、has_auth等
        """
        if proxy_info is None:
            self.debug("代理配置: 未使用代理")
            return

        host = proxy_info.get('host', 'unknown')
        port = proxy_info.get('port', 'unknown')
        has_auth = proxy_info.get('has_auth', False)

        auth_str = " (带认证)" if has_auth else ""
        self.info(f"代理配置: {host}:{port}{auth_str}")

    def log_proxy_connection_attempt(self, proxy_host: str, proxy_port: int):
        """
        记录代理连接尝试

        Args:
            proxy_host: 代理主机
            proxy_port: 代理端口
        """
        self.debug(f"正在通过代理连接: {proxy_host}:{proxy_port}")

    def log_proxy_connection_success(self, proxy_host: str, proxy_port: int):
        """
        记录代理连接成功

        Args:
            proxy_host: 代理主机
            proxy_port: 代理端口
        """
        self.info(f"代理连接成功: {proxy_host}:{proxy_port}")

    def log_proxy_connection_error(self, proxy_host: str, proxy_port: int, error: Exception):
        """
        记录代理连接错误

        Args:
            proxy_host: 代理主机
            proxy_port: 代理端口
            error: 错误信息
        """
        self.error(f"代理连接失败: {proxy_host}:{proxy_port} - {error}")

    def log_proxy_bypass(self, reason: str = "no_proxy设置"):
        """
        记录代理绕过

        Args:
            reason: 绕过原因
        """
        self.debug(f"绕过代理: {reason}")

    def log_proxy_auth(self, proxy_host: str, proxy_port: int, username: str):
        """
        记录代理认证（不记录密码）

        安全提示：此方法只记录用户名，不记录密码信息

        Args:
            proxy_host: 代理主机
            proxy_port: 代理端口
            username: 用户名
        """
        # 安全处理：只显示用户名的前3个字符，其余用*代替
        safe_username = username[:3] + '*' * max(0, len(username) - 3) if len(username) > 3 else username
        self.debug(f"使用代理认证: {proxy_host}:{proxy_port} (用户: {safe_username})")

    def log_proxy_env_loaded(self, source: str, proxy_url: str):
        """
        记录从环境变量加载代理配置

        安全提示：此方法会自动隐藏URL中的用户名和密码信息

        Args:
            source: 环境变量名称（如HTTP_PROXY）
            proxy_url: 代理URL（会隐藏密码）
        """
        # 隐藏密码和用户名部分
        safe_url = proxy_url
        if '@' in safe_url:
            # URL格式: protocol://username:password@host:port
            parts = safe_url.split('@')
            protocol_and_auth = parts[0]
            host_and_port = '@'.join(parts[1:])  # 处理可能的多个@符号

            # 提取协议部分
            if '//' in protocol_and_auth:
                protocol = protocol_and_auth.split('//')[0]
                safe_url = f"{protocol}//***:***@{host_and_port}"
            else:
                safe_url = f"***:***@{host_and_port}"

        self.debug(f"从环境变量 {source} 加载代理配置: {safe_url}")


# 全局日志器实例
_logger: Optional[CDPLogger] = None


def get_logger(name: str = "frago.cdp", level: str = "WARNING") -> CDPLogger:
    """
    获取CDP日志器

    Args:
        name: 日志器名称
        level: 日志级别（每次调用可更新级别）

    Returns:
        CDPLogger: 日志器实例
    """
    global _logger
    if _logger is None:
        _logger = CDPLogger(name, level)
    else:
        # 更新日志级别（如果不同）
        new_level = getattr(logging, level.upper(), logging.WARNING)
        if _logger.logger.level != new_level:
            _logger._setup_logger(level)
    return _logger