# frago - Multi-Runtime Automation Infrastructure

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/tsaijamey/Frago)
[![Chrome](https://img.shields.io/badge/requires-Chrome-green)](https://www.google.com/chrome/)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-purple)](https://claude.ai/code)

[简体中文](https://github.com/tsaijamey/Frago/blob/main/README.zh-CN.md)

> **Heard of [Anthropic Cowork](https://claude.com/blog/cowork-research-preview)?** frago does the same — and more.

|  | **Cowork** | **frago** |
|--|------------|-----------|
| **Foundation** | Claude Agent SDK | **Claude Code** (Anthropic's flagship) |
| **Muscle Memory** | None | **Recipe system** (98.7% token savings) |
| **Platform** | macOS only | **Windows / macOS / Linux** |
| **Price** | $20/month subscription | **Free & self-hosted** |
| **Interface** | Desktop app | **Web UI + CLI + Slash Commands** |
| **Data** | Anthropic cloud | **100% local, you own everything** |

**Docs**: [Key Concepts](https://github.com/tsaijamey/Frago/blob/main/docs/concepts.md) · [Installation](https://github.com/tsaijamey/Frago/blob/main/docs/installation.md) · [User Guide](https://github.com/tsaijamey/Frago/blob/main/docs/user-guide.md) · [Recipes](https://github.com/tsaijamey/Frago/blob/main/docs/recipes.md) · [Architecture](https://github.com/tsaijamey/Frago/blob/main/docs/architecture.md) · [Use Cases](https://github.com/tsaijamey/Frago/blob/main/docs/use-cases.md) · [Development](https://github.com/tsaijamey/Frago/blob/main/docs/development.md)

### Quick Start

```bash
uv tool install frago-cli   # Install frago
frago init                   # Initialize environment
frago server start           # Start web service
# Open http://127.0.0.1:8093 in your browser
```

> New to `uv` or setting up a fresh system? See the [Installation Guide](https://github.com/tsaijamey/Frago/blob/main/docs/installation.md) for prerequisites.

---

## Manifesto

> AI should free people from repetitive labor, not become a new instrument of extraction.

**Three beliefs that guide frago:**

### 1. Delivery over Dialogue

Chatting with AI produces nothing. The ICQ era of AI — endless conversation, zero delivery — wastes your time and money.

frago exists for *results*: recipes that run, scripts that execute, data that's extracted. If AI can't hand you a deliverable, it hasn't done its job.

### 2. Your Tools, Your Control

We reject the narrative that you must wait for some company to build AGI before automation serves you.

frago is open source. Your recipes, your skills, your Git repo. You accumulate capability, not subscription fees. The tools you build are *yours* — portable, version-controlled, independent.

### 3. Against Token Exploitation

Many "AI products" are token vending machines wrapped in pretty UIs. You pay per conversation, per generation, per retry — and get nothing persistent in return.

frago attacks this directly through its four-system architecture:

| System | First Encounter | Subsequent Use | Token Savings |
|--------|-----------------|----------------|---------------|
| **No Run/Recipe** | AI explores (150k tokens) | AI explores again (150k tokens) | 0% |
| **Run Only** | AI explores + logs (155k tokens) | Review Run logs (10k tokens) | 93.5% |
| **Run + Recipe** | AI explores + creates Recipe (160k tokens) | Execute Recipe (2k tokens) | **98.7%** |

The savings compound. The recipes stay. Your time returns to family, hobbies, creation — not to feeding another revenue stream.

---

### Recent Updates

| Version | Highlights |
|---------|------------|
| **v0.33.0** | Full Windows support; viewport border indicator; word wrap toggle for code viewer |
| **v0.32.0** | Parameter form input for recipe execution; @ directory autocomplete |
| **v0.31.0** | Per-task title generation; cache service optimization |
| **v0.30.0** | Community recipe uninstall button; improved UI hover states |
| **v0.29.0** | Unified console send button; platform-specific shortcuts |

Multi-runtime automation infrastructure designed for AI agents, providing persistent context management and reusable Recipe system.

---

## Why frago

When facing prompts, AI can only "talk" but not "do"—it "talks once" but never "follows through from start to finish." Think of ChatGPT in 2023. So people designed Agents. Agents call tools through standardized interfaces.

But reality is: tasks are infinite, while tools are finite.

You ask AI to extract YouTube subtitles. It spends 5 minutes exploring, succeeds. The next day, same request—it starts from scratch again. It completely forgot what it did yesterday.

Even an Agent like Claude Code appears clumsy when facing each person's unique task requirements: every time it must explore, every time it burns through tokens, dragging the LLM from start to finish. Slow and unstable: out of 10 attempts, maybe 5 take the right path, while the other 5 are filled with "strange" and "painful" trial-and-error.

Agents lack context—that's a fact. But what kind of context do they lack?

People tried RAG, fragmenting information so Agents could retrieve and "find methods." This is "theoretically correct but practically misguided"—a massive pitfall. The key issue: each person's task requirements are "local" and bounded. They don't need a heavyweight RAG system. RAG over-complicates how individuals solve problems.

Research from Anthropic and Google both point to: directly consulting documentation. The author of this project proposed the same view in 2024. But this approach requires Agents with sufficient capability. Claude Code is exactly such an Agent.

Claude Code designed a documentation architecture: commands and skills, to practice this philosophy. frago builds on this foundation, deeply implementing the author's design philosophy: every piece of methodological knowledge must be tied to concrete executable tools.

In frago's framework, skills are collections of methodologies, and recipes are collections of executable tools.

The author's vision: through frago's Claude Code slash commands (/frago.run and other core commands), establish an Agent specification—enabling it to explore unfamiliar problems and standardize results into structured information; through self-awareness, proactively build the association between skills and recipes.

Ultimately, your Agent can fully understand your descriptions of work and task requirements, leverage existing skills to find and properly use relevant recipes, achieving "driving automated execution with minimal token cost."

frago is not the Agent itself, but the Agent's "skeleton."

Agents are smart enough, but not yet resourceful. frago teaches them to remember how to get things done.

---

## How to Use

frago integrates with Claude Code through three slash commands, forming a complete "explore → solidify → validate" loop.

```
/frago.run     Explore and research, accumulate experience
     ↓
/frago.recipe  Solidify experience into reusable recipes
     ↓
/frago.test    Validate recipes (while context is fresh)
```

### Step 1: Explore and Research

In Claude Code, type:

```
/frago.run Research how to extract YouTube video subtitles
```

The Agent will:
- Create a project to store this run instance
- Use frago's basic tools (navigate, click, exec-js, etc.) to explore
- Automatically record `execution.jsonl` and key findings
- Persist all screenshots, scripts, and output files

```
projects/youtube-transcript-research/
├── logs/execution.jsonl    # Structured execution logs
├── screenshots/            # Screenshot archive
├── scripts/                # Validated scripts
└── outputs/                # Output files
```

### Step 2: Solidify Recipes

After exploration, type:

```
/frago.recipe
```

The Agent will:
- Analyze the experience accumulated during exploration
- Auto-generate necessary recipes for this task
- Create corresponding skills (*coming soon*)
- Associate skills with recipes

Generated recipe example:

```yaml
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
description: "Extract complete transcript text from YouTube videos"
use_cases:
  - "Batch extract video subtitle content for text analysis"
  - "Create indexes or summaries for videos"
---
```

### Step 3: Validate Recipes

While the session context is still fresh, test immediately:

```
/frago.test youtube_extract_video_transcript
```

Validation failed? Fix it on the spot, no need to re-explore. This is why recipe and test should be parallel—debugging costs more after context is lost.

**This is the value of the "skeleton"**: 5 minutes to explore the first time, seconds to execute thereafter with validated recipes.

---

## Technical Foundation

The above workflow relies on frago's underlying capabilities:

| Capability | Description |
|------------|-------------|
| **Native CDP** | Direct Chrome DevTools Protocol connection, ~2MB lightweight, no Node.js deps |
| **Run System** | Persistent task context, JSONL structured logs |
| **Recipe System** | Metadata-driven, three-tier priority (Project > User > Example) |
| **Web Service** | FastAPI backend + React frontend, browser-based GUI on port 8093 |
| **Multi-Runtime** | Chrome JS, Python, Shell runtime support |

```
Architecture Comparison:
Playwright:  Python → Node.js relay → CDP → Chrome  (~100MB)
frago:       Python → CDP → Chrome                  (~2MB)
```

---

## frago Is Not Playwright/Selenium

Playwright and Selenium are **testing tools**—launch browser, run tests, close browser. Every run starts fresh.

frago is **the skeleton for AI**—connect to an existing browser, explore, learn, remember. Experience accumulates.

| You need... | Choose |
|-------------|--------|
| Quality assurance, regression testing, CI/CD | Playwright/Selenium |
| Data collection, workflow automation, AI-assisted tasks | frago |
| One-off scripts, run and discard | Playwright/Selenium |
| Accumulate experience, faster next time | frago |

Technical differences (lightweight, direct CDP, no Node.js dependency) are outcomes, not goals.

**The core difference is design philosophy**: testing tools assume you know what to do; frago assumes you're exploring, and helps you remember what you discovered.

## frago vs Dify/Coze/n8n

Dify, Coze, and n8n are **workflow orchestration tools**.

Traditional usage: manually drag nodes, connect lines, configure parameters. n8n launched [AI Workflow Builder](https://docs.n8n.io/advanced-ai/ai-workflow-builder/) that can generate workflow nodes from natural language (Dify and Coze don't have similar features yet).

But whether manual or AI-assisted, what do you end up with? **A flowchart.**

Then what?

1. You still need to enter the platform, understand the diagram
2. Run, error, go back and modify node config
3. Run again, another error, modify again
4. After debugging passes, the flowchart runs

**AI drew the diagram for you, but debugging, modifying, maintaining—still your job.**

Using frago:

```
/frago.run Scrape data from this website
```

No flowchart. AI goes to work directly—opens browser, clicks, extracts data, handles errors. You just wait.

When done:

```
/frago.recipe
```

Recipe auto-generated, ready to reuse for similar tasks.

**You don't need to enter any platform, don't need to look at any flowchart.**

| | Orchestration Tools (incl. AI-assisted) | frago |
|--|----------------------------------------|-------|
| What AI does | Draws flowcharts for you | Does the work directly |
| What you do | Enter platform, read diagrams, debug, modify config | State needs, wait for results |
| Output | A flowchart that needs maintenance | Reusable recipe |

**Orchestration tools' AI is your "diagram assistant"; frago's AI is your "executor".**

Of course, if you need scheduled triggers, visual monitoring, team collaboration approvals—orchestration tools are better fits. But if you just want to get things done—frago lets you solve problems by talking, no platform to learn.

---

## Resource Sync

frago is open-source—anyone can install it via PyPI. But the **skeleton** is universal, while the **brain** is personal.

Your personalized resources (skills and recipes) shouldn't live in the public package. They belong to you. frago provides `frago sync` to keep your resources consistent across different machines.

### How It Works

```
┌─────────────┐              ┌─────────────┐
│   Local     │  ◄─── sync ──►  │   Remote    │
│ ~/.claude/  │              │  Git Repo   │
│ ~/.frago/   │              │             │
└─────────────┘              └─────────────┘
```

The `sync` command is bidirectional:
1. Fetch updates from your remote repository
2. Merge with local changes
3. Push modifications back to remote

### Usage

**First-time setup**:
```bash
frago sync --set-repo https://github.com/you/my-frago-resources.git
```

**Daily usage**:
```bash
frago sync              # Bidirectional sync
frago sync --dry-run    # Preview changes without syncing
frago sync --no-push    # Only fetch, don't push local changes
```

### What Gets Synced

Only frago-specific resources:
- `~/.claude/skills/frago-*` (frago skills)
- `~/.frago/recipes/` (all recipes)

Your personal, non-frago Claude commands and skills are never touched.

---

## Documentation Navigation

- **[Key Concepts](https://github.com/tsaijamey/Frago/blob/main/docs/concepts.md)** - Skill, Recipe, Run definitions and relationships
- **[Use Cases](https://github.com/tsaijamey/Frago/blob/main/docs/use-cases.md)** - Complete workflow from Recipe creation to Workflow orchestration
- **[Architecture](https://github.com/tsaijamey/Frago/blob/main/docs/architecture.md)** - Core differences, technology choices, system design
- **[Installation](https://github.com/tsaijamey/Frago/blob/main/docs/installation.md)** - Installation methods, dependencies, optional features
- **[User Guide](https://github.com/tsaijamey/Frago/blob/main/docs/user-guide.md)** - CDP commands, Recipe management, Run system
- **[Recipe System](https://github.com/tsaijamey/Frago/blob/main/docs/recipes.md)** - AI-First design, metadata-driven, Workflow orchestration
- **[Development](https://github.com/tsaijamey/Frago/blob/main/docs/development.md)** - Project structure, development standards, testing methods
- **[Roadmap](https://github.com/tsaijamey/Frago/blob/main/docs/roadmap.md)** - Completed features, todos, version planning

### Writings

Personal thoughts on AI automation, Agent design, and lessons learned.

→ **[Read the Writings](writings/README.md)**

---

## Project Status

📍 **Current Stage**: Full cross-platform support with enhanced UI

**Latest Features (v0.27.0 - v0.33.0)**:

- ✅ Full Windows support - Comprehensive compatibility fixes and optimizations
- ✅ Recipe parameter forms - Interactive input for recipe execution
- ✅ Directory autocomplete - @ trigger for path input fields
- ✅ Viewport indicator - Visual border for automation control
- ✅ Code viewer enhancements - Word wrap toggle, improved rendering

**Earlier Features (v0.17.0 - v0.26.0)**:

- ✅ Workspace file browser - Browse run instance directories in Web UI
- ✅ Media viewer - `frago view` supports video, image, audio, 3D models (glTF/GLB)
- ✅ Community recipes - `recipe install/uninstall/update/search/share` for community contributions
- ✅ WebSocket real-time sync - Server push updates, reduced polling
- ✅ Cross-platform autostart - `frago autostart` manages server boot startup
- ✅ i18n support - UI internationalization with user language preferences
- ✅ Web service mode - `frago server` launches browser-based GUI on port 8093

**Core Infrastructure**:

- ✅ Native CDP protocol layer (direct Chrome control, ~2MB lightweight)
- ✅ Recipe metadata-driven architecture (chrome-js/python/shell runtime)
- ✅ Run command system (topic-based task management, JSONL structured logs)
- ✅ Web service backend (FastAPI + React frontend)
- ✅ CLI tools and grouped command system

See [Roadmap](https://github.com/tsaijamey/Frago/blob/main/docs/roadmap.md) for details

---

## License

AGPL-3.0 License - see [LICENSE](https://github.com/tsaijamey/Frago/blob/main/LICENSE) file

## Contributing

Issues and Pull Requests are welcome!

- Project issues: [Submit Issue](https://github.com/tsaijamey/Frago/issues)
- Technical discussion: [Discussions](https://github.com/tsaijamey/Frago/discussions)

### Contributors

<a href="https://github.com/tsaijamey/Frago/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=tsaijamey/Frago" />
</a>

---

Created with Claude Code | 2025-11
