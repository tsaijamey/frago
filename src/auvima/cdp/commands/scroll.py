"""
滚动相关CDP命令

封装页面滚动功能的CDP命令。
"""

from typing import Dict, Any

from ..logger import get_logger


class ScrollCommands:
    """滚动命令类"""
    
    def __init__(self, session):
        """
        初始化滚动命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def scroll(self, distance: int) -> None:
        """
        滚动页面指定距离
        
        Args:
            distance: 滚动距离（正数向下，负数向上）
        """
        self.logger.info(f"Scrolling by {distance} pixels")
        
        script = f"window.scrollBy(0, {distance});"
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def scroll_to_top(self) -> None:
        """滚动到页面顶部"""
        self.logger.info("Scrolling to top")
        
        script = "window.scrollTo(0, 0);"
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def scroll_to_bottom(self) -> None:
        """滚动到页面底部"""
        self.logger.info("Scrolling to bottom")
        
        script = "window.scrollTo(0, document.body.scrollHeight);"
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def scroll_up(self, distance: int = 100) -> None:
        """
        向上滚动
        
        Args:
            distance: 滚动距离（像素）
        """
        self.scroll(-distance)
    
    def scroll_down(self, distance: int = 100) -> None:
        """
        向下滚动
        
        Args:
            distance: 滚动距离（像素）
        """
        self.scroll(distance)
