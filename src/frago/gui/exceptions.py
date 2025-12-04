"""GUI exceptions for Frago."""


class GuiApiError(Exception):
    """Base exception for GUI API errors."""

    pass


class TaskAlreadyRunningError(GuiApiError):
    """Raised when attempting to start a task while another is running."""

    def __init__(self, task_id: str = ""):
        self.task_id = task_id
        message = "A task is already running"
        if task_id:
            message += f" (task_id: {task_id})"
        super().__init__(message)


class RecipeNotFoundError(GuiApiError):
    """Raised when a recipe is not found."""

    def __init__(self, recipe_name: str):
        self.recipe_name = recipe_name
        super().__init__(f"Recipe not found: {recipe_name}")


class ConfigValidationError(GuiApiError):
    """Raised when configuration validation fails."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(f"Configuration validation failed: {', '.join(errors)}")


class GuiNotAvailableError(GuiApiError):
    """Raised when GUI cannot be started (headless environment)."""

    def __init__(self, reason: str = ""):
        message = "GUI is not available in this environment"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class SkillNotFoundError(GuiApiError):
    """Raised when a skill is not found."""

    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        super().__init__(f"Skill not found: {skill_name}")
