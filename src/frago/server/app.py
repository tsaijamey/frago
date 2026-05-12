"""FastAPI application factory for Frago Web Service.

Creates and configures the FastAPI application with:
- CORS middleware for local development
- Static file serving for frontend assets
- API routers for all endpoints
- WebSocket endpoint for real-time updates
- Background session synchronization
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from frago.server.routes import (
    agent_router,
    chrome_dashboard_router,
    config_router,
    dashboard_router,
    files_router,
    guide_router,
    init_router,
    recipes_router,
    settings_router,
    skills_router,
    sync_router,
    system_router,
    tasks_router,
    viewer_router,
    workspace_router,
)
from frago.server.services.community_recipe_service import CommunityRecipeService
from frago.server.services.github_sync_scheduler import GitHubSyncScheduler
from frago.server.services.scheduler_service import SchedulerService
from frago.server.services.sessions_watcher import SessionsWatcher
from frago.server.services.sync_service import SyncService
from frago.server.services.version_service import VersionCheckService
from frago.server.state import StateManager
from frago.server.websocket import MessageType, create_message, manager


def _wire_timeline_broadcast(register_hook) -> None:
    """Install hook that bridges new trace_entry writes → WS timeline_event.

    The hook humanizes the raw timeline entry into the same TimelineEvent
    shape the frontend (useTimeline.ts) already consumes. Legacy PA event
    types are skipped here because `PrimaryAgentService._broadcast_pa_event`
    already emits them on the same WS channel — double-broadcasting would
    cause duplicate renders (entries have different ids).
    """
    import asyncio

    # Types already broadcast by PrimaryAgentService._broadcast_pa_event
    _LEGACY_BROADCAST_TYPES = frozenset({
        "pa_ingestion", "pa_decision",
        "pa_agent_launched", "pa_agent_exited", "pa_reply",
    })

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    def _build_frontend_event(entry: dict) -> dict | None:
        """Humanize a raw timeline entry into the TimelineEvent shape.

        Returns None if this entry is already covered by the legacy PA broadcast
        path (to avoid duplicates).
        """
        data = entry.get("data") or {}
        legacy_event_type = data.get("event_type")
        if legacy_event_type in _LEGACY_BROADCAST_TYPES:
            return None

        from frago.server.services.timeline_service import humanize_event

        # For entries with data_type alone (no legacy event_type), synthesize
        # a reasonable title/subtitle from data_type + event + subkind
        if legacy_event_type:
            humanized = humanize_event(legacy_event_type, data)
            title = humanized["title"]
            subtitle = humanized["subtitle"]
            event_type = humanized["event_type"]
        else:
            data_type = entry.get("data_type", "event")
            subkind = entry.get("subkind", "")
            event = entry.get("event")
            title = event or f"{subkind}/{data_type}" if subkind else data_type
            subtitle = None
            # Surface reflection/os_event/task_state substatus
            if data_type == "task_state":
                status = data.get("status")
                prev = data.get("prev_status")
                if status and prev:
                    subtitle = f"{prev} → {status}"
                elif status:
                    subtitle = f"status={status}"
            elif data_type == "os_event":
                subtitle = data.get("title") or data.get("os_event_type")
            elif data_type == "thought":
                subtitle = data.get("prompt_hint") or data.get("trigger")
            event_type = data_type

        return {
            "id": entry.get("id", ""),
            "timestamp": entry.get("ts", ""),
            "event_type": event_type,
            "title": title,
            "subtitle": subtitle,
            "task_id": entry.get("task_id"),
            "msg_id": entry.get("msg_id"),
            "run_id": data.get("run_id"),
            "raw_data": {
                "thread_id": entry.get("thread_id"),
                "parent_id": entry.get("parent_id"),
                "origin": entry.get("origin"),
                "subkind": entry.get("subkind"),
                "data_type": entry.get("data_type"),
                **data,
            },
        }

    def _broadcast(entry_dict: dict) -> None:
        frontend_event = _build_frontend_event(entry_dict)
        if frontend_event is None:
            return   # covered by legacy PA broadcast path

        msg = {
            "type": MessageType.TIMELINE_EVENT,
            "timestamp": frontend_event["timestamp"],
            "event": frontend_event,
        }
        coro = manager.broadcast(msg)
        if loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(coro, loop)
                return
            except RuntimeError:
                pass
        try:
            cur_loop = asyncio.get_event_loop()
            cur_loop.create_task(coro)
        except RuntimeError:
            pass

    register_hook(_broadcast)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Application lifespan manager.

    Handles startup and shutdown events:
    - Initialize cache with preloaded data
    - Auto-sync official resources if enabled
    - Start background session sync
    - Start community recipe refresh service
    - Stop services on shutdown
    """
    import logging

    logger = logging.getLogger(__name__)

    # Startup: Initialize state manager (unified state)
    state_manager = StateManager.get_instance()
    await state_manager.initialize()

    # Clean up zombie EXECUTING tasks from previous server lifecycle.
    # Single source: board.timeline.jsonl. We read board.get_executing_tasks()
    # and transition any whose pid is dead via board.mark_task_failed.
    try:
        from frago.server.daemon import _is_pid_alive
        from frago.server.services.taskboard import get_board

        board = get_board()
        executing = board.get_executing_tasks()
        for task in executing:
            pid = task.session.pid if task.session else None
            if not _is_pid_alive(pid):
                board.mark_task_failed(
                    task.task_id,
                    error="zombie: process not found at server startup",
                    by="server_startup",
                )
                logger.info("Cleaned zombie task %s (pid=%s)", task.task_id[:8], pid)
    except Exception as e:
        logger.warning("Failed to clean zombie tasks: %s", e)

    # Auto-sync official resources if enabled
    try:
        from frago.init.config_manager import load_config
        from frago.server.services.official_resource_sync_service import (
            OfficialResourceSyncService,
        )

        config = load_config()
        if config.official_resource_sync_enabled:
            logger.info("Auto-syncing official resources from GitHub...")
            OfficialResourceSyncService.start_sync()
    except Exception as e:
        logger.warning("Failed to auto-sync official resources: %s", e)

    # Start sync service (syncs Claude Code sessions to frago storage)
    sync_service = SyncService.get_instance()
    await sync_service.start()

    # Start sessions watcher (watchdog-based real-time monitoring)
    sessions_watcher = SessionsWatcher.get_instance()
    await sessions_watcher.start()

    # Initialize and start community recipe service (60s refresh interval)
    community_service = CommunityRecipeService.get_instance()
    await community_service.initialize()  # Fetch first to populate initial data
    await community_service.start()

    # Initialize and start version check service (1h refresh interval)
    version_service = VersionCheckService.get_instance()
    await version_service.initialize()
    await version_service.start()

    # Start GitHub sync scheduler (5min interval, only if configured)
    github_sync_scheduler = GitHubSyncScheduler.get_instance()
    await github_sync_scheduler.start()

    # Prepare recipe scheduler (started after PA wiring below)
    scheduler = SchedulerService.get_instance()

    # Start tab cleanup service (periodic orphan tab reconciliation)
    from frago.server.services.tab_cleanup_service import TabCleanupService

    tab_cleanup = TabCleanupService.get_instance()
    await tab_cleanup.start()

    # Deploy frago-hook binary if missing or outdated, then sync event registration
    try:
        from frago.init.hook_binary import deploy_hook_binary, sync_hook_events
        hook_path = deploy_hook_binary()
        logger.info("Hook binary ready: %s", hook_path)
        sync_hook_events(str(hook_path))
    except Exception as e:
        logger.warning("Failed to deploy hook binary: %s", e)

    # Cleanup old trace files
    from frago.server.services.trace import cleanup_old_traces, register_broadcast_hook
    cleanup_old_traces()

    # Wire timeline entries → WS timeline_event (spec 20260418-timeline-consumer-unification Phase 3)
    _wire_timeline_broadcast(register_broadcast_hook)

    # Initialize Primary Agent (PID 1 — always available, independent of features)
    from frago.server.services.primary_agent_service import PrimaryAgentService

    primary_agent = PrimaryAgentService.get_instance()
    try:
        await primary_agent.initialize()
    except Exception as e:
        logger.warning("Failed to initialize Primary Agent: %s", e)

    # Start task ingestion scheduler (if enabled in config)
    ingestion_scheduler = await _start_ingestion_scheduler(logger)

    # Telemetry: ensure config exists + report server start for DAU tracking
    try:
        from frago.telemetry import capture
        from frago.telemetry.config import ensure_config
        ensure_config()
        capture("server_started")
    except Exception:
        pass

    # Wire ingestion scheduler ↔ PA (bidirectional)
    if ingestion_scheduler is not None:
        ingestion_scheduler.set_pa_enqueue(primary_agent.enqueue_message)
        primary_agent.set_ingestion_scheduler(ingestion_scheduler)

    # Wire recipe scheduler ↔ PA (bidirectional), then start loop
    scheduler.set_pa_enqueue(primary_agent.enqueue_message)
    primary_agent.set_scheduler_service(scheduler)
    await scheduler.start()

    yield

    # Shutdown
    if ingestion_scheduler is not None:
        await ingestion_scheduler.stop()
    await tab_cleanup.stop()
    await primary_agent.stop()
    await scheduler.stop()
    await github_sync_scheduler.stop()
    await version_service.stop()
    await community_service.stop()
    await sessions_watcher.stop()
    await sync_service.stop()


