"""Environment variables service.

Provides functionality for managing user-level environment variables
stored in ~/.frago/.env file.

Note: The env-vars and recipe-env-requirements API endpoints have been
removed as part of the secrets migration to recipes.local.json.
EnvLoader core class is preserved for other uses (workflow context, etc.).
"""

import logging

logger = logging.getLogger(__name__)


class EnvService:
    """Service for environment variable management.

    Previously provided get_env_vars(), update_env_vars(), and
    get_recipe_env_requirements() methods for the Web UI.
    These have been replaced by RecipeSecretsService.
    """

    pass
