[简体中文](architecture.zh-CN.md)

# frago Technical Architecture

## System Architecture

### frago CLI Usage Flow

![frago CLI Usage Flow](images/frago-cli-workflow.jpg)

### Recipe Three-Level Priority System

![Recipe Priority System](images/frago-recipe-priority.jpg)

```
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
Developer → frago chrome navigate https://...
          → CDP client → WebSocket → Chrome
          → Return execution result
```

## Core Differences Comparison

### frago vs Playwright / Selenium

| Dimension | **Playwright / Selenium** | **frago** |
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

- ✅ **Persistent browser sessions** - Playwright launches new browser per test, frago connects to running Chrome instance
- ✅ **Recipe metadata-driven** - Reusable automation scripts with three-level priority management
- ✅ **Zero relay layer** - Direct WebSocket to CDP, no Node.js relay, lower latency
- ✅ **Lightweight deployment** - No Node.js environment needed, pure Python implementation

### frago vs Browser Use

| Dimension | **Browser Use** | **frago** |
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
   frago:     Python → CDP → Chrome
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
   - frago: ~2MB (websocket-client)

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
frago chrome exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
```

**Difference from Browser Use**:

- Browser Use: Every task needs LLM reasoning ($$$)
- frago: AI decision-making (storyboard design) + Recipe acceleration (repeated operations)

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

- `chrome-js`: Execute JavaScript via `frago chrome exec-js`
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

## Run System Architecture

The Run system provides persistent context management and structured execution logging, serving as AI agents' working memory.

### Core Components

![Run Instance Management](images/frago-run-management.jpg)

### Run Instance Lifecycle

**1. Initialization**
```bash
uv run frago run init "Research YouTube subtitle extraction"
# Creates: projects/youtube-subtitle-research-abc123/
```

**2. Execution Phase**
- All CDP commands automatically link to active Run
- Screenshots saved to Run's screenshots/ directory
- Operations logged to execution.jsonl in real-time

**3. Manual Logging**
```bash
uv run frago run log \
  --step "Located transcript button" \
  --status "success" \
  --data '{"selector": "button[aria-label=\"Show transcript\"]"}'
```

**4. Context Persistence**
- Run directory persists across sessions
- AI can resume exploration days later
- Complete audit trail for compliance

**5. Auto-Discovery**
```python
# AI fuzzy matching algorithm
from rapidfuzz import fuzz

user_query = "Continue YouTube subtitle research"
existing_runs = get_all_runs()

matches = [
    (run, fuzz.ratio(user_query, run.topic))
    for run in existing_runs
]

best_match = max(matches, key=lambda x: x[1])
if best_match[1] > 80:  # 80% similarity threshold
    resume_run(best_match[0])
```

### JSONL Log Schema

Each operation produces a structured JSON line:

```typescript
interface LogEntry {
  timestamp: string;           // ISO 8601 format
  run_id: string;              // Run instance identifier
  action: string;              // Operation type (navigate, click, log, etc.)
  status: "success" | "failure" | "pending";
  action_type?: string;        // dom_inspection, navigation, etc.
  execution_method?: string;   // command, manual, ai_generated
  data?: Record<string, any>;  // Operation-specific data
  error?: {
    type: string;
    message: string;
    stack?: string;
  };
}
```

**Example JSONL logs**:
```jsonl
{"timestamp":"2025-01-24T14:30:22Z","run_id":"youtube-research-abc123","action":"navigate","url":"https://youtube.com/...","status":"success"}
{"timestamp":"2025-01-24T14:30:25Z","run_id":"youtube-research-abc123","action":"screenshot","file":"screenshots/20250124_143025.png","status":"success"}
{"timestamp":"2025-01-24T14:30:28Z","run_id":"youtube-research-abc123","action":"click","selector":"button[aria-label=\"Show transcript\"]","status":"success"}
{"timestamp":"2025-01-24T14:30:30Z","run_id":"youtube-research-abc123","action":"log","step":"Located transcript button","action_type":"dom_inspection","execution_method":"manual","data":{"selector":"button[aria-label=\"Show transcript\"]","reliable":true},"status":"success"}
```

### Integration with Recipe System

Run instances and Recipes work together:

**Scenario 1: Exploration → Recipe Creation**
```
1. Create Run: "Research Upwork job extraction"
2. Execute exploration (CDP commands logged to Run)
3. Identify working selectors and logic
4. AI generates Recipe from Run logs
5. Recipe becomes reusable for similar tasks
```

**Scenario 2: Recipe Execution within Run Context**
```
1. Create Run: "Batch extract 20 Python jobs"
2. Execute Workflow Recipe: upwork_batch_extract
3. Each Recipe call logged to Run's execution.jsonl
4. Complete audit trail of 20 extractions
5. Error recovery: Resume from last successful extraction
```

### Benefits of Run System

**1. Knowledge Accumulation**
- Validated scripts persist in `scripts/` directory
- AI learns from past explorations
- Reduces repeated trial-and-error

**2. Auditability**
- 100% parseable JSONL logs
- Complete operation history
- Compliance and debugging friendly

**3. Resumability**
- Continue exploration across sessions
- AI auto-discovers relevant Runs
- No context loss

**4. Error Recovery**
- Structured error logging
- Pinpoint exact failure location
- Incremental retry from checkpoints

## Session Monitoring Architecture

The Session system provides real-time monitoring and persistence of AI agent execution data.

### Core Components

![Session Monitoring](images/frago-session-monitoring.jpg)

### Session Association Logic

Sessions are matched using a 10-second time window:

```python
# When frago agent starts, it records start_time
# When a new JSONL record arrives in ~/.claude/projects/...

