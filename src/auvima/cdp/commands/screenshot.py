"""
截图相关CDP命令

封装截图功能的CDP命令。
"""

from typing import Dict, Any, Optional
import base64
import os

from ..logger import get_logger


class ScreenshotCommands:
    """截图命令类"""
    
    def __init__(self, session):
        """
        初始化截图命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def capture(
        self, 
        output_file: Optional[str] = None,
        full_page: bool = False,
        format: str = "png",
        quality: int = 80
    ) -> Dict[str, Any]:
        """
        截取页面截图
        
        Args:
            output_file: 输出文件路径，如果为None则返回base64数据
            full_page: 是否截取完整页面
            format: 图片格式（"png" 或 "jpeg"）
            quality: JPEG质量（0-100），仅对JPEG格式有效
            
        Returns:
            Dict[str, Any]: 截图结果
        """
        self.logger.info(f"Taking screenshot (full_page={full_page}, format={format}, quality={quality})")
        
        params = {
            "format": format,
            "captureBeyondViewport": full_page
        }
        
        if format == "jpeg":
            params["quality"] = quality
        
        result = self.session.send_command("Page.captureScreenshot", params)
        
        if output_file and "data" in result:
            image_data = base64.b64decode(result["data"])
            os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
            with open(output_file, "wb") as f:
                f.write(image_data)
            self.logger.info(f"Screenshot saved to: {output_file}")
            result["file"] = output_file
        
        return result
