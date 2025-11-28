"""
CDP客户端基类

提供Chrome DevTools Protocol客户端的基础功能。
"""

import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from .config import CDPConfig
from .logger import get_logger
from .exceptions import CDPError


class CDPClient(ABC):
    """CDP客户端基类"""
    
    def __init__(self, config: Optional[CDPConfig] = None):
        """
        初始化CDP客户端
        
        Args:
            config: CDP配置，如果为None则使用默认配置
        """
        self.config = config or CDPConfig()
        # 根据 debug 模式设置日志级别
        log_level = "INFO" if self.config.debug else "WARNING"
        self.logger = get_logger(level=log_level)
        self._connected = False
    
    @property
    def connected(self) -> bool:
        """检查是否已连接"""
        return self._connected
    
    @abstractmethod
    def connect(self) -> None:
        """建立连接"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        pass
    
    @abstractmethod
    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发送CDP命令
        
        Args:
            method: CDP方法名
            params: 命令参数
            
        Returns:
            Dict[str, Any]: 命令结果
            
        Raises:
            CDPError: 命令执行失败
        """
        pass
    
    def _validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证CDP响应
        
        Args:
            response: CDP响应
            
        Returns:
            Dict[str, Any]: 验证后的响应
            
        Raises:
            CDPError: 响应无效
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
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()