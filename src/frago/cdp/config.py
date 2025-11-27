"""
CDP配置管理

管理Chrome DevTools Protocol的连接配置和参数。
"""

import os
import re
from typing import Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator


class CDPConfig(BaseModel):
    """CDP配置类"""

    host: str = Field(default="127.0.0.1", description="CDP服务主机地址")
    port: int = Field(default=9222, description="CDP服务端口")

    connect_timeout: float = Field(default=5.0, description="连接超时时间（秒），本地连接优化为5秒")
    command_timeout: float = Field(default=30.0, description="命令执行超时时间（秒）")

    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试延迟时间（秒）")

    log_level: str = Field(default="INFO", description="日志级别")
    debug: bool = Field(default=False, description="是否启用调试模式")
    timeout: int = Field(default=30, description="操作超时时间（秒）")

    proxy_host: Optional[str] = Field(default=None, description="代理服务器主机地址")
    proxy_port: Optional[int] = Field(default=None, description="代理服务器端口")
    proxy_username: Optional[str] = Field(default=None, description="代理认证用户名", repr=False)
    proxy_password: Optional[str] = Field(default=None, description="代理认证密码", repr=False)
    no_proxy: bool = Field(default=False, description="是否绕过代理")

    target_id: Optional[str] = Field(default=None, description="指定目标tab的ID，不指定则自动选择第一个page")
    
    @model_validator(mode='after')
    def load_proxy_from_env(self):
        """从环境变量加载代理配置（如果未通过参数指定）

        支持的环境变量:
        - HTTP_PROXY / http_proxy: HTTP代理URL
        - HTTPS_PROXY / https_proxy: HTTPS代理URL
        - NO_PROXY / no_proxy: 不使用代理的主机列表

        代理URL格式: http://[username:password@]host:port
        """
        # 如果已经通过参数指定了no_proxy，跳过环境变量读取
        if self.no_proxy:
            return self

        # 如果代理参数已通过命令行指定，不从环境变量读取
        if self.proxy_host and self.proxy_port:
            return self

        # 尝试从环境变量读取代理配置
        proxy_url = None
        for env_var in ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy']:
            proxy_url = os.environ.get(env_var)
            if proxy_url:
                break

        if proxy_url:
            try:
                parsed = urlparse(proxy_url)

                # 提取主机和端口
                if parsed.hostname:
                    self.proxy_host = parsed.hostname
                if parsed.port:
                    self.proxy_port = parsed.port

                # 提取认证信息
                if parsed.username:
                    self.proxy_username = parsed.username
                if parsed.password:
                    self.proxy_password = parsed.password

            except Exception:
                # 如果解析失败，忽略环境变量
                pass

        # 检查NO_PROXY环境变量
        no_proxy_env = os.environ.get('NO_PROXY') or os.environ.get('no_proxy')
        if no_proxy_env:
            # 检查当前CDP主机是否在NO_PROXY列表中
            no_proxy_hosts = [h.strip() for h in no_proxy_env.split(',')]
            if self.host in no_proxy_hosts or '*' in no_proxy_hosts:
                self.no_proxy = True

        return self

    @property
    def websocket_url(self) -> str:
        """获取WebSocket连接URL"""
        return f"ws://{self.host}:{self.port}/devtools/browser"

    @property
    def http_url(self) -> str:
        """获取HTTP调试URL"""
        return f"http://{self.host}:{self.port}"

    def validate_proxy_config(self) -> tuple[bool, Optional[str]]:
        """验证代理配置的有效性

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)
        """
        # 如果禁用代理，无需验证
        if self.no_proxy:
            return True, None

        # 如果未配置代理，也是有效的（表示不使用代理）
        if not self.proxy_host and not self.proxy_port:
            return True, None

        # 如果配置了代理，必须同时指定主机和端口
        if self.proxy_host and not self.proxy_port:
            return False, "代理主机已指定，但缺少代理端口"

        if self.proxy_port and not self.proxy_host:
            return False, "代理端口已指定，但缺少代理主机"

        # 验证端口范围
        if self.proxy_port and not (1 <= self.proxy_port <= 65535):
            return False, f"代理端口无效: {self.proxy_port}，必须在1-65535之间"

        # 验证认证配置（用户名和密码必须同时存在或都不存在）
        if (self.proxy_username and not self.proxy_password) or \
           (self.proxy_password and not self.proxy_username):
            return False, "代理认证用户名和密码必须同时指定"

        return True, None

    def get_proxy_info(self) -> Optional[dict]:
        """获取代理配置信息（用于日志记录）

        注意：此方法不返回认证信息（用户名和密码），仅返回主机、端口和认证状态

        Returns:
            Optional[dict]: 代理配置信息字典，如果未配置代理则返回None
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
        """返回安全的配置表示（隐藏敏感信息）

        Returns:
            str: 安全的配置字符串表示
        """
        config_dict = self.model_dump(exclude={'proxy_username', 'proxy_password'})
        if self.proxy_username:
            config_dict['proxy_username'] = '***'
        if self.proxy_password:
            config_dict['proxy_password'] = '***'
        return f"CDPConfig({config_dict})"


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