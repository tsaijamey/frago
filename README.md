# frago

**An operating system for AI agents** — frago runs AI agents on your computer so you don't have to do repetitive work yourself.

> frago is not affiliated with OpenClaw. frago predates OpenClaw by approximately one month.

[简体中文](README.zh-CN.md)

## Why frago

**Easy to install, easy to set up.** The desktop app is ~2MB. After download, it automatically checks and installs everything it needs. Configure one AI model, and you're ready to go. No terminal, no environment setup, no dependencies to manage yourself.

You spend hours every day on tasks a computer could do for you — filling spreadsheets, pulling data from websites, moving files around. AI agents can already do these things, but they're trapped behind terminals and command lines that most people can't use.

frago gives AI agents a place to run, and gives you a window to watch and control them. Describe what you need, and frago handles the rest.

When AI figures out how to do something, frago saves the working steps so the same task can be done again with one click — no AI needed.

## Get Started

Download and install:

| Platform | Download |
|----------|----------|
| **macOS (Apple Silicon)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **macOS (Intel)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **Windows** | [.msi](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (deb)** | [.deb](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (rpm)** | [.rpm](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (AppImage)** | [.AppImage](https://github.com/tsaijamey/frago/releases/latest) |

> All downloads available on the [Releases page](https://github.com/tsaijamey/frago/releases/latest).

## How It Works

```
You describe the task
    ↓
AI does it for you
    ↓
Same task next time → one click, done
```

Why does "one click" work? When AI completes a task, it saves the working steps as executable code. This code runs the same way every time — no AI needed, no randomness, no token cost. We call these saved procedures **Recipes**.

A Recipe is software that frago built for itself. Unlike prompts or instructions that still rely on AI interpretation each time, a Recipe is real code that runs deterministically. Recipes can also be reused across different tasks — an AI that knows how to log into a website can use that Recipe as a building block for any task that starts with logging in.

## Documentation

- [User Guide](docs/user-guide.md) — Getting started after install
- [Concepts](docs/concepts.md) — How Recipes, Runs, and Skills work together
- [Developer Docs](docs/developer.md) — CLI, architecture, and technical details

## License

AGPL-3.0 — See [LICENSE](LICENSE)

## Contributing

- [Submit Issue](https://github.com/tsaijamey/Frago/issues)
- [Discussions](https://github.com/tsaijamey/Frago/discussions)

---

Created with Claude Code
