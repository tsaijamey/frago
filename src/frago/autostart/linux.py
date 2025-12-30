"""Linux systemd user service autostart management."""

import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

from .base import AutostartManager


class LinuxAutostartManager(AutostartManager):
    """Manage autostart via systemd user services.

    Creates a service file in ~/.config/systemd/user/ that runs
    'frago server start' at user login.
    """

    SERVICE_NAME = "frago-server.service"

    @property
    def platform_name(self) -> str:
        return "Linux systemd user service"

    @property
    def config_path(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / self.SERVICE_NAME

    def _get_frago_path(self) -> str:
        """Get the full path to the frago executable."""
        frago_path = shutil.which("frago")
        if frago_path:
            return frago_path
        # Fallback to common locations
        for path in [
            Path.home() / ".local" / "bin" / "frago",
            Path("/usr/local/bin/frago"),
        ]:
            if path.exists():
                return str(path)
        return "frago"  # Hope it's in PATH at login

    def _generate_service(self) -> str:
        """Generate the systemd service file content."""
        frago_path = self._get_frago_path()

        return dedent(f"""\
            [Unit]
            Description=Frago AI Automation Server
            After=network.target

            [Service]
            Type=exec
            ExecStart={frago_path} server start
            Restart=no

            [Install]
            WantedBy=default.target
        """)

    def _check_systemd_available(self) -> bool:
        """Check if systemd user services are available."""
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            text=True,
        )
        # If systemctl --user works at all, we're good
        return result.returncode in (0, 1, 3)  # 0=running, 1=some failed, 3=inactive

    def enable(self) -> tuple[bool, str]:
        """Enable autostart by creating and enabling systemd user service."""
        try:
            # Check if systemd user services are available
            if not self._check_systemd_available():
                return False, "systemd user services not available"

            # Ensure systemd user directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Generate and write service file
            service_content = self._generate_service()
            self.config_path.write_text(service_content)

            # Reload systemd daemon to pick up new service
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True,
            )

            # Enable the service (start on boot)
            result = subprocess.run(
                ["systemctl", "--user", "enable", self.SERVICE_NAME],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"Failed to enable service: {result.stderr}"

            return True, f"Autostart enabled ({self.platform_name})"

        except PermissionError:
            return False, f"Permission denied writing to {self.config_path}"
        except FileNotFoundError:
            return False, "systemctl not found. Is systemd installed?"
        except Exception as e:
            return False, f"Failed to enable autostart: {e}"

    def disable(self) -> tuple[bool, str]:
        """Disable autostart by disabling and removing systemd user service."""
        try:
            if not self.config_path.exists():
                return True, "Autostart was not enabled"

            # Disable the service
            subprocess.run(
                ["systemctl", "--user", "disable", self.SERVICE_NAME],
                capture_output=True,
                text=True,
            )

            # Stop if running
            subprocess.run(
                ["systemctl", "--user", "stop", self.SERVICE_NAME],
                capture_output=True,
                text=True,
            )

            # Remove the service file
            self.config_path.unlink()

            # Reload daemon
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True,
            )

            return True, "Autostart disabled"

        except PermissionError:
            return False, f"Permission denied removing {self.config_path}"
        except Exception as e:
            return False, f"Failed to disable autostart: {e}"

    def is_enabled(self) -> bool:
        """Check if systemd user service is enabled."""
        if not self.config_path.exists():
            return False

        # Also verify it's actually enabled in systemd
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", self.SERVICE_NAME],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
