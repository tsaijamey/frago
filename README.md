# frago - Multi-Runtime Automation Infrastructure

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/tsaijamey/Frago)
[![Chrome](https://img.shields.io/badge/requires-Chrome-green)](https://www.google.com/chrome/)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-purple)](https://claude.ai/code)

[简体中文](https://github.com/tsaijamey/Frago/blob/main/README.zh-CN.md)

Multi-runtime automation infrastructure designed for AI agents, providing persistent context management and reusable Recipe system.

**Docs**: [Key Concepts](https://github.com/tsaijamey/Frago/blob/main/docs/concepts.md) · [Installation](https://github.com/tsaijamey/Frago/blob/main/docs/installation.md) · [User Guide](https://github.com/tsaijamey/Frago/blob/main/docs/user-guide.md) · [Recipes](https://github.com/tsaijamey/Frago/blob/main/docs/recipes.md) · [Architecture](https://github.com/tsaijamey/Frago/blob/main/docs/architecture.md) · [Use Cases](https://github.com/tsaijamey/Frago/blob/main/docs/use-cases.md) · [Development](https://github.com/tsaijamey/Frago/blob/main/docs/development.md)

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

frago integrates with Claude Code through four slash commands, forming a complete "explore → solidify → execute" loop.

```
/frago.run     Explore and research, accumulate experience
     ↓
/frago.recipe  Solidify experience into reusable recipes
/frago.test    Validate recipes (while context is fresh)
     ↓
/frago.exec    Execute quickly with skill guidance
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

### Step 4: Quick Execution

Next time you have a similar need, type:

```
/frago.exec video-production Create a short video about AI
```

The Agent will:
- Load the specified skill (video-production)
- Follow the methodology in the skill to invoke relevant recipes
- Complete the task quickly, no repeated exploration

**This is the value of the "skeleton"**: 5 minutes to explore the first time, seconds to execute thereafter.

---

## Technical Foundation

The above workflow relies on frago's underlying capabilities:

| Capability | Description |
|------------|-------------|
| **Native CDP** | Direct Chrome DevTools Protocol connection, ~2MB lightweight, no Node.js deps |
| **Run System** | Persistent task context, JSONL structured logs |
| **Recipe System** | Metadata-driven, three-tier priority (Project > User > Example) |
| **Multi-Runtime** | Chrome JS, Python, Shell runtime support |

```
Architecture Comparison:
Playwright:  Python → Node.js relay → CDP → Chrome  (~100MB)
frago:       Python → CDP → Chrome                  (~2MB)
```

---

## Quick Start

### Installation

```bash
# Basic installation (core features)
pip install frago-cli
# Or use uv (recommended)
uv tool install frago-cli

# Initialize environment (check dependencies, configure auth, install resources)
frago init
```

### What `frago init` Does

The init command sets up your environment in one step:

- **Checks dependencies**: Node.js ≥18.0.0, Claude Code CLI
- **Auto-installs missing deps**: Node.js via nvm, Claude Code via npm
- **Configures authentication**: Default (Claude Code built-in) or custom API endpoint (DeepSeek, Aliyun, Kimi, MiniMax)
- **Installs resources**: Slash commands to `~/.claude/commands/`, example recipes to `~/.frago/recipes/`

```bash
# View current config and resources
frago init --show-config

# Reset and re-initialize
frago init --reset
```

See [Installation Guide](https://github.com/tsaijamey/Frago/blob/main/docs/installation.md) for details

### Basic Usage

After installation, enter Claude Code and use slash commands:

```bash
# Explore and research
/frago.run Search for Python jobs on Upwork and analyze skill requirements

# Solidify recipes
/frago.recipe

# Validate recipes
/frago.test upwork_search_jobs

# Quick execution (next time)
/frago.exec job-hunting Search for remote Python jobs
```

See the "How to Use" section above for detailed workflow.

### Command Line Tools (Human Direct Use)

frago also provides CLI tools for debugging or script integration:

```bash
# Browser operations
frago chrome navigate https://example.com
frago chrome click 'button[type="submit"]'
frago chrome screenshot output.png

# Recipe management
frago recipe list
frago recipe info <recipe_name>
frago recipe run <recipe_name> --params '{...}'

# Run instance management
frago run list
frago run info <run_id>
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

Recipe auto-generated. Next time:

```
/frago.exec Scrape similar website
```

**You don't need to enter any platform, don't need to look at any flowchart.**

| | Orchestration Tools (incl. AI-assisted) | frago |
|--|----------------------------------------|-------|
| What AI does | Draws flowcharts for you | Does the work directly |
| What you do | Enter platform, read diagrams, debug, modify config | State needs, wait for results |
| Output | A flowchart that needs maintenance | Reusable recipe |

**Orchestration tools' AI is your "diagram assistant"; frago's AI is your "executor".**

Of course, if you need scheduled triggers, visual monitoring, team collaboration approvals—orchestration tools are better fits. But if you just want to get things done—frago lets you solve problems by talking, no platform to learn.

---

## Resource Management

### Why Resource Sync Commands

frago is open-source—anyone can install it via PyPI. But the **skeleton** is universal, while the **brain** is personal.

Each person has:
- Their own application scenarios
- Personalized knowledge (skills)
- Custom automation scripts (recipes)

These personalized resources shouldn't live in the public package. They belong to you.

frago's philosophy: **cross-environment consistency**. Your resources should be available wherever you work—different machines, fresh installations, or new projects. The tool comes from PyPI; your brain comes from your private repository.

frago doesn't provide community-level cloud sync services (yet). Instead, it gives you commands to manage sync with your own Git repository.

### Resource Flow Overview

```
┌─────────────┐   publish   ┌─────────────┐    sync    ┌─────────────┐
│   Project   │ ──────────→ │   System    │ ─────────→ │   Remote    │
│  .claude/   │             │ ~/.claude/  │            │  Git Repo   │
│  examples/  │             │ ~/.frago/   │            │             │
└─────────────┘             └─────────────┘            └─────────────┘
       ↑                          │                          │
       │       dev-load           │         deploy           │
       └──────────────────────────┴──────────────────────────┘
```

### Commands

| Command | Direction | Purpose |
|---------|-----------|---------|
| `publish` | Project → System | Push project resources to system directories |
| `sync` | System → Remote | Push system resources to your private Git repo |
| `deploy` | Remote → System | Pull from your private repo to system directories |
| `dev-load` | System → Project | Load system resources into current project (dev only) |

### Typical Workflows

**Developer Flow** (local changes → cloud):
```bash
# After editing recipes in your project
frago publish              # Project → System
frago sync                 # System → Remote Git
```

**New Machine Flow** (cloud → local):
```bash
# First time setup on a new machine
frago sync --set-repo git@github.com:you/my-frago-resources.git
frago deploy               # Remote Git → System
frago dev-load             # System → Project (if developing frago)
```

**Regular User** (just uses frago):
```bash
frago deploy               # Get latest resources from your repo
# Resources are now in ~/.claude/ and ~/.frago/, ready to use
```

### What Gets Synced

Only frago-specific resources are synced:
- `frago.*.md` commands (not your other Claude commands)
- `frago-*` skills (not your other skills)
- All recipes in `~/.frago/recipes/`

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

---

## Project Status

📍 **Current Stage**: GUI app mode and session monitoring complete, entering developer experience enhancement phase

**Latest Features (Feature 008-010)**:

- ✅ GUI app mode - `frago gui` launches desktop interface with pywebview
- ✅ GUI design optimization - GitHub Dark color scheme for professional visual experience
- ✅ Agent session monitoring - Real-time tracking and parsing of Claude Code session data
- ✅ Session data persistence - `~/.frago/sessions/{agent_type}/{session_id}/` structured storage

**Core Infrastructure**:

- ✅ Native CDP protocol layer (direct Chrome control, ~2MB lightweight)
- ✅ Recipe metadata-driven architecture (chrome-js/python/shell runtime)
- ✅ Run command system (topic-based task management, JSONL structured logs)
- ✅ Init command system (dependency check, resource installation)
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
