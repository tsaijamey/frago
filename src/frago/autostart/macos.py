"""macOS LaunchAgent autostart management."""

import plistlib
import shutil
import subprocess
from pathlib import Path

from .base import AutostartManager


class MacOSAutostartManager(AutostartManager):
    """Manage autostart via macOS LaunchAgents.

    Creates a plist file in ~/Library/LaunchAgents/ that runs
    'frago server start' at user login.
    """

    LABEL = "com.frago.server"
    PLIST_NAME = f"{LABEL}.plist"

    @property
    def platform_name(self) -> str:
        return "macOS LaunchAgent"

    @property
    def config_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / self.PLIST_NAME

    def _get_frago_path(self) -> str:
        """Get the full path to the frago executable."""
        frago_path = shutil.which("frago")
        if frago_path:
            return frago_path
        # Fallback to common locations
        for path in [
            Path.home() / ".local" / "bin" / "frago",
            Path("/usr/local/bin/frago"),
            Path("/opt/homebrew/bin/frago"),
        ]:
            if path.exists():
                return str(path)
        return "frago"  # Hope it's in PATH at login

    def _generate_plist(self) -> dict:
        """Generate the LaunchAgent plist configuration."""
        frago_path = self._get_frago_path()
        log_path = Path.home() / ".frago" / "launchd.log"

        return {
            "Label": self.LABEL,
            "ProgramArguments": [frago_path, "server", "start"],
            "RunAtLoad": True,
            "KeepAlive": False,  # Only start at boot, don't restart on crash
            "StandardOutPath": str(log_path),
            "StandardErrorPath": str(log_path),
        }

    def enable(self) -> tuple[bool, str]:
        """Enable autostart by creating and loading LaunchAgent."""
        try:
            # Ensure LaunchAgents directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Ensure log directory exists
            log_dir = Path.home() / ".frago"
            log_dir.mkdir(parents=True, exist_ok=True)

            # Generate and write plist
            plist_data = self._generate_plist()
            with open(self.config_path, "wb") as f:
                plistlib.dump(plist_data, f)

            # Load the LaunchAgent (optional, makes it active immediately)
            # Using 'load' instead of 'bootstrap' for compatibility
            result = subprocess.run(
                ["launchctl", "load", str(self.config_path)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0 and "already loaded" not in result.stderr.lower():
                # Non-fatal: file is created, will work on next login
                return True, f"Autostart enabled (will start on next login)"

            return True, f"Autostart enabled ({self.platform_name})"

        except PermissionError:
            return False, f"Permission denied writing to {self.config_path}"
        except Exception as e:
            return False, f"Failed to enable autostart: {e}"

    def disable(self) -> tuple[bool, str]:
        """Disable autostart by unloading and removing LaunchAgent."""
        try:
            if not self.config_path.exists():
                return True, "Autostart was not enabled"

            # Unload the LaunchAgent
            subprocess.run(
                ["launchctl", "unload", str(self.config_path)],
                capture_output=True,
                text=True,
            )

            # Remove the plist file
            self.config_path.unlink()

            return True, "Autostart disabled"

        except PermissionError:
            return False, f"Permission denied removing {self.config_path}"
        except Exception as e:
            return False, f"Failed to disable autostart: {e}"

    def is_enabled(self) -> bool:
        """Check if LaunchAgent plist exists."""
        return self.config_path.exists()
