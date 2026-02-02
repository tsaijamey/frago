# frago

**AI Agent 的骨架框架** — 让 AI 记住如何完成任务，而不是每次从头探索。

[简体中文](README.zh-CN.md)

## Why frago

AI Agents are smart, but unpredictable. Ask the same task 10 times, you might get 10 different results — some work, some don't.

frago solves this with **Recipe system**: validated automation scripts that run deterministically. Once a Recipe works, it works every time.

**Predictable execution. That's what matters.**

> Same philosophy as Anthropic's ["Code execution with MCP"](https://www.anthropic.com/engineering/code-execution-with-mcp): deterministic code beats repeated LLM exploration. frago uses Recipes instead of MCP.

## Comparison

| | **Cowork** | **OpenClaw** | **frago** |
|--|------------|--------------|-----------|
| **Best for** | Non-tech file management | Multi-channel messaging | Reusable automation + Claude Code |
| **Memory** | None (fresh each session) | Context across conversations | **Recipe system** (validated scripts) |
| **Reliability** | AI explores each time | Varies by task | **Deterministic** (Recipe = guaranteed) |
| **Platform** | macOS (Windows planned) | Any OS | Windows / macOS / Linux |
| **Price** | $20-200/mo subscription | Free + API costs | **Free & self-hosted** |
| **Foundation** | Claude Agent SDK | Pi agent + multi-channel | **Claude Code** (Anthropic flagship) |
| **Data** | Anthropic cloud | Local-first | **100% local** |

**Choose based on your needs:**
- **Cowork** — Great UX for organizing files, ideal for non-developers
- **OpenClaw** — Powerful multi-channel inbox (WhatsApp, Telegram, Slack...)
- **frago** — Deterministic automation with Claude Code integration

## Quick Start

```bash
uv tool install frago-cli   # Install
frago init                   # Initialize
frago server start           # Start Web UI → http://127.0.0.1:8093
```

> New to `uv`? See [Installation Guide](docs/installation.md).

## Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.13+ |
| Node.js | 20+ |
| Chrome | Latest |

## How It Works

frago integrates with Claude Code through slash commands:

```
/frago.run     Explore and research, accumulate experience
     ↓
/frago.recipe  Solidify experience into reusable recipes
     ↓
/frago.test    Validate recipes (while context is fresh)
```

### The Recipe Advantage

```
AI exploration:   Unpredictable — might succeed, might fail, might take wrong path
                      ↓
                  Once it works → save as Recipe
                      ↓
Recipe execution: Deterministic — validated script, guaranteed results
```

**Recipe = muscle memory. No thinking, just doing.**

## Core Systems

| System | Purpose |
|--------|---------|
| **Recipe** | Reusable automation scripts (chrome-js/python/shell) |
| **Run** | Persistent task context with JSONL logs |
| **CDP** | Native Chrome control (~2MB, no Node.js relay) |
| **Web UI** | Browser-based GUI on port 8093 |

## CLI Commands

```bash
# Recipe management
frago recipe list              # List all recipes
frago recipe run <name>        # Execute recipe

# Browser control
frago chrome navigate <url>
frago chrome click <selector>
frago chrome screenshot <file>

# Server
frago server start/stop/status
```

## Documentation

- [Installation](docs/installation.md) — Setup and prerequisites
- [User Guide](docs/user-guide.md) — Commands and usage
- [Concepts](docs/concepts.md) — Run, Recipe, Skill relationships
- [Architecture](docs/architecture.md) — Technical design
- [Recipes](docs/recipes.md) — Recipe system deep dive

## Resource Sync

Keep your recipes synced across machines:

```bash
frago sync --set-repo git@github.com:you/my-resources.git
frago sync  # Bidirectional sync
```

## License

AGPL-3.0 — See [LICENSE](LICENSE)

## Contributing

- [Submit Issue](https://github.com/tsaijamey/Frago/issues)
- [Discussions](https://github.com/tsaijamey/Frago/discussions)

---

Created with Claude Code
