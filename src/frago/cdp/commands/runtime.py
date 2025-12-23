"""
Runtime-related CDP commands

Encapsulates CDP commands for the Runtime domain.
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class RuntimeCommands:
    """Runtime commands class"""

    def __init__(self, session: CDPSession):
        """
        Initialize runtime commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def evaluate(self, expression: str, return_by_value: bool = True) -> Dict[str, Any]:
        """
        Execute JavaScript expression in page context

        Args:
            expression: JavaScript expression
            return_by_value: Whether to return value instead of object reference

        Returns:
            Dict[str, Any]: Execution result
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
        Call JavaScript function

        Args:
            function_declaration: Function declaration
            args: Function arguments
            return_by_value: Whether to return value instead of object reference

        Returns:
            Dict[str, Any]: Call result
        """
        self.logger.debug(f"Calling function: {function_declaration}")

        # Wrap function call as expression
        if args is None:
            args = []

        # Build function call expression
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