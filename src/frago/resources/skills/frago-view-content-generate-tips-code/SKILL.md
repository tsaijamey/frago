---
name: frago-view-content-generate-tips-code
description: Code file content generation guide. Use this skill when you need to create code files that can be previewed via `frago view`. Covers supported languages, theme selection, and best practices.
---

# Code File Content Generation Guide

Preview code files via `frago view` with automatic syntax highlighting.

## Preview Commands

```bash
frago view script.py                      # Default theme
frago view script.py --theme monokai      # Specify theme
```

---

## Supported File Types

| Extension | Language | highlight.js Tag |
|--------|------|------------------|
| `.py` | Python | python |
| `.js` | JavaScript | javascript |
| `.ts` | TypeScript | typescript |
| `.jsx` | JSX | javascript |
| `.tsx` | TSX | typescript |
| `.css` | CSS | css |
| `.scss` | SCSS | scss |
| `.html` | HTML | html |
| `.json` | JSON | json |
| `.yaml` / `.yml` | YAML | yaml |
| `.toml` | TOML | toml |
| `.xml` | XML | xml |
| `.sql` | SQL | sql |
| `.sh` / `.bash` | Bash | bash |
| `.go` | Go | go |
| `.rs` | Rust | rust |
| `.java` | Java | java |
| `.c` / `.h` | C | c |
| `.cpp` / `.hpp` | C++ | cpp |
| `.rb` | Ruby | ruby |
| `.php` | PHP | php |
| `.swift` | Swift | swift |
| `.kt` | Kotlin | kotlin |
| `.lua` | Lua | lua |
| `.r` | R | r |
| `.txt` | Plain Text | plaintext |

---

## Code Themes

| Theme | Style | Use Case |
|-------|-------|----------|
| `github-dark` | GitHub Dark (default) | Daily use |
| `github` | GitHub Light | White background preference |
| `monokai` | Monokai Classic | Developer preference |
| `atom-one-dark` | Atom Dark | Modern style |
| `atom-one-light` | Atom Light | Light preference |
| `vs2015` | Visual Studio | Windows style |

```bash
# Preview with different themes
frago view main.py --theme monokai
frago view config.yaml --theme atom-one-dark
```

---

## Best Practices

### 1. File Encoding

- **Must use UTF-8 encoding**
- Avoid BOM header
- Use LF line endings (Unix style)

### 2. Line Length

- Single line no more than **120 characters**
- Very long lines will be truncated on display

### 3. Comment Guidelines

```python
# Single-line comments should be clear and concise

"""
Multi-line comments used for:
- Module documentation
- Function documentation
- Complex logic explanation
"""
```

### 4. Code Structure

- Group logic with blank line separation
- Two blank lines between functions/classes
- Group related imports

---

## Display Features

### Automatic Line Numbers

Code preview automatically displays line numbers for easy reference.

### Syntax Highlighting

Based on highlight.js, automatically recognizes language and highlights:
- Keywords
- Strings
- Comments
- Numbers
- Function names
- Class names

### Style Reference (github-dark)

| Element | Color |
|---------|-------|
| Background | `#0d1117` |
| Text | `#c9d1d9` |
| Keywords | `#ff7b72` |
| Strings | `#a5d6ff` |
| Comments | `#8b949e` |
| Functions | `#d2a8ff` |
| Numbers | `#79c0ff` |

---

## Notes

| Issue | Cause | Solution |
|-------|-------|----------|
| No syntax highlighting | Extension not recognized | Use standard extensions |
| Chinese garbled text | Encoding issue | Ensure UTF-8 |
| Truncated display | Line too long | Control line length |
| Slow rendering | File too large | Split or simplify |

---

## Use Cases

- Code snippet display
- Configuration file preview
- Script review
- Code sharing

**Not suitable for**: Complete source code of large projects (recommend using IDE)
