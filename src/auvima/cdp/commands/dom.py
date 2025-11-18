"""
DOM相关CDP命令

封装DOM域的CDP命令。
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class DOMCommands:
    """DOM命令类"""
    
    def __init__(self, session: CDPSession):
        """
        初始化DOM命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def get_document(self) -> Dict[str, Any]:
        """
        获取文档根节点
        
        Returns:
            Dict[str, Any]: 文档信息
        """
        self.logger.info("Getting document")
        
        result = self.session.send_command("DOM.getDocument")
        
        self.logger.debug("Document retrieved")
        return result
    
    def query_selector(self, node_id: int, selector: str) -> Dict[str, Any]:
        """
        在指定节点中查询选择器匹配的元素
        
        Args:
            node_id: 节点ID
            selector: CSS选择器
            
        Returns:
            Dict[str, Any]: 查询结果
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
        获取节点的属性
        
        Args:
            node_id: 节点ID
            
        Returns:
            Dict[str, Any]: 属性信息
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
        获取节点的盒子模型
        
        Args:
            node_id: 节点ID
            
        Returns:
            Dict[str, Any]: 盒子模型信息
        """
        self.logger.info(f"Getting box model for node {node_id}")
        
        result = self.session.send_command(
            "DOM.getBoxModel",
            {"nodeId": node_id}
        )
        
        self.logger.debug(f"Box model result: {result}")
        return result