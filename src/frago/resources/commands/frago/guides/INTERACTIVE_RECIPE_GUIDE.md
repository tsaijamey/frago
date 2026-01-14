# Interactive Recipe Guide

Applies to: `/frago.recipe`

Interactive recipes provide web-based UI for user collaboration. They combine automated processing with human decision-making through browser interfaces.

## When to Use Interactive Recipes

| Use Case | Why Interactive |
|----------|-----------------|
| Media annotation | User selects clips, marks timestamps |
| Multi-step creative workflow | User reviews/adjusts between steps |
| Reference-based generation | User assigns images to purposes |
| Quality control | User approves/rejects results |

**Not suitable for**: fully automatable tasks, headless environments, batch processing without review.

## Architecture Overview

```
~/.frago/recipes/workflows/<name>/
├── recipe.md           # Metadata (type: workflow, runtime: python)
├── recipe.py           # Launcher script
└── assets/
    ├── index.html      # Entry point
    ├── app.js          # Application logic
    └── style.css       # Styles

Runtime Flow:
1. recipe.py scans working directory
2. recipe.py generates config.json
3. recipe.py copies assets to viewer/content/{id}/
4. recipe.py opens browser via frago chrome navigate
5. UI interacts with frago server API
```

## Required Components

### 1. recipe.md Frontmatter

```markdown
---
name: tool_name_here
type: workflow
runtime: python
version: "1.0.0"
description: "Interactive tool for..."
use_cases:
  - "User-guided workflow scenario"
tags:
  - interactive    # REQUIRED for interactive recipes
  - workflow
output_targets:
  - stdout
  - file
inputs:
  dir:
    type: string
    required: true
    description: "Working directory path"
outputs:
  url:
    type: string
    description: "Web UI access URL"
  content_id:
    type: string
    description: "Viewer content identifier"
dependencies:
  - other_recipe_if_called_from_ui
---

# tool_name_here

Recipe documentation body...
```

**Note**: This is `recipe.md` file content with YAML frontmatter, NOT a separate `.yaml` file.

### 2. recipe.py Core Structure

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""
Recipe: <name>
Description: <description>
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Paths
FRAGO_HOME = Path.home() / '.frago'
VIEWER_CONTENT_DIR = FRAGO_HOME / 'viewer' / 'content'
UI_ASSETS_DIR = Path(__file__).parent / 'assets'


def generate_content_id(dir_path: str) -> str:
    """Generate unique content ID from directory path."""
    return hashlib.sha256(dir_path.encode()).hexdigest()[:12]


def setup_viewer_content(content_id: str, dir_path: str, files: list) -> Path:
    """Setup viewer content directory."""
    content_dir = VIEWER_CONTENT_DIR / content_id
    content_dir.mkdir(parents=True, exist_ok=True)

    # Copy UI assets
    if UI_ASSETS_DIR.exists():
        for asset in UI_ASSETS_DIR.iterdir():
            if asset.is_file():
                shutil.copy2(asset, content_dir / asset.name)
    else:
        raise FileNotFoundError(f"UI assets not found: {UI_ASSETS_DIR}")

    # Generate config.json
    config = {
        'dir': dir_path,
        'files': files,
        'contentId': content_id,
        'apiBase': 'http://127.0.0.1:8093/api'
    }
    (content_dir / 'config.json').write_text(
        json.dumps(config, ensure_ascii=False, indent=2)
    )

    return content_dir


