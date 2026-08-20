"""Install the GitHub CLI on the user's behalf.

frago leans on `gh` for everything it does with GitHub — syncing the working
directory to a private repo, reading community recipes, starring. A user who
never installs it silently loses the free backup of their own data, so the web
UI offers to do the install rather than handing over a command to paste.

Two install shapes are supported, in this order:

1. A package manager that is already on the machine (Homebrew, winget). What it
   installs lands on the user's normal PATH, so their own terminal sees `gh`
   too.
2. The official release archive from GitHub, unpacked into
   ``~/.frago/tools/gh/bin``. Needs no admin rights and works everywhere, at
   the cost of that directory not being on the shell PATH until the user adds
   it — which is why a path hint comes back with the result.

Installing takes minutes, far longer than an HTTP request should hold open, so
:meth:`GhInstallService.start` returns immediately and the UI polls
:meth:`GhInstallService.get_status`.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

from frago.server.services.subprocess_utils import (
    GH_MANAGED_BIN_DIR,
    get_utf8_env,
    resolve_command_path,
)

logger = logging.getLogger(__name__)

# Where the release archive comes from when no package manager is available.
GH_RELEASE_API = "https://api.github.com/repos/cli/cli/releases/latest"

# Keeping the whole log would grow without bound on a stuck download.
_MAX_LOG_LINES = 200


def _brew_command() -> list[str] | None:
    """Homebrew's path, or None when it is not installed.

    ``shutil.which`` alone misses the common case where the server was started
    from a launch agent whose PATH predates the Homebrew install, so the two
    standard prefixes are checked directly as well.
    """
    found = shutil.which("brew")
    if found:
        return [found]
    for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if Path(candidate).exists():
            return [candidate]
    return None


def _winget_command() -> list[str] | None:
    found = shutil.which("winget")
    return [found] if found else None


def detect_install_plan() -> dict[str, Any]:
    """Work out how this machine would install gh, without installing anything.

    Returns a dict with:
    - method: "brew" | "winget" | "binary"
    - command: the human-readable command, for users who would rather run it
      themselves (empty for the binary download, which is not one command)
    - needs_path_hint: whether the result will land outside the shell PATH
    - manual_url: where to go if the automated path fails
    """
    system = platform.system()

    if system in ("Darwin", "Linux") and _brew_command():
        return {
            "method": "brew",
            "command": "brew install gh",
            "needs_path_hint": False,
            "manual_url": "https://cli.github.com/",
        }

    if system == "Windows" and _winget_command():
        return {
            "method": "winget",
            "command": "winget install --id GitHub.cli",
            "needs_path_hint": False,
            "manual_url": "https://cli.github.com/",
        }

    return {
        "method": "binary",
        "command": "",
        "needs_path_hint": True,
        "manual_url": "https://cli.github.com/",
    }


def _release_asset_pattern() -> tuple[str, str] | None:
    """The (os, arch) fragment GitHub uses in gh's asset filenames.

    Returns None on a platform gh publishes no build for, which is the caller's
    cue to stop rather than download something that cannot run.
    """
    system = platform.system()
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine in ("i386", "i686", "x86"):
        arch = "386"
    else:
        return None

    if system == "Darwin":
        return ("macOS", arch)
    if system == "Linux":
        return ("linux", arch)
    if system == "Windows":
        return ("windows", arch)
    return None


class GhInstallService:
    """Runs one gh install at a time and reports how it is going."""

    _lock = threading.Lock()
    _thread: threading.Thread | None = None
    _state: dict[str, Any] = {
        "status": "idle",  # idle | running | success | error
        "method": None,
        "message": "",
        "error": None,
        "log": [],
        "path_hint": None,
    }

    # ------------------------------------------------------------------
    # State plumbing
    # ------------------------------------------------------------------

    @classmethod
    def get_status(cls) -> dict[str, Any]:
        with cls._lock:
            return {
                "status": cls._state["status"],
                "method": cls._state["method"],
                "message": cls._state["message"],
                "error": cls._state["error"],
                "log": list(cls._state["log"]),
                "path_hint": cls._state["path_hint"],
            }

    @classmethod
    def _log(cls, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        with cls._lock:
            log: list[str] = cls._state["log"]
            log.append(line)
            if len(log) > _MAX_LOG_LINES:
                del log[: len(log) - _MAX_LOG_LINES]
        logger.debug("gh install: %s", line)

    @classmethod
    def _set(cls, **fields: Any) -> None:
        with cls._lock:
            cls._state.update(fields)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @classmethod
    def start(cls) -> dict[str, Any]:
        """Kick off an install in the background.

        Returns the status the caller should start polling from. A second call
        while one is already running is a no-op rather than a second install.
        """
        with cls._lock:
            if cls._state["status"] == "running":
                return {
                    "status": "ok",
                    "already_running": True,
                    "method": cls._state["method"],
                }

        plan = detect_install_plan()
        cls._set(
            status="running",
            method=plan["method"],
            message="Starting install",
            error=None,
            log=[],
            path_hint=None,
        )

        thread = threading.Thread(
            target=cls._run_install,
            args=(plan,),
            name="gh-install",
            daemon=True,
        )
        cls._thread = thread
        thread.start()

        return {"status": "ok", "already_running": False, "method": plan["method"]}

    @classmethod
    def _run_install(cls, plan: dict[str, Any]) -> None:
        method = plan["method"]
        try:
            if method == "brew":
                cls._install_via_command(_brew_command() + ["install", "gh"])
            elif method == "winget":
                cls._install_via_command(
                    _winget_command()
                    + [
                        "install",
                        "--id",
                        "GitHub.cli",
                        "-e",
                        "--source",
                        "winget",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ]
                )
            else:
                cls._install_via_release_archive()
        except Exception as e:  # noqa: BLE001 - the UI has to survive any failure
            logger.warning("gh install failed: %s", e)
            cls._set(
                status="error",
                message="Install failed",
                error=str(e),
            )
            return

        # A package manager can report success while the new binary is not yet
        # visible to this process; verify before claiming victory.
        from frago.server.services.github_service import GitHubService

        GitHubService.clear_token_cache()
        status = GitHubService.check_gh_cli()
        if status.get("installed"):
            cls._set(
                status="success",
                message=f"GitHub CLI {status.get('version') or ''}".strip(),
                error=None,
            )
        else:
            cls._set(
                status="error",
                message="Install finished but gh is still not runnable",
                error=(
                    "The install command reported success, but `gh --version` "
                    "still fails. Restarting frago server usually picks up a "
                    "freshly installed binary."
                ),
            )

    # ------------------------------------------------------------------
    # Method: package manager
    # ------------------------------------------------------------------

    @classmethod
    def _install_via_command(cls, cmd: list[str]) -> None:
        cls._set(message=f"Running {' '.join(cmd[:2])}")
        cls._log(f"$ {' '.join(cmd)}")

        from frago.compat import get_windows_subprocess_kwargs

        process = subprocess.Popen(
            resolve_command_path(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=get_utf8_env(),
            **get_windows_subprocess_kwargs(),
        )

        assert process.stdout is not None
        for line in process.stdout:
            cls._log(line)

        returncode = process.wait()
        if returncode != 0:
            raise RuntimeError(
                f"`{' '.join(cmd)}` exited with code {returncode}. "
                "See the log above for what it reported."
            )

    # ------------------------------------------------------------------
    # Method: official release archive
    # ------------------------------------------------------------------

    @classmethod
    def _install_via_release_archive(cls) -> None:
        import requests

        pattern = _release_asset_pattern()
        if pattern is None:
            raise RuntimeError(
                f"GitHub publishes no gh build for {platform.system()} "
                f"{platform.machine()}. Install it manually from "
                "https://cli.github.com/."
            )
        os_fragment, arch = pattern

        cls._set(message="Looking up the latest GitHub CLI release")
        cls._log(f"Fetching {GH_RELEASE_API}")

        from frago.server.services.github_service import GitHubService

        response = requests.get(
            GH_RELEASE_API, headers=GitHubService.get_auth_headers(), timeout=20
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Could not read the GitHub CLI release list (HTTP "
                f"{response.status_code}). This is usually a network or "
                "rate-limit problem; try again in a few minutes."
            )
        release = response.json()
        tag = release.get("tag_name", "")
        cls._log(f"Latest release: {tag}")

        wanted_suffix = ".zip" if os_fragment in ("macOS", "windows") else ".tar.gz"
        asset = None
        for candidate in release.get("assets", []):
            name = candidate.get("name", "")
            if (
                name.startswith("gh_")
                and f"_{os_fragment}_{arch}" in name
                and name.endswith(wanted_suffix)
            ):
                asset = candidate
                break

        if asset is None:
            raise RuntimeError(
                f"Release {tag} has no {os_fragment}/{arch} archive. "
                "Install gh manually from https://cli.github.com/."
            )

        url = asset["browser_download_url"]
        cls._set(message=f"Downloading {asset['name']}")
        cls._log(f"Downloading {url}")

        with tempfile.TemporaryDirectory(prefix="frago-gh-") as tmpdir:
            archive_path = Path(tmpdir) / asset["name"]
            with requests.get(url, stream=True, timeout=120) as download:
                download.raise_for_status()
                with open(archive_path, "wb") as handle:
                    for chunk in download.iter_content(chunk_size=1024 * 256):
                        handle.write(chunk)

            cls._set(message="Unpacking")
            binary_name = "gh.exe" if os_fragment == "windows" else "gh"
            target_dir = GH_MANAGED_BIN_DIR
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / binary_name

            cls._extract_binary(archive_path, binary_name, target)

            if os_fragment != "windows":
                target.chmod(
                    target.stat().st_mode
                    | stat.S_IXUSR
                    | stat.S_IXGRP
                    | stat.S_IXOTH
                )

        cls._log(f"Installed to {target}")
        cls._set(path_hint=cls._path_hint(target_dir))

    @staticmethod
    def _extract_binary(archive_path: Path, binary_name: str, target: Path) -> None:
        """Pull just ``bin/<binary_name>`` out of the archive.

        Only the one member is written, and it is written to a path we chose —
        so a doctored archive cannot place files anywhere else on disk.
        """
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path) as archive:
                member = next(
                    (
                        name
                        for name in archive.namelist()
                        if name.endswith(f"bin/{binary_name}")
                    ),
                    None,
                )
                if member is None:
                    raise RuntimeError(
                        f"{archive_path.name} contains no bin/{binary_name}"
                    )
                with archive.open(member) as source, open(target, "wb") as dest:
                    shutil.copyfileobj(source, dest)
            return

        with tarfile.open(archive_path, "r:gz") as archive:
            member = next(
                (
                    item
                    for item in archive.getmembers()
                    if item.isfile() and item.name.endswith(f"bin/{binary_name}")
                ),
                None,
            )
            if member is None:
                raise RuntimeError(f"{archive_path.name} contains no bin/{binary_name}")
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"Could not read bin/{binary_name} from the archive")
            with source, open(target, "wb") as dest:
                shutil.copyfileobj(source, dest)

    @staticmethod
    def _path_hint(target_dir: Path) -> str:
        """The line the user adds so their own terminal finds gh too.

        frago itself does not need this — it resolves the managed path
        directly — but a user who later types `gh` at a prompt does.
        """
        if platform.system() == "Windows":
            return f'setx PATH "%PATH%;{target_dir}"'
        shell = os.environ.get("SHELL", "")
        rc = "~/.zshrc" if "zsh" in shell else "~/.bashrc"
        return f'echo \'export PATH="{target_dir}:$PATH"\' >> {rc}'
