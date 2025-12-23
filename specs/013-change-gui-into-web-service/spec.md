# Feature Specification: Web Service Based GUI

**Feature Branch**: `013-change-gui-into-web-service`
**Created**: 2025-12-23
**Status**: Draft
**Input**: Replace pywebview-based GUI with a local HTTP web service, allowing users to control Frago through any browser.

## Motivation

### Current Limitations with pywebview

1. **Heavy system dependencies**: GTK/WebView2/WebKit required on different platforms
2. **Installation friction**: Linux users need to install system packages (python3-gi, webkit2gtk)
3. **Debugging difficulty**: Cannot use standard browser DevTools effectively
4. **Inconsistent behavior**: Different rendering engines on different platforms

### Benefits of Web Service Architecture

1. **Zero GUI dependencies**: Only Python packages needed
2. **Universal compatibility**: Works in any modern browser
3. **Developer friendly**: Full browser DevTools support
4. **Future extensibility**: Enables remote access, mobile control, multi-user scenarios

## User Scenarios & Testing

### User Story 1 - Start Web Service (Priority: P1)

As a Frago user, I want to start a local web server with `frago serve` so that I can access the GUI through my browser.

**Why this priority**: This is the foundation - without the server running, nothing else works.

**Acceptance Scenarios**:

1. **Given** user has frago installed, **When** user runs `frago serve`, **Then** server starts on `127.0.0.1:8080` and opens browser automatically
2. **Given** port 8080 is occupied, **When** user runs `frago serve`, **Then** server finds next available port and displays the URL
3. **Given** server is running, **When** user opens `http://127.0.0.1:8080` in any browser, **Then** the Frago GUI loads correctly

---

### User Story 2 - Execute Commands via Web UI (Priority: P1)

As a user, I want to run recipes and agent tasks through the web interface, same as the current pywebview GUI.

**Why this priority**: Core functionality must work through the new interface.

**Acceptance Scenarios**:

1. **Given** web GUI is open, **When** user clicks a recipe to run, **Then** API call is made and result is displayed
2. **Given** user submits an agent task, **When** task is running, **Then** progress updates appear in real-time via WebSocket
3. **Given** task completes, **When** user views result, **Then** output and status are correctly displayed

---

### User Story 3 - Real-time Updates (Priority: P2)

As a user, I want to see task progress and session updates in real-time without refreshing the page.

**Why this priority**: Good UX requires live feedback, but basic functionality can work with polling.

**Acceptance Scenarios**:

1. **Given** an agent task is running, **When** new log entries appear, **Then** they stream to the browser immediately
2. **Given** a new Claude session is created, **When** tasks page is open, **Then** task list updates automatically

---

### User Story 4 - Backward Compatibility (Priority: P2)

As an existing user, I want `frago --gui` to still work, launching the web service and opening my default browser.

**Why this priority**: Smooth migration for existing users.

**Acceptance Scenarios**:

1. **Given** user runs `frago --gui`, **When** command executes, **Then** equivalent to `frago serve --open`

---

### Edge Cases

- What happens if user tries to start multiple servers? → Detect running instance, show URL
- What if browser fails to open automatically? → Print URL to console
- What about CORS when accessing from different origin? → Bind to 127.0.0.1 only, reject external
- What if user wants a specific port? → Support `--port` option

## Requirements

### Functional Requirements

**Server Core**

- **FR-001**: System must start HTTP server on configurable port (default 8080)
- **FR-002**: Server must bind to `127.0.0.1` only (security: no external access)
- **FR-003**: Server must serve static files (HTML/CSS/JS) from built assets
- **FR-004**: Server must provide REST API endpoints for all GUI operations
- **FR-005**: Server must support WebSocket for real-time updates

**API Endpoints**

- **FR-006**: `GET /api/recipes` - List recipes
- **FR-007**: `POST /api/recipes/{name}/run` - Execute recipe
- **FR-008**: `GET /api/tasks` - List tasks/sessions
- **FR-009**: `GET /api/tasks/{id}` - Get task details
- **FR-010**: `POST /api/agent` - Start agent task
- **FR-011**: `GET /api/config` - Get configuration
- **FR-012**: `PUT /api/config` - Update configuration
- **FR-013**: `GET /api/status` - System status (Chrome, etc.)
- **FR-014**: `WS /ws` - WebSocket for real-time updates

