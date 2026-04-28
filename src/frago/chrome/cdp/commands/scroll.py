"""
Scroll-related CDP commands

Encapsulates CDP commands for page scrolling functionality.
"""

from typing import Dict, Any

from ..logger import get_logger


class ScrollCommands:
    """Scroll commands class"""

    def __init__(self, session):
        """
        Initialize scroll commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def scroll(self, distance: int) -> None:
        """
        Scroll page by specified distance

        Args:
            distance: Scroll distance (positive for down, negative for up)
        """
        self.logger.info(f"Scrolling by {distance} pixels")
        
        script = f"window.scrollBy(0, {distance});"
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def scroll_to_top(self) -> None:
        """Scroll to page top"""
        self.logger.info("Scrolling to top")

        script = "window.scrollTo(0, 0);"
        self.session.send_command("Runtime.evaluate", {"expression": script})

    def scroll_to_bottom(self) -> None:
        """Scroll to page bottom"""
        self.logger.info("Scrolling to bottom")

        script = "window.scrollTo(0, document.body.scrollHeight);"
        self.session.send_command("Runtime.evaluate", {"expression": script})

    def scroll_up(self, distance: int = 100) -> None:
        """
        Scroll up

        Args:
            distance: Scroll distance (pixels)
        """
        self.scroll(-distance)

    def scroll_down(self, distance: int = 100) -> None:
        """
        Scroll down

        Args:
            distance: Scroll distance (pixels)
        """
        self.scroll(distance)
