[简体中文](architecture.zh-CN.md)

# Frago Technical Architecture

## System Architecture

```
Frago Usage Flow Architecture
==============================

┌─────────────────────────────────────────────────────────────────────┐
│                        User Entry (Claude Code)                      │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ▼                 ▼                 ▼
         ┌─────────┐       ┌─────────┐      ┌─────────┐
         │/frago  │       │/frago  │      │  Direct │
         │  .run   │       │ .recipe │      │CLI Cmds │
         └─────────┘       └─────────┘      └─────────┘
                │                 │                 │
                │                 │                 │
                ▼                 ▼                 ▼
┌───────────────────────────────────────────────────────────────────────┐
│                       AI Task Analysis Layer                           │
│  - Understand user intent                                              │
│  - Discover/create Run instances                                       │
│  - Select appropriate Recipes                                          │
│  - Orchestrate execution plans                                         │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ▼                 ▼                 ▼
         ┌──────────┐      ┌──────────┐     ┌──────────┐
         │ Recipe   │      │   CDP    │     │ Python/  │
         │Dispatch  │      │Commands  │     │  Shell   │
         │(chrome-js│      │(navigate,│     │  Scripts │
         │/python/  │      │ click,   │     │          │
         │ shell)   │      │screenshot│     │          │
         └──────────┘      └──────────┘     └──────────┘
                │                 │                 │
                └─────────────────┼─────────────────┘
                                  │
                                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│                     Execution Engine (Multi-Runtime)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │
│  │ Chrome CDP  │  │   Python    │  │    Shell    │                   │
│  │  WebSocket  │  │   Runtime   │  │   Runtime   │                   │
│  └─────────────┘  └─────────────┘  └─────────────┘                   │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ▼                 ▼                 ▼
         ┌──────────┐      ┌──────────┐     ┌──────────┐
         │  JSONL   │      │  Output  │     │   Run    │
         │Structured│      │  Files   │     │ Context  │
         │   Logs   │      │(JSON/MD/ │     │Persistence│
         │          │      │  TXT)    │     │          │
         └──────────┘      └──────────┘     └──────────┘
                │                 │                 │
                └─────────────────┼─────────────────┘
                                  │
                                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│                           Final Output                                 │
│  - Task execution report                                               │
│  - Structured data files                                               │
│  - Auditable complete logs                                             │
│  - Reusable Run instances                                              │
└───────────────────────────────────────────────────────────────────────┘


Recipe Three-Level Priority System:
====================================

┌─────────────────────────────────────┐
│  Project (.frago/recipes/)         │  ← Highest priority
│  - Project-specific Recipes         │
│  - Team shared                      │
└─────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  User (~/.frago/recipes/)          │  ← Medium priority
│  - User personal Recipes            │
│  - Reusable across projects         │
└─────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Example (examples/)                │  ← Lowest priority
│  - Official examples                │
│  - Can copy to User or Project      │
└─────────────────────────────────────┘


Data Flow Examples:
===================

Scenario 1: /frago.run "Extract Python jobs from Upwork"
─────────────────────────────────────────────────────────
User → /frago.run → AI analysis → Discover Recipe: upwork_extract_job_details
     → Create Run: cong-upwork-ti-qu-python-zhi-wei
     → Call Recipe(chrome-js) → CDP execution → Output markdown file
     → Record JSONL logs → Persist Run context


Scenario 2: /frago.recipe "Extract YouTube subtitles"
──────────────────────────────────────────────────────
User → /frago.recipe → AI generates Recipe → Save to .frago/recipes/
     → Test Recipe → CDP execution → Verify output
     → Add to Recipe registry


Scenario 3: Direct CLI commands
────────────────────────────────
Developer → uv run frago navigate https://...
          → CDP client → WebSocket → Chrome
          → Return execution result
```

## Core Differences Comparison

### Frago vs Playwright / Selenium

| Dimension | **Playwright / Selenium** | **Frago** |
|-----------|---------------------------|-----------|
| **Core Positioning** | Test automation framework | AI-driven multi-runtime automation framework |
| **Design Goal** | Verify software quality | Reusable automation scripts and task orchestration |
| **Main Scenarios** | E2E testing, UI automation testing | Browser automation, data collection, workflow orchestration |
| **Browser Management** | Complete lifecycle (launch→test→close) | Connect to existing CDP instance (persistent session) |
| **Output Products** | Test reports (✅❌ statistics) | Structured data (JSONL logs) |
| **Core Capabilities** | Assertion validation, concurrent testing | Recipe system, Run context management, multi-runtime support |
| **Dependency Size** | ~400MB + Node.js runtime | ~2MB (pure Python WebSocket) |
| **Architecture** | Dual RPC (Python→Node.js→Browser) | Direct CDP (Python→Browser) |
| **Use Cases** | Quality assurance, regression testing | Data collection, automation scripts, AI-assisted tasks |

