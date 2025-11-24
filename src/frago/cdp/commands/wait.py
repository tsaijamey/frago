"""
等待相关CDP命令

封装等待功能的CDP命令。
"""

import time
from typing import Optional

from ..logger import get_logger
from ..exceptions import TimeoutError as CDPTimeoutError


class WaitCommands:
    """等待命令类"""
    
    def __init__(self, session):
        """
        初始化等待命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def wait_for_selector(
        self, 
        selector: str, 
        timeout: Optional[float] = None
    ) -> None:
        """
        等待选择器匹配的元素出现
        
        Args:
            selector: CSS选择器
            timeout: 超时时间（秒），如果为None则使用配置的默认超时
            
        Raises:
            CDPTimeoutError: 等待超时
        """
        timeout = timeout or self.session.config.command_timeout
        self.logger.info(f"Waiting for selector: {selector} (timeout={timeout}s)")
        
        start_time = time.time()
        check_script = f"document.querySelector('{selector}') !== null"
        
        while True:
            result = self.session.send_command("Runtime.evaluate", {
                "expression": check_script,
                "returnByValue": True
            })
            
            if result.get("result", {}).get("value") is True:
                self.logger.info(f"Element found: {selector}")
                return
            
            if time.time() - start_time > timeout:
                raise CDPTimeoutError(f"Timeout waiting for selector: {selector}")
            
            time.sleep(0.5)
    
    def wait(self, seconds: float) -> None:
        """
        等待指定秒数
        
        Args:
            seconds: 等待时间（秒）
        """
        self.logger.info(f"Waiting for {seconds} seconds")
        time.sleep(seconds)
