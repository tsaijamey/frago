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
)
from frago.server.services.recipe_service import RecipeService

router = APIRouter()


@router.get("/recipes", response_model=List[RecipeItemResponse])
async def list_recipes() -> List[RecipeItemResponse]:
    """List all available recipes.

    Returns a list of all recipes from both atomic and workflow categories.
    """
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
