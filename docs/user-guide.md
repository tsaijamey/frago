# User Guide

[简体中文](user-guide.zh-CN.md)

## Browser Commands

All browser control goes through `frago browser <command>`:

```bash
# Navigation
frago browser navigate <url>
frago browser status

# Interaction
frago browser click <selector>
frago browser scroll <distance>
frago browser wait <seconds>

# JavaScript
frago browser exec-js <expression> --return-value

# Screenshots
frago browser screenshot <output_file>

# Visual effects
frago browser spotlight <selector> --life-time 3
frago browser highlight <selector> --color "#FF6B6B"
frago browser annotate <selector> "text" --position top
```

Every page command targets a **tab group**: pass `--group <name>`
explicitly, or let it default to `$FRAGO_CURRENT_RUN`. Groups are real
browser tab groups — `navigate` replaces the group's current tab, and
`--new` is the only way to open another one.

There are two backends. The default **extension** backend drives the
browser's own real profile (no flags needed). The **CDP** backend
(`-b cdp`) is the fallback for true headless or dedicated instances; see
[Browser Support](browser-support.md) for when to use it.

### Proxy Configuration

```bash
# Environment variables
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# CLI parameters (global flags, placed before the subcommand)
frago --proxy-host proxy.example.com --proxy-port 8080 browser navigate https://example.com
frago --no-proxy browser navigate https://example.com
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
1. User (~/.frago/recipes/)                 ← Higher (personal)
2. Community (~/.frago/community-recipes/)  ← Lower (installed)
```

### Where recipes come from

**The install bundles none.** A fresh frago can run nothing until you write
a recipe or install one — which is the point: what a machine can do is
visible in what has been put on it, not hidden in the wheel.

Public recipes (YouTube, Bilibili, arXiv, Feishu/Lark, WeChat, TTS, vision
classification, ...) live in [frago-recipe-community](https://github.com/tsaijamey/frago-recipe-community) and install on
demand:

```bash
frago recipe search <keyword>
frago recipe install community:<recipe-name>
frago recipe list --source community
```

Wrote one worth sharing? `frago recipe share <name>` opens the pull request
for you.

The recipe command group also offers `plan`, `create`, `schedule`,
`publish`, `search`, `update`, `uninstall` and more — see
[Recipe System Guide](recipes.md).

## Output and knowledge capture

> The old Run system (`run init` / `set-context` / `archive` / `insights`) is retired, and
> `~/.frago/projects/` is now frago's own session ledger, which agents don't write to.

```bash
# Look for an existing home before creating one
frago context data:<keyword>

# Save what you learned into a knowledge domain, as you go
frago def list                       # Which domains exist
frago <domain> find                  # What the domain already holds
frago <domain> save --name=<doc> \
  --data='{"tags":["..."]}' --content='[...]'

# Look up something you did before
frago session search "<a sentence>"  # By meaning, across Claude Code and opencode
```

### Output directory structure

Output always lands in `~/.frago/data/<subject>/<YYYYMMDD>-<slug>/`. Both levels are required:

```
~/.frago/data/research/20260812-youtube-transcript/
├── scripts/                  # Validated scripts
├── outputs/                  # Result files
└── screenshots/              # Timestamped screenshots
```


## Session Monitoring

```bash
frago session list                   # List sessions (all agent types)
frago session list --status running  # Filter by status
frago session list --agent-type opencode  # Filter by agent (claude|opencode|cursor|cline)
frago session show <session_id>      # Show details
frago session search "keyword"       # Search transcripts
frago session watch                  # Watch latest session
frago session watch <session_id>     # Watch specific session
frago session sync --all             # Re-sync Claude Code / opencode sessions
frago session clean                  # Clean stale records
frago session delete <session_id>    # Delete one session
```

Sessions from multiple agent runtimes (Claude Code, opencode, Cursor,
Cline) are normalized into `~/.frago/sessions/`.

## Web Service

```bash
frago server start      # Start on port 8093
frago server stop       # Stop server
frago server status     # Check status
frago server --debug    # Foreground with logs
```

Access: `http://127.0.0.1:8093`

### Features

- **Workbench**: live timeline of agent sessions and their records
- **Tasks**: start a new agent task and watch it run
- **Recipes**: browse local and community recipes, inspect parameters, run with one click
- **Skills**: manage installed skills
- **Workspace**: project files, logs, screenshots and outputs
- **Guide**: built-in documentation
- **Settings**: prompting capability (static rules + lightweight AI), model profiles, task channels, official resource sync, appearance, init status, about

## Resources & Sync

Recipes and skills move between machines through three separate paths.

### Project resources (workspace)

```bash
frago workspace set-scan-roots ~/repos/ ~/work/   # Where to look for projects
frago workspace list                              # Discovered projects
frago workspace collect --dry-run                 # Preview what would be collected
frago workspace pending                           # Deployments waiting from another device
```

`workspace` collects agent resources — skills, `CLAUDE.md`, project
memories — from your configured scan roots.

### Session records

```bash
frago session sync           # Pull Claude Code / opencode sessions into ~/.frago/sessions/
frago session sync --all     # Sync all projects
frago session sync --force   # Re-sync existing sessions too
```

### Official resources

**Settings → Resources** toggles scheduled sync of official commands and
skills. Recipes are not part of it — they come from the community
repository, on the schedule you choose, via `frago recipe update`.
Secrets are never synced anywhere.

## Troubleshooting

### CDP Connection

The CDP backend is a frago-managed browser instance — never a
hand-launched Chrome:

```bash
frago browser -b cdp start --headless   # Dedicated headless instance (port 9222)
frago browser status                    # Health check
frago browser -b cdp stop               # Tear it down
```

- Ports are whitelisted: **9222** (default) and **9223** (the agent_os recorder). Any other value is rejected.
- While the virtual desktop stage is running, its actor lives on **9222** — `-b cdp start` replaces whatever is already on that port, so check `frago desktop status` first.
- Never launch a browser with raw `--remote-debugging-port`; the CDP backend already covers headless and dedicated-instance needs.

### Common Issues

| Problem | Solution |
|---------|----------|
| CDP timeout | Ensure the CDP instance is running: `frago browser -b cdp start` (check `frago desktop status` first if the stage is up) |
| Recipe not found | Check spelling with `frago recipe list` |
| Screenshot failed | Use absolute paths, ensure directory exists |
| Node.js version | Use nvm: `nvm install 20 && nvm use 20` |

---

**Next**: [Concepts](concepts.md) · [Recipes](recipes.md)
