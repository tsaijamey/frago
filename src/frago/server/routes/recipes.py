"""Recipe API endpoints.

Provides endpoints for listing, viewing, and executing recipes.
"""

from typing import List

from fastapi import APIRouter, HTTPException

from frago.server.models import (
    RecipeItemResponse,
    RecipeDetailResponse,
    RecipeInputSchema,
    RecipeOutputSchema,
    RecipeRunRequest,
    TaskItemResponse,
    CommunityRecipeItemResponse,
    CommunityRecipeInstallRequest,
    CommunityRecipeInstallResponse,
)
from frago.server.services.cache_service import CacheService
from frago.server.services.recipe_service import RecipeService

router = APIRouter()


@router.get("/recipes", response_model=List[RecipeItemResponse])
async def list_recipes() -> List[RecipeItemResponse]:
    """List all available recipes.

    Returns a list of all recipes from both atomic and workflow categories.
    Uses cache for fast response when available.
    """
    # Use cache if available
    cache = CacheService.get_instance()
    if cache.is_initialized():
        recipes = await cache.get_recipes()
    else:
        recipes = RecipeService.get_recipes()

    return [
        RecipeItemResponse(
            name=r.get("name", ""),
            description=r.get("description"),
            category=r.get("category", "atomic"),
            icon=r.get("icon"),
            tags=r.get("tags", []),
            path=r.get("path"),
            source=r.get("source"),
            runtime=r.get("runtime"),
        )
        for r in recipes
    ]


@router.get("/recipes/{name}", response_model=RecipeDetailResponse)
async def get_recipe(name: str) -> RecipeDetailResponse:
    """Get recipe details by name.

    Args:
        name: Recipe name

    Returns:
        Recipe details including rich metadata

    Raises:
        HTTPException: 404 if recipe not found
    """
    recipe = RecipeService.get_recipe(name)

    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    # Parse inputs
    inputs = {}
    raw_inputs = recipe.get("inputs", {})
    if isinstance(raw_inputs, dict):
        for k, v in raw_inputs.items():
            if isinstance(v, dict):
                inputs[k] = RecipeInputSchema(
                    type=v.get("type", "string"),
                    required=v.get("required", False),
                    default=v.get("default"),
                    description=v.get("description"),
                )

    # Parse outputs
    outputs = {}
    raw_outputs = recipe.get("outputs", {})
    if isinstance(raw_outputs, dict):
        for k, v in raw_outputs.items():
            if isinstance(v, dict):
                outputs[k] = RecipeOutputSchema(
                    type=v.get("type", "string"),
                    description=v.get("description"),
                )

    return RecipeDetailResponse(
        name=recipe.get("name", name),
        description=recipe.get("description"),
        category=recipe.get("type") or recipe.get("category") or "atomic",
        icon=recipe.get("icon"),
        tags=recipe.get("tags", []),
        path=recipe.get("path") or recipe.get("script_path"),
        source=recipe.get("source"),
        runtime=recipe.get("runtime"),
        # Rich metadata
        version=recipe.get("version"),
        base_dir=recipe.get("base_dir"),
        script_path=recipe.get("script_path"),
        metadata_path=recipe.get("metadata_path"),
        use_cases=recipe.get("use_cases", []),
        output_targets=recipe.get("output_targets", []),
        inputs=inputs,
        outputs=outputs,
        dependencies=recipe.get("dependencies", []),
        env=recipe.get("env", {}),
        source_code=recipe.get("source_code"),
    )


@router.post("/recipes/{name}/run", response_model=TaskItemResponse)
async def run_recipe(name: str, request: RecipeRunRequest = None) -> TaskItemResponse:
    """Execute a recipe.

    Args:
        name: Recipe name
        request: Optional execution parameters

    Returns:
        Started task information

    Raises:
        HTTPException: 404 if recipe not found
    """
    import uuid
    from datetime import datetime, timezone

    # Verify recipe exists
    recipe = RecipeService.get_recipe(name)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    # Execute recipe
    params = request.params if request else None
    timeout = request.timeout if request else 300

    result = RecipeService.run_recipe(name, params, timeout)

    # Check for error
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Return task information
    return TaskItemResponse(
        id=str(uuid.uuid4()),
        title=f"Recipe: {name}",
        status="completed" if result.get("status") == "ok" else "error",
        project_path=None,
        agent_type="recipe",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_ms=result.get("duration_ms"),
    )


