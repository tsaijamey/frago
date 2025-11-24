"""
输入相关CDP命令

封装Input域的CDP命令。
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class InputCommands:
    """输入命令类"""
    
    def __init__(self, session: CDPSession):
        """
        初始化输入命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def click(self, x: int, y: int, button: str = "left") -> Dict[str, Any]:
        """
        在指定坐标点击

        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮（"left", "right", "middle"）

        Returns:
            Dict[str, Any]: 点击结果
        """
        self.logger.info(f"Clicking at ({x}, {y}) with {button} button")

        # 先发送鼠标移动事件（现代Web应用需要）
        self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": x,
                "y": y
            }
        )

        # 发送鼠标按下事件
        self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": button,
                "clickCount": 1
            }
        )

        # 发送鼠标释放事件
        result = self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": button,
                "clickCount": 1
            }
        )

        self.logger.debug("Click completed")
        return result
    
    def type(self, text: str) -> Dict[str, Any]:
        """
        输入文本
        
        Args:
            text: 要输入的文本
            
        Returns:
            Dict[str, Any]: 输入结果
        """
        self.logger.info(f"Typing text: {text[:50]}{'...' if len(text) > 50 else ''}")
        
        # 逐个字符发送键盘事件
        for char in text:
            self.session.send_command(
                "Input.dispatchKeyEvent",
                {
                    "type": "char",
                    "text": char
                }
            )
        
        self.logger.debug("Typing completed")
        return {"status": "completed"}
    
    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Dict[str, Any]:
        """
        滚动页面
        
        Args:
            x: 起始X坐标
            y: 起始Y坐标
            delta_x: X轴滚动距离
            delta_y: Y轴滚动距离
            
        Returns:
            Dict[str, Any]: 滚动结果
        """
        self.logger.info(f"Scrolling from ({x}, {y}) by ({delta_x}, {delta_y})")
        
        result = self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y
            }
        )
        
        self.logger.debug("Scroll completed")
        return result