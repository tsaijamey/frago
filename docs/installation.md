# Installation Guide

[简体中文](installation.zh-CN.md)

## Basic Installation

Install core features (CDP operations + Recipe system core):

```bash
# Using pip
pip install frago

# Using uv (recommended)
uv add frago
```

**Core features include**:
- ✅ Chrome DevTools Protocol (CDP) operations
- ✅ Recipe system (list, execute, metadata management)
- ✅ Output to stdout and file
- ✅ Python/Shell Recipe execution
- ✅ Workflow orchestration

---

## Environment Initialization

After installing the package, run the init command to set up your environment:

```bash
frago init
```

### What `frago init` Does

The init command performs the following steps:

1. **Dependency Check**
   - Detects Node.js (required version ≥18.0.0) and its path
   - Detects Claude Code CLI and its version
   - Displays status with ✅/❌ indicators

2. **Automatic Installation** (if dependencies are missing)
   - Node.js: Installs via nvm (Node Version Manager)
   - Claude Code: Installs via `npm install -g @anthropic-ai/claude-code`

3. **Authentication Configuration**
   - **Default**: Uses Claude Code's built-in authentication (Anthropic account or existing settings)
   - **Custom Endpoint**: Configures third-party API providers that support Anthropic API compatibility:
     - DeepSeek (deepseek-chat)
     - Aliyun Bailian (qwen3-coder-plus)
     - Kimi K2 (kimi-k2-turbo-preview)
     - MiniMax M2
     - Custom URL/Key/Model

4. **Resource Installation**
   - Installs Claude Code slash commands to `~/.claude/commands/`
   - Installs example recipes to `~/.frago/recipes/`

### Init Command Options

```bash
# Show current configuration and installed resources
frago init --show-config

# Skip dependency checks (only update config)
frago init --skip-deps

# Reset configuration and re-initialize
frago init --reset

# Non-interactive mode (uses defaults, for CI/CD)
frago init --non-interactive

# Skip resource installation
frago init --skip-resources

# Force update all resources (overwrite existing recipes)
frago init --update-resources
```

### Configuration Files

| File | Purpose |
|------|---------|
| `~/.frago/config.json` | Frago configuration (auth method, resource status) |
| `~/.claude/settings.json` | Claude Code settings (custom API endpoint config) |
| `~/.claude/commands/frago.*.md` | Installed slash commands |
| `~/.frago/recipes/` | User-level recipes |

---

## Optional Features

### Clipboard Support

If you need to output Recipe results to clipboard:

```bash
# Using pip
pip install frago[clipboard]

# Using uv
uv add "frago[clipboard]"
```

**Additional features provided**:
- ✅ `--output-clipboard` option
- ✅ `clipboard_read` Recipe (system clipboard read)

---

### Full Installation (All Optional Features)

Install all features:

```bash
# Using pip
pip install frago[all]

# Using uv
uv add "frago[all]"
```

---

## Development Environment Installation

If you want to contribute to development or run tests:

```bash
# Clone repository
git clone https://github.com/frago/frago.git
cd frago

# Install development dependencies using uv (recommended)
uv sync --all-extras --dev

# Or using pip
pip install -e ".[dev,all]"
```

**Development dependencies include**:
- pytest (test framework)
- pytest-cov (coverage)
- ruff (code linting)
- mypy (type checking)
- black (code formatting)

---

## Dependency Details

### Required Dependencies (installed for all users)

```toml
dependencies = [
    "websocket-client>=1.9.0",  # CDP WebSocket connection
    "click>=8.1.0",             # CLI framework
    "pydantic>=2.0.0",          # Data validation
    "python-dotenv>=1.0.0",     # Environment variables
    "pyyaml>=6.0.0",            # Recipe metadata parsing
]
```

### Optional Dependencies (install as needed)

```toml
[project.optional-dependencies]
clipboard = ["pyperclip>=1.8.0"]  # Clipboard functionality
all = ["pyperclip>=1.8.0"]        # All optional features
dev = ["pytest>=7.4.0", ...]      # Development tools
```

---

## System Requirements

- **Python**: 3.9+
- **Operating System**: macOS, Linux, Windows
- **Chrome Browser**: For chrome-js Recipe execution

---

## Verify Installation

Verify after installation:

```bash
# Check version
frago --version

# List available Recipes
frago recipe list

# View help
frago --help
```

---

## Upgrade

```bash
# Using pip
pip install --upgrade frago

# Using uv
uv add --upgrade frago
```

---

## Uninstall

```bash
# Using pip
pip uninstall frago

# Using uv
uv remove frago
```
