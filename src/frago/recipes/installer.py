"""Recipe installation and management module"""
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import requests

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
        """Get HTTP headers, including GitHub token if available"""
        import os
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "frago-recipe-installer",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

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
        # Fetch community recipes directory listing
        api_url = (
            f"{self.GITHUB_API_BASE}/repos/{self.COMMUNITY_REPO}"
            f"/contents/{self.COMMUNITY_PATH}?ref={self.COMMUNITY_BRANCH}"
        )

        try:
            response = requests.get(
                api_url,
                headers=self._get_headers(),
                timeout=self.REQUEST_TIMEOUT
            )
            if response.status_code == 404:
                return []  # Directory doesn't exist yet
            response.raise_for_status()
        except requests.RequestException:
            return []

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
                meta_response = requests.get(
                    metadata_url,
                    headers=self._get_headers(),
                    timeout=self.REQUEST_TIMEOUT
                )
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