record_time = parse_timestamp(record)
delta = abs((record_time - start_time).total_seconds())

if delta < 10:  # 10-second window
    associate_session(record.session_id)
```

### Multi-Agent Architecture

The system uses an adapter pattern for extensibility:

```python
class AgentAdapter:
    """Abstract base class for agent-specific implementations"""

    def get_session_dir(self, project_path: str) -> Path:
        """Get session file directory for this agent type"""
        raise NotImplementedError

    def encode_project_path(self, project_path: str) -> str:
        """Encode project path to directory name"""
        raise NotImplementedError

    def parse_record(self, data: Dict) -> ParsedRecord:
        """Parse agent-specific record format"""
        raise NotImplementedError

# Currently implemented
_adapters = {
    AgentType.CLAUDE: ClaudeCodeAdapter(),
    # Future: CursorAdapter, ClineAdapter
}
```

### Session Data Flow

```
frago agent "Extract data from website"
    │
    ├─ Start SessionMonitor (watchdog)
    │   └─ Watch: ~/.claude/projects/-home-yammi-repos-Project/
    │
    ├─ Claude Code executes task
    │   └─ Writes: {session_id}.jsonl
    │
    ├─ SessionMonitor detects file change
    │   ├─ Parse new JSONL records
    │   ├─ Match session by timestamp
    │   └─ Extract steps and tool calls
    │
    └─ Persist to frago storage
        ├─ metadata.json (session info)
        ├─ steps.jsonl (execution steps)
        └─ summary.json (tool call stats)
```

## Web Service Architecture

The Web Service system provides a browser-based GUI through FastAPI backend and React frontend.

### Technology Stack

![Web Service Architecture](images/frago-web-architecture.jpg)

### Server Commands

```bash
frago server start      # Start background daemon on port 8093
frago server stop       # Stop background daemon
frago server status     # Check server status
frago server --debug    # Run in foreground with logs
```

### API Endpoints

```python
# Recipe endpoints
GET  /api/recipes              # List all recipes
GET  /api/recipes/{name}       # Get recipe details
POST /api/recipes/{name}/run   # Execute recipe

# Session endpoints
GET  /api/sessions             # List all sessions
GET  /api/sessions/{id}        # Get session details
POST /api/sessions/{id}/title  # Update session title

# Config endpoints
GET  /api/config               # Get configuration
PUT  /api/config               # Update configuration

# Sync endpoint
POST /api/sync                 # Trigger resource sync
```

### Frontend Architecture

```typescript
// State management with Zustand
interface AppStore {
  sessions: Session[];
  selectedSession: Session | null;
  aiTitleEnabled: boolean;
  syncSessions: () => Promise<void>;
  generateTitle: (sessionId: string) => Promise<void>;
}

// Real-time session monitoring
useEffect(() => {
  const interval = setInterval(() => {
    syncSessions();
  }, 5000);
  return () => clearInterval(interval);
}, []);
```

### Key Features

- **Dashboard**: Overview of recent sessions and system status
- **Tasks Page**: Interactive Claude Code console with real-time monitoring
- **Recipes Page**: Browse, search, and execute recipes
- **Skills Page**: View and manage installed skills
- **Settings Page**: Configure models, appearance, and sync options
- **AI Title Generation**: Auto-generate session titles using Claude Haiku

---

## Four Systems Integration

How Run System, Recipe System, Session System, and Native CDP work together:

![Four Systems Integration](images/frago-systems-integration.jpg)

### Token Efficiency through Four Systems

| System | First Encounter | Subsequent Use | Token Savings |
|--------|----------------|----------------|---------------|
| **No Run/Recipe** | AI explores (150k tokens) | AI explores again (150k tokens) | 0% |
| **With Run Only** | AI explores + logs (155k tokens) | Review Run logs (10k tokens) | 93.5% |
| **With Run + Recipe** | AI explores + creates Recipe (160k tokens) | Execute Recipe (2k tokens) | **98.7%** |

---

## Next Steps

- **Understanding core concepts?** Start with [Use Cases](use-cases.md)
- **Want to create Recipes?** Read [Recipe System Guide](recipes.md)
- **Ready to develop?** Check [Development Guide](development.md)
- **Curious about progress?** See [Roadmap](roadmap.md)

---

Created with Claude Code | 2025-11
