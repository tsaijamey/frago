"""FastAPI application factory for Frago Web Service.

Creates and configures the FastAPI application with:
- CORS middleware for local development
- Static file serving for frontend assets
- API routers for all endpoints
- WebSocket endpoint for real-time updates
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from frago.server.routes import (
    system_router,
    recipes_router,
    tasks_router,
    agent_router,
    config_router,
    skills_router,
    settings_router,
)
from frago.server.websocket import manager, MessageType, create_message


def get_frontend_path() -> Path:
    """Get the path to frontend build assets.

    Returns:
        Path to the frontend dist directory
    """
    # Look for built assets in gui/assets (packaged) or gui/frontend/dist (dev)
    gui_dir = Path(__file__).parent.parent / "gui"

    # Check for packaged assets first
    assets_dir = gui_dir / "assets"
    if assets_dir.exists() and (assets_dir / "index.html").exists():
        return assets_dir

    # Fall back to frontend build output
    frontend_dist = gui_dir / "frontend" / "dist"
    if frontend_dist.exists():
        return frontend_dist

    # Return assets dir even if it doesn't exist (will be created during build)
    return assets_dir


def create_app(
    title: str = "Frago Web Service",
    version: Optional[str] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        title: Application title for OpenAPI docs
        version: Application version (defaults to frago version)

    Returns:
        Configured FastAPI application
    """
    # Get version from package if not provided
    if version is None:
        try:
            from frago import __version__

            version = __version__
        except ImportError:
            version = "0.0.0"

    app = FastAPI(
        title=title,
        version=version,
        description="Local web service for Frago GUI",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Configure CORS for local development
    # Allow localhost origins on common ports for security
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8093",
            "http://127.0.0.1:8093",
            "http://localhost:3000",  # Vite dev server
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global error handler for consistent API error responses
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all uncaught exceptions with a consistent JSON response."""
        import logging
        import traceback

        logger = logging.getLogger(__name__)
        logger.error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")

        # Return JSON error for API routes, let others pass through
        if request.url.path.startswith("/api"):
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "detail": str(exc) if app.debug else "An unexpected error occurred",
                },
            )
        raise exc

    # Include API routers
    app.include_router(system_router, prefix="/api", tags=["system"])
    app.include_router(recipes_router, prefix="/api", tags=["recipes"])
    app.include_router(tasks_router, prefix="/api", tags=["tasks"])
    app.include_router(agent_router, prefix="/api", tags=["agent"])
    app.include_router(config_router, prefix="/api", tags=["config"])
    app.include_router(skills_router, prefix="/api", tags=["skills"])
    app.include_router(settings_router, prefix="/api", tags=["settings"])

    # WebSocket endpoint for real-time updates
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates.

        Clients connect here to receive:
        - Task status updates
        - Session sync events
        - Log streaming
        """
        await manager.connect(websocket)
        try:
            # Send welcome message
            await manager.send_personal(
                websocket,
                create_message(
                    MessageType.CONNECTED,
                    {"message": "Connected to Frago Web Service"},
                ),
            )

            # Keep connection alive and handle incoming messages
            while True:
                data = await websocket.receive_text()
                # Handle ping/pong for keepalive
                try:
                    import json
                    msg = json.loads(data)
                    if msg.get("type") == MessageType.PING:
                        await manager.send_personal(
                            websocket,
                            create_message(MessageType.PONG),
                        )
                except (json.JSONDecodeError, KeyError):
                    pass
        except WebSocketDisconnect:
            await manager.disconnect(websocket)

    # Mount static files for frontend
    frontend_path = get_frontend_path()
    if frontend_path.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(frontend_path / "assets") if (frontend_path / "assets").exists() else str(frontend_path)),
            name="assets",
        )

    # SPA fallback: serve index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes.

        This enables client-side routing by serving index.html
        for any path that doesn't match an API route.
        """
        # Don't serve SPA for API routes (they should 404 naturally)
        if full_path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="API endpoint not found")

        # Serve index.html for SPA routing
        index_path = frontend_path / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))

        # Return a helpful message if frontend not built
        from fastapi.responses import HTMLResponse

        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head><title>Frago - Frontend Not Built</title></head>
            <body style="font-family: system-ui; padding: 2rem; background: #1a1a1a; color: #fff;">
                <h1>Frontend assets not found</h1>
                <p>Please build the frontend first:</p>
                <pre style="background: #333; padding: 1rem; border-radius: 4px;">
cd src/frago/gui/frontend
pnpm install
pnpm build
                </pre>
                <p>Then restart <code>frago serve</code></p>
            </body>
            </html>
            """,
            status_code=503,
        )

    return app
