[简体中文](development.zh-CN.md)

# Frago Development Guide

## Project Directory Structure

```
Frago/
├── README.md                        # Project description
├── CLAUDE.md                        # Project configuration (tech stack, code style)
├── .claude/
│   ├── commands/                    # Claude Code Slash Commands
│   │   ├── frago_run.md            # AI-driven complex task execution
│   │   ├── frago_recipe.md         # Recipe management command (create/test)
│   │   └── frago_exec.md           # One-time task execution
│   └── settings.local.json          # Project configuration
│
├── src/                             # Core Python code
│   ├── frago/                      # Frago core package
│   │   ├── cdp/                     # CDP protocol implementation (native WebSocket)
│   │   │   ├── client.py            # CDP client base class
│   │   │   ├── session.py           # Session management (connection/retry/events)
│   │   │   ├── config.py            # Configuration management (proxy support)
│   │   │   ├── logger.py            # Logging system
│   │   │   ├── retry.py             # Retry strategies
│   │   │   ├── exceptions.py        # Exception definitions
│   │   │   ├── types.py             # Data types
│   │   │   └── commands/            # CDP command implementations
│   │   │       ├── page.py          # Page operations (navigate/title/content)
│   │   │       ├── screenshot.py    # Screenshot functionality
│   │   │       ├── runtime.py       # JavaScript execution
│   │   │       ├── input.py         # Input operations (click)
│   │   │       ├── scroll.py        # Scroll operations
│   │   │       ├── wait.py          # Wait operations
│   │   │       ├── zoom.py          # Zoom operations
│   │   │       ├── status.py        # Status checks
│   │   │       └── visual_effects.py # Visual effects (spotlight/highlight)
│   │   ├── cli/                     # Command-line interface
│   │   │   ├── main.py              # CLI entry (Click framework)
│   │   │   ├── commands.py          # Basic CDP command implementations
│   │   │   └── recipe_commands.py   # Recipe management commands (list/info/run)
│   │   ├── recipes/                 # Recipe engine code (metadata-driven architecture)
│   │   │   ├── __init__.py          # Module exports
│   │   │   ├── metadata.py          # Metadata parsing and validation
│   │   │   ├── registry.py          # Recipe registry and discovery
│   │   │   ├── runner.py            # Recipe executor
│   │   │   ├── output_handler.py    # Output handling (stdout/file/clipboard)
│   │   │   └── exceptions.py        # Recipe exception definitions
│   │   ├── run/                      # Run command system (Feature 005)
│   │   │   ├── manager.py            # Run instance management
│   │   │   ├── logger.py             # JSONL structured logging
│   │   │   └── discovery.py          # RapidFuzz-based auto-discovery
│   │   ├── session/                   # Session monitoring (Feature 010)
│   │   │   ├── monitor.py             # File system monitoring (watchdog)
│   │   │   ├── parser.py              # JSONL incremental parsing
│   │   │   ├── storage.py             # Session data persistence
│   │   │   ├── models.py              # Data models (Session, Step, ToolCall)
│   │   │   └── formatter.py           # Output formatters (terminal/JSON)
│   │   ├── gui/                        # GUI app mode (Feature 008-009)
│   │   │   ├── app.py                  # Main application (pywebview)
│   │   │   ├── api.py                  # JS-Python bridge API
│   │   │   ├── models.py               # GUI configuration models
│   │   │   └── assets/                 # HTML/CSS/JS frontend
│   │   │       └── index.html
│   │   └── tools/                    # Development tools
│   │       └── function_mapping.py   # CDP function mapping validation tool
│   ├── chrome_cdp_launcher.py        # Chrome CDP launcher (cross-platform)
│   └── requirements.txt              # Python dependencies
│
├── examples/                        # Example Recipes (not packaged in wheel)
│   └── atomic/
│       └── chrome/
│           ├── test_inspect_tab.js/.md                  # Page inspection diagnostics
│           ├── youtube_extract_video_transcript.js/.md  # YouTube subtitle extraction
│           ├── upwork_extract_job_details_as_markdown.js/.md  # Upwork job details
│           └── x_extract_tweet_with_comments.js/.md    # X(Twitter) tweet+comment extraction
│
├── specs/                           # Feature specs and iteration records
│   ├── 001-standardize-cdp-scripts/ # CDP script standardization
│   ├── 002-cdp-integration-refactor/# CDP integration refactor (Python implementation)
│   ├── 003-skill-automation/        # Recipe system design
│   ├── 004-recipe-architecture-refactor/ # Recipe architecture refactor
│   ├── 005-run-command-system/      # Run system implementation
│   ├── 006-init-command/            # Init command design
│   ├── 007-init-commands-setup/     # Resource installation
│   ├── 008-gui-app-mode/            # GUI desktop application
│   ├── 009-gui-design-redesign/     # GUI visual design optimization
│   └── 010-agent-session-monitor/   # Agent session monitoring
│
├── docs/                            # Project documentation
│   ├── architecture.md              # Technical architecture
│   ├── user-guide.md                # User guide
│   ├── development.md               # Development guide
│   ├── roadmap.md                   # Project progress
│   └── examples.md                  # Example reference
│
├── projects/                        # Run instance working directories
│   └── <run_id>/                   # Topic-based task context
│       ├── logs/
│       │   └── execution.jsonl      # Structured JSONL logs
│       ├── screenshots/             # Timestamped screenshots
│       │   └── 20250124_143022.png
│       ├── scripts/                 # Validated working scripts
│       │   └── extract_transcript.js
│       └── outputs/                 # Result files
│           ├── result.json
│           └── report.md
│
├── chrome_profile/                  # Chrome user configuration
└── pyproject.toml                   # Python package configuration (uv managed)
```

