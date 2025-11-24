[简体中文](roadmap.zh-CN.md)

# Frago Project Progress

## Project Status

📍 **Current Phase**: Core architecture complete, AI command system in implementation

**Completed**:
- ✅ Native CDP protocol layer (~3,763 lines of Python)
- ✅ CLI tools and command system
- ✅ Pipeline scheduling framework
- ✅ Recipe metadata-driven architecture

**In Progress**:
- 🔄 AI Slash Commands implementation (5 phase commands)
- 🔄 Recipe system refinement (multi-language support, user-level Recipes)
- 🔄 Pipeline integration with Claude AI

**Technical Highlights**:
- 🏆 Native CDP (no Playwright/Selenium dependencies)
- 🏆 AI-First design (Claude AI hosts task execution and workflow orchestration)
- 🏆 Recipe acceleration system (solidify high-frequency operations, avoid repeated AI reasoning)
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

### Pipeline System

- [x] **Pipeline Master Controller**
  - 5-stage scheduling (start/storyboard/generate/evaluate/merge)
  - .done file synchronization mechanism
  - Chrome auto-launch and cleanup
  - Complete logging system

- [x] **Slash Commands Configuration** (5 AI stage commands)
  - `/frago.start` - AI autonomous information collection
  - `/frago.storyboard` - AI autonomous storyboard design
  - `/frago.generate` - AI creates recording scripts
  - `/frago.evaluate` - AI quality evaluation
  - `/frago.merge` - AI video synthesis

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

- [x] **Spec System** (4 iterations)
  - 001: CDP script standardization (unified websocat method)
  - 002: CDP integration refactor (Python implementation + proxy support)
  - 003: Recipe automation system design
  - 004: Recipe architecture refactor (metadata-driven + AI-First design)
    - Phase 1-3 completed: Basic architecture + AI availability (US0)
    - Pending: Multi-language support (US1) + User-level Recipes (US2) + Workflow orchestration (US3)

## Pending Features 📝

### High Priority

- [ ] **AI Slash Commands Implementation**
  - [ ] `/frago.start` - AI information collection logic
  - [ ] `/frago.storyboard` - AI storyboard design logic
  - [ ] `/frago.generate` - AI recording script generation
  - [ ] `/frago.evaluate` - AI quality evaluation
  - [ ] `/frago.merge` - AI video synthesis

- [ ] **Recipe System Refinement (Iteration 004 Remaining)**
  - [x] Phase 1-3: Basic architecture + AI availability (metadata framework, registry, executor, CLI)
  - [ ] Phase 4: Multi-language Recipe support (Python/Shell runtime execution)
  - [ ] Phase 5: User-level Recipe directory (`~/.frago/recipes/` + `init` command)
  - [ ] Phase 6: Workflow Recipe orchestration (call multiple atomic Recipes)
  - [ ] Phase 7: Parameter validation and type checking
  - [ ] Phase 8: Project-level Recipe support (`.frago/recipes/`)
  - [ ] `/frago.recipe` - AI interactive Recipe creation (slash command)
  - [ ] `/frago.recipe update` - Iterative Recipe updates

- [ ] **Pipeline Integration**
  - [ ] Integration between Pipeline and Claude CLI
  - [ ] .done file monitoring and stage switching
  - [ ] Error handling and retry mechanism

### Medium Priority

- [ ] **Audio Generation**
  - [ ] Volcano Engine voice cloning API integration
  - [ ] Audio-video duration sync verification
  - [ ] Multiple audio segment support

- [ ] **Recording Optimization**
  - [ ] Recording script template system
  - [ ] Visual effects timeline control
  - [ ] Keyframe quality checking

- [ ] **Recipe Ecosystem**
  - [ ] Common platform recipe library (YouTube/GitHub/Twitter)
  - [ ] Recipe sharing and import mechanism
  - [ ] Recipe performance optimization

### Low Priority

- [ ] Code display recording (VS Code recording)
- [ ] Local static page generation (for MVP demos)
- [ ] Progress monitoring Dashboard
- [ ] Recipe version management system
- [ ] Multilingual voiceover support

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

## Version History

### v0.1.0 (Planned)
- Core CDP implementation
- Basic Pipeline framework
- Recipe metadata system
- 4 example Recipes

### v0.2.0 (Planned)
- Complete AI Slash Commands implementation
- Recipe system refinement
- Pipeline integration with Claude AI
- Audio generation functionality

### v0.3.0 (Planned)
- Recording optimization features
- Recipe ecosystem building
- Performance optimization

### v1.0.0 (Long-term Goal)
- Complete feature release
- Stable public API
- Comprehensive documentation and examples
- Community Recipe library
