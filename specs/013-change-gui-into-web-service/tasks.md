# Tasks: Web Service Based GUI

**Input**: Design documents from `/specs/013-change-gui-into-web-service/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml

**Tests**: Not explicitly requested - test tasks omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `src/frago/` at repository root
- **Frontend**: `src/frago/gui/frontend/src/`
- **New server module**: `src/frago/server/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and server module structure

- [x] T001 Add FastAPI and Uvicorn dependencies to `pyproject.toml`
- [x] T002 Create server module structure: `src/frago/server/__init__.py`
- [x] T003 [P] Create server routes directory: `src/frago/server/routes/__init__.py`
- [x] T004 [P] Create Pydantic request/response models in `src/frago/server/models.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core server infrastructure that MUST be complete before user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Implement FastAPI app factory in `src/frago/server/app.py` with CORS and static file mounting
- [x] T006 [P] Create FragoGuiApi adapter class in `src/frago/server/adapter.py` to wrap existing API methods
- [x] T007 [P] Implement port discovery utility (find available port) in `src/frago/server/utils.py`
- [x] T008 Implement server startup with Uvicorn in `src/frago/server/runner.py`

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Start Web Service (Priority: P1) 🎯 MVP

**Goal**: Users can run `frago serve` to start a local web server and access GUI in browser

**Independent Test**: Run `frago serve`, verify browser opens with GUI loaded at `127.0.0.1:8080`

### Implementation for User Story 1

- [x] T009 [US1] Add `frago serve` command to CLI in `src/frago/cli/main.py`
- [x] T010 [US1] Implement `--port` option for custom port selection in `src/frago/cli/main.py`
- [x] T011 [US1] Implement `--open/--no-open` option for browser auto-open in `src/frago/cli/main.py`
- [x] T012 [US1] Mount static files from built frontend assets in `src/frago/server/app.py`
- [x] T013 [US1] Implement `/api/status` endpoint in `src/frago/server/routes/system.py`
- [x] T014 [US1] Implement `/api/info` endpoint in `src/frago/server/routes/system.py`
- [x] T015 [US1] Add SPA fallback routing (serve index.html for non-API routes) in `src/frago/server/app.py`
- [x] T016 [US1] Implement browser auto-open using `webbrowser` module in `src/frago/server/runner.py`
- [x] T017 [US1] Handle port-in-use detection and auto-increment in `src/frago/server/utils.py`

**Checkpoint**: `frago serve` starts server, browser opens, GUI loads. Basic server info available via API.

---

## Phase 4: User Story 2 - Execute Commands via Web UI (Priority: P1)

**Goal**: Users can run recipes and agent tasks through the web interface

**Independent Test**: Execute a recipe via web UI, verify results display correctly

### Implementation for User Story 2

- [ ] T018 [P] [US2] Implement `/api/recipes` (GET list) endpoint in `src/frago/server/routes/recipes.py`
- [ ] T019 [P] [US2] Implement `/api/recipes/{name}` (GET detail) endpoint in `src/frago/server/routes/recipes.py`
- [ ] T020 [US2] Implement `/api/recipes/{name}/run` (POST execute) endpoint in `src/frago/server/routes/recipes.py`
- [ ] T021 [P] [US2] Implement `/api/tasks` (GET list) endpoint in `src/frago/server/routes/tasks.py`
- [ ] T022 [P] [US2] Implement `/api/tasks/{id}` (GET detail) endpoint in `src/frago/server/routes/tasks.py`
- [ ] T023 [US2] Implement `/api/tasks/{id}/steps` (GET paginated) endpoint in `src/frago/server/routes/tasks.py`
- [ ] T024 [US2] Implement `/api/agent` (POST start task) endpoint in `src/frago/server/routes/agent.py`
- [ ] T025 [P] [US2] Implement `/api/config` (GET) endpoint in `src/frago/server/routes/config.py`
- [ ] T026 [US2] Implement `/api/config` (PUT update) endpoint in `src/frago/server/routes/config.py`
- [ ] T027 [US2] Create HTTP API client in `src/frago/gui/frontend/src/api/client.ts`
- [ ] T028 [US2] Replace `window.pywebview.api` calls with fetch in `src/frago/gui/frontend/src/hooks/useApi.ts`
- [ ] T029 [US2] Update recipe list component to use HTTP API in `src/frago/gui/frontend/src/components/RecipeList.tsx`
- [ ] T030 [US2] Update task list component to use HTTP API in `src/frago/gui/frontend/src/components/TaskList.tsx`
- [ ] T031 [US2] Handle API errors and loading states in frontend components

**Checkpoint**: Recipes list, execute, view results. Tasks list and view details. Configuration read/update.

---

## Phase 5: User Story 3 - Real-time Updates (Priority: P2)

**Goal**: Users see task progress and session updates in real-time without page refresh

**Independent Test**: Start a long-running task, observe live log updates in browser

### Implementation for User Story 3

- [ ] T032 [US3] Implement WebSocket connection manager in `src/frago/server/websocket.py`
- [ ] T033 [US3] Add `/ws` WebSocket endpoint to FastAPI app in `src/frago/server/app.py`
- [ ] T034 [US3] Modify session sync thread to broadcast via WebSocket in `src/frago/server/adapter.py`
- [ ] T035 [US3] Implement WebSocket message types (session_sync, task_updated, etc.) in `src/frago/server/websocket.py`
- [ ] T036 [US3] Create WebSocket client in `src/frago/gui/frontend/src/api/websocket.ts`
- [ ] T037 [US3] Add WebSocket connection hook in `src/frago/gui/frontend/src/hooks/useWebSocket.ts`
- [ ] T038 [US3] Update task detail component to receive real-time updates in `src/frago/gui/frontend/src/components/TaskDetail.tsx`
- [ ] T039 [US3] Implement connection status indicator in `src/frago/gui/frontend/src/components/ConnectionStatus.tsx`
- [ ] T040 [US3] Add auto-reconnect logic (3s retry) in WebSocket client

**Checkpoint**: Task progress streams live. Session list updates automatically. Connection status visible.

---

## Phase 6: User Story 4 - Backward Compatibility (Priority: P2)

**Goal**: Existing `frago --gui` command continues to work, launching web service

**Independent Test**: Run `frago --gui`, verify browser opens with GUI (same as `frago serve --open`)

### Implementation for User Story 4

- [ ] T041 [US4] Modify `--gui` flag handler in `src/frago/cli/main.py` to call `frago serve --open`
- [ ] T042 [US4] Add deprecation notice for pywebview mode in `src/frago/cli/main.py`
- [ ] T043 [US4] Update CLI help text to reflect new serve command

**Checkpoint**: `frago --gui` launches web service and opens browser. Deprecation warning shown if applicable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T044 [P] Update README.md with new `frago serve` command documentation
- [ ] T045 [P] Add CORS configuration for local development in `src/frago/server/app.py`
- [ ] T046 Implement graceful server shutdown handling in `src/frago/server/runner.py`
- [ ] T047 [P] Add error handling middleware for consistent API error responses in `src/frago/server/app.py`
- [ ] T048 Build frontend assets with `pnpm build` in `src/frago/gui/frontend/`
- [ ] T049 Validate quickstart.md scenarios work end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 and US2 are both P1 and can proceed in parallel
  - US3 depends on US2 (needs API endpoints to have something to update)
  - US4 depends on US1 (needs serve command to exist)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

```
                    ┌─────────────┐
                    │   Setup     │
                    │  (Phase 1)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ Foundational│
                    │  (Phase 2)  │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────▼──────┐┌──────▼──────┐       │
     │    US1      ││    US2      │       │
     │ Web Server  ││ Commands UI │       │
     │   (P1)      ││    (P1)     │       │
     └──────┬──────┘└──────┬──────┘       │
            │              │              │
            │       ┌──────▼──────┐       │
            │       │    US3      │       │
            │       │ Real-time   │       │
            │       │   (P2)      │       │
            │       └─────────────┘       │
            │                             │
     ┌──────▼──────┐                      │
     │    US4      │                      │
     │ Backward    │                      │
     │ Compat (P2) │                      │
     └─────────────┘                      │
                                          │
                    ┌─────────────────────▼
                    │      Polish         │
                    │    (Phase 7)        │
                    └─────────────────────┘
