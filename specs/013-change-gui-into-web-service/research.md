# Research: Web Service Based GUI

**Date**: 2025-12-23
**Feature**: 013-change-gui-into-web-service

## Technical Decisions

### 1. Web Framework Selection

**Decision**: FastAPI with Uvicorn

**Rationale**:
- **Startup time**: <500ms for minimal app, well under the 3s requirement
- **WebSocket support**: Native first-class support via Starlette foundation
- **Minimal dependencies**: `fastapi[standard]` includes uvicorn, clean dependency tree
- **Sync/Async migration**: Built-in `run_in_threadpool()` for converting existing sync code
- **Auto-documentation**: OpenAPI/Swagger docs generated automatically (useful for debugging)
- **Type safety**: Pydantic integration for request/response validation

**Considered Alternatives**:

| Framework | Startup | WebSocket | Dependencies | Migration | Verdict |
|-----------|---------|-----------|--------------|-----------|---------|
| **FastAPI** | 100-200ms | Excellent | ~15 packages | Easy | SELECTED |
| Starlette | <100ms | Excellent | ~6 packages | Manual | Too low-level, more boilerplate |
| Flask | 50-100ms | Poor (extension needed) | ~5 packages | Very difficult | Not async-native |
| aiohttp | 100-150ms | Excellent | ~8 packages | Requires rewrite | Steeper learning curve |

### 2. ASGI Server

**Decision**: Uvicorn (included with `fastapi[standard]`)

**Rationale**:
- Industry standard for FastAPI
- Fast startup (<100ms)
- Production-ready
- Handles both HTTP and WebSocket

### 3. Static File Serving

**Decision**: Use FastAPI's `StaticFiles` mount

**Rationale**:
- Built-in to FastAPI/Starlette
- No additional dependencies
- Serves pre-built frontend assets efficiently
- Supports SPA fallback routing

### 4. Real-time Updates Pattern

**Decision**: WebSocket with broadcast pattern

**Rationale**:
- Lower latency than Server-Sent Events (SSE)
- Bidirectional communication (future-proof for interactive features)
- Native browser support
- Existing session sync thread can push updates to WebSocket manager

### 5. API Migration Strategy

**Decision**: Wrap existing `FragoGuiApi` methods in HTTP endpoints

**Rationale**:
- Reuse 100% of existing business logic
- Minimal code changes
- Only change transport layer (pywebview → HTTP)
- Use `run_in_threadpool()` for sync methods

### 6. Port Selection

**Decision**: Default 8080, auto-find if occupied

**Rationale**:
- 8080 is standard for development servers
- Auto-increment to find available port (8080, 8081, 8082...)
- Display actual port in console

### 7. Security

**Decision**: Bind to 127.0.0.1 only, no authentication

**Rationale**:
- Local-only access ensures no external connections
- Same security model as pywebview (no auth needed for local app)
- Future: Can add token-based auth if remote access is needed

## Integration Points

### Existing Code Reuse

1. **`FragoGuiApi` class** (`src/frago/gui/api.py`):
   - All 70+ methods can be wrapped as HTTP endpoints
   - No logic changes needed, only add HTTP decorators

2. **Session sync thread** (`_sync_sessions_on_startup`):
   - Already runs in background
   - Add WebSocket broadcast on sync completion

3. **Frontend** (`src/frago/gui/frontend/`):
   - React + TypeScript + Vite
   - Replace `window.pywebview.api.xxx()` with `fetch('/api/xxx')`
   - Add WebSocket client for real-time updates

### New Components

1. **Server module** (`src/frago/server/`):
   - `app.py`: FastAPI application with routes
   - `websocket.py`: WebSocket connection manager

2. **CLI command** (`frago serve`):
   - New subcommand in `src/frago/cli/main.py`

## Open Questions (Resolved)

All technical questions resolved through research. No outstanding clarifications needed.
