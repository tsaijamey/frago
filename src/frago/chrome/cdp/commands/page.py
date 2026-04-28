"""
Page-related CDP commands

Encapsulates CDP commands for the Page domain.
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class PageCommands:
    """Page commands class"""

    def __init__(self, session: CDPSession):
        """
        Initialize page commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def navigate(self, url: str) -> Dict[str, Any]:
        """
        Navigate to specified URL

        Args:
            url: Target URL

        Returns:
            Dict[str, Any]: Navigation result
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
        Capture page screenshot

        Args:
            format: Image format ("png" or "jpeg")
            quality: JPEG quality (0-100), only valid for JPEG format

        Returns:
            Dict[str, Any]: Screenshot result, contains base64-encoded image data
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
        Wait for element matching selector to appear

        Args:
            selector: CSS selector
            timeout: Timeout (seconds)
            visible: Whether element must be visible

        Returns:
            Dict[str, Any]: Wait result
        """
        self.logger.info(f"Waiting for selector: {selector}")

        # Use Runtime.evaluate to wait for element
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

                // Set timeout
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
        Get current page title

        Returns:
            str: Page title
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
        Get text content of page or specified element

        Args:
            selector: CSS selector, if None gets entire page content

        Returns:
            str: Text content
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
        Wait for page load to complete

        Uses document.readyState to detect page load status,
        waits for 'complete' indicating page and all resources loaded.

        Args:
            timeout: Timeout (seconds)

        Returns:
            bool: Whether load completed
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

                // Timeout handling
                setTimeout(() => {{
                    window.removeEventListener('load', onLoad);
                    // Return current state even on timeout, not considered failure
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