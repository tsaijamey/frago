---
name: frago-view-content-generate-tips-html
description: HTML/reveal.js content generation guide. Use this skill when you need to create HTML presentations that can be previewed via `frago view`. Covers reveal.js advanced design, CSS techniques, and multi-page collaboration workflow.
---

# HTML/reveal.js Content Generation Guide

Create professionally designed HTML presentations and preview them via `frago view`.

## Quick Start

### Basic Structure

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Presentation Title</title>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            <section>Slide 1</section>
            <section>Slide 2</section>
        </div>
    </div>
</body>
</html>
```

**Note**: `frago view` automatically injects reveal.js library, no manual inclusion needed.

### Trigger Condition

HTML file automatically enters presentation mode when it contains `class="reveal"` or `class="slides"`.

### Preview Commands

```bash
frago view slides.html              # Default theme
frago view slides.html --theme dracula  # Specify theme
frago view slides.html --fullscreen     # Fullscreen mode
```

---

## Available Themes

| Theme | Style | Use Case |
|-------|-------|----------|
| `black` | Dark background (default) | Technical presentations |
| `white` | Light background | Formal reports |
| `dracula` | Dracula color scheme | Developer presentations |
| `moon` | Dark blue | Night mode |
| `night` | Dark blue gradient | Tech style |
| `serif` | Serif font | Academic presentations |
| `solarized` | Solarized color scheme | Soft style |
| `blood` | Dark red | Emphasis style |
| `beige` | Beige | Warm style |
| `sky` | Blue | Fresh style |
| `league` | Gray gradient | Business style |
| `simple` | Simple white | Minimalist style |

---

## Slide Organization

### Horizontal Navigation

Each `<section>` is one slide:

```html
<section>Slide 1</section>
<section>Slide 2</section>
<section>Slide 3</section>
```

### Vertical Navigation (Nested)

Nested `<section>` creates sub-slides within a section:

```html
<section>
    <section>Topic A - Overview</section>
    <section>Topic A - Detail 1</section>
    <section>Topic A - Detail 2</section>
</section>
<section>
    <section>Topic B - Overview</section>
</section>
```

---

## Common Elements

### Headings and Text

```html
<section>
    <h1>Main Heading</h1>
    <h2>Subtitle</h2>
    <p>Body paragraph</p>
</section>
```

### Lists

```html
<section>
    <h2>Key Points</h2>
    <ul>
        <li>Point 1</li>
        <li>Point 2</li>
        <li>Point 3</li>
    </ul>
</section>
```

### Code Blocks

```html
<section>
    <h2>Code Example</h2>
    <pre><code class="language-python">
def hello():
    print("Hello, World!")
    </code></pre>
</section>
```

### Images

```html
<section>
    <h2>Architecture Diagram</h2>
    <img src="./images/architecture.png" alt="Architecture diagram">
</section>
```

---

## Fragment Animations

`class="fragment"` makes elements appear progressively:

```html
<p class="fragment">First step appears</p>
<p class="fragment">Second step appears</p>
<p class="fragment fade-up">Slide up and fade in</p>
<p class="fragment highlight-red">Highlight in red</p>
```

**Animation Types**:

| Type | Effect |
|------|--------|
| `fade-in` | Fade in |
| `fade-out` | Fade out |
| `fade-up` | Slide up and fade in |
| `fade-down` | Slide down and fade in |
| `fade-left` | Slide left and fade in |
| `fade-right` | Slide right and fade in |
| `highlight-red` | Highlight in red |
| `highlight-green` | Highlight in green |
| `highlight-blue` | Highlight in blue |
| `grow` | Grow |
| `shrink` | Shrink |

---

## Keyboard Shortcuts

| Shortcut | Function |
|----------|----------|
| `→` / `Space` | Next slide |
| `←` | Previous slide |
| `↑` / `↓` | Vertical navigation |
| `F` | Fullscreen |
| `Esc` | Exit fullscreen / Overview |
| `O` | Slide overview |
| `S` | Speaker notes |

---

## Multi-Page PPT Collaboration Workflow

### Phase 1: Planning

Confirm with user:
1. Presentation theme and target audience
2. Section outline
3. Type and core information for each slide

### Phase 2: Skeleton Generation

Create basic structure and output directory:

```
outputs/presentation/
├── slides.html       # Main file
└── images/           # Images directory
```

### Phase 3: Slide-by-Slide Design

Iterative workflow:
1. User provides core content for current slide
2. Agent generates HTML + CSS
3. User previews: `frago view slides.html`
4. User provides feedback for adjustments
5. Move to next slide when satisfied

### Phase 4: Overall Optimization

1. Check slide transitions
2. Unify visual style
3. Add fragment animations
4. Final preview confirmation

---

## Template Library

| Template | Purpose | Path |
|----------|---------|------|
| Basic skeleton | Quick start | [templates/basic-structure.html](templates/basic-structure.html) |
| Cover slide | Opening | [templates/cover-slide.html](templates/cover-slide.html) |
| Content slide | Body content | [templates/content-slide.html](templates/content-slide.html) |
| Comparison slide | Comparison | [templates/comparison-slide.html](templates/comparison-slide.html) |
| Timeline slide | Timeline | [templates/timeline-slide.html](templates/timeline-slide.html) |
| Closing slide | Ending | [templates/closing-slide.html](templates/closing-slide.html) |

---

## Design Pitfalls

| Pitfall | Reason | Alternative |
|---------|--------|-------------|
| Too much text | Slides are not documents | Extract keywords |
| External CDN | Not available offline | Local resources |
| iframe embedding | Security restrictions | Screenshots |
| Complex JavaScript | pywebview limitations | CSS implementation |

---

## References

- [REFERENCE.md](REFERENCE.md) - Advanced CSS techniques + pywebview limitations
- [reveal.js Official Documentation](https://revealjs.com/)
