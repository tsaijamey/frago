---
id: getting-started
title: Getting Started
category: getting-started
order: 1
version: 0.38.1
last_updated: 2026-01-17
tags:
  - beginner
  - first-time
  - quick-start
---

# Getting Started

## Q: I just installed frago and opened the Web UI. Where should I start?

**A**: Here's the recommended way to get started:

1. **Explore available recipes** → Click "Recipes" in the left sidebar
   - Switch to "Community" tab to browse community recipes
   - Recipes are standardized automation task definitions, e.g., "Extract YouTube subtitles"
   - Find an interesting recipe and click to see what it does

2. **Let AI help you** → Click "Console" in the left sidebar
   - Type what you want to do in the input box
   - Example: "Extract content from this webpage"
   - AI will execute automatically and show you the results

3. **Run deterministic tasks** → Click "Tasks" in the left sidebar
   - Execute existing Recipes
   - Run automation tasks that don't need route adjustments

**💡 Tip**: Beginners should start with community recipes to experience frago's capabilities.

---

## Q: There are so many menu items on the left. What does each one do?

**A**: Here's what each menu item does:

- **Dashboard**: System overview
  - Server status and uptime
  - Activity statistics for the past 6 hours
  - Overview of Tasks/Recipes/Skills count

- **Console**: Recipe development workspace
  - Auto-approves all operations (file I/O, commands, etc.)
  - No waiting for confirmation, AI executes directly
  - ⚠️ Warning: All operations are executed automatically

- **Tasks**: Deterministic task execution
  - Run existing Recipes or standardized tasks
  - For tasks that don't require mid-course adjustments
  - Input a prompt or select a recipe to execute

- **Recipes**: Recipe management center
  - Browse local and community recipes
  - View recipe parameters, use cases, examples
  - One-click execution with parameter input

- **Skills**: Methodology documents (advanced)
  - Tell AI "how to do certain types of tasks"
  - Works with Recipes
  - Beginners can skip this for now

- **Workspace**: Project file browser
  - View Run project directories
  - Browse logs, screenshots, output files
  - File preview functionality

- **Sync**: Cross-device synchronization
  - Configure Git repository
  - Sync Recipes and Skills across machines
  - Not needed for single-machine usage

- **Secrets**: Sensitive information management
  - Store API keys
  - Recipes can reference them securely
  - Environment variable configuration

- **Settings**: Configuration center
  - API Key configuration
  - Model Override (switch Claude models)
  - Appearance settings: theme, language

---

## Q: I want to try frago. What's the simplest task to run?

**A**: Run the `test_inspect_tab` Recipe - it's the simplest test.

**Steps**:
1. Click "Recipes" in the left sidebar
2. Search for "test" or find `test_inspect_tab`
3. Click to view details
4. Click the "Run" button
5. Wait a few seconds and check the output

**What this Recipe does**:
- Inspects current browser tab info (title, URL, DOM stats)
- Doesn't modify anything - completely safe
- Helps you understand how Recipe execution works

**After seeing the results**:
- You'll see the current page's title, URL, and other info
- This confirms frago's Chrome automation is working
- Try other more complex Recipes

---

## Q: What is "Claude Code" mentioned in the tutorial?

**A**: Claude Code is Anthropic's official CLI tool. frago works best when paired with it.

**Claude Code CLI vs frago Web UI**:

| Feature | Claude Code CLI | frago Web UI |
|---------|----------------|--------------|
| Interaction | Command line | Browser interface |
| Tool Approval | Manual confirmation | Auto-approve (Console) |
| Use Case | Sensitive projects, control | Fast development, visual |
| Learning Curve | Requires CLI familiarity | Intuitive and easy |

**frago's Unique Value**:
- frago Web UI works independently without Claude Code CLI
- Web UI provides visual interface and Recipe management
- Console mode for rapid development and testing
- Tasks mode for running deterministic automation tasks

**How to use together** (optional):
```bash
# Use frago commands in CLI
/frago.run Research how to extract YouTube subtitles
/frago.recipe Create a recipe to extract subtitles
/frago.test youtube_extract_video_transcript
```

**Beginner Tip**: Start with frago Web UI. CLI can be explored later.
