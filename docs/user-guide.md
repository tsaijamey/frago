[简体中文](user-guide.zh-CN.md)

# Frago User Guide

## Overview

Frago is a multi-runtime automation infrastructure designed for AI agents, providing four core systems that work together to solve automation challenges:

- **🧠 Run System**: AI's working memory - persistent context and structured logs
- **📚 Recipe System**: AI's "muscle memory" - reusable automation scripts
- **🔍 Session System**: Agent monitoring - real-time execution tracking
- **⚡ Native CDP**: Lightweight execution engine - direct Chrome control

---

## Core Use Cases

Frago is suitable for various browser automation and data collection tasks:

1. **Interactive Exploration & Debugging**
   - Explore unknown pages while maintaining full context
   - Example: `"Research YouTube subtitle extraction methods"`

2. **Web Data Collection**
   - Batch extract structured information
   - Example: `"Extract job details from Upwork and export as Markdown"`

3. **Social Media Analysis**
   - Collect and analyze social content
   - Example: `"Extract Twitter/X posts and comments"`

4. **Content Transcription**
   - Extract text content from videos/audio
   - Example: `"Download YouTube video subtitles as text"`

5. **Custom Workflows**
   - Combine multiple Recipes to complete complex tasks
   - Example: `"Monitor competitor prices across multiple platforms"`

**Typical Workflow**:
1. AI analyzes task requirements and selects appropriate approach (Run exploration vs Recipe execution)
2. Invoke CDP commands to control Chrome execution
3. Record execution logs to JSONL files (100% parsable and auditable)
4. Output structured data (JSON/Markdown/text)
5. Persist task context to Run instances for future reference

---

## Environment Requirements

- **Python**: 3.9+ (required for core functionality)
- **Chrome Browser**: For chrome-js Recipe execution
- **Operating System**: macOS, Linux, Windows
- **Package Manager**: `uv` (recommended) or `pip`

---

## Installation

See [Installation Guide](installation.md) for detailed instructions.

**Quick Start**:
```bash
uv tool install frago-cli
frago --version
```

---

## Run Command System

The Run system provides persistent context management for AI agents, recording complete exploration and execution history.

### Core Concepts

**Run Instance**: A topic-based task context that persists across multiple operations.

**Key Features**:
- ✅ **JSONL Logs**: 100% programmatically parseable execution records
- ✅ **Screenshot Archive**: Timestamped visual evidence
- ✅ **Script Accumulation**: Validated scripts persist for reuse
- ✅ **Auto-Discovery**: RapidFuzz-based fuzzy matching for finding relevant Runs

### Run Instance Lifecycle

```bash
# 1. Create new Run instance
frago run init "Research YouTube subtitle extraction methods"
# Output: Created Run instance: youtube-subtitle-research-abc123

# 2. Set as current working context (optional)
frago run set-context youtube-subtitle-research-abc123

# 3. Execute operations (automatically logged to current Run)
frago chrome navigate https://youtube.com/watch?v=...
frago chrome screenshot initial_page.png
frago chrome click 'button[aria-label="Show transcript"]'

# 4. Manually log observations or analysis
frago run log \
  --step "Located transcript button selector" \
  --status "success" \
  --action-type "dom_inspection" \
  --execution-method "manual" \
  --data '{"selector": "button[aria-label=\"Show transcript\"]", "reliable": true}'

# 5. View Run details and history
frago run info youtube-subtitle-research-abc123

# 6. List all Run instances
frago run list

# 7. Archive completed Run
frago run archive youtube-subtitle-research-abc123
```

### Run Instance Directory Structure

Each Run instance creates a persistent directory:

```
projects/<run_id>/
├── logs/
│   └── execution.jsonl           # Structured execution logs
├── screenshots/
│   ├── 20250124_143022.png       # Timestamped screenshots
│   └── 20250124_143045.png
├── scripts/
│   └── extract_transcript.js     # Validated working scripts
└── outputs/
    ├── result.json               # Output files
    └── report.md                 # AI-generated reports
```

