"""
运行时相关CDP命令

封装Runtime域的CDP命令。
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class RuntimeCommands:
    """运行时命令类"""
    
    def __init__(self, session: CDPSession):
        """
        初始化运行时命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def evaluate(self, expression: str, return_by_value: bool = True) -> Dict[str, Any]:
        """
        在页面上下文中执行JavaScript表达式
        
        Args:
            expression: JavaScript表达式
            return_by_value: 是否返回值而不是对象引用
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        self.logger.debug(f"Evaluating expression: {expression}")
        
        result = self.session.send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": return_by_value,
                "awaitPromise": True
            }
        )
        
        self.logger.debug(f"Evaluation result: {result}")
        return result
    
    def call_function(
        self, 
        function_declaration: str, 
        args: Optional[list] = None,
        return_by_value: bool = True
    ) -> Dict[str, Any]:
        """
        调用JavaScript函数
        
        Args:
            function_declaration: 函数声明
            args: 函数参数
            return_by_value: 是否返回值而不是对象引用
            
        Returns:
            Dict[str, Any]: 调用结果
        """
        self.logger.debug(f"Calling function: {function_declaration}")
        
        # 将函数调用包装为表达式
        if args is None:
            args = []
        
        # 构建函数调用表达式
        call_expression = f"({function_declaration})({', '.join(map(repr, args))})"
        
        result = self.session.send_command(
            "Runtime.evaluate",
            {
                "expression": call_expression,
                "returnByValue": return_by_value
            }
        )
        
        self.logger.debug(f"Function call result: {result}")
        return result