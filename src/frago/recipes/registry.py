"""Recipe registry"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .exceptions import RecipeNotFoundError
from .metadata import RecipeMetadata, parse_metadata_file, validate_metadata


@dataclass
class Recipe:
    """Recipe entity"""
    metadata: RecipeMetadata
    script_path: Path
    metadata_path: Path
    source: str  # Project | User | Example
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
        self._setup_search_paths()

    def _setup_search_paths(self) -> None:
        """Set up search paths - unified to use ~/.frago/recipes/"""
        # Only use user directory
        user_path = Path.home() / '.frago' / 'recipes'
        if user_path.exists():
            self.search_paths.append(user_path)

    def scan(self) -> None:
        """Scan all search_paths, parse metadata and build index"""
        self.recipes.clear()

        for search_path in self.search_paths:
            source = self._get_source_label(search_path)
            self._scan_directory(search_path, source)

        # Validate Workflow dependencies
        self._validate_dependencies()

    def _get_source_label(self, path: Path) -> str:
        """Return source label based on path"""
        # Unified to use user directory
        return 'User'

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

        except Exception:
            # Parse or validation failed, skip this Recipe (silently)
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
            source: Specify source ('project' | 'user' | 'example'), return by priority when None

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

        # Source not specified: return User source
        if 'User' in sources_dict:
            return sources_dict['User']

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
                # Return User source
                if 'User' in sources_dict:
                    result.append(sources_dict['User'])
        return sorted(result, key=lambda r: r.metadata.name)

    def get_by_source(self, source: str) -> list[Recipe]:
        """
        Filter Recipes by source

        Args:
            source: Source label (Project | User | Example)

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

    def find_all_sources(self, name: str) -> list[tuple[str, Path]]:
        """
        Find if same-name Recipe exists in all sources

        Args:
            name: Recipe name

        Returns:
            [(source, recipe_dir), ...] list, sorted by priority
        """
        if name not in self.recipes:
            return []

        # Return User source
        result = []
        if 'User' in self.recipes[name]:
            recipe = self.recipes[name]['User']
            result.append(('User', recipe.base_dir))
        return result
