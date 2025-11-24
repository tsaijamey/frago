[简体中文](roadmap.zh-CN.md)

# Frago Project Progress

## Project Status

📍 **Current Phase**: Three-system architecture complete (Run + Recipe + CDP)

**Completed**:
- ✅ Native CDP protocol layer (~3,763 lines of Python)
- ✅ CLI tools and command system
- ✅ Recipe metadata-driven architecture
- ✅ Run command system (Feature 005)

**In Progress**:
- 🔄 Recipe system refinement (multi-language support, user-level Recipes)
- 🔄 Workflow Recipe orchestration
- 🔄 Claude Code slash command integration

**Technical Highlights**:
- 🏆 Native CDP (no Playwright/Selenium dependencies)
- 🏆 AI-First design (Claude AI hosts task execution and workflow orchestration)
- 🏆 Recipe acceleration system (solidify high-frequency operations, avoid repeated AI reasoning)
- 🏆 Run System (AI's working memory with persistent context)
- 🏆 Lightweight deployment (~2MB dependencies)

## Completed Features ✅

### Core CDP Implementation (Iterations 001-002)

- [x] **Native CDP Protocol Layer** (~3,763 lines of Python code)
  - WebSocket direct to Chrome (no Node.js relay)
  - Intelligent retry mechanism (proxy environment optimized)
  - Complete command modules (page/screenshot/runtime/input/scroll/wait/zoom/status/visual_effects)
  - Type-safe configuration system

- [x] **CLI Tools** (Click framework)
  - `uv run frago <command>` - Unified interface for all CDP functionality
  - Proxy configuration support (environment variables + CLI parameters)
  - Function mapping validation tool (100% coverage)

- [x] **Cross-Platform Chrome Launcher**
  - macOS/Linux support
  - Auto profile initialization
  - Window size control (1280x960, position 20,20)

### Run Command System (Iteration 005)

- [x] **Topic-Based Task Management**
  - Run instance creation and discovery
  - RapidFuzz-based fuzzy matching (80% threshold)
  - Context persistence across sessions
  - Lifecycle: init → execute → log → archive

- [x] **Structured JSONL Logs**
  - 100% programmatically parseable format
  - Each line is valid JSON
  - Operation tracking (navigate, click, screenshot, etc.)
  - Error logging with stack traces
  - Auditable execution history

- [x] **Persistent Context Storage**
  - `projects/<run_id>/` directory structure
  - `logs/execution.jsonl` - Complete operation history
  - `screenshots/` - Timestamped images
  - `scripts/` - Validated working scripts
  - `outputs/` - Result files and reports

- [x] **AI-Driven Task Execution**
  - `/frago.run` slash command integration
  - Automatic Run instance discovery
  - Recipe selection and orchestration
  - Complete test coverage

### Recipe System (Iterations 003-004)

- [x] **Recipe Metadata-Driven Architecture** (Iteration 004 Phase 1-3)
  - Metadata parser (YAML frontmatter)
  - Recipe registry (three-level lookup path: project>user>example)
  - Recipe executor (chrome-js/python/shell runtime)
  - Output handler (stdout/file/clipboard)
  - CLI command group (list/info/run)

- [x] **Recipe Management Commands** (`/frago.recipe`)
  - AI interactive exploration to create Recipes (003 design)
  - `recipe list` - List all Recipes (supports JSON format)
  - `recipe info` - View Recipe detailed information
  - `recipe run` - Execute Recipe (parameter validation + output handling)

- [x] **Recipe Storage Structure**
  - Code-resource separation (`src/frago/recipes/` for engine code)
  - Example Recipes in `examples/atomic/chrome/`
  - Descriptive naming (`<platform>_<operation>_<object>.js`)
  - Supporting metadata documentation (.md + YAML frontmatter)
  - AI-understandable fields (description/use_cases/tags/output_targets)

### Project Iteration Records

- [x] **Spec System** (5 iterations)
  - 001: CDP script standardization (unified websocat method)
  - 002: CDP integration refactor (Python implementation + proxy support)
  - 003: Recipe automation system design
  - 004: Recipe architecture refactor (metadata-driven + AI-First design)
    - Phase 1-3 completed: Basic architecture + AI availability (US0)
    - Pending: Multi-language support (US1) + User-level Recipes (US2) + Workflow orchestration (US3)
  - 005: Run command system (completed)
    - Topic-based task management
    - JSONL structured logging
    - AI auto-discovery mechanism

## Pending Features 📝

### High Priority

- [ ] **Recipe System Refinement (Iteration 004 Remaining)**
  - [x] Phase 1-3: Basic architecture + AI availability (metadata framework, registry, executor, CLI)
  - [ ] Phase 4: Multi-language Recipe support (Python/Shell runtime execution)
  - [ ] Phase 5: User-level Recipe directory (`~/.frago/recipes/` + `init` command)
  - [ ] Phase 6: Workflow Recipe orchestration (call multiple atomic Recipes)
  - [ ] Phase 7: Parameter validation and type checking
  - [ ] Phase 8: Project-level Recipe support (`.frago/recipes/`)

- [ ] **Claude Code Integration**
  - [x] `/frago.run` - AI-driven task execution
  - [x] `/frago.recipe` - Recipe management
  - [x] `/frago.exec` - One-time task execution
  - [ ] Enhanced AI orchestration logic
  - [ ] Better Recipe selection algorithm

- [ ] **Run System Enhancement**
  - [ ] Run templates for common workflows
  - [ ] Run metrics and analytics
  - [ ] Export Run logs to different formats
  - [ ] Run comparison and diff tools

### Medium Priority

- [ ] **Recipe Ecosystem**
  - [ ] Common platform recipe library (YouTube/GitHub/X/Upwork)
  - [ ] Recipe sharing and import mechanism
  - [ ] Recipe performance optimization
  - [ ] Community Recipe contributions

- [ ] **Documentation and Examples**
  - [ ] Video tutorials for key workflows
  - [ ] Interactive documentation
  - [ ] More real-world Recipe examples
  - [ ] Best practices guide

- [ ] **Developer Experience**
  - [ ] Recipe testing framework
  - [ ] Recipe debugging tools
  - [ ] Better error messages
  - [ ] IDE integrations (VS Code extension)

### Low Priority

- [ ] **Advanced Features**
  - [ ] Recipe version management system
  - [ ] Multi-browser support (Firefox, Safari)
  - [ ] Distributed Recipe execution
  - [ ] Recipe marketplace
  - [ ] AI-powered Recipe optimization suggestions

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

### 003: Recipe Automation System
**Goal**: Design Recipe system, solidify high-frequency operations, accelerate AI reasoning

**Achievements**:
- Recipe system architecture design
- `/frago.recipe` command design
- Recipe creation and update workflow
- Recipe storage and naming conventions

### 004: Recipe Architecture Refactor
**Goal**: Metadata-driven + AI-First design, enabling AI to autonomously discover and use Recipes

**Achievements (Phase 1-3 completed)**:
- Metadata parser (YAML frontmatter)
- Recipe registry (three-level lookup path)
- Recipe executor (multi-runtime support)
- CLI command group (list/info/run)
- AI-understandable field design

**Pending (Phase 4-8)**:
- Python/Shell runtime execution
- User-level Recipe directory
- Workflow Recipe orchestration
- Parameter validation and type checking
- Project-level Recipe support

### 005: Run Command System
**Goal**: Provide persistent context management for AI agents, serving as working memory

**Achievements (Completed)**:
- Topic-based Run instance creation and management
- RapidFuzz-based fuzzy matching for auto-discovery
- JSONL structured logging (100% parseable)
- Persistent context storage (`projects/<run_id>/`)
- Integration with CDP commands and Recipe system
- `/frago.run` slash command for Claude Code
- Complete test coverage

**Key Features**:
- **Knowledge Accumulation**: Validated scripts persist across sessions
- **Auditability**: Complete operation history in JSONL format
- **Resumability**: AI can resume exploration days later
- **Error Recovery**: Structured error logging for debugging
- **Token Efficiency**: 93.5% token savings vs. repeated exploration

## Version History

### v0.1.0 (Current)
- Core CDP implementation (~3,763 lines)
- Recipe metadata-driven architecture
- Run command system (Feature 005)
- 4 example Recipes
- Claude Code slash commands (/frago.run, /frago.recipe, /frago.exec)

### v0.2.0 (Planned - Q1 2025)
- Recipe system refinement (Phase 4-8)
  - Python/Shell runtime support
  - User-level Recipe directory
  - Workflow Recipe orchestration
- Run System enhancements
  - Run templates
  - Export tools
- Enhanced Claude Code integration

### v0.3.0 (Planned - Q2 2025)
- Recipe ecosystem building
  - Common platform recipe library
  - Recipe sharing mechanism
- Developer experience improvements
  - Recipe testing framework
  - Better debugging tools
- Performance optimization

### v1.0.0 (Long-term Goal - Q4 2025)
- Stable public API
- Comprehensive documentation and tutorials
- Community Recipe marketplace
- Multi-browser support
- Enterprise features (distributed execution, analytics)
