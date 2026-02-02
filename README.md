# frago

**Skeleton framework for AI Agents** — Let AI remember how to complete tasks, instead of exploring from scratch every time.

[简体中文](README.zh-CN.md)

## Why frago

AI Agents are smart, but unpredictable. Ask the same task 10 times, you might get 10 different results — some work, some don't.

frago solves this with **Recipe system**: validated automation scripts that run deterministically. Once a Recipe works, it works every time.

**Predictable execution. That's what matters.**

> Same philosophy as Anthropic's ["Code execution with MCP"](https://www.anthropic.com/engineering/code-execution-with-mcp): deterministic code beats repeated LLM exploration. frago uses Recipes instead of MCP.

## Comparison

| | **Cowork** | **OpenClaw** | **frago** |
|--|------------|--------------|-----------|
| **Best for** | Daily tasks | Cross-platform assistant | Reusable automation |
| **Workflow** | Chat → AI explores | Chat → AI explores | Explore → Agent auto-solidifies → Deterministic execution |
| **Foundation** | Claude Agent SDK | Custom | Claude Code |

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
