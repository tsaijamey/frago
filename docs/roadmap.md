[简体中文](roadmap.zh-CN.md)

# Frago Project Progress

## Project Status

📍 **Current Phase**: GUI and session monitoring complete, entering developer experience enhancement phase

**Completed**:
- ✅ Native CDP protocol layer (~3,763 lines of Python)
- ✅ CLI tools and grouped command system
- ✅ Recipe metadata-driven architecture (multi-runtime support)
- ✅ Run command system (topic-based task management)
- ✅ Init command (dependency check, resource installation)
- ✅ Environment variable support (three-level config priority)
- ✅ GUI app mode (pywebview desktop interface)
- ✅ Agent session monitoring (Claude Code session parsing and persistence)

**Technical Highlights**:
- 🏆 Native CDP (no Playwright/Selenium dependencies, ~2MB)
- 🏆 AI-First design (Claude AI hosts task execution and workflow orchestration)
- 🏆 Recipe acceleration system (solidify high-frequency operations, avoid repeated AI reasoning)
- 🏆 Run System (AI's working memory with persistent context)
- 🏆 Environment variable system (sensitive info management + Workflow context sharing)
- 🏆 Session monitoring (real-time Claude Code session tracking with watchdog)

---

## Completed Features ✅

### Feature 001-002: Core CDP Implementation

- [x] **Native CDP Protocol Layer** (~3,763 lines of Python code)
  - WebSocket direct to Chrome (no Node.js relay)
  - Intelligent retry mechanism (proxy environment optimized)
  - Complete command modules (page/screenshot/runtime/input/scroll/wait/zoom/status/visual_effects)
  - Type-safe configuration system

- [x] **CLI Tools** (Click framework)
  - `uv run frago <command>` - Unified interface for all CDP functionality
  - Proxy configuration support (environment variables + CLI parameters)
  - Function mapping validation tool

- [x] **Cross-Platform Chrome Launcher**
  - macOS/Linux support
  - Auto profile initialization
  - Window size control

### Feature 003-004: Recipe System

- [x] **Recipe Metadata-Driven Architecture**
  - Metadata parser (YAML frontmatter)
  - Recipe registry (three-level lookup path: project > user > example)
  - Recipe executor (chrome-js/python/shell runtime)
  - Output handler (stdout/file/clipboard)
  - CLI command group (list/info/run/copy)

- [x] **AI-Understandable Field Design**
  - `description`: Functionality description
  - `use_cases`: Usage scenarios
  - `tags`: Category tags
  - `output_targets`: Output targets

- [x] **Recipe Storage Structure**
  - Code-resource separation
  - Example Recipes in `examples/`
  - Descriptive naming convention
  - Supporting metadata documentation

### Feature 005: Run Command System

- [x] **Topic-Based Task Management**
  - Run instance creation and discovery
  - RapidFuzz fuzzy matching (80% threshold)
  - Context persistence across sessions
  - Lifecycle: init → execute → log → archive

- [x] **Structured JSONL Logs**
  - 100% programmatically parseable
  - Complete operation history tracking
  - Error logging with stack traces
  - Auditable execution history

- [x] **Persistent Context Storage**
  - `projects/<run_id>/` directory structure
  - `logs/execution.jsonl` - Complete operation history
  - `screenshots/` - Timestamped images
  - `scripts/` - Validated working scripts
  - `outputs/` - Result files

- [x] **AI-Driven Task Execution**
  - `/frago.run` slash command integration
  - Automatic Run instance discovery
  - Recipe selection and orchestration

### Feature 006-007: Init Command System

- [x] **Dependency Check and Installation**
  - Parallel detection of Node.js and Claude Code
  - Smart installation of missing components
  - Installation verification

- [x] **Authentication Configuration**
  - Official Claude Code login
  - Custom API endpoints (DeepSeek, Aliyun, Kimi, MiniMax)
  - Mutually exclusive selection design

- [x] **Resource Installation**
  - Slash commands installed to `~/.claude/commands/`
  - User-level Recipe directory creation `~/.frago/recipes/`
  - Example Recipe copying

- [x] **Config Persistence**
  - `~/.frago/config.json` configuration file
  - Config status view `--show-config`
  - Reset functionality `--reset`

### Environment Variable Support (2025-11-26)

- [x] **Three-Level Config Priority**
  - CLI `--env` parameter (highest)
  - Project-level `.frago/.env`
  - User-level `~/.frago/.env`
  - System environment variables
  - Recipe defaults (lowest)

- [x] **Recipe Metadata Extension**
  - `env` field to declare required environment variables
  - `required`/`default`/`description` attributes
  - Validation and default value application at execution time

- [x] **Workflow Context Sharing**
  - `WorkflowContext` class for cross-Recipe sharing
  - Complete system environment inheritance
  - CLI `-e KEY=VALUE` override

### Feature 008: GUI App Mode

- [x] **Desktop GUI Application**
  - `frago gui` command launches desktop interface
  - pywebview backend (WebKit2GTK on Linux, WebView2 on Windows, WKWebView on macOS)
  - Cross-platform support (Linux, macOS, Windows)
  - Dynamic window sizing (80% of screen height, maintain aspect ratio)

- [x] **GUI Features**
  - Recipe listing and detail view
  - Recipe execution with parameter input
  - Command input and output display
  - Connection status indicator

- [x] **Installation**
  - Optional GUI dependencies: `pip install frago-cli[gui]`
  - Platform-specific backend auto-detection
  - Graceful fallback with installation instructions

### Feature 009: GUI Design Redesign

- [x] **Color Scheme Optimization**
  - GitHub Dark color palette (`--bg-base: #0d1117`)
  - Soft blue accent color (`--accent-primary: #58a6ff`)
  - Harmonious text and border colors
  - Reduced eye strain for long sessions

- [x] **Layout Improvements**
  - Clear visual hierarchy (input > content > navigation)
  - Recipe card design with action buttons
  - Empty state guidance
  - Responsive layout (600-1600px width)

- [x] **Interaction Feedback**
  - Loading states with smooth transitions
  - Message bubble animations
  - Status indicator updates
  - Native window title bar (resolved macOS close hang)

### Feature 010: Agent Session Monitoring

- [x] **Session File Monitoring**
  - watchdog-based file system monitoring
  - Real-time JSONL parsing from `~/.claude/projects/`
  - Incremental parsing (only new records)
  - Session association via timestamp matching (10s window)

- [x] **Session Data Persistence**
  - Structured storage: `~/.frago/sessions/{agent_type}/{session_id}/`
  - `metadata.json` - session metadata (project, start time, status)
  - `steps.jsonl` - execution steps (messages, tool calls)
  - `summary.json` - session summary (tool call stats)

- [x] **Multi-Agent Support**
  - `AgentType` enum (CLAUDE, CURSOR, CLINE, OTHER)
  - `AgentAdapter` abstract base class for extensibility
  - `ClaudeCodeAdapter` implementation for Claude Code
  - Adapter registry for future agent support

- [x] **CLI Commands**
  - `frago session list` - list sessions
  - `frago session show <id>` - show session details
  - `frago session watch` - real-time session monitoring

---

## Pending Features 📝

### High Priority

- [ ] **Chrome-JS Parameter Injection**
  - Currently chrome-js runtime doesn't support parameter passing
  - Need to inject parameters via global variables or script wrapping
  - Support passing Recipe-declared `inputs` to JS scripts

- [ ] **Workflow Orchestration Enhancement**
  - Combine atomic Recipes into complex workflows
  - Conditional branching and loop support
  - Error handling and rollback mechanisms
  - Parallel execution support

- [ ] **Recipe Ecosystem Building**
  - Common platform Recipe library (YouTube, GitHub, X, Upwork, LinkedIn)
  - Recipe sharing and import mechanism
  - Community Recipe contribution process
  - Recipe performance benchmarking

### Medium Priority

- [ ] **Run System Enhancement**
  - Run templates for common workflows
  - Run metrics and analytics reports
  - Multi-format log export (CSV, Excel)
  - Run comparison and diff tools

- [ ] **Developer Experience**
  - Recipe testing framework
  - Recipe debugging tools
  - Better error messages
  - VS Code extension (syntax highlighting, intellisense)

- [ ] **Documentation and Examples**
  - Video tutorials for key workflows
  - Interactive documentation
  - More real-world Recipe examples
  - Best practices guide

### Low Priority

- [ ] **Advanced Features**
  - Recipe version management system
  - Multi-browser support (Firefox, Safari)
  - Distributed Recipe execution
  - Recipe marketplace
  - AI-powered Recipe optimization suggestions

- [ ] **Enterprise Features**
  - Team Recipe sharing
  - Execution audit logs
  - Access control
  - API call statistics

---

## Iteration Details

### 001: CDP Script Standardization
**Goal**: Unify websocat method, establish basic CDP operation patterns

**Achievements**:
- Standardized CDP script templates
- Unified websocat interface
- Basic operation command set

### 002: CDP Integration Refactor
**Goal**: Replace Shell scripts with native Python implementation, support proxy

**Achievements**:
- ~3,763 lines of Python CDP implementation
- Native WebSocket connection
- Proxy configuration support
- Intelligent retry mechanism
- CLI tools (Click framework)

### 003: Recipe Automation System Design
**Goal**: Design Recipe system, solidify high-frequency operations, accelerate AI reasoning

**Achievements**:
- Recipe system architecture design
- `/frago.recipe` command design
- Recipe creation and update workflow
- Recipe storage and naming conventions

### 004: Recipe Architecture Refactor
**Goal**: Metadata-driven + AI-First design

**Achievements**:
- Metadata parser (YAML frontmatter)
- Recipe registry (three-level lookup path)
- Recipe executor (multi-runtime)
- CLI command group (list/info/run)
- AI-understandable field design

### 005: Run Command System
**Goal**: Provide persistent context management for AI agents

**Achievements**:
- Topic-based Run instance creation and management
- RapidFuzz-based fuzzy matching auto-discovery
- JSONL structured logging (100% parseable)
- Persistent context storage
- `/frago.run` slash command integration
- Complete test coverage

**Key Features**:
- **Knowledge Accumulation**: Validated scripts persist across sessions
- **Auditability**: Complete operation history in JSONL format
- **Resumability**: AI can resume exploration days later
- **Token Efficiency**: 93.5% token savings vs. repeated exploration

### 006: Init Command
**Goal**: One-click environment initialization after user installation

**Achievements**:
- Parallel dependency check (Node.js, Claude Code)
- Smart installation of missing components
- Authentication configuration (official/custom endpoints)
- Config persistence

### 007: Init Resource Installation
**Goal**: Auto-install slash commands and example Recipes

**Achievements**:
- Slash commands installed to `~/.claude/commands/`
- User-level Recipe directory creation
- Example Recipe copying
- Resource status view

### 008: GUI App Mode
**Goal**: Provide desktop GUI interface for non-CLI users

**Achievements**:
- pywebview-based desktop application
- Cross-platform support (Linux, macOS, Windows)
- Recipe management interface
- Command execution interface
- Dynamic window sizing based on screen

### 009: GUI Design Redesign
**Goal**: Improve visual experience and user cognition

**Achievements**:
- GitHub Dark color scheme (professional, low eye strain)
- Clear visual hierarchy (input > content > navigation)
- Interaction feedback (loading states, animations)
- Native window title bar (resolved macOS close hang issue)

### 010: Agent Session Monitoring
**Goal**: Real-time monitoring and persistence of Claude Code session data

**Achievements**:
- watchdog-based file system monitoring
- JSONL incremental parsing
- Session data persistence (`~/.frago/sessions/`)
- Multi-agent architecture (extensible to Cursor, Cline)
- CLI commands (list, show, watch)

**Key Features**:
- **Real-time Display**: See Agent execution status as it happens
- **Data Persistence**: All session data saved for later analysis
- **Concurrency Isolation**: Multiple sessions don't interfere
- **Extensibility**: Adapter pattern for future agent support

---

## Version History

### v0.1.0 (Released - 2025-11-26)

First official release, core infrastructure complete.

**Included Features**:
- Native CDP protocol layer (~3,763 lines Python, direct Chrome connection)
- Recipe metadata-driven architecture (chrome-js/python/shell runtime)
- Run command system (persistent task context, JSONL structured logs)
- Init command (dependency check, resource installation)
- Environment variable support (three-level config priority)
- Claude Code slash commands (/frago.run, /frago.recipe, /frago.exec)

### v0.2.0 (Released - 2025-11-26)

**Milestone**: Architecture Enhancement & Workspace Isolation

**Major Changes**:

1. **Recipe Directory-Based Structure**
   - Recipes changed from file-based to directory-based format
   - Each recipe is now a directory: `recipe_name/recipe.md + recipe.py + examples/`
   - Schemas and example data travel with recipes for shareability
   - Two recipe types clarified: Type A (external structures like DOM) vs Type B (self-defined structures like VideoScript)

2. **Single Run Mutex Mechanism**
   - System only allows one active Run context at a time
   - Added `uv run frago run release` command to release context
   - `set-context` rejects if another run is active (except for same run)
   - Design constraint to ensure focused work

3. **Workspace Isolation Principle**
   - All outputs must be in `projects/<run_id>/` directory
   - Recipes must specify `output_dir` parameter explicitly
   - Documented in `/frago.run` and `/frago.exec` commands

4. **Tool Priority Principle**
   - Priority: Recipe > frago commands > Claude Code tools
   - frago CDP commands are cross-agent compatible
   - Documented guidelines for search/browse operations

5. **Dependency Changes**
   - `pyperclip` moved from optional to base dependencies
   - Clipboard support now included by default

6. **Version Management**
   - `__version__` now reads from `pyproject.toml` via `importlib.metadata`
   - Single source of truth for version number

### v0.3.0 (Released - 2025-12-01)

**Milestone**: CLI Command Grouping & Resource Sync

**Major Changes**:

1. **CLI Command Grouping**
   - Commands organized into groups: `chrome`, `recipe`, `run`, `session`
   - `frago chrome navigate` instead of `frago navigate`
   - `frago recipe list` instead of `frago list`
   - Improved discoverability with `--help`

2. **Resource Sync Commands**
   - `frago publish` - Push project resources to system directories
   - `frago sync` - Push system resources to remote Git repo
   - `frago deploy` - Pull from remote Git repo to system
   - `frago dev-load` - Load system resources to project (dev only)

3. **Agent Command**
   - `frago agent "task"` - Execute AI-driven tasks
   - Integration with session monitoring

### v0.4.0 (Released - 2025-12-05)

**Milestone**: GUI App Mode & Session Monitoring

**Major Changes**:

1. **GUI App Mode (Feature 008)**
   - `frago gui` command launches desktop interface
   - pywebview backend (cross-platform)
   - Recipe management and execution
   - Optional dependency: `pip install frago-cli[gui]`

2. **GUI Design Redesign (Feature 009)**
   - GitHub Dark color scheme
   - Improved visual hierarchy
   - Native window title bar (resolved macOS hang)

3. **Agent Session Monitoring (Feature 010)**
   - Real-time Claude Code session tracking
   - JSONL parsing with watchdog
   - Session data persistence
   - `frago session list/show/watch` commands

### v0.5.0 (Planned)

**Milestone**: Recipe System Enhancement

**Core Goals**:
- Chrome-JS parameter injection (solve current JS script parameter passing issue)
- Workflow orchestration enhancement (conditional branching, loops, error handling)
- Common platform Recipe library expansion (YouTube, GitHub, Upwork)

**Secondary Goals**:
- Run system template support
- Log export (CSV/Excel)

### v1.0.0 (Long-term Goal)

**Milestone**: Production Ready

**Core Goals**:
- Stable public API
- Comprehensive documentation and tutorials
- Community Recipe marketplace

**Secondary Goals**:
- Multi-browser support (Firefox, Safari)
- Enterprise features (team sharing, audit logs, access control)
