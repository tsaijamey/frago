"""
Wait-related CDP commands

Encapsulates CDP commands for wait functionality.
"""

import time
from typing import Optional

from ..logger import get_logger
from ..exceptions import TimeoutError as CDPTimeoutError


class WaitCommands:
    """Wait commands class"""

    def __init__(self, session):
        """
        Initialize wait commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def wait_for_selector(
        self,
        selector: str,
        timeout: Optional[float] = None
    ) -> None:
        """
        Wait for element matching selector to appear

        Args:
            selector: CSS selector
            timeout: Timeout (seconds), uses configured default timeout if None

        Raises:
            CDPTimeoutError: Wait timeout
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
        Wait for specified seconds

        Args:
            seconds: Wait time (seconds)
        """
        self.logger.info(f"Waiting for {seconds} seconds")
        time.sleep(seconds)
