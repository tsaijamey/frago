"""
Status check related CDP commands

Encapsulates CDP status check functionality.
"""

from typing import List, Dict, Any
import requests

from ..logger import get_logger


class StatusCommands:
    """Status commands class"""

    def __init__(self, session):
        """
        Initialize status commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def health_check(self) -> bool:
        """
        Perform connection health check

        Returns:
            bool: Whether connection is healthy
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
        Get all pages list

        Returns:
            List[Dict[str, Any]]: Pages information list
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
        Check Chrome status

        Returns:
            Dict[str, Any]: Chrome status information
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
