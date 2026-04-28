"""
Input-related CDP commands

Encapsulates CDP commands for the Input domain.
"""

from typing import Dict, Any, Optional

from ..session import CDPSession
from ..logger import get_logger


class InputCommands:
    """Input commands class — CDP Input domain wrappers.

    Wayland Native Chrome compatibility:
    - click() [dispatchMouseEvent]: NOT compatible — does not generate DOM events.
      Use CDPSession.click() (JS-first) for element clicks; this method is only
      called by CDPSession.click_precise() as a fallback or explicit override.
    - type() [dispatchKeyEvent]: Compatible — keyboard events work normally.
    - scroll() [dispatchMouseEvent mouseWheel]: Unverified — mouseWheel may behave
      differently from mouseMoved/mousePressed. CDPSession.scroll() uses JS
      window.scrollBy() as a platform-independent alternative.
    """

    def __init__(self, session: CDPSession):
        """
        Initialize input commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def click(self, x: int, y: int, button: str = "left") -> Dict[str, Any]:
        """
        Click at specified coordinates via Input.dispatchMouseEvent.

        Wayland Native: NOT compatible — dispatched mouse events do not generate
        DOM events. Prefer CDPSession.click() (JS-first) for element interactions.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Mouse button ("left", "right", "middle")

        Returns:
            Dict[str, Any]: Click result
        """
        self.logger.info(f"Clicking at ({x}, {y}) with {button} button")

        # Send mouse move event first (required by modern web apps)
        self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": x,
                "y": y
            }
        )

        # Send mouse pressed event
        self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": button,
                "clickCount": 1
            }
        )

        # Send mouse released event
        result = self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": button,
                "clickCount": 1
            }
        )

        self.logger.debug("Click completed")
        return result
    
    def type(self, text: str) -> Dict[str, Any]:
        """
        Type text via Input.dispatchKeyEvent.

        Wayland Native: Compatible — keyboard events work normally.

        Args:
            text: Text to type

        Returns:
            Dict[str, Any]: Type result
        """
        self.logger.info(f"Typing text: {text[:50]}{'...' if len(text) > 50 else ''}")

        # Send keyboard events character by character
        for char in text:
            self.session.send_command(
                "Input.dispatchKeyEvent",
                {
                    "type": "char",
                    "text": char
                }
            )
        
        self.logger.debug("Typing completed")
        return {"status": "completed"}
    
    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Dict[str, Any]:
        """
        Scroll page via Input.dispatchMouseEvent (mouseWheel).

        Wayland Native: Unverified — mouseWheel may not generate scroll events.
        CDPSession.scroll() uses JS window.scrollBy() as a platform-independent alternative.

        Args:
            x: Starting X coordinate
            y: Starting Y coordinate
            delta_x: X-axis scroll distance
            delta_y: Y-axis scroll distance

        Returns:
            Dict[str, Any]: Scroll result
        """
        self.logger.info(f"Scrolling from ({x}, {y}) by ({delta_x}, {delta_y})")
        
        result = self.session.send_command(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y
            }
        )
        
        self.logger.debug("Scroll completed")
        return result