---
name: frago-view-content-generate-tips-json
description: JSON file content generation guide. Use this skill when you need to create JSON files that can be previewed via `frago view`. Covers formatted display and best practices.
---

# JSON File Content Generation Guide

Preview JSON files via `frago view` with automatic formatting and syntax highlighting.

## Preview Commands

```bash
frago view data.json                      # Default theme
frago view config.json --theme monokai    # Specify theme
```

---

## Rendering Features

### Automatic Formatting

- JSON content automatically beautified (Pretty Print)
- Indentation aligned
- Key-value pairs clearly displayed

### Syntax Highlighting

| Element | Color Example (github-dark) |
|---------|----------------------------|
| Key names | Purple `#d2a8ff` |
| String values | Blue `#a5d6ff` |
| Numbers | Cyan `#79c0ff` |
| Booleans | Red `#ff7b72` |
| null | Red `#ff7b72` |
| Brackets/commas | White `#c9d1d9` |

---

## JSON Format Specification

### Correct Format

```json
{
    "name": "Project Name",
    "version": "1.0.0",
    "enabled": true,
    "count": 42,
    "tags": ["tag1", "tag2"],
    "config": {
        "nested": "value"
    },
    "nullable": null
}
```

### Common Errors

| Error | Example | Fix |
|-------|---------|-----|
| Trailing comma | `{"a": 1,}` | `{"a": 1}` |
| Single quotes | `{'a': 1}` | `{"a": 1}` |
| Unquoted keys | `{a: 1}` | `{"a": 1}` |
| Comments | `// comment` | Comments not supported |
| undefined | `undefined` | Use `null` |

---

## Best Practices

### 1. Indentation

- Use **2 or 4 spaces** for indentation
- Maintain consistency

### 2. Key Naming

- Use **snake_case** or **camelCase**
- Maintain consistency throughout the file

```json
{
    "user_name": "snake_case style",
    "userName": "camelCase style"
}
```

### 3. Data Organization

- Group related fields
- Place important fields first

```json
{
    "id": "001",
    "name": "Important fields first",
    "metadata": {
        "created_at": "2024-01-01",
        "updated_at": "2024-01-02"
    }
}
```

### 4. File Size

- Single file < 1MB optimal
- Consider pagination or splitting files for large data

---

## Use Cases

- API response data preview
- Configuration file viewing
- Data structure review
- Debug data inspection

---

## Display Themes

Same as code files, supports the following themes:

| Theme | Command |
|-------|---------|
| github-dark (default) | `frago view data.json` |
| monokai | `frago view data.json --theme monokai` |
| atom-one-dark | `frago view data.json --theme atom-one-dark` |

---

## Notes

| Issue | Cause | Solution |
|-------|-------|----------|
| Parse failure | JSON format error | Use JSON validator |
| Truncated display | Value too long | Use nested structure |
| Slow rendering | File too large | Split or simplify |

---

## JSON Validation

Ensure JSON is valid before preview:

```bash
# Python validation
python -m json.tool data.json

# jq validation
jq . data.json
```

---

## Related Tools

- **jq**: Command-line JSON processor
- **jsonlint**: JSON validator
- **VSCode**: JSON editing and formatting
