"""
DOM-related CDP commands

Encapsulates CDP commands for the DOM domain.
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class DOMCommands:
    """DOM commands class"""

    def __init__(self, session: CDPSession):
        """
        Initialize DOM commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def get_document(self) -> Dict[str, Any]:
        """
        Get document root node

        Returns:
            Dict[str, Any]: Document information
        """
        self.logger.info("Getting document")
        
        result = self.session.send_command("DOM.getDocument")
        
        self.logger.debug("Document retrieved")
        return result
    
    def query_selector(self, node_id: int, selector: str) -> Dict[str, Any]:
        """
        Query for element matching selector in specified node

        Args:
            node_id: Node ID
            selector: CSS selector

        Returns:
            Dict[str, Any]: Query result
        """
        self.logger.info(f"Querying selector '{selector}' in node {node_id}")
        
        result = self.session.send_command(
            "DOM.querySelector",
            {
                "nodeId": node_id,
                "selector": selector
            }
        )
        
        self.logger.debug(f"Query selector result: {result}")
        return result
    
    def get_attributes(self, node_id: int) -> Dict[str, Any]:
        """
        Get node attributes

        Args:
            node_id: Node ID

        Returns:
            Dict[str, Any]: Attribute information
        """
        self.logger.info(f"Getting attributes for node {node_id}")
        
        result = self.session.send_command(
            "DOM.getAttributes",
            {"nodeId": node_id}
        )
        
        self.logger.debug(f"Attributes result: {result}")
        return result
    
    def get_box_model(self, node_id: int) -> Dict[str, Any]:
        """
        Get node box model

        Args:
            node_id: Node ID

        Returns:
            Dict[str, Any]: Box model information
        """
        self.logger.info(f"Getting box model for node {node_id}")
        
        result = self.session.send_command(
            "DOM.getBoxModel",
            {"nodeId": node_id}
        )
        
        self.logger.debug(f"Box model result: {result}")
        return result