**Key Differences**:
- ✅ **Persistent browser sessions** - Playwright launches new browser per test, Frago connects to running Chrome instance
- ✅ **Recipe metadata-driven** - Reusable automation scripts with three-level priority management
- ✅ **Zero relay layer** - Direct WebSocket to CDP, no Node.js relay, lower latency
- ✅ **Lightweight deployment** - No Node.js environment needed, pure Python implementation

### Frago vs Browser Use

| Dimension | **Browser Use** | **Frago** |
|-----------|----------------|-----------|
| **Core Positioning** | General AI automation platform | AI-assisted reusable automation framework |
| **AI Role** | Task executor (user says "do what") | Task orchestrator (AI schedules Recipes and commands) |
| **Execution Mode** | Single natural language task → AI autonomously completes | Recipe manifest → AI scheduling → Multi-runtime execution |
| **Decision Scope** | How to complete single task (like form filling, data scraping) | How to orchestrate complex workflows (which Recipes to call, how to combine) |
| **Complexity Handling** | AI dynamically adapts to DOM changes | Precise control + Recipe solidifies high-frequency operations |
| **Token Consumption** | Full AI reasoning, massive token consumption | AI only for orchestration, Recipe execution without token consumption |
| **Result Controllability** | Medium (AI may deviate) | High (metadata manifest defines clearly) |
| **Execution Speed** | Slow (needs LLM reasoning + trial and error) | Fast (direct command execution/Recipe reuse) |
| **Cost Model** | Cloud service $500/month + LLM API calls | Self-hosted free (optional Claude API) |
| **Typical Use Cases** | Auto-fill forms, data scraping | Reusable data collection, batch task processing, workflow automation |

