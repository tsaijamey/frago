# Developer Docs

[简体中文](developer.zh-CN.md)

frago is an agent OS. This page is the entry point for developers who want to use the CLI or contribute to the project.

## CLI

The command-line interface to frago — like a shell to an OS. Everything the desktop app can do, the CLI can do too, plus browser automation, Recipe development, and direct agent control.

### Quick Install

```bash
# macOS/Linux
curl -fsSL https://frago.ai/install.sh | sh

# Windows
powershell -c "irm https://frago.ai/install.ps1 | iex"
```

See [Installation Guide](installation.md) for requirements, manual install, and platform-specific prerequisites.

## Development Setup

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```

## Documentation

- [Installation](installation.md) — CLI install and platform prerequisites
- [Concepts](concepts.md) — How Recipes, Runs, and Skills work together
- [Recipe System](recipes.md) — Recipe system deep dive
- [Examples](examples.md) — Practical automation examples
- [Browser Support](browser-support.md) — Supported browsers and CDP commands
