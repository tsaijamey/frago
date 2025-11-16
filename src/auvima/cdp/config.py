"""
CDP配置管理

管理Chrome DevTools Protocol的连接配置和参数。
"""

import os
from typing import Optional
from pydantic import BaseModel, Field


class CDPConfig(BaseModel):
    """CDP配置类"""
    
    host: str = Field(default="127.0.0.1", description="CDP服务主机地址")
    port: int = Field(default=9222, description="CDP服务端口")
    
    connect_timeout: float = Field(default=30.0, description="连接超时时间（秒）")
    command_timeout: float = Field(default=60.0, description="命令执行超时时间（秒）")
    
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试延迟时间（秒）")
    
    log_level: str = Field(default="INFO", description="日志级别")
    debug: bool = Field(default=False, description="是否启用调试模式")
    timeout: int = Field(default=30, description="操作超时时间（秒）")
    
    proxy_host: Optional[str] = Field(default=None, description="代理服务器主机地址")
    proxy_port: Optional[int] = Field(default=None, description="代理服务器端口")
    proxy_username: Optional[str] = Field(default=None, description="代理认证用户名")
    proxy_password: Optional[str] = Field(default=None, description="代理认证密码")
    no_proxy: bool = Field(default=False, description="是否绕过代理")
    
    @property
    def websocket_url(self) -> str:
        """获取WebSocket连接URL"""
        return f"ws://{self.host}:{self.port}/devtools/browser"
    
    @property
    def http_url(self) -> str:
        """获取HTTP调试URL"""
        return f"http://{self.host}:{self.port}"


def load_config(config_file: Optional[str] = None) -> CDPConfig:
    """
    加载CDP配置
    
    Args:
        config_file: 配置文件路径，如果为None则使用默认配置
        
    Returns:
        CDPConfig: 配置实例
    """
    # 简化配置加载，直接返回默认配置
    return CDPConfig()