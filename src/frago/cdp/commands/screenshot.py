"""
Screenshot-related CDP commands

Encapsulates CDP commands for screenshot functionality.
"""

from typing import Dict, Any, Optional
import base64
import os

from ..logger import get_logger


class ScreenshotCommands:
    """Screenshot commands class"""

    def __init__(self, session):
        """
        Initialize screenshot commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def capture(
        self,
        output_file: Optional[str] = None,
        full_page: bool = False,
        format: str = "png",
        quality: int = 80
    ) -> Dict[str, Any]:
        """
        Capture page screenshot

        Args:
            output_file: Output file path, if None returns base64 data
            full_page: Whether to capture full page
            format: Image format ("png" or "jpeg")
            quality: JPEG quality (0-100), only valid for JPEG format

        Returns:
            Dict[str, Any]: Screenshot result
        """
        self.logger.info(f"Taking screenshot (full_page={full_page}, format={format}, quality={quality})")
        
        params = {
            "format": format,
            "captureBeyondViewport": full_page
        }
        
        if format == "jpeg":
            params["quality"] = quality
        
        response = self.session.send_command("Page.captureScreenshot", params)

        # CDP return format: {'id': ..., 'result': {'data': ...}}
        result = response.get('result', {}) if isinstance(response, dict) else {}

        if output_file and "data" in result:
            image_data = base64.b64decode(result["data"])
            output_dir = os.path.dirname(output_file)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_file, "wb") as f:
                f.write(image_data)
            self.logger.info(f"Screenshot saved to: {output_file}")
            result["file"] = output_file

        return result
