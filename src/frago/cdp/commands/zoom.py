"""
缩放相关CDP命令

封装页面缩放功能的CDP命令。
"""

from typing import Dict, Any

from ..logger import get_logger


class ZoomCommands:
    """缩放命令类"""
    
    def __init__(self, session):
        """
        初始化缩放命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def set_zoom_factor(self, factor: float) -> None:
        """
        设置页面缩放比例
        
        Args:
            factor: 缩放因子（0.5-3.0）
            
        Raises:
            ValueError: 如果因子超出范围
        """
        if factor < 0.5 or factor > 3.0:
            raise ValueError("Zoom factor must be between 0.5 and 3.0")
        
        self.logger.info(f"Setting zoom factor to {factor}")
        
        self.session.send_command("Emulation.setPageScaleFactor", {
            "pageScaleFactor": factor
        })
    
    def zoom_in(self) -> None:
        """放大（1.2倍）"""
        self.set_zoom_factor(1.2)
    
    def zoom_out(self) -> None:
        """缩小（0.8倍）"""
        self.set_zoom_factor(0.8)
    
    def reset_zoom(self) -> None:
        """重置缩放（1.0倍）"""
        self.set_zoom_factor(1.0)
