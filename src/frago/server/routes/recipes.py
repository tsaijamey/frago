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
    RecipeFlowStep,
    RecipeRunRequest,
    TaskItemResponse,
    CommunityRecipeItemResponse,
    CommunityRecipeInstallRequest,
    CommunityRecipeInstallResponse,
)
from frago.server.state import StateManager
from frago.server.services.recipe_service import RecipeService

router = APIRouter()


@router.get("/recipes", response_model=List[RecipeItemResponse])
async def list_recipes() -> List[RecipeItemResponse]:
    """List all available recipes.

    Returns a list of all recipes from both atomic and workflow categories.
    Checks registry for disk changes on each request to pick up new recipes.
    """
    state_manager = StateManager.get_instance()

    if state_manager.is_initialized():
        # Check if recipe directories changed since last StateManager load
        try:
            from frago.recipes.registry import get_registry
            registry = get_registry()
            if registry.needs_rescan():
                from frago.recipes.registry import invalidate_registry
                invalidate_registry()
                await state_manager.refresh_recipes(broadcast=True)
        except Exception:
            pass

        recipes = state_manager.get_recipes()
        return [
            RecipeItemResponse(
                name=r.name,
                description=r.description,
                category=r.category,
                icon=r.icon,
                tags=r.tags,
                path=r.path,
                source=r.source,
                runtime=r.runtime,
            )
            for r in recipes
        ]

    # Fallback to direct service call
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

    # Parse flow (for workflows)
    flow = []
    raw_flow = recipe.get("flow", [])
    if isinstance(raw_flow, list):
        for step in raw_flow:
            if isinstance(step, dict):
                flow.append(RecipeFlowStep(
                    step=step.get("step", 0),
                    action=step.get("action", ""),
                    description=step.get("description", ""),
                    recipe=step.get("recipe"),
                    inputs=step.get("inputs", []),
                    outputs=step.get("outputs", []),
                ))

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
        flow=flow,
    )


@router.post("/recipes/{name}/run")
async def run_recipe(name: str, request: RecipeRunRequest = None):
    """Execute a recipe synchronously.

    Args:
        name: Recipe name
        request: Optional execution parameters

    Returns:
        Recipe output (JSON parsed if valid) or task information

    Raises:
        HTTPException: 404 if recipe not found
    """
    # Verify recipe exists
    recipe = RecipeService.get_recipe(name)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    import asyncio

    params = request.params if request else None
    timeout = request.timeout if request else 300

    # Run in thread pool to avoid blocking the event loop
    result = await asyncio.to_thread(
        RecipeService.run_recipe, name, params, timeout
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Record usage for dashboard Quick Recipes
    try:
        from frago.recipes.usage_tracker import record_usage
        record_usage(name)
    except Exception:
        pass

    return {
        "success": True,
        "data": result.get("data"),
        "duration_ms": result.get("duration_ms"),
        "execution_id": result.get("execution_id"),
    }


@router.post("/recipes/{name}/run-async")
async def run_recipe_async(name: str, request: RecipeRunRequest = None):
    """Execute a recipe asynchronously, return execution_id immediately.

    Client polls GET /api/executions/{id} for status updates.

    Args:
        name: Recipe name
        request: Optional execution parameters

    Returns:
        execution_id, status, and poll URL

    Raises:
        HTTPException: 404 if recipe not found, 400 on validation error
    """
    recipe = RecipeService.get_recipe(name)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    params = request.params if request else None
    timeout = request.timeout if request else 300

    try:
        execution_id = RecipeService.run_recipe_async(name, params, timeout)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Record usage
    try:
        from frago.recipes.usage_tracker import record_usage
        record_usage(name)
    except Exception:
        pass

    return {
        "execution_id": execution_id,
        "status": "pending",
        "poll_url": f"/api/executions/{execution_id}",
    }


# ============================================================
# Execution Endpoints
# ============================================================


@router.get("/executions")
async def list_executions(
    recipe_name: str = None,
    limit: int = 20,
    status: str = None,
    workflow_id: str = None,
):
    """List recent execution records.

    Args:
        recipe_name: Filter by recipe name
        limit: Max results (default 20)
        status: Filter by status (pending/running/succeeded/failed/timeout/cancelled)
        workflow_id: Filter by parent workflow execution ID

    Returns:
        List of execution records
    """
    if workflow_id:
        return RecipeService.list_workflow_executions(workflow_id)
    executions = RecipeService.list_executions(
        recipe_name=recipe_name,
        limit=limit,
        status=status,
    )
    return executions


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str):
    """Cancel a running execution.

    Args:
        execution_id: Execution ID

    Returns:
        Cancel result with status and message
    """
    result = RecipeService.cancel_execution(execution_id)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    """Get a single execution by ID.

    Args:
        execution_id: Execution ID

    Returns:
        Execution record

    Raises:
        HTTPException: 404 if not found
    """
    execution = RecipeService.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return execution


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
    state_manager = StateManager.get_instance()
    await state_manager.refresh_recipes(broadcast=True)

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
    state_manager = StateManager.get_instance()
    await state_manager.refresh_recipes(broadcast=True)

    # Trigger community recipes refresh to update status
    await service._do_refresh()

    return CommunityRecipeInstallResponse(
        status=result.get("status", "error"),
        recipe_name=result.get("recipe_name"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.post(
    "/community-recipes/{name}/uninstall",
    response_model=CommunityRecipeInstallResponse
)
async def uninstall_community_recipe(name: str) -> CommunityRecipeInstallResponse:
    """Uninstall an installed community recipe.

    Args:
        name: Recipe name to uninstall

    Returns:
        Uninstall result
    """
    import asyncio
    from frago.server.services.community_recipe_service import CommunityRecipeService

    service = CommunityRecipeService.get_instance()

    # Run in thread pool (blocking I/O)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: service.uninstall_recipe(name)
    )

    # Trigger local recipe cache refresh after uninstall
    state_manager = StateManager.get_instance()
    await state_manager.refresh_recipes(broadcast=True)

    # Trigger community recipes refresh to update status
    await service._do_refresh()

    return CommunityRecipeInstallResponse(
        status=result.get("status", "error"),
        recipe_name=result.get("recipe_name"),
        message=result.get("message"),
        error=result.get("error"),
    )