### JSONL Log Format

Each operation is recorded as a JSON line:

```jsonl
{"timestamp": "2025-01-24T14:30:22Z", "action": "navigate", "url": "https://youtube.com/...", "status": "success"}
{"timestamp": "2025-01-24T14:30:25Z", "action": "screenshot", "file": "screenshots/20250124_143025.png", "status": "success"}
{"timestamp": "2025-01-24T14:30:28Z", "action": "click", "selector": "button[aria-label=\"Show transcript\"]", "status": "success"}
{"timestamp": "2025-01-24T14:30:30Z", "action": "log", "step": "Located transcript button", "data": {"selector": "...", "reliable": true}}
```

### Auto-Discovery

AI agents can automatically find relevant Run instances using fuzzy matching:

```bash
# User says: "Continue researching YouTube subtitle extraction"
# AI executes:
frago run list --format json

# AI uses RapidFuzz to match "YouTube subtitle extraction" against existing Run topics
# Finds: youtube-subtitle-research-abc123 (95% match)
# AI resumes this Run instance automatically
```

---

## CDP Command Usage Guide

All CDP functionality is accessed through a unified CLI interface (`frago chrome <command>`).

### Basic CDP Commands

```bash
# Navigate to webpage
frago chrome navigate <url>

# Click element
frago chrome click <selector>

# Execute JavaScript and return result
frago chrome exec-js <expression> --return-value

# Take screenshot
frago chrome screenshot <output_file>

# Scroll page
frago chrome scroll <direction> <pixels>

# Wait for condition
frago chrome wait <seconds>

# Get page status
frago chrome status

# View all commands
frago --help
```

### Visual Effects (Optional)

Add visual guidance to browser operations:

```bash
# Spotlight effect (dim surrounding area)
frago chrome spotlight <selector> --duration 3

# Highlight element
frago chrome highlight <selector> --color "#FF6B6B" --duration 2

# Add annotation
frago chrome annotate <selector> "Annotation text" --position top

# Pointer indicator
frago chrome pointer <selector> --duration 2
```

### Proxy Configuration

Frago's CDP integration supports proxy configuration for environments requiring network access through a proxy.

#### Environment Variable Configuration

```bash
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1
```

#### CLI Parameter Configuration

```bash
# Use proxy
frago chrome navigate https://example.com \
    --proxy-host proxy.example.com \
    --proxy-port 8080

# Bypass proxy
frago chrome navigate https://example.com --no-proxy
```

### Retry Mechanism

CDP connections support intelligent retry mechanisms:

- **Default retry strategy**: Up to 3 attempts, exponential backoff delay
- **Proxy connection retry**: Up to 5 attempts, optimized for proxy environments
- **Connection timeout**: Default 30 seconds
- **Command timeout**: Default 60 seconds

---

## Recipe Management and Usage

The Recipe system provides metadata-driven automation script management, designed for AI-first discoverability.

### Recipe Discovery

```bash
# List all available Recipes (table format)
frago recipe list

# List in JSON format (for AI parsing)
frago recipe list --format json

# Filter by source
frago recipe list --source project   # Project-level only
frago recipe list --source user      # User-level only
frago recipe list --source example   # Example-level only

# Filter by type
frago recipe list --type atomic      # Atomic Recipes only
frago recipe list --type workflow    # Workflow Recipes only
```

### Recipe Information

```bash
# View Recipe detailed information
frago recipe info youtube_extract_video_transcript

# View in JSON format (for AI parsing)
frago recipe info youtube_extract_video_transcript --format json
```

**Example Output**:
```json
{
  "name": "youtube_extract_video_transcript",
  "type": "atomic",
  "runtime": "chrome-js",
  "version": "1.2.0",
  "description": "Extract complete subtitle content from YouTube video page",
  "use_cases": [
    "Get subtitles for translation",
    "Create subtitle files",
    "Analyze video content"
  ],
  "tags": ["youtube", "transcript", "web-scraping"],
  "output_targets": ["stdout", "file"],
  "source": "Example",
  "path": "examples/atomic/chrome/youtube_extract_video_transcript.js"
}
```

