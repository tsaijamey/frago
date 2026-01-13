"""Recipe installation and management module"""
import json
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import platform
import subprocess

import requests

logger = logging.getLogger(__name__)

from frago.compat import get_windows_subprocess_kwargs

from .exceptions import RecipeAlreadyExistsError, RecipeInstallError
from .metadata import parse_metadata_file, validate_metadata


class InstallSource(str, Enum):
    """Recipe installation source types"""
    COMMUNITY = "community"
    LOCAL_PATH = "local_path"


@dataclass
class InstalledRecipeInfo:
    """Installed recipe metadata"""
    name: str
    source_type: str  # InstallSource value
    source_url: str
    version: str
    installed_at: str  # ISO format datetime
    recipe_type: str  # atomic or workflow
    runtime: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "version": self.version,
            "installed_at": self.installed_at,
            "recipe_type": self.recipe_type,
            "runtime": self.runtime,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstalledRecipeInfo":
        """Create from dictionary"""
        return cls(
            name=data["name"],
            source_type=data["source_type"],
            source_url=data["source_url"],
            version=data["version"],
            installed_at=data["installed_at"],
            recipe_type=data["recipe_type"],
            runtime=data["runtime"],
        )


@dataclass
class InstallManifest:
    """Tracks all installed recipes"""
    schema_version: str = "1.0"
    recipes: dict[str, InstalledRecipeInfo] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "InstallManifest":
        """Load manifest from file"""
        if not path.exists():
            return cls()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            manifest = cls(schema_version=data.get("schema_version", "1.0"))
            for name, info in data.get("recipes", {}).items():
                manifest.recipes[name] = InstalledRecipeInfo.from_dict(info)
            return manifest
        except Exception:
            # If loading fails, return empty manifest
            return cls()

    def save(self, path: Path) -> None:
        """Save manifest to file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": self.schema_version,
            "recipes": {
                name: info.to_dict()
                for name, info in self.recipes.items()
            }
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


class RecipeInstaller:
    """Handles recipe installation from various sources"""

    # Community repository configuration (defaults, can be overridden by config)
    DEFAULT_COMMUNITY_REPO = "tsaijamey/frago"
    COMMUNITY_BRANCH = "main"
    COMMUNITY_PATH = "community-recipes/recipes"

    # GitHub API configuration
    GITHUB_API_BASE = "https://api.github.com"
    REQUEST_TIMEOUT = 30

    def __init__(self):
        self.community_dir = Path.home() / ".frago" / "community-recipes"
        self.manifest_path = self.community_dir / ".installed" / "manifest.json"
        self._manifest: Optional[InstallManifest] = None

        # Load community repo from config
        from frago.init.config_manager import load_config
        config = load_config()
        self.community_repo = config.community_repo

    @property
    def COMMUNITY_REPO(self) -> str:
        """Community repository (from config or default)"""
        return self.community_repo

    @property
    def manifest(self) -> InstallManifest:
        """Lazy load manifest"""
        if self._manifest is None:
            self._manifest = InstallManifest.load(self.manifest_path)
        return self._manifest

    def _save_manifest(self) -> None:
        """Save manifest to file"""
        self.manifest.save(self.manifest_path)

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers, including GitHub token if available.

        Token lookup order:
        1. GITHUB_TOKEN environment variable
        2. gh auth token (from gh CLI)
        """
        import os
        import platform
        import shutil
        import subprocess
        from pathlib import Path

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "frago-recipe-installer",
        }

        # Try environment variable first
        token = os.environ.get("GITHUB_TOKEN")

        # Fall back to gh CLI token
        if not token:
            try:
                # Get gh command - use direct exe path on Windows to avoid cmd flash
                gh_cmd = ["gh"]
                if platform.system() == "Windows":
                    gh_path = shutil.which("gh")
                    if gh_path:
                        gh_path_obj = Path(gh_path)
                        if gh_path_obj.suffix.lower() == ".cmd":
                            gh_exe = gh_path_obj.with_suffix(".exe")
                            if gh_exe.exists():
                                gh_cmd = [str(gh_exe)]
                            else:
                                gh_exe = gh_path_obj.parent / "gh.exe"
                                if gh_exe.exists():
                                    gh_cmd = [str(gh_exe)]
                        else:
                            gh_cmd = [str(gh_path_obj)]

                run_kwargs: dict = {
                    "capture_output": True,
                    "text": True,
                    "timeout": 5,
                    **get_windows_subprocess_kwargs(),
                }

                result = subprocess.run(
                    gh_cmd + ["auth", "token"],
                    **run_kwargs,
                )
                if result.returncode == 0 and result.stdout.strip():
                    token = result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass

        if token:
            headers["Authorization"] = f"token {token}"

        return headers

    def _get_rate_limit_manager(self):
        """Get rate limit manager instance (lazy import to avoid circular deps)."""
        try:
            from frago.server.services.github_rate_limit import GitHubRateLimitManager
            return GitHubRateLimitManager.get_instance()
        except ImportError:
            return None

    def _request_with_retry(
        self,
        url: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> requests.Response:
        """Make request with exponential backoff retry.

        Args:
            url: URL to request
            max_retries: Maximum retry attempts
            base_delay: Base delay in seconds for backoff

        Returns:
            Response object

        Raises:
            requests.RequestException: If all retries fail
        """
        rate_manager = self._get_rate_limit_manager()
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                # Pre-request delay based on rate limit state
                if rate_manager:
                    delay = rate_manager.get_recommended_delay()
                    if delay > 0.1:  # Only sleep for meaningful delays
                        logger.debug(f"Rate limit delay: {delay:.1f}s before request")
                        time.sleep(min(delay, 60))  # Cap at 60s

                response = requests.get(
                    url,
                    headers=self._get_headers(),
                    timeout=self.REQUEST_TIMEOUT
                )

                # Update rate limit state from response
                if rate_manager:
                    rate_manager.update_from_headers(dict(response.headers))

                if response.status_code == 200:
                    return response
                elif response.status_code == 403:
                    if rate_manager:
                        rate_manager.record_error(is_rate_limit=True)
                    # Check if we should retry
                    if attempt < max_retries - 1 and rate_manager:
                        wait_time = rate_manager.get_recommended_delay()
                        if wait_time > 0:
                            logger.info(
                                f"Rate limited, waiting {wait_time:.0f}s before retry "
                                f"(attempt {attempt + 1}/{max_retries})"
                            )
                            time.sleep(min(wait_time, 60))
                            continue
                    return response  # Return 403 for caller to handle
                elif response.status_code >= 500:
                    if rate_manager:
                        rate_manager.record_error(is_rate_limit=False)
                    # Server error, retry with backoff
                    if attempt < max_retries - 1:
                        backoff = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Server error {response.status_code}, "
                            f"retrying in {backoff:.1f}s"
                        )
                        time.sleep(backoff)
                        continue

                return response

            except requests.RequestException as e:
                last_error = e
                if rate_manager:
                    rate_manager.record_error(is_rate_limit=False)
                if attempt < max_retries - 1:
                    backoff = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Request failed, retrying in {backoff:.1f}s: {e}"
                    )
                    time.sleep(backoff)
                else:
                    raise

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise requests.RequestException("Max retries exceeded")

    def install(
        self,
        source: str,
        force: bool = False,
        name_override: Optional[str] = None,
    ) -> str:
        """
        Install recipe from source

        Args:
            source: Source identifier (community:name, URL, or local path)
            force: Overwrite existing recipe if exists
            name_override: Override recipe name

        Returns:
            Installed recipe name

        Raises:
            RecipeInstallError: If installation fails
            RecipeAlreadyExistsError: If recipe exists and force is False
        """
        source_type, source_value = self._parse_source(source)

        if source_type == InstallSource.COMMUNITY:
            return self._install_from_community(source_value, force, name_override)
        elif source_type == InstallSource.LOCAL_PATH:
            return self._install_from_local_path(source_value, force, name_override)
        else:
            raise RecipeInstallError("unknown", source, f"Unknown source type: {source_type}")

    def _parse_source(self, source: str) -> tuple[InstallSource, str]:
        """Parse source string into type and value"""
        if source.startswith("community:"):
            return InstallSource.COMMUNITY, source[10:]
        elif Path(source).exists():
            return InstallSource.LOCAL_PATH, source
        else:
            raise RecipeInstallError(
                "unknown",
                source,
                "Invalid source format. Use 'community:<name>' or local path"
            )

    def _install_from_community(
        self,
        name: str,
        force: bool,
        name_override: Optional[str],
    ) -> str:
        """Install recipe from community repository"""
        # Fetch recipe directory listing from GitHub
        api_url = (
            f"{self.GITHUB_API_BASE}/repos/{self.COMMUNITY_REPO}"
            f"/contents/{self.COMMUNITY_PATH}/{name}"
            f"?ref={self.COMMUNITY_BRANCH}"
        )

        try:
            response = requests.get(
                api_url,
                headers=self._get_headers(),
                timeout=self.REQUEST_TIMEOUT
            )
            if response.status_code == 404:
                raise RecipeInstallError(
                    name,
                    f"community:{name}",
                    f"Recipe '{name}' not found in community repository"
                )
            response.raise_for_status()
        except requests.RequestException as e:
            raise RecipeInstallError(name, f"community:{name}", str(e))

        # Download recipe files to temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / name
            self._download_github_directory(response.json(), temp_path)
            return self._install_recipe_dir(
                temp_path,
                source_type=InstallSource.COMMUNITY,
                source_url=f"community:{name}",
                force=force,
                name_override=name_override,
            )

    def _install_from_local_path(
        self,
        path: str,
        force: bool,
        name_override: Optional[str],
    ) -> str:
        """Install recipe from local path"""
        source_path = Path(path)
        if not source_path.exists():
            raise RecipeInstallError(
                name_override or source_path.name,
                path,
                "Path does not exist"
            )

        return self._install_recipe_dir(
            source_path,
            source_type=InstallSource.LOCAL_PATH,
            source_url=str(source_path.absolute()),
            force=force,
            name_override=name_override,
        )

    def _install_recipe_dir(
        self,
        source_dir: Path,
        source_type: InstallSource,
        source_url: str,
        force: bool,
        name_override: Optional[str],
    ) -> str:
        """Install recipe from a directory"""
        # Validate recipe structure
        metadata_path = source_dir / "recipe.md"
        if not metadata_path.exists():
            raise RecipeInstallError(
                name_override or source_dir.name,
                source_url,
                "Missing recipe.md"
            )

        # Parse and validate metadata
        try:
            metadata = parse_metadata_file(metadata_path)
            validate_metadata(metadata)
        except Exception as e:
            raise RecipeInstallError(
                name_override or source_dir.name,
                source_url,
                f"Invalid recipe metadata: {e}"
            )

        recipe_name = name_override or metadata.name

        # Determine target directory based on type
        if metadata.type == "workflow":
            target_parent = self.community_dir / "workflows"
        else:  # atomic
            if metadata.runtime == "chrome-js":
                target_parent = self.community_dir / "atomic" / "chrome"
            else:
                target_parent = self.community_dir / "atomic" / "system"

        target_dir = target_parent / recipe_name

        # Check for existing
        if target_dir.exists():
            if not force:
                raise RecipeAlreadyExistsError(recipe_name, str(target_dir))
            # Remove existing
            shutil.rmtree(target_dir)

        # Copy recipe
        target_parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_dir,
            target_dir,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", ".DS_Store"
            ),
        )

        # Update manifest
        self.manifest.recipes[recipe_name] = InstalledRecipeInfo(
            name=recipe_name,
            source_type=source_type.value,
            source_url=source_url,
            version=metadata.version,
            installed_at=datetime.now().isoformat(),
            recipe_type=metadata.type,
            runtime=metadata.runtime,
        )
        self._save_manifest()

        return recipe_name

    def _download_github_directory(self, contents: list[dict], target_dir: Path) -> None:
        """Download a directory from GitHub using contents API response"""
        target_dir.mkdir(parents=True, exist_ok=True)

        for item in contents:
            if item["type"] == "file":
                # Download file
                try:
                    file_response = requests.get(
                        item["download_url"],
                        timeout=self.REQUEST_TIMEOUT
                    )
                    file_response.raise_for_status()
                    file_path = target_dir / item["name"]
                    file_path.write_bytes(file_response.content)
                except requests.RequestException as e:
                    raise RecipeInstallError(
                        target_dir.name,
                        "github",
                        f"Failed to download {item['name']}: {e}"
                    )
            elif item["type"] == "dir":
                # Recursively download subdirectory
                try:
                    dir_response = requests.get(
                        item["url"],
                        headers=self._get_headers(),
                        timeout=self.REQUEST_TIMEOUT
                    )
                    dir_response.raise_for_status()
                    self._download_github_directory(
                        dir_response.json(),
                        target_dir / item["name"]
                    )
                except requests.RequestException as e:
                    raise RecipeInstallError(
                        target_dir.name,
                        "github",
                        f"Failed to download directory {item['name']}: {e}"
                    )

    def uninstall(self, name: str) -> bool:
        """
        Uninstall a recipe

        Args:
            name: Recipe name to uninstall

        Returns:
            True if uninstalled successfully
        """
        # Check manifest for installation info
        if name in self.manifest.recipes:
            info = self.manifest.recipes[name]
            # Determine path based on metadata
            if info.recipe_type == "workflow":
                recipe_dir = self.community_dir / "workflows" / name
            else:
                if info.runtime == "chrome-js":
                    recipe_dir = self.community_dir / "atomic" / "chrome" / name
                else:
                    recipe_dir = self.community_dir / "atomic" / "system" / name
        else:
            # Try to find in filesystem
            recipe_dir = self._find_installed_recipe(name)
            if not recipe_dir:
                return False

        if recipe_dir.exists():
            shutil.rmtree(recipe_dir)

        # Remove from manifest
        if name in self.manifest.recipes:
            del self.manifest.recipes[name]
            self._save_manifest()

        return True

    def _find_installed_recipe(self, name: str) -> Optional[Path]:
        """Find recipe directory by name in community-recipes"""
        for subdir in ["atomic/chrome", "atomic/system", "workflows"]:
            path = self.community_dir / subdir / name
            if path.exists():
                return path
        return None

    def update(self, name: str) -> str:
        """
        Update an installed recipe by re-fetching from original source

        Args:
            name: Recipe name to update

        Returns:
            Updated recipe name

        Raises:
            RecipeInstallError: If update fails
        """
        if name not in self.manifest.recipes:
            raise RecipeInstallError(name, "unknown", "Recipe not found in manifest")

        info = self.manifest.recipes[name]

        # Re-install from original source with force
        return self.install(info.source_url, force=True)

    def update_all(self) -> list[tuple[str, bool, str]]:
        """
        Update all installed recipes

        Returns:
            List of (name, success, message) tuples
        """
        results = []
        for name in list(self.manifest.recipes.keys()):
            try:
                self.update(name)
                results.append((name, True, "Updated successfully"))
            except Exception as e:
                results.append((name, False, str(e)))
        return results

    def list_installed(self) -> list[InstalledRecipeInfo]:
        """List all installed recipes from manifest"""
        return list(self.manifest.recipes.values())

    def search_community(self, query: Optional[str] = None) -> list[dict[str, Any]]:
        """
        Search for recipes in community repository

        Args:
            query: Optional search query (filters by name)
                   Supports '|' separated multiple keywords (OR logic)
                   Example: 'twitter|x' matches 'twitter-scraper' or 'x-extractor'

        Returns:
            List of recipe info dictionaries
        """
        rate_manager = self._get_rate_limit_manager()

        # Check if we should skip due to rate limits
        if rate_manager and rate_manager.should_skip_refresh():
            logger.warning("Skipping community search due to rate limit")
            return []

        # Fetch community recipes directory listing
        api_url = (
            f"{self.GITHUB_API_BASE}/repos/{self.COMMUNITY_REPO}"
            f"/contents/{self.COMMUNITY_PATH}?ref={self.COMMUNITY_BRANCH}"
        )

        try:
            response = self._request_with_retry(api_url)
            if response.status_code == 404:
                return []  # Directory doesn't exist yet
            if response.status_code == 403:
                raise RuntimeError("GitHub API rate limit exceeded")
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"GitHub API request failed: {e}") from e

        contents = response.json()
        results = []

        # Parse query keywords (support '|' separated multiple keywords)
        keywords = []
        if query:
            keywords = [k.strip().lower() for k in query.split('|') if k.strip()]

        for item in contents:
            if item["type"] != "dir":
                continue

            name = item["name"]
            # Check if any keyword matches (OR logic)
            if keywords:
                name_lower = name.lower()
                if not any(kw in name_lower for kw in keywords):
                    continue

            # Try to fetch recipe.md for more details
            metadata_url = (
                f"{self.GITHUB_API_BASE}/repos/{self.COMMUNITY_REPO}"
                f"/contents/{self.COMMUNITY_PATH}/{name}/recipe.md"
                f"?ref={self.COMMUNITY_BRANCH}"
            )

            recipe_info: dict[str, Any] = {
                "name": name,
                "url": item["html_url"],
            }

            try:
                # Use retry mechanism for metadata requests
                meta_response = self._request_with_retry(metadata_url, max_retries=2)
                if meta_response.status_code == 200:
                    import base64
                    content = base64.b64decode(
                        meta_response.json()["content"]
                    ).decode('utf-8')

                    # Parse YAML frontmatter
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            import yaml
                            metadata = yaml.safe_load(parts[1])
                            recipe_info.update({
                                "description": metadata.get("description", ""),
                                "version": metadata.get("version", ""),
                                "type": metadata.get("type", ""),
                                "runtime": metadata.get("runtime", ""),
                                "tags": metadata.get("tags", []),
                            })
            except Exception:
                pass  # Continue without detailed metadata

            results.append(recipe_info)

        return results
