---
name: cdp_list_tabs_and_select_target
type: atomic
runtime: python
description: "List all Chrome tabs and select/lock one as the CDP operation target"
use_cases:
  - "Specify which page to operate on in a multi-tab environment"
  - "Switch CDP connection to a different tab"
  - "Get information about all currently open Chrome pages"
tags:
  - cdp
  - tab-management
  - session
output_targets:
  - stdout
  - file
inputs:
  action:
    type: string
    required: false
    description: "Operation type: list (list all tabs) or select (select and lock tab), default list"
  index:
    type: number
    required: false
    description: "Select tab by index (when action=select)"
  title:
    type: string
    required: false
    description: "Select tab by fuzzy matching title (when action=select)"
  url:
    type: string
    required: false
    description: "Select tab by fuzzy matching URL (when action=select)"
  id:
    type: string
    required: false
    description: "Select tab by exact ID (when action=select)"
  host:
    type: string
    required: false
    description: "CDP host address, default 127.0.0.1"
  port:
    type: number
    required: false
    description: "CDP port, default 9222"
  save_config:
    type: boolean
    required: false
    description: "Whether to save selected tab config to ~/.frago/current_target.json, default true"
outputs:
  tabs:
    type: array
    description: "Information list of all tabs (when action=list)"
  selected_tab:
    type: object
    description: "Details of selected tab (when action=select)"
  config_path:
    type: string
    description: "Path to saved config file (when action=select)"
dependencies: []
version: "1.0.0"
---

# cdp_list_tabs_and_select_target

## Description

This recipe solves a core problem in CDP automation: when Chrome has multiple tabs open, how to precisely control which page to operate on.

By default, frago automatically connects to the first available page. But in complex scenarios (such as simultaneously opening multiple websites for data collection), you need to explicitly specify the target tab.

The recipe provides two operation modes:
- **list**: List basic information of all Chrome tabs (index, title, URL)
- **select**: Select and lock a tab by index/title/url/id

## Usage

**List all tabs**:
```bash
uv run frago recipe run cdp_list_tabs_and_select_target
# Or with parameters
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "list"}'
```

**Select tab by index**:
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "index": 0}'
```

**Select by fuzzy matching title**:
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "title": "GitHub"}'
```

**Select by fuzzy matching URL**:
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "url": "youtube.com"}'
```

**Select by exact ID**:
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "id": "F7D7569E470E12306173702FCD3E2DE2"}'
```

## Prerequisites

- Chrome started in remote debugging mode: `google-chrome --remote-debugging-port=9222`
- CDP port accessible (default 9222)

## Expected Output

**list operation output**:
```json
{
  "success": true,
  "action": "list",
  "tabs_count": 5,
  "tabs": [
    {
      "index": 0,
      "id": "F7D7569E470E12306173702FCD3E2DE2",
      "title": "Google Gemini",
      "url": "https://gemini.google.com/app/...",
      "full_title": "Google Gemini",
      "full_url": "https://gemini.google.com/app/2b531fd00e311183"
    },
    {
      "index": 1,
      "id": "3EAFDE3EDB2CF5BDDF32862E38D66FC4",
      "title": "Claude",
      "url": "https://claude.ai/new"
    }
  ]
}
```

**select operation output**:
```json
{
  "success": true,
  "action": "select",
  "selected_tab": {
    "id": "3EAFDE3EDB2CF5BDDF32862E38D66FC4",
    "title": "Claude",
    "url": "https://claude.ai/new",
    "websocket_url": "ws://127.0.0.1:9222/devtools/page/3EAFDE3EDB2CF5BDDF32862E38D66FC4"
  },
  "config_saved": true,
  "config_path": "/home/user/.frago/current_target.json",
  "usage_hint": "Use in subsequent commands: uv run frago --target-id 3EAFDE3EDB2CF5BDDF32862E38D66FC4 <command>"
}
```

## Notes

- **Tab ID Instability**: Tab IDs change with each Chrome session, do not hardcode IDs
- **Title/URL Matching**: Uses case-insensitive fuzzy matching, returns the first matching tab
- **Config Persistence**: Selected tab information is saved in `~/.frago/current_target.json`, available for other tools to read
- **Background Operations**: Use `--target-id` to operate on a specified tab without activating it

## AI Agent Usage Recommendations

1. Before performing multi-tab operations, first `list` to get all tab information
2. Choose the appropriate matching method based on task requirements (title is usually more stable than URL)
3. Save the returned `selected_tab.id` or `websocket_url` for subsequent operations
4. If the target tab is closed, need to re-execute `list` and `select`

## Update History

| Date | Version | Change Description |
|------|---------|-------------------|
| 2025-11-27 | v1.0.0 | Initial version |