### Recipe Execution

```bash
# Execute Recipe with parameters
frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt

# Output to clipboard
frago recipe run upwork_extract_job_details_as_markdown \
    --params '{"url": "..."}' \
    --output-clipboard

# Use parameter file
cat > params.json <<EOF
{
  "url": "https://youtube.com/watch?v=...",
  "format": "srt"
}
EOF

frago recipe run youtube_extract_video_transcript \
    --params-file params.json

# Set execution timeout
frago recipe run youtube_extract_video_transcript \
    --params '{"url": "..."}' \
    --timeout 300
```

**Supported Options**:
- `--params '{...}'` - JSON parameters (inline)
- `--params-file <path>` - JSON parameters (from file)
- `--output-file <path>` - Save output to file
- `--output-clipboard` - Copy output to clipboard
- `--timeout <seconds>` - Execution timeout (default: 120)

### Three-Level Recipe Priority System

Recipes are discovered in priority order:

```
1. Project (.frago/recipes/)     ← Highest priority (project-specific)
2. User (~/.frago/recipes/)      ← Medium priority (personal recipes)
3. Example (examples/)            ← Lowest priority (official examples)
```

**Why Three Levels?**
- **Project-level**: Team-shared Recipes for specific project
- **User-level**: Personal Recipes reusable across projects
- **Example-level**: Official Recipes that can be copied and customized

### Creating Custom Recipes

#### Method 1: Copy Example Recipe

```bash
# Copy example Recipe to user-level
frago recipe copy youtube_extract_video_transcript

# Recipe is now at: ~/.frago/recipes/atomic/chrome/youtube_extract_video_transcript.js
# Customize as needed
```

#### Method 2: Use Claude Code Integration

```
/frago.recipe create "Extract complete job information from Upwork and format as Markdown"
```

AI will:
1. Analyze requirements
2. Generate Recipe script (.js/.py/.sh)
3. Generate metadata documentation (.md with YAML frontmatter)
4. Save to appropriate location
5. Test Recipe execution

### Available Example Recipes

Currently provides 4 example Recipes:

| Name | Function | Runtime | Outputs |
|------|----------|---------|---------|
| `test_inspect_tab` | Get current tab diagnostic info (title, URL, DOM stats) | chrome-js | stdout |
| `youtube_extract_video_transcript` | Extract complete YouTube video subtitles | chrome-js | stdout, file |
| `upwork_extract_job_details_as_markdown` | Extract Upwork job details as Markdown | chrome-js | stdout, file |
| `x_extract_tweet_with_comments` | Extract X(Twitter) tweets and comments | chrome-js | stdout, file, clipboard |

---

## Session Monitoring

The Session system provides real-time monitoring and persistence of AI agent execution data.

### Session Commands

```bash
# List all sessions
frago session list
frago session list --status running   # Only running sessions
frago session list --agent claude     # Only Claude Code sessions

# Show session details
frago session show <session_id>
frago session show <session_id> --format json

# Watch session in real-time
frago session watch                    # Watch latest session
frago session watch <session_id>       # Watch specific session
frago session watch --json             # JSON output format
```

### Session Storage

Session data is stored in `~/.frago/sessions/{agent_type}/{session_id}/`:

```
~/.frago/sessions/claude/abc123-def456/
├── metadata.json    # Session metadata (project, time, status)
├── steps.jsonl      # Execution steps (messages, tool calls)
└── summary.json     # Session summary (tool call statistics)
```

### Integration with frago agent

When running `frago agent "task"`, the session monitor automatically:
1. Starts watching `~/.claude/projects/...` for changes
2. Associates new session by timestamp (10-second window)
3. Parses JSONL records incrementally
4. Displays real-time execution status
5. Persists session data to `~/.frago/sessions/`