def ensure_chrome_running() -> bool:
    """Ensure Chrome CDP is available."""
    result = subprocess.run(
        ['frago', 'chrome', 'status'],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        return True

    print("Starting Chrome CDP...", file=sys.stderr)
    result = subprocess.run(
        ['frago', 'chrome', 'start'],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0


def open_browser(url: str) -> bool:
    """Open URL in Chrome via CDP."""
    try:
        if not ensure_chrome_running():
            return False
        result = subprocess.run(
            ['frago', 'chrome', 'navigate', url, '--no-border'],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Warning: Failed to open browser: {e}", file=sys.stderr)
        return False


def main():
    # Parse parameters (standard pattern)
    if len(sys.argv) < 2:
        print(json.dumps({'success': False, 'error': 'Missing params'}))
        sys.exit(1)

    params = json.loads(sys.argv[1])
    dir_path = Path(params.get('dir', '')).expanduser().resolve()

    # Validate directory
    if not dir_path.is_dir():
        print(json.dumps({'success': False, 'error': f'Invalid dir: {dir_path}'}))
        sys.exit(1)

    # Scan files (customize per recipe)
    files = scan_files(dir_path)

    # Setup content
    content_id = generate_content_id(str(dir_path))
    content_dir = setup_viewer_content(content_id, str(dir_path), files)

    # Open browser
    url = f"http://127.0.0.1:8093/viewer/content/{content_id}/index.html"
    browser_opened = open_browser(url)

    # Output result
    print(json.dumps({
        'success': True,
        'url': url,
        'content_id': content_id,
        'browser_opened': browser_opened
    }, indent=2))


if __name__ == '__main__':
    main()
```

### 3. UI Files (assets/)

#### index.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tool Name</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>Tool Name</h1>
    <div id="status-message"></div>
  </header>

  <main>
    <!-- UI components -->
  </main>

  <script src="app.js"></script>
</body>
</html>
```

#### app.js Core Pattern

```javascript
const API_BASE = 'http://127.0.0.1:8093/api';

const state = {
  config: null,
  files: [],
  // ... domain-specific state
};

document.addEventListener('DOMContentLoaded', async () => {
  await loadConfig();
  await loadFiles();
  await loadSavedData();
  setupEventListeners();
  updateUI();
});

async function loadConfig() {
  const resp = await fetch('./config.json');
  state.config = await resp.json();
}
```

## API Interaction Patterns

### Reading Files

```javascript
// Read file content
const resp = await fetch(`${API_BASE}/file?path=${encodeURIComponent(filePath)}`);

// For JSON files
const data = await resp.json();

// For binary files (images, media)
// Use as src directly
img.src = `${API_BASE}/file?path=${encodeURIComponent(imagePath)}`;
```

### Writing Files

```javascript
// Write JSON data
await fetch(`${API_BASE}/file?path=${encodeURIComponent(filePath)}`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: JSON.stringify(data, null, 2) })
});

// Write binary (base64 encoded)
await fetch(`${API_BASE}/file?path=${encodeURIComponent(filePath)}`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    content: base64Data,
    encoding: 'base64'
  })
});
```

### Calling Recipes from UI

```javascript
const resp = await fetch(`${API_BASE}/recipes/${recipeName}/run`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    params: { key: 'value' }
  })
});

const result = await resp.json();
// result.success, result.data, result.error
```

## Data Storage Patterns

### config.json (Generated by recipe.py)

```json
{
  "dir": "/absolute/path/to/working/directory",
  "files": [...],
  "contentId": "abc123def456",
  "apiBase": "http://127.0.0.1:8093/api"
}
```

### User Data Files (In working directory)

| File | Purpose | Format |
|------|---------|--------|
| `markers.json` | Temporal annotations | `{ "filename": [{ id, start, end }] }` |
| `project.json` | Project state | Domain-specific |
| `timeline.json` | Ordering/sequencing | `{ order: [...] }` |
| `tts_clips.json` | Generated audio refs | `[{ id, text, audioFile }]` |

## UI State Management

### Auto-Save Pattern

```javascript
let autoSaveTimeout = null;

function autoSave() {
  if (autoSaveTimeout) clearTimeout(autoSaveTimeout);
  autoSaveTimeout = setTimeout(saveProject, 2000);
}

async function saveProject() {
  await fetch(`${API_BASE}/file?path=${encodeURIComponent(savePath)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON.stringify(state.data, null, 2) })
  });
}

// Call autoSave() after any state change
```

### Keyboard Shortcuts

```javascript
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch (e.key.toLowerCase()) {
    case 'i': markStart(); break;
    case 'o': markEnd(); break;
    case 's':
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        saveProject();
      }
      break;
  }
});
```

## Prerequisites

Interactive recipes require:

1. **frago server running**: `frago server` (port 8093)
2. **Chrome CDP available**: `frago chrome start`
3. **Working directory exists**: Recipe validates before proceeding

## Output Format

Standard JSON output:

```json
{
  "success": true,
  "url": "http://127.0.0.1:8093/viewer/content/{id}/index.html",
  "content_id": "abc123def456",
  "content_dir": "/home/user/.frago/viewer/content/abc123def456",
  "file_count": 5,
  "browser_opened": true
}
```

## Recipe Examples

| Recipe | Purpose | Key Features |
|--------|---------|--------------|
| `storyboard_character_generator` | AI image generation with refs | Drag-drop refs, prompt building, scene ordering |
| `video_clip_annotator` | Video editing timeline | Waveform, markers, TTS integration |

## Checklist for Creating Interactive Recipes

- [ ] recipe.md has `interactive` tag
- [ ] recipe.py uses standard content_id generation
- [ ] recipe.py copies assets to viewer/content/
- [ ] recipe.py generates config.json with apiBase
- [ ] UI loads config.json on DOMContentLoaded
- [ ] UI uses `/api/file` for data read/write
- [ ] UI implements auto-save pattern
- [ ] UI has keyboard shortcuts for common actions
- [ ] Recipe declares dependencies for recipes called from UI