# ============================================================
# Community Recipe Endpoints
# ============================================================


@router.get("/community-recipes", response_model=List[CommunityRecipeItemResponse])
async def list_community_recipes() -> List[CommunityRecipeItemResponse]:
    """List all community recipes with installation status.

    Returns:
        List of community recipes with installed/update status
    """
    import asyncio
    from frago.server.services.community_recipe_service import CommunityRecipeService

    service = CommunityRecipeService.get_instance()
    recipes = await service.get_recipes()

    return [
        CommunityRecipeItemResponse(
            name=r.get("name", ""),
            url=r.get("url", ""),
            description=r.get("description"),
            version=r.get("version"),
            type=r.get("type", "atomic"),
            runtime=r.get("runtime"),
            tags=r.get("tags", []),
            installed=r.get("installed", False),
            installed_version=r.get("installed_version"),
            has_update=r.get("has_update", False),
        )
        for r in recipes
    ]


@router.get(
    "/community-recipes/{name}",
    response_model=CommunityRecipeItemResponse
)
async def get_community_recipe(name: str) -> CommunityRecipeItemResponse:
    """Get specific community recipe details.

    Args:
        name: Recipe name

    Returns:
        Community recipe details

    Raises:
        HTTPException: 404 if recipe not found
    """
    from frago.server.services.community_recipe_service import CommunityRecipeService

    service = CommunityRecipeService.get_instance()
    recipes = await service.get_recipes()

    for recipe in recipes:
        if recipe.get("name") == name:
            return CommunityRecipeItemResponse(
                name=recipe.get("name", ""),
                url=recipe.get("url", ""),
                description=recipe.get("description"),
                version=recipe.get("version"),
                type=recipe.get("type", "atomic"),
                runtime=recipe.get("runtime"),
                tags=recipe.get("tags", []),
                installed=recipe.get("installed", False),
                installed_version=recipe.get("installed_version"),
                has_update=recipe.get("has_update", False),
            )

    raise HTTPException(
        status_code=404,
        detail=f"Community recipe '{name}' not found"
    )


@router.post(
    "/community-recipes/{name}/install",
    response_model=CommunityRecipeInstallResponse
)
async def install_community_recipe(
    name: str,
    request: CommunityRecipeInstallRequest = None
) -> CommunityRecipeInstallResponse:
    """Install a community recipe.

    Args:
        name: Recipe name to install
        request: Optional install options (force overwrite)

    Returns:
        Installation result
    """
    import asyncio
    from frago.server.services.community_recipe_service import CommunityRecipeService

    service = CommunityRecipeService.get_instance()
    force = request.force if request else False

    # Run in thread pool (blocking I/O)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: service.install_recipe(name, force)
    )

    # Trigger local recipe cache refresh after install
    cache = CacheService.get_instance()
    await cache.refresh_recipes(broadcast=True)

    # Trigger community recipes refresh to update install status
    await service._do_refresh()

    return CommunityRecipeInstallResponse(
        status=result.get("status", "error"),
        recipe_name=result.get("recipe_name"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.post(
    "/community-recipes/{name}/update",
    response_model=CommunityRecipeInstallResponse
)
async def update_community_recipe(name: str) -> CommunityRecipeInstallResponse:
    """Update an installed community recipe.

    Args:
        name: Recipe name to update

    Returns:
        Update result
    """
    import asyncio
    from frago.server.services.community_recipe_service import CommunityRecipeService

    service = CommunityRecipeService.get_instance()

    # Run in thread pool (blocking I/O)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: service.update_recipe(name)
    )

    # Trigger local recipe cache refresh after update
    cache = CacheService.get_instance()
    await cache.refresh_recipes(broadcast=True)

    # Trigger community recipes refresh to update status
    await service._do_refresh()

    return CommunityRecipeInstallResponse(
        status=result.get("status", "error"),
        recipe_name=result.get("recipe_name"),
        message=result.get("message"),
        error=result.get("error"),
    )