## CDP Command Directory Structure

CDP functionality organized by type in `src/frago/cdp/commands/`:

```
src/frago/cdp/commands/
├── __init__.py         # Command module exports
├── page.py             # Page operations (navigate, get title/content)
├── screenshot.py       # Screenshot functionality
├── runtime.py          # JavaScript execution
├── input.py            # Input operations (click)
├── scroll.py           # Scroll operations
├── wait.py             # Wait operations
├── zoom.py             # Zoom operations
├── status.py           # Status checks
└── visual_effects.py   # Visual effects (highlight, pointer, spotlight, annotation)
```

All CDP functionality accessed through unified CLI interface (`uv run frago <command>`).

## Tech Stack

- **AI Orchestration**: Claude Code (task analysis, Recipe scheduling, workflow design)
- **Browser Control**: Chrome DevTools Protocol (CDP) - native WebSocket
- **Multi-Runtime Support**: Chrome JS, Python, Shell
- **Task Management**: Run command system (context persistence, JSONL logs)
- **Session Monitoring**: watchdog + incremental JSONL parsing
- **GUI Framework**: pywebview (cross-platform WebView)
- **Script Orchestration**: Python 3.9+ (Recipe system + CDP tool layer)

## Development Standards

1. **Script locations**:
   - CDP command implementations in `src/frago/cdp/commands/`
   - Recipe engine code in `src/frago/recipes/`
   - Run system code in `src/frago/run/`
   - Session monitoring code in `src/frago/session/`
   - GUI application code in `src/frago/gui/`
   - Example Recipes in `examples/atomic/chrome/`

2. **File naming**:
   - Screenshot files: Must use absolute paths
   - JSONL logs: `execution.jsonl` (one log per Run instance)
   - Recipe scripts: `<platform>_<operation>_<object>.js/.py/.sh`
   - Recipe metadata: `<recipe_name>.md` (with YAML frontmatter)

3. **Run System Usage**:
   - Create Run instance for exploration tasks
   - All CDP operations auto-logged to current Run
   - Manual logs for observations and analysis
   - Archive completed Runs for future reference

## Function Mapping Validation Tool

The function mapping tool validates completeness and consistency of all CDP functionality.

### Run Function Mapping Validation

```bash
# Generate console report
uv run python -m frago.tools.function_mapping

# Generate detailed HTML report
uv run python -m frago.tools.function_mapping --format html --output function_mapping_report.html

# Generate JSON report
uv run python -m frago.tools.function_mapping --format json --output function_mapping_report.json
```

### View Function Coverage

The tool scans all CDP function implementations and generates coverage report:

```
================================
Function Mapping Validation Report
================================
Total functions: 18
Implemented: 18 (100.0%)
Behavior consistent: 18 (100.0%)
================================
```

## Important Notes

1. **Chrome CDP Connection**:
   - Chrome must run with `--remote-debugging-port=9222`
   - Use `chrome_cdp_launcher.py` for cross-platform compatibility
   - Verify port 9222 is accessible before operations

2. **File Paths**:
   - Always use absolute paths for screenshots and output files
   - Relative paths may cause issues in different execution contexts

3. **Run System**:
   - Create Run instance before exploration tasks
   - All operations automatically logged to JSONL
   - Archive Runs to maintain clean working directory

4. **Recipe Development**:
   - Always include YAML frontmatter in metadata file
   - Test Recipe execution before committing
   - Follow naming conventions for discoverability

## Recipe Development Standards

### Recipe File Structure

Each Recipe contains two files:
- `<recipe_name>.js`/`.py`/`.sh` - Execution script
- `<recipe_name>.md` - Metadata and documentation (YAML frontmatter)

### Metadata Specification

```yaml
---
name: recipe_name
type: atomic                    # atomic | workflow
runtime: chrome-js              # chrome-js | python | shell
version: "1.0"
description: "Short function description (<200 chars)"
use_cases: ["Scenario 1", "Scenario 2"]
tags: ["tag1", "tag2"]
output_targets: [stdout, file]  # stdout | file | clipboard
inputs:
  param1:
    type: string
    description: "Parameter description"
    required: true
outputs:
  result1:
    type: string
    description: "Output description"
---
```

### Markdown Documentation Structure

Standard 6 sections:
1. Function Description
2. Usage
3. Prerequisites
4. Expected Output
5. Notes
6. Update History

### Recipe Naming Convention

Descriptive naming: `<platform>_<operation>_<object>.js`

Examples:
- `youtube_extract_video_transcript.js`
- `upwork_extract_job_details_as_markdown.js`
- `x_extract_tweet_with_comments.js`

## Recipe Storage Structure

- **Code-resource separation**:
  - `src/frago/recipes/` - Python engine code (no Recipe scripts)
  - `examples/atomic/chrome/` - Example Recipe scripts + metadata documentation
  - `~/.frago/recipes/` - User-level Recipes (to be implemented)
  - `.frago/recipes/` - Project-level Recipes (to be implemented)

- **Lookup priority**: Project-level > User-level > Example-level

## Testing

```bash
# Run all tests
uv run pytest

# Run specific tests
uv run pytest tests/integration/recipe/

# Test Recipe execution
uv run pytest tests/integration/recipe/test_recipe_execution.py
```

## Contribution Guidelines

1. Fork the project
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

## Code Review Checklist

- [ ] All CDP commands have corresponding CLI interfaces
- [ ] Recipe metadata complete and compliant
- [ ] New features have test coverage
- [ ] Code complies with project standards
- [ ] Documentation updated
