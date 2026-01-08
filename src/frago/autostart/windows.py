"""Windows Registry Run key autostart management."""

import shutil
import sys
from pathlib import Path

from .base import AutostartManager


class WindowsAutostartManager(AutostartManager):
    """Manage autostart via Windows Registry Run key.

    Adds an entry to HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    that runs 'frago server start' at user login.
    """

    REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "FragoServer"

    @property
    def platform_name(self) -> str:
        return "Windows Registry"

    @property
    def config_path(self) -> Path:
        # Registry doesn't have a file path, return a pseudo-path for display
        return Path(f"HKEY_CURRENT_USER\\{self.REGISTRY_KEY}\\{self.VALUE_NAME}")

    def _get_frago_path(self) -> str:
        """Get the full path to the frago executable."""
        frago_path = shutil.which("frago")
        if frago_path:
            return frago_path
        # Try to find frago.exe in Python Scripts directory
        scripts_dir = Path(sys.executable).parent / "Scripts"
        frago_exe = scripts_dir / "frago.exe"
        if frago_exe.exists():
            return str(frago_exe)
        return "frago"  # Hope it's in PATH at login

    def _build_command(self) -> str:
        """Build the autostart command for completely invisible startup.

        Uses pythonw.exe directly to avoid any console window.
        """
        # Find pythonw.exe for windowless execution
        pythonw_candidates = [
            Path(sys.executable).parent / "pythonw.exe",
            Path(sys.base_exec_prefix) / "pythonw.exe",
        ]
        pythonw_path = None
        for candidate in pythonw_candidates:
            if candidate.exists():
                pythonw_path = str(candidate)
                break

        if pythonw_path:
            # Use pythonw.exe directly - no console window at all
            if " " in pythonw_path:
                return f'"{pythonw_path}" -m frago.cli.main server start'
            return f"{pythonw_path} -m frago.cli.main server start"

        # Fallback: use frago command with PowerShell hidden
        frago_path = self._get_frago_path()
        if " " in frago_path:
            frago_cmd = f"'{frago_path}'"
        else:
            frago_cmd = frago_path

        extra_paths = self._collect_environment_path()
        if extra_paths:
            ps_cmd = f"$env:PATH='{extra_paths};'+$env:PATH; & {frago_cmd} server start"
        else:
            ps_cmd = f"& {frago_cmd} server start"

        return f'powershell -WindowStyle Hidden -Command "{ps_cmd}"'

    def enable(self) -> tuple[bool, str]:
        """Enable autostart by adding Registry Run key."""
        try:
            import winreg

            command = self._build_command()

            # Open the Run key
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REGISTRY_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )

            try:
                winreg.SetValueEx(
                    key,
                    self.VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    command,
                )
            finally:
                winreg.CloseKey(key)

            return True, f"Autostart enabled ({self.platform_name})"

        except ImportError:
            return False, "winreg module not available (not running on Windows?)"
        except PermissionError:
            return False, "Permission denied accessing registry"
        except Exception as e:
            return False, f"Failed to enable autostart: {e}"

    def disable(self) -> tuple[bool, str]:
        """Disable autostart by removing Registry Run key."""
        try:
            import winreg

            # Open the Run key
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REGISTRY_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )

            try:
                winreg.DeleteValue(key, self.VALUE_NAME)
            except FileNotFoundError:
                # Value doesn't exist, that's fine
                return True, "Autostart was not enabled"
            finally:
                winreg.CloseKey(key)

            return True, "Autostart disabled"

        except ImportError:
            return False, "winreg module not available (not running on Windows?)"
        except PermissionError:
            return False, "Permission denied accessing registry"
        except Exception as e:
            return False, f"Failed to disable autostart: {e}"

    def is_enabled(self) -> bool:
        """Check if Registry Run key exists."""
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REGISTRY_KEY,
                0,
                winreg.KEY_READ,
            )

            try:
                winreg.QueryValueEx(key, self.VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)

        except ImportError:
            return False
        except Exception:
            return False