```

### Within Each User Story

- Core implementation before integration
- Backend endpoints before frontend adaptation
- Story complete before moving to next priority

### Parallel Opportunities

- T003, T004 can run in parallel (different files)
- T006, T007 can run in parallel (different utilities)
- T018, T019, T021, T022, T025 can run in parallel (different endpoint files)
- T044, T045, T047 can run in parallel (different concerns)

---

## Parallel Example: User Story 2

```bash
# Launch parallel endpoint implementations:
Task: "Implement /api/recipes (GET list) in src/frago/server/routes/recipes.py"
Task: "Implement /api/tasks (GET list) in src/frago/server/routes/tasks.py"
Task: "Implement /api/config (GET) in src/frago/server/routes/config.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2)

1. Complete Phase 1: Setup (T001-T004)
2. Complete Phase 2: Foundational (T005-T008)
3. Complete Phase 3: User Story 1 - Server starts (T009-T017)
4. Complete Phase 4: User Story 2 - Commands work (T018-T031)
5. **STOP and VALIDATE**: Test `frago serve`, execute recipes, view tasks
6. Deploy/demo if ready - this is a functional MVP!

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → Test `frago serve` → Demo (basic server)
3. Add US2 → Test recipe execution → Demo (functional GUI)
4. Add US3 → Test real-time updates → Demo (enhanced UX)
5. Add US4 → Test `frago --gui` → Full feature parity

### Task Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| Phase 1: Setup | T001-T004 | 4 tasks |
| Phase 2: Foundational | T005-T008 | 4 tasks |
| Phase 3: US1 (P1) | T009-T017 | 9 tasks |
| Phase 4: US2 (P1) | T018-T031 | 14 tasks |
| Phase 5: US3 (P2) | T032-T040 | 9 tasks |
| Phase 6: US4 (P2) | T041-T043 | 3 tasks |
| Phase 7: Polish | T044-T049 | 6 tasks |
| **Total** | | **49 tasks** |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- US1 + US2 combined form the MVP - minimum viable web service GUI
