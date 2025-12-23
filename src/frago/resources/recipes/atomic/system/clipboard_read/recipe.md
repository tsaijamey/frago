---
name: clipboard_read
type: atomic
runtime: python
version: "1.0.0"
description: Read text content from system clipboard
use_cases:
  - Get user-copied text data from clipboard
  - Use clipboard as temporary data source in workflows
  - Quickly extract clipboard content for subsequent processing
tags:
  - clipboard
  - system
  - input
output_targets:
  - stdout
  - file
inputs: {}
outputs:
  content:
    type: string
    description: Text content in clipboard
  length:
    type: number
    description: Character length of content
---

# Recipe: Read Clipboard Content

## Description

Read the current text content of the system clipboard and output in JSON format. Supports cross-platform (Linux, macOS, Windows).

## Usage

```bash
# Standard output
uv run frago recipe run clipboard_read

# Output to file
uv run frago recipe run clipboard_read --output-file clipboard.json
```

## Prerequisites

- Requires `pyperclip` module installed: `pip install pyperclip`
- Linux systems may require additional installation of `xclip` or `xsel`

## Expected Output

```json
{
  "success": true,
  "data": {
    "content": "Text content in clipboard",
    "length": 26
  }
}
```

## Notes

- Only supports text-type clipboard content, does not support images or other binary data
- If clipboard is empty, `content` will be an empty string
- Linux environments require X11 or Wayland session

## Update History

- **v1.0.0** (2025-11-21): Initial version, supports basic clipboard reading functionality