**Core Differences**:
- 💡 **Token Efficiency Theory Support** - Follows [Anthropic's Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) design philosophy: Let AI generate code to call tools rather than full reasoning for every operation. Cases show token consumption can be reduced from 150k to 2k (**98.7% reduction**)
- 📦 **Recipe System** - Solidifies high-frequency operations as executable code (Chrome JS/Python/Shell), AI only responsible for orchestration scheduling, avoiding repeated DOM operation reasoning
- 🔄 **Multi-Runtime Support** - Chrome JS, Python, Shell three runtimes can be combined, data processing completed in code rather than repeatedly through AI context
- 📊 **Structured Logs** - JSONL format 100% parsable, facilitates auditing and analysis
- ⚡ **Hybrid Strategy** - AI orchestration (workflow design) + Precise control (Recipe execution) + Context accumulation (Run management)

## Technical Architecture Selection

### Why Choose Native CDP Over Playwright?

**Lessons from Browser Use** (they migrated from Playwright to native CDP):

1. **Performance Bottleneck Elimination**
   ```
   Playwright: Python → Node.js relay → CDP → Chrome
   Frago:     Python → CDP → Chrome
   ```
   - Dual RPC architecture produces noticeable latency with many CDP calls
   - After migration: "Massively increased speed for element extraction and screenshots"

2. **Known Playwright Limitations**
   - ❌ `fullPage=True` screenshots crash on pages >16,000px
   - ❌ Node.js process hangs indefinitely when tab crashes
   - ❌ Cross-domain iframe (OOPIF) support gaps
   - ✅ Native CDP directly accesses full protocol, no abstraction layer limitations

3. **Dependency Lightweighting**
   - Playwright: ~400MB + Node.js runtime
   - Frago: ~2MB (websocket-client)

**Conclusion**: For automation scenarios requiring **frequent CDP calls, extensive screenshots, persistent sessions**, native CDP is the better choice.

### Recipe System: AI's Accelerator

**Design Philosophy**:
- ❌ **Not** replacing AI autonomous decision-making
- ✅ **Is** avoiding AI repeatedly reasoning same DOM operations

**Working Mechanism**:
```
High-frequency operation path:
  First encounter → AI interactive exploration → Solidify as Recipe → Subsequent direct reuse

  Example: YouTube subtitle extraction
  1. User: /frago.recipe "Extract YouTube subtitles"
  2. AI: Interactively locate button, extract text
  3. Solidify: youtube_extract_video_transcript.js + metadata documentation
  4. Reuse: uv run frago recipe run youtube_extract_video_transcript

  Savings: 3-5 rounds of LLM reasoning each time → 1 script execution (~100ms)
```

**Three Ways to Use Recipes**:
```bash
# Method 1: Recommended - Metadata-driven (parameter validation, output handling)
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file transcript.txt

# Method 2: Discover available Recipes
uv run frago recipe list --format json

# Method 3: Traditional method - Direct JS execution (bypass metadata system)
uv run frago exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
```

**Difference from Browser Use**:
- Browser Use: Every task needs LLM reasoning ($$$)
- Frago: AI decision-making (storyboard design) + Recipe acceleration (repeated operations)

### Recipe Metadata-Driven Architecture (Iteration 004)

**Design Philosophy: Code-Resource Separation**
- `src/frago/recipes/` - Python engine code (metadata parsing, registry, executor)
- `examples/atomic/chrome/` - Example Recipe scripts + metadata documentation
- `~/.frago/recipes/` - User-level Recipes (to be implemented)
- `.frago/recipes/` - Project-level Recipes (to be implemented)

**Metadata File Structure (Markdown + YAML frontmatter)**:
```markdown
---
name: youtube_extract_video_transcript
type: atomic                    # atomic | workflow
runtime: chrome-js              # chrome-js | python | shell
version: "1.0"
description: "Extract complete YouTube video subtitles"
use_cases: ["Video content analysis", "Subtitle download"]
tags: ["youtube", "transcript", "web-scraping"]
output_targets: [stdout, file]
inputs: {}
outputs:
  transcript:
    type: string
    description: "Complete subtitle text"
---

# Function Description
...Detailed explanation...
```

**Metadata Field Explanation**:
- **Required fields**: `name`, `type`, `runtime`, `version`, `inputs`, `outputs`
- **AI-understandable fields** (for discovering and selecting Recipes):
  - `description`: Short function description (<200 chars), helps AI understand purpose
  - `use_cases`: Applicable scenarios list, helps AI judge applicability
  - `tags`: Semantic tags for classification and search
  - `output_targets`: Supported output methods (stdout/file/clipboard), lets AI choose correct output option

**Three-Level Lookup Path (Priority)**:
1. Project-level: `.frago/recipes/` (current working directory)
2. User-level: `~/.frago/recipes/` (user home directory)
3. Example-level: `examples/` (repository root)

**Three Runtime Support**:
- `chrome-js`: Execute JavaScript via `uv run frago exec-js`
- `python`: Execute via Python interpreter
- `shell`: Execute script via Shell

**Three Output Targets**:
- `stdout`: Print to console
- `file`: Save to file (`--output-file`)
- `clipboard`: Copy to clipboard (`--output-clipboard`)

**Available Example Recipes (4)**:

| Name | Function | Supported Output |
|------|----------|------------------|
| `test_inspect_tab` | Get current tab diagnostic info (title, URL, DOM stats) | stdout |
| `youtube_extract_video_transcript` | Extract complete YouTube video subtitles | stdout, file |
| `upwork_extract_job_details_as_markdown` | Extract Upwork job details as Markdown | stdout, file |
| `x_extract_tweet_with_comments` | Extract X(Twitter) tweets and comments | stdout, file, clipboard |

```bash
# View all Recipes
uv run frago recipe list

# View Recipe detailed information
uv run frago recipe info youtube_extract_video_transcript
```

### AI-First Design Philosophy

The core goal of the Recipe system is to **enable AI Agents to autonomously discover, understand, and use Recipes**, not just a tool for human developers.

**How AI Uses the Recipe System**:

```bash
# 1. AI discovers available Recipes (get structured data via JSON format)
uv run frago recipe list --format json

# 2. AI analyzes metadata to understand Recipe capabilities
#    - description: What does this Recipe do?
#    - use_cases: What scenarios is it suitable for?
#    - tags: Semantic classification
#    - output_targets: What output methods are supported?

# 3. AI selects appropriate Recipe and output method based on task requirements
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file /tmp/transcript.txt  # AI determines file output needed

# 4. AI processes Recipe execution results (JSON format)
#    Success: {"success": true, "data": {...}}
#    Failure: {"success": false, "error": {...}}
```

**Design Principles**:
- All metadata designed for AI comprehensibility (semantic descriptions > technical details)
- JSON format output for easy AI parsing and processing
- Error messages structured for AI to understand failure reasons and take action
- Output targets explicitly declared so AI chooses correct command options

**Relationship with Human Users**:
- Human users: Create and maintain Recipes (via `/frago.recipe` command)
- AI Agent: Discover and use Recipes (via `recipe list/run` commands)
- Recipe system is the bridge connecting both

## System Architecture

### Three-Layer Architecture Design

```
┌─────────────────────────────────────────────────────────┐
│  Pipeline Master (Python scheduler)                      │
│  - Launch Chrome CDP                                     │
│  - Schedule 5 stages                                     │
│  - Sync via .done files                                  │
└──────────────────┬──────────────────────────────────────┘
                   │ Call slash commands
                   ↓
┌─────────────────────────────────────────────────────────┐
│  Claude AI (Creative executor)                           │
│  - /frago.start:      AI autonomous info collection      │
│  - /frago.storyboard: AI autonomous storyboard design    │
│  - /frago.generate:   AI creates recording script for    │
│                       each clip                          │
│  - /frago.evaluate:   AI autonomous quality evaluation   │
│  - /frago.merge:      AI autonomous video synthesis      │
└──────────────────┬──────────────────────────────────────┘
                   │ Use tool layer
                   ↓
┌─────────────────────────────────────────────────────────┐
│  CDP Tool Layer (Direct Chrome connection)               │
│  - uv run frago <command>                               │
│  - Recipe system (optional acceleration)                 │
│  - Native WebSocket connection (no Node.js relay)        │
└──────────────────┬──────────────────────────────────────┘
                   ↓
             Chrome browser
```

### Embodiment of AI Autonomous Decision-Making

**Each stage is an AI creative process**, not simple script execution:

#### Stage 0: Environment Preparation
- **Executor**: Pipeline Master
- **Task**: Launch Chrome CDP (port 9222)
- **Output**: Chrome process runs persistently

#### Stage 1: Information Collection (`/frago.start`)
- **Executor**: **Claude AI**
- **Input**: Video topic
- **AI Decision Content**:
  - Identify topic type (news/GitHub/product/MVP)
  - Plan information sources and collection strategy
  - Determine which screenshots and content are core
  - Decide which tools to use (CDP/Git/Recipe)
- **Output**:
  - `research/report.json` - Information report
  - `research/screenshots/` - Screenshot materials
  - `start.done` - Completion marker

#### Stage 2: Storyboard Planning (`/frago.storyboard`)
- **Executor**: **Claude AI**
- **Input**: `research/report.json`
- **AI Decision Content**:
  - Design narrative structure and logic flow
  - Plan focus and duration for each shot
  - Design precise action timeline down to the second
  - Select appropriate visual effects (spotlight/highlight)
- **Output**:
  - `shots/shot_xxx.json` - Shot sequence (with detailed action_timeline)
  - `storyboard.done` - Completion marker

#### Stage 3: Video Generation Loop (`/frago.generate`)
**Pipeline controls loop, AI creates each clip**:

```
for each shot_xxx.json:
    ├── AI analyzes shot requirements
    ├── AI writes dedicated recording script (clips/shot_xxx_record.sh)
    │   - Precisely control timing of each action
    │   - Design appearance and disappearance of visual effects
    │   - Coordinate recording and operation synchronization
    ├── Execute script to record shot_xxx.mp4
    ├── Generate audio shot_xxx_audio.mp3
    ├── AI verifies quality (duration, content, sync)
    └── Create marker shot_xxx.done
```

- **Executor**: **Claude AI** (each time is independent creation)
- **Core Philosophy**: Not batch processing, but custom script for each clip
- **Recipe Role**: Accelerate high-frequency DOM operations (like YouTube subtitle extraction), avoid repeated LLM reasoning
- **Completion Marker**: `generate.done`

#### Stage 4: Material Evaluation (`/frago.evaluate`)
- **Executor**: **Claude AI**
- **AI Decision Content**:
  - Analyze completeness of all clips
  - Identify quality issues (blur, truncation, duration mismatch)
  - Propose fixes or auto-repair
  - Verify audio-video sync
- **Output**:
  - `evaluation_report.json` - Evaluation report
  - `evaluate.done` - Completion marker

#### Stage 5: Video Synthesis (`/frago.merge`)
- **Executor**: **Claude AI**
- **AI Decision Content**:
  - Determine merge order and transition effects
  - Handle audio sync and smoothing
  - Add intro/outro (if needed)
  - Select output format and quality parameters
- **Output**:
  - `outputs/final_output.mp4` - Final video
  - `merge.done` - Completion marker

#### Stage 6: Environment Cleanup
- **Executor**: Pipeline Master
- **Task**: Close Chrome, clean temporary files

### Core Design Philosophy

1. **AI is Creator, Not Executor**
   - AI makes creative decisions at each stage
   - Pipeline only responsible for scheduling and synchronization
   - Recipe is acceleration tool for AI to use

2. **Hybrid Strategy Advantage**
   ```
   New scenario: AI explores → Understands → Executes
   Familiar scenario: Recipe direct reuse (save time and tokens)
   Complex scenario: AI creation + Recipe accelerates high-frequency parts
   ```

3. **Essential Difference from Browser Use**
   - Browser Use: General task automation (strong adaptability)
   - Frago: Video creation workflow (strong control)
