# Implementation Plan: Web Service Based GUI

**Branch**: `013-change-gui-into-web-service` | **Date**: 2025-12-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/013-change-gui-into-web-service/spec.md`

## Summary

Replace the pywebview-based GUI with a local HTTP web service architecture. This eliminates platform-specific system dependencies (GTK/WebView2/WebKit) by serving the GUI through a standard web browser. The implementation uses FastAPI for the HTTP server with WebSocket support for real-time updates.

## Technical Context

**Language/Version**: Python 3.9+ (existing project requirement)
**Primary Dependencies**: FastAPI, Uvicorn (new), existing React/TypeScript frontend
**Storage**: N/A (uses existing session storage in `~/.frago/sessions/`)
**Testing**: pytest (existing)
**Target Platform**: macOS, Linux, Windows (cross-platform)
**Project Type**: Single project with frontend (existing structure)
**Performance Goals**: Server starts in <3s, real-time updates <1s latency
**Constraints**: Bind to 127.0.0.1 only (security), minimal new dependencies
**Scale/Scope**: Single-user local application

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No project constitution defined. Proceeding with standard development practices:
- ✅ All changes maintain backward compatibility (`frago --gui` continues to work)
- ✅ No breaking changes to existing API methods
- ✅ Minimal new dependencies (only FastAPI + Uvicorn)
- ✅ Cross-platform compatibility maintained

## Project Structure

### Documentation (this feature)

```text
specs/013-change-gui-into-web-service/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0: Technology research
├── data-model.md        # Phase 1: Data models
├── quickstart.md        # Phase 1: Development quickstart
├── contracts/           # Phase 1: API contracts
│   └── openapi.yaml     # OpenAPI 3.1 specification
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/frago/
├── server/              # NEW: Web server module
│   ├── __init__.py
│   ├── app.py           # FastAPI application
│   ├── routes/
│   │   ├── recipes.py   # Recipe endpoints
│   │   ├── tasks.py     # Task endpoints
│   │   ├── config.py    # Configuration endpoints
│   │   └── system.py    # System status endpoints
│   ├── websocket.py     # WebSocket connection manager
│   └── dependencies.py  # FastAPI dependencies
├── cli/
│   └── main.py          # MODIFY: Add 'serve' command
└── gui/
    ├── api.py           # REUSE: Existing business logic
    └── frontend/
        └── src/
            ├── api/
            │   ├── client.ts      # NEW: HTTP API client
            │   └── websocket.ts   # NEW: WebSocket client
            └── hooks/
                └── useApi.ts      # NEW: React hooks for API
```

**Structure Decision**: Extends existing single-project structure. New `server/` module added alongside existing `gui/` module. Frontend gains new API client layer.

## Complexity Tracking

No complexity violations. The implementation follows standard web service patterns:
- Single HTTP server (FastAPI)
- Single WebSocket endpoint
- Reuses 100% of existing business logic

## Design Artifacts

| Artifact | Path | Description |
|----------|------|-------------|
| Research | [research.md](./research.md) | Technology decisions and alternatives |
| Data Model | [data-model.md](./data-model.md) | Entity definitions and state transitions |
| API Contract | [contracts/openapi.yaml](./contracts/openapi.yaml) | OpenAPI 3.1 specification |
| Quickstart | [quickstart.md](./quickstart.md) | Development setup guide |

## Implementation Phases

### Phase 1: Server Infrastructure

1. Create `src/frago/server/` module structure
2. Implement FastAPI application with static file serving
3. Add `frago serve` CLI command
4. Verify server starts and serves existing frontend

### Phase 2: API Migration

1. Create route handlers wrapping `FragoGuiApi` methods
2. Implement `/api/recipes`, `/api/tasks`, `/api/config`, `/api/status` endpoints
3. Add Pydantic models for request/response validation
4. Test all endpoints with curl

### Phase 3: Real-time Updates

1. Implement WebSocket manager
2. Modify session sync to broadcast via WebSocket
3. Add connection/reconnection handling

### Phase 4: Frontend Adaptation

1. Create HTTP API client (`src/api/client.ts`)
2. Create WebSocket client (`src/api/websocket.ts`)
3. Replace `window.pywebview.api` calls with HTTP fetch
4. Add reconnection UI component
5. Test full integration

### Phase 5: Migration Support

1. Update `frago --gui` to use web service
2. Add deprecation warning for pywebview (optional dependency)
3. Update documentation

## Dependencies to Add

```toml
# pyproject.toml additions
dependencies = [
    # ... existing ...
    "fastapi>=0.100.0",
    "uvicorn[standard]>=0.23.0",
]
```

## Next Steps

Run `/speckit.tasks` to generate the detailed task breakdown for implementation.
