"""Linux systemd user service autostart management."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from frago.server.launch_guard import SPAWN_TOKEN_ENV, SPAWN_TOKEN_VALUE

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
        """Get the full path to the system-installed frago executable."""
        from frago.server.launch_guard import is_checkout_venv_path

        clean_entries = [
            entry
            for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry and not is_checkout_venv_path(entry)
        ]
        frago_path = shutil.which("frago", path=os.pathsep.join(clean_entries))
        if frago_path and not is_checkout_venv_path(frago_path):
            return frago_path
        # Fallback to common locations
        for path in [
            Path.home() / ".local" / "bin" / "frago",
            Path("/usr/local/bin/frago"),
        ]:
            if path.exists():
                return str(path)
        return "frago"  # Hope it's in PATH at login

    def _get_python_path(self) -> str:
        """Get the Python interpreter path that can run the system-installed frago.

        Returns the Python from the same environment where frago is installed.
        """
        from frago.server.launch_guard import is_checkout_venv_path

        frago_path = self._get_frago_path()

        # Follow the launcher symlink (e.g. ~/.local/bin/frago ->
        # ~/.local/share/uv/tools/frago-cli/bin/frago) so we look inside the
        # uv tool venv's bin/ directory rather than ~/.local/bin, while keeping
        # the venv's python3 symlink itself unresolved so pyvenv.cfg activates.
        candidate_dirs = [
            Path(frago_path).resolve(strict=False).parent,
            Path(frago_path).parent,
        ]
        for frago_bin_dir in candidate_dirs:
            if is_checkout_venv_path(frago_bin_dir):
                continue
            for name in ("python3", "python"):
                python_path = frago_bin_dir / name
                if python_path.exists() and not is_checkout_venv_path(python_path):
                    return str(python_path)

        # Fallback to current Python
        return sys.executable

    def reconcile_service_unit(self) -> bool:
        """Ensure an existing systemd unit file satisfies current launch guards
        and points at the system-installed frago runtime.

        Fixes three classes of drift in-place without clobbering user/deployment
        customisations (such as ``EnvironmentFile=`` or proxy vars):
        1. ``ExecStart=`` pointing at a source checkout ``.venv`` (blocked by
           Gate 2), a missing interpreter, or an outdated interpreter path.
        2. Missing or stale ``Environment=FRAGO_DAEMON_SPAWN_TOKEN=...`` (blocked
           by Gate 1).
        3. ``Environment=PATH=...`` carrying a source checkout ``.venv/bin``
           entry (causes child recipes/hooks to hit the CLI checkout guard).

        If the unit file is modified, writes it back and runs
        ``systemctl --user daemon-reload``.

        Returns:
            True if the unit file was modified and reloaded, False otherwise.
        """
        from frago.server.launch_guard import is_checkout_venv_path

        if not self.config_path.exists():
            return False

        try:
            original = self.config_path.read_text(encoding="utf-8")
        except OSError:
            return False

        expected_python = self._get_python_path()
        expected_exec = f"ExecStart={expected_python} -m frago.server.runner --daemon"
        expected_token = f"Environment={SPAWN_TOKEN_ENV}={SPAWN_TOKEN_VALUE}"

        lines = original.splitlines()
        new_lines: list[str] = []
        has_spawn_token = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Environment=PATH="):
                raw_path = stripped[len("Environment=PATH=") :]
                entries = [e for e in raw_path.split(":") if e]
                kept = [e for e in entries if not is_checkout_venv_path(e)]
                if len(kept) != len(entries):
                    line = f"Environment=PATH={':'.join(kept)}"
                new_lines.append(line)
            elif stripped.startswith(f"Environment={SPAWN_TOKEN_ENV}="):
                has_spawn_token = True
                new_lines.append(expected_token)
            elif stripped.startswith("ExecStart="):
                if not has_spawn_token:
                    new_lines.append(expected_token)
                    has_spawn_token = True
                new_lines.append(expected_exec)
            else:
                new_lines.append(line)

        if not has_spawn_token:
            for idx, line in enumerate(new_lines):
                if line.strip() == "[Service]":
                    new_lines.insert(idx + 1, expected_token)
                    break

        updated = "\n".join(new_lines) + "\n"
        if updated == original:
            return False

        try:
            self.config_path.write_text(updated, encoding="utf-8")
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except OSError:
            return False
        return True

    def _collect_proxy_environment(self) -> list[str]:
        """Collect proxy environment variables from current environment.

        Systemd services don't inherit user shell configurations (.bashrc, .zshrc).
        This captures proxy settings at enable-time so the service can access
        networks that require proxy (e.g., Claude API behind corporate proxy).

        Returns:
            List of Environment= lines for systemd service file
        """
        proxy_vars = [
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "no_proxy",
            "NO_PROXY",
        ]

        env_lines = []
        for var in proxy_vars:
            value = os.environ.get(var)
            if value:
                # systemd Environment= format: VAR=value (no quotes needed for simple values)
                env_lines.append(f"Environment={var}={value}")

        return env_lines

    def _generate_service(self) -> str:
        """Generate the systemd service file content.

        Uses Python to run the server runner module directly, allowing systemd
        to manage the process lifecycle properly.
        """
        python_path = self._get_python_path()
        env_path = self._collect_environment_path()
        proxy_env_lines = self._collect_proxy_environment()

        # Build service file lines
        lines = [
            "[Unit]",
            "Description=Frago AI Automation Server",
            "After=network.target",
            # Prevent infinite restart loops: max 5 restarts within 5 minutes.
            # After limit is hit, `systemctl --user reset-failed` + start to recover.
            "StartLimitBurst=5",
            "StartLimitIntervalSec=300",
            "",
            "[Service]",
            "Type=exec",
            f"Environment=PATH={env_path}",
            # Gate 1 token: the daemon entry refuses to start without it, so a
            # bare `python -m frago.server.runner --daemon` cannot launch a
            # server. systemd is a sanctioned spawner, hence it sets the token.
            f"Environment={SPAWN_TOKEN_ENV}={SPAWN_TOKEN_VALUE}",
        ]

        # Add proxy environment variables
        lines.extend(proxy_env_lines)

        lines.extend([
            f"ExecStart={python_path} -m frago.server.runner --daemon",
            "Restart=always",
            "RestartSec=30",
            # Memory protection: server + Claude Code sub-agents + recipes can
            # legitimately use a few GB. Cap so a runaway (e.g. git push on a
            # bloated sync repo) is killed cgroup-internally instead of taking
            # down the host. MemoryHigh applies soft pressure (reclaim);
            # MemoryMax is a hard kill ceiling.
            "MemoryHigh=6G",
            "MemoryMax=8G",
            "",
            "[Install]",
            "WantedBy=default.target",
        ])

        return "\n".join(lines) + "\n"

    def _check_systemd_available(self) -> bool:
        """Check if systemd user services are available."""
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            text=True,
        )
        # If systemctl --user works at all, we're good
        return result.returncode in (0, 1, 3)  # 0=running, 1=some failed, 3=inactive

    def _is_linger_enabled(self) -> bool:
        """Check if lingering is enabled for current user.

        Lingering allows user services to run at boot without requiring login.
        """
        username = os.environ.get("USER", "")
        if not username:
            return False
        linger_file = Path("/var/lib/systemd/linger") / username
        return linger_file.exists()

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

            # Enable lingering to allow service start at boot without login
            if not self._is_linger_enabled():
                linger_result = subprocess.run(
                    ["loginctl", "enable-linger"],
                    capture_output=True,
                    text=True,
                )
                if linger_result.returncode != 0:
                    # Non-fatal: service is enabled but won't start at boot
                    return True, (
                        f"Autostart enabled ({self.platform_name}). "
                        f"Warning: lingering not enabled, service will only start after login."
                    )

            return True, f"Autostart enabled ({self.platform_name})"

        except PermissionError:
            return False, f"Permission denied writing to {self.config_path}"
        except FileNotFoundError:
            return False, "systemctl not found. Is systemd installed?"
        except Exception as e:
            return False, f"Failed to enable autostart: {e}"

    def disable(self) -> tuple[bool, str]:
        """Disable autostart by disabling and removing systemd user service.

        Note: We intentionally do NOT disable lingering here, as other user
        services may depend on it. Lingering is a user-wide setting.
        """
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
