# Tool Priority

Applies to: `/frago.run`

## Priority Order

```
1. Existing Recipe            ← Highest priority
2. frago commands              ← Universal across agents
3. System or third-party commands ← Powerful functionality
4. Claude Code built-in tools  ← Last resort
```

## ⚠️ CRITICAL: WebSearch Prohibition Rule

**WebSearch causes system crash in desktop environments!**

```
if GUI_AVAILABLE (desktop mode):
    WebSearch => FORBIDDEN (causes system crash!)
    MUST USE: frago chrome navigate "https://google.com/search?q=..."

if HEADLESS (no GUI):
    WebSearch => allowed as fallback
```

## ⚠️ CRITICAL: Tab Creation Prohibition Rule

**NEVER create tabs via `window.open`, `exec-js`, or raw CDP WebSocket.**

```
Opening any URL => MUST USE: frago chrome navigate <url>
    ✅ frago chrome navigate "https://example.com"
    ❌ exec-js "window.open('https://example.com')"
    ❌ Raw CDP Target.createTarget via WebSocket
```

`frago chrome navigate` handles tab routing, group isolation, and logging automatically. Bypassing it breaks all of these.

## Scenario Comparison

- **Search info**: ❌ `WebSearch` (crashes in desktop!) → ✅ `frago chrome navigate "https://google.com/search?q=..."`
- **View webpage**: ❌ `Fetch` → ✅ `frago chrome navigate <url>` + `get-content`
- **Open URL**: ❌ `window.open` / raw CDP → ✅ `frago chrome navigate <url>`
- **Extract data**: ❌ Hand-write JS → ✅ Check `frago recipe list` first
- **File operations**: ❌ Manual creation → ✅ Use Claude Code's Write/Edit tools

## Why This Design

### 1. Recipe Has Highest Priority

- **Reusable**: Verified automation workflows
- **Stable**: Contains error handling and fallback selectors
- **Documented**: Has usage instructions and preconditions

### 2. frago Commands Come Second

- **Universal across agents**: Can be used in run/recipe/test
- **Auto logging**: CDP commands automatically logged to execution.jsonl
- **Unified interface**: Consistent `frago <command>` format

### 3. System Commands

- **Powerful**: `jq` for JSON processing, `ffmpeg` for video
- **Flexible composition**: Shell features like pipes, redirects

### 4. Claude Code Tools as Fallback

- **File operations**: Read/Write/Edit/Glob/Grep
- **Auxiliary functions**: AskUserQuestion, TodoWrite
- Use only when above tools cannot satisfy requirements

## Discovering Existing Recipes

```bash
# List all Recipes
frago recipe list

# AI format (JSON)
frago recipe list --format json

# View specific Recipe details
frago recipe info <recipe_name>

# Search related Recipes
frago recipe list | grep "keyword"
```

## Command Help

```bash
# View all frago commands
frago --help

# View specific command usage
frago <command> --help
```