async def _start_ingestion_scheduler(logger):
    """Start the task ingestion scheduler if enabled in config."""
    try:
        import json as _json

        config_file = Path.home() / ".frago" / "config.json"
        if not config_file.exists():
            return None
        raw_config = _json.loads(config_file.read_text(encoding="utf-8"))
        ingestion_config = raw_config.get("task_ingestion") or {}
        if not ingestion_config.get("enabled", False):
            return None

        from frago.server.services.ingestion.scheduler import (
            ChannelConfig,
            IngestionScheduler,
        )

        channel_configs = [
            ChannelConfig(**ch) for ch in ingestion_config.get("channels", [])
        ]
        if not channel_configs:
            logger.info("No ingestion channels configured, skipping scheduler")
            return None

        scheduler = IngestionScheduler(channels=channel_configs)
        await scheduler.start()
        return scheduler
    except Exception as e:
        logger.warning("Failed to start ingestion scheduler: %s", e)
        return None


def get_frontend_path() -> Path:
    """Get the path to frontend build assets for the web service.

    Returns:
        Path to the server frontend dist directory
    """
    # Look for built assets in server/assets (packaged) or server/web/dist (dev)
    server_dir = Path(__file__).parent

    # Check for packaged assets first
    assets_dir = server_dir / "assets"
    if assets_dir.exists() and (assets_dir / "index.html").exists():
        return assets_dir

    # Fall back to client build output (development mode)
    client_dist = server_dir.parent / "client" / "dist"
    if client_dist.exists():
        return client_dist

    # Return assets dir even if it doesn't exist (will be created during build)
    return assets_dir