```bash
# Execute task with session monitoring
frago agent "Extract data from website"

# Output shows real-time status:
# [Session] Started: abc123
# [Step 1] User message: Extract data from website
# [Tool] Read file: /home/user/project/README.md (success)
# [Tool] WebFetch: https://example.com (success)
# [Session] Completed: 5 steps, 3 tool calls
```

---

## GUI Mode

Frago provides a desktop GUI interface for users who prefer graphical interaction.

### Starting GUI

```bash
# Launch GUI
frago gui

# Launch with debug mode (developer tools enabled)
frago gui --debug
```

### GUI Requirements

GUI is included by default—no extra installation needed.

**Platform-specific system dependencies**:

| Platform | Backend | Additional Requirements |
|----------|---------|------------------------|
| Linux | WebKit2GTK | `sudo apt install python3-gi gir1.2-webkit2-4.1` |
| macOS | WKWebView | None (built-in) |
| Windows | WebView2 | Edge WebView2 Runtime (recommended) |

### GUI Features

The GUI provides:

- **Recipe Browser**: List, view details, and execute recipes
- **Command Input**: Execute frago commands with visual feedback
- **Status Display**: Real-time connection and execution status
- **History**: View command and execution history

### GUI Design

The GUI uses GitHub Dark color scheme for comfortable long-term use:

- **Background**: Deep blue-gray (`#0d1117`)
- **Accent**: Soft blue (`#58a6ff`)
- **Text**: High contrast but not harsh
- **Layout**: Clear visual hierarchy with input area as focal point

---

## Integration with Claude Code

Frago provides slash commands for Claude Code integration, enabling AI-driven task execution.

### Available Slash Commands

```
/frago.run <task_description>
```
Execute complex tasks with AI orchestration. AI will:
- Create or discover relevant Run instance
- Select appropriate Recipes or CDP commands
- Record all operations to structured logs
- Generate execution reports

**Examples**:
```
/frago.run Research YouTube subtitle extraction methods: locate button, test extraction, save script

/frago.run Extract 20 Python jobs from Upwork and save as JSON

/frago.run Monitor iPhone 15 prices on Amazon and eBay, generate comparison report
```

---

```
/frago.recipe create <recipe_description>
```
Create new Recipe with AI assistance. AI will:
- Analyze recipe requirements
- Generate script and metadata
- Test execution
- Save to appropriate location

**Examples**:
```
/frago.recipe create "Extract GitHub repository README and save as Markdown"

/frago.recipe create workflow "Batch extract subtitles from 10 YouTube videos"
```

---

```
/frago.exec <one_time_task>
```
Execute one-time tasks without creating Run instance.

**Examples**:
```
/frago.exec Take screenshot of current page and annotate the login button

/frago.exec Extract all links from https://news.ycombinator.com/
```

---

## Best Practices

### When to Use Run System

✅ **Use Run System when**:
- Exploring unknown pages or workflows
- Debugging complex issues
- Need to maintain context across sessions
- Want auditable execution history
- Planning to create Recipe from exploration results

❌ **Don't use Run System when**:
- Executing well-defined one-time tasks
- Using existing Recipes that don't need context
- Simple operations that don't benefit from logging

### When to Create Recipe

✅ **Create Recipe when**:
- Task will be repeated frequently (saves AI tokens)
- High-frequency operations consume too many AI tokens
- Need standardized, reproducible automation
- Want to share automation scripts with team

❌ **Don't create Recipe when**:
- Task is truly one-time
- Workflow is still evolving and unclear
- Page structure changes frequently

### Recipe Naming Conventions

- Use lowercase letters, numbers, underscores, hyphens
- **Atomic Recipe**: `<platform>_<action>_<object>`
  - Examples: `youtube_extract_video_transcript`, `github_read_readme`
- **Workflow Recipe**: `<platform>_batch_<action>` or `<workflow_name>`
  - Examples: `upwork_batch_extract_jobs`, `competitor_price_monitor`

---

## Troubleshooting

### Common Issues

**Problem**: CDP connection timeout
```
Error: Failed to connect to Chrome CDP at ws://localhost:9222
```

