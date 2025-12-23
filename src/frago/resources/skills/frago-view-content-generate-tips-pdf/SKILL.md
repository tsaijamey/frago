---
name: frago-view-content-generate-tips-pdf
description: PDF file content generation guide. Use this skill when you need to understand how `frago view` previews PDF files. Covers rendering features and limitations.
---

# PDF File Content Generation Guide

Preview PDF files via `frago view`, based on PDF.js client-side rendering.

## Preview Commands

```bash
frago view document.pdf
```

---

## Rendering Features

### Based on PDF.js

- Uses Mozilla PDF.js library
- Client-side rendering, no server support needed
- All pages displayed continuously

### Supported PDF Features

| Feature | Support Status |
|---------|---------------|
| Text content | Supported |
| Images | Supported |
| Vector graphics | Supported |
| Embedded fonts | Supported |
| Bookmarks/TOC | Navigation not supported |
| Form filling | Not supported |
| Annotations | Read-only display |
| Encrypted PDF | Not supported |

---

## Display Mode

### Continuous Scrolling

All pages arranged vertically in sequence, supports scrolling.

### Page Spacing

Appropriate spacing between pages for easy distinction.

### Adaptive Width

PDF pages automatically adapt to window width.

---

## Best Practices

### 1. PDF Generation Recommendations

- Use standard fonts or embed fonts
- Avoid oversized images (recommend compression)
- Single file size < 10MB

### 2. Page Layout

- Portrait layout works best
- Landscape layout may require scrolling

### 3. File Naming

- Use English or numbers for naming
- Avoid special characters

---

## Limitations

| Limitation | Description | Workaround |
|------------|-------------|------------|
| No TOC navigation | Clicking TOC doesn't jump | Manual scrolling |
| No search function | Cannot search text | Use professional PDF reader |
| No zoom control | Fixed zoom ratio | Adjust window size |
| Forms not fillable | Read-only display | Use Adobe Reader |
| Encryption not supported | Cannot open | Decrypt first |
| Large files slow | Time-consuming rendering | Split or compress |

---

## Use Cases

- Quick PDF report preview
- Simple document reading
- PDF slide browsing

**Not suitable for**:
- Long documents requiring TOC navigation
- Interactive PDFs requiring form filling
- Encrypted or protected PDFs

---

## Alternatives

For complex PDF needs, recommend using:
- macOS: Preview.app
- Windows: Adobe Acrobat Reader
- Cross-platform: Firefox/Chrome built-in PDF viewer
