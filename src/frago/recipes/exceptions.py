"""Recipe system specific exception classes"""


class RecipeError(Exception):
    """Recipe base exception class"""
    pass


class RecipeNotFoundError(RecipeError):
    """Recipe not found exception"""
    def __init__(self, name: str, searched_paths: list[str] | None = None):
        self.name = name
        self.searched_paths = searched_paths or []
        message = f"Recipe '{name}' not found"
        if self.searched_paths:
            paths_str = '\n  - '.join(self.searched_paths)
            message += f"\n\nSearched paths:\n  - {paths_str}"
        super().__init__(message)


class RecipeExecutionError(RecipeError):
    """Recipe execution failed exception"""
    def __init__(
        self,
        recipe_name: str,
        runtime: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ):
        self.recipe_name = recipe_name
        self.runtime = runtime
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        message = f"Recipe '{recipe_name}' execution failed (exit code: {exit_code})"
        if stderr:
            message += f"\nError: {stderr[:200]}"
        super().__init__(message)


class RecipeValidationError(RecipeError):
    """Recipe validation failed exception"""
    def __init__(self, recipe_name: str, errors: list[str]):
        self.recipe_name = recipe_name
        self.errors = errors
        errors_str = '\n  - '.join(errors)
        message = f"Recipe '{recipe_name}' validation failed:\n  - {errors_str}"
        super().__init__(message)


class MetadataParseError(RecipeError):
    """Metadata parsing failed exception"""
    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        message = f"Metadata file parsing failed: {file_path}\nReason: {reason}"
        super().__init__(message)


class RecipeInstallError(RecipeError):
    """Recipe installation failed exception"""
    def __init__(self, recipe_name: str, source: str, reason: str):
        self.recipe_name = recipe_name
        self.source = source
        self.reason = reason
        message = f"Failed to install recipe '{recipe_name}' from {source}: {reason}"
        super().__init__(message)


class RecipeAlreadyExistsError(RecipeError):
    """Recipe already exists exception"""
    def __init__(self, recipe_name: str, existing_path: str):
        self.recipe_name = recipe_name
        self.existing_path = existing_path
        message = (
            f"Recipe '{recipe_name}' already exists at {existing_path}\n"
            "Use --force to overwrite"
        )
        super().__init__(message)
