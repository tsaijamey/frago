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

**Independent Test**: Can be fully tested by running `frago serve` and verifying the browser opens with the GUI loaded.

**Acceptance Scenarios**:

1. **Given** user has frago installed, **When** user runs `frago serve`, **Then** server starts on `127.0.0.1:8080` and opens browser automatically
2. **Given** port 8080 is occupied, **When** user runs `frago serve`, **Then** server finds next available port and displays the URL
3. **Given** server is running, **When** user opens `http://127.0.0.1:8080` in any browser, **Then** the Frago GUI loads correctly

---

### User Story 2 - Execute Commands via Web UI (Priority: P1)

As a user, I want to run recipes and agent tasks through the web interface, same as the current pywebview GUI.

**Why this priority**: Core functionality must work through the new interface.

**Independent Test**: Can be fully tested by executing a recipe through the web UI and verifying results display correctly.

**Acceptance Scenarios**:

1. **Given** web GUI is open, **When** user clicks a recipe to run, **Then** the recipe executes and result is displayed
2. **Given** user submits an agent task, **When** task is running, **Then** progress updates appear in real-time
3. **Given** task completes, **When** user views result, **Then** output and status are correctly displayed

---

### User Story 3 - Real-time Updates (Priority: P2)

As a user, I want to see task progress and session updates in real-time without refreshing the page.

**Why this priority**: Good UX requires live feedback, but basic functionality can work with manual refresh.

**Independent Test**: Can be tested by starting a long-running task and observing live log updates without page refresh.

**Acceptance Scenarios**:

1. **Given** an agent task is running, **When** new log entries appear, **Then** they stream to the browser immediately
2. **Given** a new Claude session is created, **When** tasks page is open, **Then** task list updates automatically

---

### User Story 4 - Backward Compatibility (Priority: P2)

As an existing user, I want `frago --gui` to still work, launching the web service and opening my default browser.

**Why this priority**: Smooth migration for existing users.

**Independent Test**: Can be tested by running `frago --gui` and verifying browser opens with GUI.

**Acceptance Scenarios**:

1. **Given** user runs `frago --gui`, **When** command executes, **Then** equivalent to `frago serve --open`

---

### Edge Cases

- What happens if user tries to start multiple servers? → Detect running instance, show URL to existing instance
- What if browser fails to open automatically? → Print URL to console for manual access
- What about access from external network? → Bind to 127.0.0.1 only, reject external connections
- What if user wants a specific port? → Support `--port` option

## Requirements

### Functional Requirements

**Server Core**

- **FR-001**: System MUST start HTTP server on configurable port (default 8080)
- **FR-002**: Server MUST bind to `127.0.0.1` only for security (no external access)
- **FR-003**: Server MUST serve the web-based GUI application
- **FR-004**: Server MUST provide API endpoints for all GUI operations
- **FR-005**: Server MUST support real-time updates for task progress

**API Capabilities**

- **FR-006**: System MUST allow listing available recipes
- **FR-007**: System MUST allow executing recipes with parameters
- **FR-008**: System MUST allow listing tasks/sessions
- **FR-009**: System MUST allow viewing task details and output
- **FR-010**: System MUST allow starting agent tasks
- **FR-011**: System MUST allow reading configuration
- **FR-012**: System MUST allow updating configuration
- **FR-013**: System MUST expose system status (Chrome availability, etc.)
- **FR-014**: System MUST push real-time updates for running tasks

**CLI Integration**

- **FR-015**: `frago serve` command MUST start the web server
- **FR-016**: `frago serve --port <port>` MUST allow custom port selection
- **FR-017**: `frago serve --open` MUST auto-open browser (default behavior)
- **FR-018**: `frago --gui` MUST behave as alias for `frago serve --open`

**Frontend Adaptation**

- **FR-019**: Web GUI MUST provide all features currently available in pywebview GUI
- **FR-020**: Web GUI MUST display real-time updates for running tasks
- **FR-021**: Web GUI MUST handle connection errors gracefully (show reconnection status)

### Key Entities

- **WebServer**: HTTP server instance that hosts the GUI and handles API requests
- **Session**: User's work context containing tasks and configuration
- **Task**: An agent task or recipe execution with its state and output
- **Recipe**: A predefined automation script that can be executed

## Success Criteria

### Measurable Outcomes

- **SC-001**: Server starts and GUI loads in browser within 3 seconds of running command
- **SC-002**: All existing GUI features work identically through web interface
- **SC-003**: Real-time updates appear within 1 second of task state changes
- **SC-004**: Zero additional system-level dependencies required (no GTK/WebView2/WebKit)
- **SC-005**: `frago --gui` continues to work for existing users
- **SC-006**: Users can access GUI from any modern browser (Chrome, Firefox, Edge, Safari)

## Migration Path

1. **v0.17.0**: Add `frago serve` command (web service mode available)
2. **v0.17.0**: `frago --gui` still uses pywebview (default unchanged)
3. **v0.18.0**: `frago --gui` uses web service by default
4. **v0.18.0**: `frago --gui-native` for legacy pywebview
5. **v0.19.0**: Remove pywebview dependency, deprecate `--gui-native`

## Assumptions

- Users have a modern browser installed (Chrome, Firefox, Edge, Safari)
- Python 3.9+ is available
- Port 8080 or nearby ports are available on localhost
- HTTPS is not required on localhost (browser security allows HTTP for localhost)
