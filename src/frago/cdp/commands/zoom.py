"""
Zoom-related CDP commands

Encapsulates CDP commands for page zoom functionality.
"""

from typing import Dict, Any

from ..logger import get_logger


class ZoomCommands:
    """Zoom commands class"""

    def __init__(self, session):
        """
        Initialize zoom commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def set_zoom_factor(self, factor: float) -> None:
        """
        Set page zoom factor

        Args:
            factor: Zoom factor (0.5-3.0)

        Raises:
            ValueError: If factor is out of range
        """
        if factor < 0.5 or factor > 3.0:
            raise ValueError("Zoom factor must be between 0.5 and 3.0")

        self.logger.info(f"Setting zoom factor to {factor}")

        self.session.send_command("Emulation.setPageScaleFactor", {
            "pageScaleFactor": factor
        })

    def zoom_in(self) -> None:
        """Zoom in (1.2x)"""
        self.set_zoom_factor(1.2)

    def zoom_out(self) -> None:
        """Zoom out (0.8x)"""
        self.set_zoom_factor(0.8)

    def reset_zoom(self) -> None:
        """Reset zoom (1.0x)"""
        self.set_zoom_factor(1.0)
