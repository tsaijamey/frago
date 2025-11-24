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
