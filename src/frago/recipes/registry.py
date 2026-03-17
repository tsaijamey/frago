"""Recipe registry"""
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .exceptions import RecipeNotFoundError
from .metadata import RecipeMetadata, parse_metadata_file, validate_metadata


# Source priority order (highest to lowest)
SOURCE_PRIORITY = ['User', 'Community', 'Official']

# Module-level singleton for RecipeRegistry
_registry_instance: Optional["RecipeRegistry"] = None
_registry_lock = threading.Lock()


def get_registry() -> "RecipeRegistry":
    """Get or create singleton RecipeRegistry.

    This function provides a cached registry instance that avoids
    re-scanning the filesystem on every call.
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = RecipeRegistry()
                _registry_instance.scan()
    return _registry_instance


def invalidate_registry() -> None:
    """Force re-scan on next access by clearing the singleton."""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None


@dataclass
class Recipe:
    """Recipe entity"""
    metadata: RecipeMetadata
    script_path: Path
    metadata_path: Path
    source: str  # User | Community | Official
    base_dir: Optional[Path] = None  # Recipe root directory (directory-based recipe)

    @property
    def examples_dir(self) -> Optional[Path]:
        """Return examples directory path (if exists)"""
        if self.base_dir:
            examples = self.base_dir / 'examples'
            if examples.exists():
                return examples
        return None

    def list_examples(self) -> list[Path]:
        """List all example files"""
        if self.examples_dir:
            return list(self.examples_dir.glob('*'))
        return []


class RecipeRegistry:
    """Recipe registry, managing all available Recipe indices"""

    def __init__(self):
        self.search_paths: list[Path] = []
        # Nested dictionary: {recipe_name: {source: Recipe}}
        self.recipes: dict[str, dict[str, Recipe]] = {}
        # Track modification times for cache invalidation
        self._last_scan_mtimes: dict[Path, float] = {}
        self._setup_search_paths()

    def _setup_search_paths(self) -> None:
        """Set up search paths for User > Community > Official priority"""
        # 1. User recipes (highest priority)
        user_path = Path.home() / '.frago' / 'recipes'
        if user_path.exists():
            self.search_paths.append(user_path)

        # 2. Community recipes
        community_path = Path.home() / '.frago' / 'community-recipes'
        if community_path.exists():
            self.search_paths.append(community_path)

        # 3. Official recipes (from package resources)
        try:
            from frago.init.resources import get_package_resources_path
            official_path = get_package_resources_path("recipes")
            if official_path.exists():
                self.search_paths.append(official_path)
        except (ImportError, FileNotFoundError, ValueError):
            # Official resources not available
            pass

    def needs_rescan(self) -> bool:
        """Check if any recipe directory or metadata file was modified since last scan.

        Checks top-level search paths, category subdirectories, individual recipe
        directories, AND recipe.md files. On Linux, editing a file's content updates
        the file's mtime but NOT the parent directory's mtime, so we must track
        recipe.md files directly to detect in-place edits.

        Returns:
            True if any path has been modified and needs re-scanning.
        """
        for path in self.search_paths:
            if not path.exists():
                continue
            paths_to_check = [path]
            for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
                sub = path / subdir
                if sub.exists():
                    paths_to_check.append(sub)
                    try:
                        for recipe_dir in sub.iterdir():
                            if recipe_dir.is_dir():
                                paths_to_check.append(recipe_dir)
                                # Track recipe.md file itself
                                metadata_file = recipe_dir / 'recipe.md'
                                if metadata_file.exists():
                                    paths_to_check.append(metadata_file)
                    except OSError:
                        return True
            for p in paths_to_check:
                try:
                    current_mtime = p.stat().st_mtime
                    if p not in self._last_scan_mtimes:
                        return True
                    if current_mtime > self._last_scan_mtimes[p]:
                        return True
                except OSError:
                    return True
        return False

    def scan(self) -> None:
        """Scan all search_paths, parse metadata and build index"""
        self.recipes.clear()
        self._last_scan_mtimes.clear()

        for search_path in self.search_paths:
            # Record mtime for top-level path, subdirectories, and recipe dirs
            if search_path.exists():
                try:
                    self._last_scan_mtimes[search_path] = search_path.stat().st_mtime
                except OSError:
                    pass
                for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
                    sub = search_path / subdir
                    if sub.exists():
                        try:
                            self._last_scan_mtimes[sub] = sub.stat().st_mtime
                        except OSError:
                            pass
                        # Record mtime for each recipe directory
                        # NOTE: recipe.md file mtime is recorded in _register_recipe()
                        # only on successful parse. Failed parses leave no mtime record,
                        # so needs_rescan() will trigger a re-scan next time.
                        try:
                            for recipe_dir in sub.iterdir():
                                if recipe_dir.is_dir():
                                    try:
                                        self._last_scan_mtimes[recipe_dir] = recipe_dir.stat().st_mtime
                                    except OSError:
                                        pass
                        except OSError:
                            pass
            source = self._get_source_label(search_path)
            self._scan_directory(search_path, source)

        # Validate Workflow dependencies
        self._validate_dependencies()

    def _get_source_label(self, path: Path) -> str:
        """Return source label based on path"""
        path_str = str(path)
        if 'community-recipes' in path_str:
            return 'Community'
        elif '.frago/recipes' in path_str or '.frago\\recipes' in path_str:
            return 'User'
        else:
            return 'Official'

    def _scan_directory(self, base_path: Path, source: str) -> None:
        """Recursively scan directory, find Recipes (directory-based)"""
        # Scan subdirectories: atomic/chrome/, atomic/system/, workflows/
        for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
            dir_path = base_path / subdir
            if not dir_path.exists():
                continue

            # Find all recipe directories (directories containing recipe.md)
            for recipe_dir in dir_path.iterdir():
                if recipe_dir.is_dir():
                    metadata_path = recipe_dir / 'recipe.md'
                    if metadata_path.exists():
                        self._register_recipe(metadata_path, source, recipe_dir)

    def _register_recipe(self, metadata_path: Path, source: str, base_dir: Path) -> None:
        """Register a single Recipe (directory-based)"""
        try:
            # Parse metadata
            metadata = parse_metadata_file(metadata_path)

            # Validate metadata
            validate_metadata(metadata)

            # Find corresponding script file (search for recipe.py/js/sh in recipe directory)
            script_path = self._find_script_file(base_dir, metadata.runtime)
            if not script_path:
                # Script file does not exist, skip
                return

            # Create Recipe object
            recipe = Recipe(
                metadata=metadata,
                script_path=script_path,
                metadata_path=metadata_path,
                source=source,
                base_dir=base_dir
            )

            # Initialize dictionary for recipe name (if not exists)
            if metadata.name not in self.recipes:
                self.recipes[metadata.name] = {}

            # Store by source (same-name recipes under the same source still override)
            self.recipes[metadata.name][source] = recipe

            # Record recipe.md mtime only after successful registration.
            # If parse/validation failed, we intentionally skip this so that
            # needs_rescan() detects the unrecorded file and triggers re-scan.
            try:
                self._last_scan_mtimes[metadata_path] = metadata_path.stat().st_mtime
            except OSError:
                pass

        except Exception:
            # Parse or validation failed, skip this Recipe.
            # recipe.md mtime is NOT recorded, so next needs_rescan() will retry.
            pass

    def _find_script_file(self, recipe_dir: Path, runtime: str) -> Optional[Path]:
        """Find script file in recipe directory based on runtime type"""
        # Determine extension based on runtime
        extensions = {
            'chrome-js': ['.js'],
            'python': ['.py'],
            'shell': ['.sh']
        }

        for ext in extensions.get(runtime, []):
            script_path = recipe_dir / f"recipe{ext}"
            if script_path.exists():
                return script_path

        return None
    
    def find(self, name: str, source: Optional[str] = None) -> Recipe:
        """
        Find Recipe by specified name

        Args:
            name: Recipe name
            source: Specify source ('user' | 'community' | 'official'), return by priority when None

        Returns:
            Recipe object

        Raises:
            RecipeNotFoundError: Raised when Recipe does not exist
        """
        searched_paths = [str(p) for p in self.search_paths]

        if name not in self.recipes:
            raise RecipeNotFoundError(name, searched_paths)

        sources_dict = self.recipes[name]

        if source:
            # Find by specified source
            source_label = source.capitalize()
            if source_label not in sources_dict:
                raise RecipeNotFoundError(f"{name} (source: {source})", searched_paths)
            return sources_dict[source_label]

        # Source not specified: return by priority (User > Community > Official)
        for priority_source in SOURCE_PRIORITY:
            if priority_source in sources_dict:
                return sources_dict[priority_source]

        # Should not reach here in theory, since sources_dict is not empty
        raise RecipeNotFoundError(name, searched_paths)

    def list_all(self, include_all_sources: bool = False) -> list[Recipe]:
        """
        List all Recipes

        Args:
            include_all_sources: Whether to include recipes from all sources (default only returns highest priority)

        Returns:
            Recipe list (sorted by name)
        """
        result = []
        for name, sources_dict in self.recipes.items():
            if include_all_sources:
                # Return recipes from all sources
                result.extend(sources_dict.values())
            else:
                # Return highest priority version (User > Community > Official)
                for priority_source in SOURCE_PRIORITY:
                    if priority_source in sources_dict:
                        result.append(sources_dict[priority_source])
                        break
        return sorted(result, key=lambda r: r.metadata.name)

    def get_by_source(self, source: str) -> list[Recipe]:
        """
        Filter Recipes by source

        Args:
            source: Source label (User | Community | Official)

        Returns:
            Recipe list matching the source (sorted by name)
        """
        source_label = source.capitalize()
        result = []
        for sources_dict in self.recipes.values():
            if source_label in sources_dict:
                result.append(sources_dict[source_label])
        return sorted(result, key=lambda r: r.metadata.name)

    def _validate_dependencies(self) -> None:
        """
        Validate if all Workflow Recipe dependencies exist

        If a Workflow declares dependencies, check if these dependent Recipes are registered.
        Recipes with missing dependencies will be removed from the registry and warnings logged.
        """
        # Collect recipes to be removed: [(recipe_name, source), ...]
        invalid_recipes = []

        for name, sources_dict in self.recipes.items():
            for source, recipe in sources_dict.items():
                # Only check Workflow type Recipes
                if recipe.metadata.type != 'workflow':
                    continue

                # Check dependency list
                dependencies = recipe.metadata.dependencies or []
                missing_deps = []

                for dep_name in dependencies:
                    # Dependency exists as long as it's in any source
                    if dep_name not in self.recipes:
                        missing_deps.append(dep_name)

                if missing_deps:
                    # Record Recipes with missing dependencies
                    invalid_recipes.append((name, source, missing_deps))

        # Remove Recipes with missing dependencies
        for recipe_name, source, missing_deps in invalid_recipes:
            del self.recipes[recipe_name][source]
            # If no more sources under this recipe name, delete the entire entry
            if not self.recipes[recipe_name]:
                del self.recipes[recipe_name]
            # Can add logging here, but to keep it simple, we just silently remove
            # print(f"Warning: Recipe '{recipe_name}' ({source}) has missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)

    def exact_match(self, text: str) -> str | None:
        """Try to match input text against registered recipes.

        Matching layers (in order):
        1. Exact recipe name in text (e.g. "run poll-gmail")
        2. use_cases keyword match
        3. tags keyword match

        Returns the recipe name if matched, None otherwise.
        When multiple recipes match, selects by source priority (User > Community > Official).
        """
        text_lower = text.lower().strip()

        # Layer 1: exact name match — check if any recipe name appears in text
        for name in self.recipes:
            if name.lower() in text_lower:
                return name

        # Layer 2: use_cases match — check if any use_case phrase appears in text
        best_match: str | None = None
        best_score = 0
        for recipe_name, sources_dict in self.recipes.items():
            # Pick highest-priority source version
            recipe = None
            for src in SOURCE_PRIORITY:
                if src in sources_dict:
                    recipe = sources_dict[src]
                    break
            if recipe is None:
                continue

            score = 0
            for use_case in recipe.metadata.use_cases:
                uc_lower = use_case.lower()
                if uc_lower in text_lower or text_lower in uc_lower:
                    score += 2
                else:
                    # Check individual words overlap
                    uc_words = set(uc_lower.split())
                    text_words = set(text_lower.split())
                    overlap = uc_words & text_words
                    if len(overlap) >= 2:
                        score += 1

            for tag in recipe.metadata.tags:
                if tag.lower() in text_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = recipe_name

        # Only return if we have a meaningful match (score >= 2)
        if best_score >= 2:
            return best_match

        return None

    def find_all_sources(self, name: str) -> list[tuple[str, Path]]:
        """
        Find if same-name Recipe exists in all sources

        Args:
            name: Recipe name

        Returns:
            [(source, recipe_dir), ...] list, sorted by priority (User > Community > Official)
        """
        if name not in self.recipes:
            return []

        # Return all sources in priority order
        result = []
        sources_dict = self.recipes[name]
        for priority_source in SOURCE_PRIORITY:
            if priority_source in sources_dict:
                recipe = sources_dict[priority_source]
                result.append((priority_source, recipe.base_dir))
        return result