**CLI Integration**

- **FR-015**: `frago serve` command starts the web server
- **FR-016**: `frago serve --port <port>` allows custom port
- **FR-017**: `frago serve --open` auto-opens browser (default: true)
- **FR-018**: `frago --gui` becomes alias for `frago serve --open`

**Frontend Changes**

- **FR-019**: Replace `window.pywebview.api.xxx()` calls with `fetch('/api/xxx')`
- **FR-020**: Implement WebSocket client for real-time updates
- **FR-021**: Handle connection errors gracefully (show reconnection UI)

### Key Entities

- **WebServer**: HTTP server instance with routes and WebSocket support
- **APIRouter**: Routes HTTP requests to handler functions
- **WebSocketManager**: Manages connected clients and broadcasts updates
- **SessionBroadcaster**: Monitors session changes and pushes to WebSocket

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    frago serve                              │
├─────────────────────────────────────────────────────────────┤
│  FastAPI/Starlette Server (127.0.0.1:8080)                 │
│  ├── Static Files (/index.html, /assets/*)                 │
│  ├── REST API (/api/*)                                     │
│  └── WebSocket (/ws)                                       │
├─────────────────────────────────────────────────────────────┤
│  Existing Logic (reused)                                   │
│  ├── FragoGuiApi methods → HTTP handlers                   │
│  ├── Session sync thread → WebSocket broadcaster           │
│  └── subprocess calls → unchanged                          │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Approach

**Phase 1: Server Infrastructure**

1. Create `src/frago/server/` module
2. Implement minimal HTTP server with FastAPI/Starlette
3. Serve existing built frontend assets
4. Add `frago serve` command

**Phase 2: API Migration**

1. Convert `FragoGuiApi` methods to HTTP endpoints
2. Keep method logic unchanged, only wrap with HTTP handlers
3. Add request/response models with Pydantic

**Phase 3: Real-time Updates**

1. Add WebSocket endpoint
2. Modify session sync to broadcast changes
3. Update frontend to use WebSocket

**Phase 4: Frontend Adaptation**

1. Create API client wrapper (`api.ts`)
2. Replace all `window.pywebview.api` calls
3. Add WebSocket connection management
4. Add offline/reconnection UI

### File Structure

```
src/frago/
├── server/
│   ├── __init__.py
│   ├── app.py           # FastAPI app, routes
│   ├── api.py           # HTTP endpoint handlers
│   ├── websocket.py     # WebSocket manager
│   └── models.py        # Request/Response schemas
├── cli/
│   └── main.py          # Add 'serve' command
└── gui/
    └── frontend/
        └── src/
            ├── api/
            │   ├── client.ts      # HTTP API client
            │   └── websocket.ts   # WebSocket client
            └── hooks/
                └── useApi.ts      # React hooks for API
```

### Dependency Changes

```toml
# pyproject.toml additions
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
    # Remove: pywebview (optional, for legacy support)
]

[project.optional-dependencies]
gui-legacy = ["pywebview>=5.0"]  # Keep for users who prefer native window
```

## Success Criteria

- **SC-001**: `frago serve` starts server in < 2 seconds
- **SC-002**: All existing GUI features work through web interface
- **SC-003**: Real-time updates appear within 1 second of changes
- **SC-004**: Zero additional system dependencies (no GTK/WebView2)
- **SC-005**: Frontend bundle size unchanged (no new JS dependencies)
- **SC-006**: `frago --gui` continues to work as before

## Migration Path

1. **v0.17.0**: Add `frago serve` command (web service mode)
2. **v0.17.0**: `frago --gui` still uses pywebview (default)
3. **v0.18.0**: `frago --gui` uses web service by default
4. **v0.18.0**: `frago --gui-native` for legacy pywebview
5. **v0.19.0**: Remove pywebview dependency, deprecate `--gui-native`

## Assumptions

- Users have a modern browser (Chrome, Firefox, Edge, Safari)
- Python 3.9+ available
- Port 8080 or nearby ports available on localhost
- No need for HTTPS on localhost (browser security allows this)
