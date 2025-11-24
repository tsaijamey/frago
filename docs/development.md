[简体中文](development.zh-CN.md)

# Frago Development Guide

## Project Directory Structure

```
Frago/
├── README.md                        # Project description
├── CLAUDE.md                        # Project configuration (tech stack, code style)
├── .claude/
│   ├── commands/                    # Claude Code Slash Commands
│   │   ├── frago_start.md          # AI information collection command
│   │   ├── frago_storyboard.md     # AI storyboard planning command
│   │   ├── frago_generate.md       # AI video generation command (create recording scripts)
│   │   ├── frago_evaluate.md       # AI material evaluation command
│   │   ├── frago_merge.md          # AI video synthesis command
│   │   └── frago_recipe.md         # Recipe management command (create/update/list)
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
│   │   └── tools/                   # Development tools
│   │       └── function_mapping.py  # CDP function mapping validation tool
│   ├── chrome_cdp_launcher.py       # Chrome CDP launcher (cross-platform)
│   ├── pipeline_master.py           # Pipeline master controller
│   └── requirements.txt             # Python dependencies
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
│   └── 004-recipe-architecture-refactor/ # Recipe architecture refactor
│
├── docs/                            # Project documentation
│   ├── architecture.md              # Technical architecture
│   ├── user-guide.md                # User guide
│   ├── development.md               # Development guide
│   ├── roadmap.md                   # Project progress
│   └── examples.md                  # Example reference
│
├── projects/                        # Video project working directories
│   └── <project_name>/
│       ├── research/                # AI information collection output
│       │   ├── report.json
│       │   └── screenshots/
│       ├── shots/                   # AI storyboard planning output
│       │   └── shot_xxx.json
│       ├── clips/                   # AI-generated video clips
│       │   ├── shot_xxx_record.sh   # AI-created recording scripts
│       │   ├── shot_xxx.mp4
│       │   └── shot_xxx_audio.mp3
│       ├── outputs/                 # Final video output
│       └── logs/                    # Execution logs
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
- **Script Orchestration**: Python 3.9+ (Recipe system + CDP tool layer)

## Development Standards

1. **Script locations**:
   - Command implementation scripts in `scripts/`
   - Python core scripts in `src/`

2. **File naming**:
   - Video clips: `shot_xxx.mp4` (based on timestamp)
   - Audio clips: `shot_xxx_audio.mp3` or `shot_xxx_1.mp3`
   - Screenshot files: Must use absolute paths

3. **Chrome CDP usage**:
   - prepare phase: Only for information collection
   - generate phase: Add visual guidance effects

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

1. Chrome must run through CDP launcher with port 9222 available
2. Screen recording permission must be authorized before recording
3. All screenshots must use absolute paths
4. Video length must be greater than or equal to total audio length
5. Must create `.completed` marker file after each shot completes

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
