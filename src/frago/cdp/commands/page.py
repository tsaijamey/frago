"""
页面相关CDP命令

封装Page域的CDP命令。
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class PageCommands:
    """页面命令类"""
    
    def __init__(self, session: CDPSession):
        """
        初始化页面命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def navigate(self, url: str) -> Dict[str, Any]:
        """
        导航到指定URL
        
        Args:
            url: 目标URL
            
        Returns:
            Dict[str, Any]: 导航结果
        """
        self.logger.info(f"Navigating to: {url}")
        
        result = self.session.send_command(
            "Page.navigate",
            {"url": url}
        )
        
        self.logger.debug(f"Navigation result: {result}")
        return result
    
    def screenshot(self, format: str = "png", quality: Optional[int] = None) -> Dict[str, Any]:
        """
        截取页面截图
        
        Args:
            format: 图片格式（"png" 或 "jpeg"）
            quality: JPEG质量（0-100），仅对JPEG格式有效
            
        Returns:
            Dict[str, Any]: 截图结果，包含base64编码的图片数据
        """
        self.logger.info(f"Taking screenshot with format: {format}")
        
        params = {"format": format}
        if quality is not None:
            params["quality"] = quality
        
        result = self.session.send_command(
            "Page.captureScreenshot",
            params
        )
        
        self.logger.debug("Screenshot captured")
        return result
    
    def wait_for_selector(
        self, 
        selector: str, 
        timeout: Optional[float] = None,
        visible: bool = True
    ) -> Dict[str, Any]:
        """
        等待选择器匹配的元素出现
        
        Args:
            selector: CSS选择器
            timeout: 超时时间（秒）
            visible: 是否要求元素可见
            
        Returns:
            Dict[str, Any]: 等待结果
        """
        self.logger.info(f"Waiting for selector: {selector}")
        
        # 使用Runtime.evaluate来等待元素
        script = f"""
        (function() {{
            return new Promise((resolve, reject) => {{
                const element = document.querySelector('{selector}');
                if (element && (!{str(visible).lower()} || element.offsetParent !== null)) {{
                    resolve(true);
                    return;
                }}
                
                const observer = new MutationObserver(() => {{
                    const element = document.querySelector('{selector}');
                    if (element && (!{str(visible).lower()} || element.offsetParent !== null)) {{
                        observer.disconnect();
                        resolve(true);
                    }}
                }});
                
                observer.observe(document.body, {{
                    childList: true,
                    subtree: true
                }});
                
                // 设置超时
                setTimeout(() => {{
                    observer.disconnect();
                    reject(new Error('Timeout waiting for selector'));
                }}, {int((timeout or 30) * 1000)});
            }});
        }})()
        """
        
        result = self.session.send_command(
            "Runtime.evaluate",
            {
                "expression": script,
                "awaitPromise": True,
                "returnByValue": True
            }
        )
        
        self.logger.debug(f"Wait for selector result: {result}")
        return result
    
    def get_title(self) -> str:
        """
        获取当前页面标题
        
        Returns:
            str: 页面标题
        """
        self.logger.info("Getting page title")
        
        script = "document.title"
        result = self.session.send_command(
            "Runtime.evaluate",
            {
                "expression": script,
                "returnByValue": True
            }
        )
        
        title = result.get("result", {}).get("value", "")
        self.logger.debug(f"Page title: {title}")
        return title
    
    def get_content(self, selector: Optional[str] = None) -> str:
        """
        获取页面或指定元素的文本内容

        Args:
            selector: CSS选择器，如果为None则获取整个页面内容

        Returns:
            str: 文本内容
        """
        if selector:
            self.logger.info(f"Getting content of element: {selector}")
            script = f"document.querySelector('{selector}')?.textContent || ''"
        else:
            self.logger.info("Getting page content")
            script = "document.body.textContent || ''"

        result = self.session.send_command(
            "Runtime.evaluate",
            {
                "expression": script,
                "returnByValue": True
            }
        )

        content = result.get("result", {}).get("value", "")
        self.logger.debug(f"Content length: {len(content)} characters")
        return content

    def wait_for_load(self, timeout: float = 30) -> bool:
        """
        等待页面加载完成

        使用 document.readyState 检测页面加载状态，
        等待变为 'complete' 表示页面及所有资源加载完成。

        Args:
            timeout: 超时时间（秒）

        Returns:
            bool: 是否加载完成
        """
        self.logger.info("Waiting for page load complete")

        script = f"""
        (function() {{
            return new Promise((resolve) => {{
                if (document.readyState === 'complete') {{
                    resolve(true);
                    return;
                }}

                const onLoad = () => {{
                    window.removeEventListener('load', onLoad);
                    resolve(true);
                }};

                window.addEventListener('load', onLoad);

                // 超时处理
                setTimeout(() => {{
                    window.removeEventListener('load', onLoad);
                    // 超时时也返回当前状态，不算失败
                    resolve(document.readyState === 'complete');
                }}, {int(timeout * 1000)});
            }});
        }})()
        """

        result = self.session.send_command(
            "Runtime.evaluate",
            {
                "expression": script,
                "awaitPromise": True,
                "returnByValue": True
            }
        )

        loaded = result.get("result", {}).get("value", False)
        self.logger.debug(f"Page load complete: {loaded}")
        return loaded