"""Recipe API endpoints.

Provides endpoints for listing, viewing, and executing recipes.
"""

from typing import List

from fastapi import APIRouter, HTTPException

from frago.server.adapter import FragoApiAdapter
from frago.server.models import (
    RecipeItemResponse,
    RecipeRunRequest,
    TaskItemResponse,
)

router = APIRouter()


@router.get("/recipes", response_model=List[RecipeItemResponse])
async def list_recipes() -> List[RecipeItemResponse]:
    """List all available recipes.

    Returns a list of all recipes from both atomic and workflow categories.
    """
    adapter = FragoApiAdapter.get_instance()
    recipes = adapter.get_recipes()

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


@router.get("/recipes/{name}", response_model=RecipeItemResponse)
async def get_recipe(name: str) -> RecipeItemResponse:
    """Get recipe details by name.

    Args:
        name: Recipe name

    Returns:
        Recipe details including source code

    Raises:
        HTTPException: 404 if recipe not found
    """
    adapter = FragoApiAdapter.get_instance()
    recipe = adapter.get_recipe(name)

    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    return RecipeItemResponse(
        name=recipe.get("name", name),
        description=recipe.get("description"),
        category=recipe.get("category", "atomic"),
        icon=recipe.get("icon"),
        tags=recipe.get("tags", []),
        path=recipe.get("path"),
        source=recipe.get("source"),
        runtime=recipe.get("runtime"),
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
    from datetime import datetime, timezone

    adapter = FragoApiAdapter.get_instance()

    # Verify recipe exists
    recipe = adapter.get_recipe(name)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    # Execute recipe
    params = request.params if request else None
    timeout = request.timeout if request else None

    result = adapter.run_recipe(name, params, timeout)

    # Check for error
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Return task information
    return TaskItemResponse(
        id=result.get("id", ""),
        title=result.get("title", f"Recipe: {name}"),
        status=result.get("status", "running"),
        project_path=result.get("project_path"),
        agent_type=result.get("agent_type", "recipe"),
        started_at=datetime.fromisoformat(result.get("started_at", datetime.now(timezone.utc).isoformat())),
        completed_at=None,
        duration_ms=None,
    )
