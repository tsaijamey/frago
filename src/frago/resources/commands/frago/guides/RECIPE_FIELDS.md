# Recipe Fields Specification

Applies to: `/frago.recipe`, `/frago.test`

## Validation Commands

```bash
frago recipe validate <recipe directory or recipe.md path>
frago recipe validate <path> --format json
```

## Required Fields

| Field | Type | Requirement |
|------|------|------|
| `name` | string | Only contains `[a-zA-Z0-9_-]` |
| `type` | string | `atomic` or `workflow` |
| `runtime` | string | `chrome-js`, `python`, `shell` |
| `version` | string | Format `1.0` or `1.0.0` |
| `description` | string | Required, ≤200 characters |
| `use_cases` | list | At least one scenario |
| `output_targets` | list | Values from `stdout`, `file`, `clipboard` |

## Optional Fields

| Field | Type | Notes |
|------|------|------|
| `inputs` | dict | Input parameter definition (needs `type` and `required`) |
| `outputs` | dict | Output definition |
| `dependencies` | list | Other recipes depended on (workflow type) |
| `tags` | list | Tags (AI-understandable field) |
| `env` | dict | Environment variable definition (see below) |
| `system_packages` | bool | Whether to use system Python |

## Environment Variables (env) Field Specification

Recipes can declare required environment variables, which will be automatically loaded from `~/.frago/.env` at runtime.

### env Field Structure

```yaml
env:
  VAR_NAME:
    required: true          # Whether required (default false)
    default: "default value" # Default value (string)
    description: "Variable description"  # Description
```

### Example

```yaml
env:
  OPENAI_API_KEY:
    required: true
    description: "OpenAI API key"
  MODEL_NAME:
    required: false
    default: "gpt-4"
    description: "Model name to use"
```

### Environment Variable Loading Priority (High to Low)

1. Workflow context shared variables
2. **`~/.frago/.env`**
3. System environment variables
4. Recipe-defined `default` value

### ~/.frago/.env Configuration

Configure commonly used environment variables in `~/.frago/.env`:

```bash
# API Keys
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx

# Other configurations
DEFAULT_MODEL=gpt-4
```

These variables will be automatically loaded when recipes run.

## Python Recipe Dependency Declaration (PEP 723)

Python recipes are executed using `uv run`, supporting **PEP 723 inline dependency declaration**.

### Format

Add at the top of `recipe.py` file (no shebang needed):

```python
# /// script
# requires-python = ">=3.9"
# dependencies = ["package1", "package2>=1.0"]
# ///
```

### Example

```python
# /// script
# requires-python = ">=3.9"
# dependencies = ["edge-tts", "httpx>=0.24"]
# ///
"""
Recipe: tts_generate_voice
Description: Generate voice using Edge TTS
"""

import json
import sys
# ...
```

### Notes

- `uv run` will automatically parse inline dependencies and create a temporary virtual environment
- No need for `requirements.txt` or `pyproject.toml`
- Dependencies are installed only on first run, subsequent executions use cache
- If system packages (like `dbus`) are needed, set `system_packages: true` in `recipe.md`

## Validation Content

`frago recipe validate` checks the following:

1. **YAML frontmatter** - Parse YAML header in recipe.md
2. **Required fields** - Whether all required fields exist
3. **Field format** - name character rules, version format, enum values
4. **Script files** - Check if corresponding script (recipe.js/py/sh) exists and is non-empty based on runtime
5. **Syntax check** - Python scripts undergo syntax checking
6. **Dependency check** - workflow type checks if depended recipes are registered

## Validation Output Examples

### Validation Passed

```
✓ Recipe validation passed: examples/atomic/chrome/my_recipe
  Name: my_recipe
  Type: atomic
  Runtime: chrome-js
```

### Validation Failed

```
✗ Recipe validation failed: examples/atomic/chrome/broken_recipe
Errors:
  • name must only contain letters, numbers, underscores, hyphens
  • use_cases must contain at least one use case
  • Script file does not exist: recipe.js (runtime: chrome-js)
```

### JSON Format

```json
{
  "valid": false,
  "path": "examples/atomic/chrome/broken_recipe",
  "name": null,
  "type": null,
  "runtime": null,
  "errors": ["Metadata parsing failed: Missing required field: 'name'"],
  "warnings": []
}
```

## Complete recipe.md Template

```yaml
---
name: platform_action_object
type: atomic
runtime: chrome-js
version: "1.0.0"
description: "One-sentence description of recipe function (≤200 characters)"
use_cases:
  - "Scenario 1: User needs..."
  - "Scenario 2: When..."
output_targets:
  - stdout
  - file
tags:
  - extraction
  - chrome
inputs:
  param_name:
    type: string
    required: true
    description: "Parameter description"
outputs:
  result:
    type: object
    description: "Output description"
env:
  API_KEY:
    required: true
    description: "API key, configure in ~/.frago/.env"
  TIMEOUT:
    required: false
    default: "30"
    description: "Timeout (seconds)"
---

# platform_action_object

## Feature Description
## Usage
## Prerequisites
## Expected Output
## Notes
## Update History
```