**Solutions**:
1. Check if Chrome is running in CDP mode:
   ```bash
   # Launch Chrome with CDP enabled
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
       --remote-debugging-port=9222 \
       --user-data-dir=./chrome_profile
   ```
2. Verify port 9222 is accessible: `lsof -i :9222`
3. Check proxy configuration (if using proxy)

---

**Problem**: Recipe not found
```
Error: Recipe 'youtube_extract_subtitles' not found
```

**Solutions**:
1. List available Recipes: `frago recipe list`
2. Check Recipe name spelling (exact match required)
3. Verify metadata file (.md) exists alongside script file

---

**Problem**: Screenshot save failed
```
Error: Failed to save screenshot to /path/to/screenshot.png
```

**Solutions**:
1. Use absolute paths for screenshot files
2. Ensure target directory exists: `mkdir -p screenshots/`
3. Check file write permissions

---

### Linux-Specific Issues

**Problem**: `pip: command not found`

**Solutions**:
```bash
# Ubuntu/Debian
sudo apt install python3-pip

# Fedora
sudo dnf install python3-pip

# Arch Linux
sudo pacman -S python-pip

# Alternative: use python -m pip
python3 -m pip install frago-cli
```

---

**Problem**: `npm EACCES permission denied`
```
npm ERR! Error: EACCES: permission denied, mkdir '/usr/local/lib/node_modules'
```

**Solutions**:
```bash
# Option 1: Use nvm (recommended)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc  # or ~/.zshrc
nvm install --lts

# Option 2: Change npm global directory
mkdir -p ~/.npm-global
npm config set prefix ~/.npm-global
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```

---

**Problem**: `nvm: command not found` after installation

**Solutions**:
```bash
# Ensure nvm is loaded in current shell
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Add to ~/.bashrc or ~/.zshrc for persistence
echo 'export NVM_DIR="$HOME/.nvm"' >> ~/.bashrc
echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> ~/.bashrc
source ~/.bashrc
```

---

**Problem**: Chrome CDP connection issues on Linux

**Solutions**:
```bash
# 1. Verify Chrome is installed
google-chrome --version

# 2. Launch Chrome in CDP mode
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# 3. Verify CDP port is listening
lsof -i :9222 | grep LISTEN
curl http://localhost:9222/json/version

# 4. If port 9222 is occupied
# Find the process using the port
lsof -i :9222
# Kill it or use a different port
google-chrome --remote-debugging-port=9223 --user-data-dir=/tmp/chrome-debug
```

---

**Problem**: Node.js version mismatch
```
Error: Node.js version 18.x detected, but 20.0.0 or higher is required
```

**Solutions**:
```bash
# Using nvm
nvm install 20
nvm use 20
nvm alias default 20

# Verify
node --version
```

---

### macOS-Specific Issues

**Problem**: `pip: command not found`

**Solutions**:
```bash
# macOS uses pip3, not pip
pip3 install frago-cli

# Or use python3 -m pip (most reliable)
python3 -m pip install frago-cli
```

---

**Problem**: `xcrun: error: invalid active developer path`
```
xcrun: error: invalid active developer path (/Library/Developer/CommandLineTools)
```

**Solutions**:
```bash
# Install Xcode Command Line Tools
xcode-select --install

# If already installed but broken, reset
sudo xcode-select --reset
```

---

**Problem**: Chrome CDP connection on macOS

**Solutions**:
```bash
# 1. Launch Chrome with CDP enabled
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=~/.frago/chrome_profile

# 2. Verify CDP is running
lsof -i :9222 | grep LISTEN
curl http://localhost:9222/json/version

# 3. If port is in use, find and kill the process
lsof -i :9222
kill -9 <PID>
```

---

**Problem**: Homebrew Node.js conflicts with nvm

**Solutions**:
```bash
# If you have Node.js via Homebrew and want to use nvm instead:
brew uninstall node

# If you want to keep Homebrew Node.js, ensure version is 20+
node --version

# To install specific version with Homebrew
brew install node@20
```