def create_app(
    title: str = "Frago Web Service",
    version: str | None = None,
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
        lifespan=lifespan,
    )

    # Configure CORS for local development and home LAN access
    # Allows localhost plus RFC1918 private network ranges (10/8, 172.16/12, 192.168/16)
    # on any port — safe assumption for a trusted home network.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^http://("
            r"localhost"
            r"|127\.\d+\.\d+\.\d+"
            r"|10\.\d+\.\d+\.\d+"
            r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
            r"|192\.168\.\d+\.\d+"
            r")(:\d+)?$"
        ),
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
    app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])
    app.include_router(recipes_router, prefix="/api", tags=["recipes"])
    app.include_router(tasks_router, prefix="/api", tags=["tasks"])
    app.include_router(agent_router, prefix="/api", tags=["agent"])
    app.include_router(config_router, prefix="/api", tags=["config"])
    app.include_router(skills_router, prefix="/api", tags=["skills"])
    app.include_router(settings_router, prefix="/api", tags=["settings"])
    app.include_router(sync_router, prefix="/api", tags=["sync"])
    app.include_router(init_router, prefix="/api", tags=["init"])
    app.include_router(guide_router, prefix="/api", tags=["guide"])

    # Viewer routes for content preview (not under /api)
    app.include_router(viewer_router, prefix="/viewer", tags=["viewer"])

    # Chrome landing page dashboard (not under /api)
    app.include_router(chrome_dashboard_router, prefix="/chrome", tags=["chrome"])
    app.include_router(files_router, prefix="/api", tags=["files"])
    app.include_router(workspace_router, prefix="/api", tags=["workspace"])

    from frago.server.routes.pa import router as pa_router
    app.include_router(pa_router, prefix="/api", tags=["pa"])

    from frago.server.routes.timeline import router as timeline_router
    app.include_router(timeline_router, prefix="/api", tags=["timeline"])

    # WebSocket endpoint for real-time updates
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates.

        Clients connect here to receive:
        - Task status updates
        - Session sync events
        - Log streaming
        - Initial data push on connect
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

            # Push initial data immediately if state is ready
            state_manager = StateManager.get_instance()
            if state_manager.is_initialized():
                initial_data = state_manager.get_initial_data()
                await manager.send_personal(
                    websocket,
                    create_message(MessageType.DATA_INITIAL, initial_data),
                )

            # Push version info if available
            version_service = VersionCheckService.get_instance()
            version_info = await version_service.get_version_info()
            if version_info:
                await manager.send_personal(
                    websocket,
                    create_message(MessageType.DATA_VERSION, {"data": version_info}),
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
        # Mount icons directory
        icons_path = frontend_path / "icons"
        if icons_path.exists():
            app.mount(
                "/icons",
                StaticFiles(directory=str(icons_path)),
                name="icons",
            )

    # SPA fallback: serve index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes.

        This enables client-side routing by serving index.html
        for any path that doesn't match an API route.
        """
        # Don't serve SPA for API or viewer routes (they should 404 naturally)
        if full_path.startswith("api/") or full_path.startswith("viewer/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Endpoint not found")

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
cd src/frago/client
pnpm install
pnpm build
                </pre>
                <p>Then restart <code>frago server</code></p>
            </body>
            </html>
            """,
            status_code=503,
        )

    return app
