# User Guide

[简体中文](user-guide.zh-CN.md)

## CDP Commands

All browser control through `frago chrome <command>`:

```bash
# Navigation
frago chrome navigate <url>
frago chrome status

# Interaction
frago chrome click <selector>
frago chrome scroll <direction> <pixels>
frago chrome wait <seconds>

# JavaScript
frago chrome exec-js <expression> --return-value

# Screenshots
frago chrome screenshot <output_file>

# Visual effects
frago chrome spotlight <selector> --duration 3
frago chrome highlight <selector> --color "#FF6B6B"
frago chrome annotate <selector> "text" --position top
```

### Proxy Configuration

```bash
# Environment variables
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# CLI parameters
frago chrome navigate https://example.com --proxy-host proxy.example.com --proxy-port 8080
frago chrome navigate https://example.com --no-proxy
```

## Recipe Management

```bash
# Discovery
frago recipe list                    # List all recipes
frago recipe list --format json      # JSON format (for AI)
frago recipe list --source user      # Filter by source
frago recipe list --type atomic      # Filter by type

# Information
frago recipe info <name>             # View details
frago recipe info <name> --format json

# Execution
frago recipe run <name> --params '{"url": "..."}'
frago recipe run <name> --params-file params.json
frago recipe run <name> --output-file result.txt
frago recipe run <name> --output-clipboard
frago recipe run <name> --timeout 300
```

### Recipe Priority

```
1. Project (.frago/recipes/)     ← Highest (project-specific)
2. User (~/.frago/recipes/)      ← Medium (personal)
3. Example (examples/)           ← Lowest (official)
```

### Built-in Recipes

| Name | Function |
|------|----------|
| `test_inspect_tab` | Current tab diagnostics |
| `youtube_extract_video_transcript` | Extract YouTube subtitles |
| `upwork_extract_job_details_as_markdown` | Extract Upwork jobs |
| `x_extract_tweet_with_comments` | Extract X/Twitter posts |

## Run System

```bash
# Lifecycle
frago run init "task description"    # Create run instance
frago run set-context <run_id>       # Set working context
frago run info <run_id>              # View details
frago run list                       # List all runs
frago run archive <run_id>           # Archive completed run

# Logging
frago run log --step "description" --status success --action-type "type"
```

### Run Directory Structure

```
projects/<run_id>/
├── logs/execution.jsonl      # Structured logs
├── screenshots/              # Timestamped screenshots
├── scripts/                  # Validated scripts
└── outputs/                  # Result files
```

## Session Monitoring

```bash
frago session list                   # List sessions
frago session list --status running  # Filter by status
frago session show <session_id>      # Show details
frago session watch                  # Watch latest session
frago session watch <session_id>     # Watch specific session
```

## Web Service

```bash
frago server start      # Start on port 8093
frago server stop       # Stop server
frago server status     # Check status
frago server --debug    # Foreground with logs
```

Access: `http://127.0.0.1:8093`

### Features

- **Dashboard**: Recent sessions overview
- **Tasks**: Interactive Claude Code console
- **Recipes**: Browse and execute recipes
- **Skills**: Manage installed skills
- **Settings**: Model, appearance, sync options

## Resource Sync

```bash
# First time
frago sync --set-repo git@github.com:you/my-resources.git

# Daily use
frago sync              # Bidirectional sync
frago sync --dry-run    # Preview changes
frago sync --no-push    # Pull only
frago sync -m "message" # Custom commit message
```

### What Gets Synced

| Type | Pattern | Location |
|------|---------|----------|
| Skills | `frago-*` | `~/.claude/skills/` |
| Recipes | All | `~/.frago/recipes/` |

## Troubleshooting

### CDP Connection

```bash
# Launch Chrome with CDP
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 --user-data-dir=~/.frago/chrome_profile

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# Windows
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 --user-data-dir="$env:USERPROFILE\.frago\chrome_profile"

# Verify
curl http://localhost:9222/json/version
```

### Common Issues

| Problem | Solution |
|---------|----------|
| CDP timeout | Ensure Chrome is running with `--remote-debugging-port=9222` |
| Recipe not found | Check spelling with `frago recipe list` |
| Screenshot failed | Use absolute paths, ensure directory exists |
| Node.js version | Use nvm: `nvm install 20 && nvm use 20` |

---

**Next**: [Concepts](concepts.md) · [Architecture](architecture.md) · [Recipes](recipes.md)
