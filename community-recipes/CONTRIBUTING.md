# Contributing Recipes

Thank you for contributing to the frago community recipes!

## Recipe Structure

Each recipe must be in its own directory under `recipes/`:

```
recipes/
└── my-recipe/
    ├── recipe.md       # Metadata and documentation (REQUIRED)
    ├── recipe.py       # Python script (for python runtime)
    ├── recipe.js       # JavaScript script (for chrome-js runtime)
    ├── recipe.sh       # Shell script (for shell runtime)
    └── examples/       # Example files (optional)
        └── example.json
```

## Recipe Metadata Requirements

Your `recipe.md` must include YAML frontmatter with the following fields:

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Must match directory name, alphanumeric with `-` and `_` |
| `type` | string | `atomic` or `workflow` |
| `runtime` | string | `chrome-js`, `python`, or `shell` |
| `version` | string | Semantic version (e.g., `"1.0"` or `"1.0.0"`) |
| `description` | string | Clear description, max 200 characters |
| `use_cases` | list | At least one use case |
| `output_targets` | list | At least one of: `stdout`, `file`, `clipboard` |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `tags` | list | Tags for categorization |
| `inputs` | object | Input parameter definitions |
| `outputs` | object | Output field definitions |
| `dependencies` | list | Required recipes (for workflows) |
| `env` | object | Environment variable definitions |
| `warnings` | list | Security warnings (required if using warning-level operations) |

### Example recipe.md

```markdown
---
name: my-recipe
type: atomic
runtime: python
version: "1.0"
description: A brief description of what this recipe does
use_cases:
  - Use case 1
  - Use case 2
tags:
  - category
  - subcategory
output_targets:
  - stdout
  - file
inputs:
  url:
    type: string
    required: true
    description: The URL to process
  timeout:
    type: number
    required: false
    default: 30
    description: Timeout in seconds
outputs:
  result:
    type: object
    description: The processed data
---

# My Recipe

Detailed documentation goes here...

## Usage

```bash
frago recipe run my-recipe --params '{"url": "https://example.com"}'
```
```

## Submission Process

1. **Fork** this repository
2. **Create** your recipe in `community-recipes/recipes/<recipe-name>/`
3. **Test** locally:
   ```bash
   frago recipe validate /path/to/your/recipe
   frago recipe run your-recipe --params '{...}'
   ```
4. **Submit** a Pull Request

## Validation

CI will automatically validate your recipe on PR submission:

- YAML frontmatter format
- Required fields presence
- Script file existence
- Python/JavaScript syntax (basic check)

## Best Practices

1. **Naming**: Use lowercase with hyphens (e.g., `my-awesome-recipe`)
2. **Description**: Be clear and concise, AI agents will read this
3. **Use Cases**: Describe when to use this recipe
4. **Examples**: Include example parameter files in `examples/` directory
5. **Documentation**: Add usage instructions in the Markdown section

## Script Requirements

### Python (`recipe.py`)

- Output JSON to stdout for `stdout` target
- Use `sys.stdin` to read input parameters
- Handle errors gracefully with appropriate exit codes

### JavaScript (`recipe.js`)

- Will be executed in browser context via CDP
- Must return a value (use `return` statement)
- Output will be serialized to JSON

### Shell (`recipe.sh`)

- Receives parameters as JSON via stdin
- Output JSON to stdout
- Use `jq` for JSON processing

## Security Requirements

All recipes must comply with [SECURITY.md](./SECURITY.md). Key points:

### Warning-Level Operations

If your recipe uses any of these operations, you MUST declare them in the `warnings` field:

- `curl`, `wget` - Network downloads
- `rm`, `rmdir` - File deletion
- `brew install`, `apt install`, `pip install` - Software installation
- `chmod` - Permission changes
- `kill`, `pkill` - Process control
- `git clone`, `git pull` - Code fetching
- `open`, `xdg-open` - External applications

### Example warnings declaration

```yaml
---
name: youtube-downloader
# ... other fields
warnings:
  - type: network_download
    command: curl
    reason: "Downloads video from YouTube"
  - type: software_install
    command: yt-dlp
    reason: "Requires yt-dlp to be installed"
---
```

### Prohibited Operations

These will result in immediate rejection:
- `rm -rf /`, `sudo`, `chmod 777`
- `eval()`, `exec()`, dynamic code execution
- `curl | sh`, download and execute
- Reverse shells, backdoors
- Accessing `~/.frago/`, `~/.claude/`, `~/.ssh/`

## Questions?

Open an issue in the main frago repository if you have questions about contributing.
