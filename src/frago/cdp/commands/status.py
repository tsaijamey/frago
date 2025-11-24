"""
状态检查相关CDP命令

封装CDP状态检查功能。
"""

from typing import List, Dict, Any
import requests

from ..logger import get_logger


class StatusCommands:
    """状态命令类"""
    
    def __init__(self, session):
        """
        初始化状态命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def health_check(self) -> bool:
        """
        执行连接健康检查
        
        Returns:
            bool: 连接是否健康
        """
        try:
            self.logger.info("Performing health check")
            
            result = self.session.send_command("Browser.getVersion")
            
            if result:
                self.logger.info(f"Browser version: {result.get('product', 'unknown')}")
                return True
            
            return False
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False
    
    def get_pages(self) -> List[Dict[str, Any]]:
        """
        获取所有页面列表
        
        Returns:
            List[Dict[str, Any]]: 页面信息列表
        """
        try:
            self.logger.info("Getting pages list")
            
            http_url = self.session.config.http_url
            response = requests.get(f"{http_url}/json/list", timeout=10)
            
            if response.status_code == 200:
                pages = response.json()
                self.logger.info(f"Found {len(pages)} pages")
                return pages
            
            return []
        except Exception as e:
            self.logger.error(f"Failed to get pages: {e}")
            return []
    
    def check_chrome_status(self) -> Dict[str, Any]:
        """
        检查Chrome状态
        
        Returns:
            Dict[str, Any]: Chrome状态信息
        """
        try:
            self.logger.info("Checking Chrome status")
            
            http_url = self.session.config.http_url
            response = requests.get(f"{http_url}/json/version", timeout=10)
            
            if response.status_code == 200:
                version_info = response.json()
                self.logger.info(f"Chrome is running: {version_info.get('Browser', 'unknown')}")
                return version_info
            
            return {"status": "unavailable"}
        except Exception as e:
            self.logger.error(f"Failed to check Chrome status: {e}")
            return {"status": "error", "error": str(e)}