---

**Problem**: Gatekeeper blocks downloaded apps

**Solutions**:
```bash
# If Chrome or other apps are blocked, allow in System Preferences:
# System Preferences → Security & Privacy → General → "Allow apps downloaded from"

# Or remove quarantine attribute (use with caution)
xattr -d com.apple.quarantine /path/to/app
```

---

### Windows-Specific Issues

**Problem**: `python` or `pip` not recognized
```
'python' is not recognized as an internal or external command
```

**Solutions**:
```powershell
# Option 1: Use py launcher (if installed)
py -m pip install frago-cli

# Option 2: Add Python to PATH
# Reinstall Python and check "Add Python to PATH"
# Or manually add to System Environment Variables:
# C:\Users\<username>\AppData\Local\Programs\Python\Python311\
# C:\Users\<username>\AppData\Local\Programs\Python\Python311\Scripts\

# Option 3: Use Microsoft Store Python
# Search "Python 3.11" in Microsoft Store
```

---

**Problem**: `node` not recognized after installation
```
'node' is not recognized as an internal or external command
```

**Solutions**:
```powershell
# Restart PowerShell after Node.js installation

# If still not working, add to PATH manually:
# C:\Program Files\nodejs\

# Verify installation
node --version
```

---

**Problem**: npm global packages not found (e.g., claude)
```
'claude' is not recognized as an internal or external command
```

**Solutions**:
```powershell
# Add npm global directory to PATH
$env:PATH += ";$env:APPDATA\npm"

# To make permanent, add to user environment variables:
# System Properties → Environment Variables → User variables → Path → Add:
# %APPDATA%\npm

# Then restart PowerShell
```

---

**Problem**: PowerShell script execution disabled
```
cannot be loaded because running scripts is disabled on this system
```

**Solutions**:
```powershell
# Allow scripts for current user
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify
Get-ExecutionPolicy -List
```

---

**Problem**: Chrome CDP connection on Windows

**Solutions**:
```powershell
# 1. Launch Chrome with CDP enabled
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="$env:USERPROFILE\.frago\chrome_profile"

# 2. Verify CDP is running
Test-NetConnection -ComputerName localhost -Port 9222
Invoke-WebRequest -Uri "http://localhost:9222/json/version"

# 3. If port is in use, find process
netstat -ano | findstr :9222
# Then kill by PID:
taskkill /PID <PID> /F
```

---

**Problem**: Windows does not support automatic Node.js installation
```
Error: Windows 不支持自动安装 Node.js
```

**Solutions**:
```powershell
# You must install Node.js manually before running frago init
winget install OpenJS.NodeJS.LTS

# Or download from https://nodejs.org/

# Verify installation
node --version  # Should be 20.x or higher
```

---

## Resource Management

Your skills and recipes are personal assets—workflow patterns you've discovered, automation scripts you've built. They shouldn't be tied to a single machine.

### Sync Command

The `sync` command handles bidirectional synchronization between your local system and a private Git repository:

```bash
# First time: configure your private repository
frago sync --set-repo git@github.com:you/my-frago-resources.git

# Daily use
frago sync              # Push local changes and pull remote updates
frago sync --dry-run    # Preview what will be synced
frago sync --no-push    # Only pull, don't push
frago sync -m "message" # Custom commit message
```

### What Gets Synced

| Resource Type | Pattern | Location |
|--------------|---------|----------|
| Skills | `frago-*` prefix | `~/.claude/skills/` |
| Recipes | All recipes | `~/.frago/recipes/` |

Your personal, non-Frago Claude commands and skills are **never touched**.

---

## Next Steps

- **New to Frago?** Start with [Use Cases](use-cases.md) for real-world examples
- **Want technical details?** Read [Architecture](architecture.md)
- **Creating Recipes?** See [Recipe System Guide](recipes.md)
- **Contributing?** Check [Development Guide](development.md)

---

Created with Claude Code | 2025-11
