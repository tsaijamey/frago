"""
Target-related CDP commands

Encapsulates CDP commands for the Target domain.
Used for managing browser tabs/targets.
"""

from typing import Dict, Any, List, Optional

from ..logger import get_logger


class TargetCommands:
    """Target commands class for managing browser tabs"""

    def __init__(self, session):
        """
        Initialize target commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def create_target(self, url: str, width: Optional[int] = None, height: Optional[int] = None) -> str:
        """
        Create a new browser tab and navigate to URL

        Args:
            url: URL to open in new tab
            width: Optional viewport width
            height: Optional viewport height

        Returns:
            str: Target ID of the new tab
        """
        self.logger.info(f"Creating new tab with URL: {url}")

        params: Dict[str, Any] = {"url": url}
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height

        result = self.session.send_command("Target.createTarget", params)

        target_id = result.get("result", {}).get("targetId", "")
        self.logger.debug(f"Created target: {target_id}")
        return target_id

    def close_target(self, target_id: str) -> bool:
        """
        Close a browser tab

        Args:
            target_id: Target ID to close

        Returns:
            bool: Whether close was successful
        """
        self.logger.info(f"Closing target: {target_id}")

        result = self.session.send_command(
            "Target.closeTarget",
            {"targetId": target_id}
        )

        success = result.get("result", {}).get("success", False)
        self.logger.debug(f"Close target result: {success}")
        return success

    def get_targets(self) -> List[Dict[str, Any]]:
        """
        Get list of all targets (tabs)

        Returns:
            List of target info dictionaries
        """
        self.logger.info("Getting target list")

        result = self.session.send_command("Target.getTargets", {})

        targets = result.get("result", {}).get("targetInfos", [])
        self.logger.debug(f"Found {len(targets)} targets")
        return targets

    def activate_target(self, target_id: str) -> None:
        """
        Bring target to front (focus tab)

        Args:
            target_id: Target ID to activate
        """
        self.logger.info(f"Activating target: {target_id}")

        self.session.send_command(
            "Target.activateTarget",
            {"targetId": target_id}
        )

        self.logger.debug("Target activated")
