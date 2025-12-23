# HTML/reveal.js Detailed Reference

## Advanced CSS Design Techniques

### 1. Background Design

#### Solid Color Background

```html
<section data-background="#4d7e65">
```

#### Gradient Background

```html
<section data-background="linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
```

#### Image Background

```html
<section
    data-background="./images/bg.jpg"
    data-background-size="cover"
    data-background-opacity="0.3">
```

#### Video Background

```html
<section data-background-video="./videos/bg.mp4" data-background-video-loop>
```

---

### 2. Layered Design

#### Multi-layer Stacking (z-index)

```html
<section>
    <style>
        .layer-bg { position: absolute; inset: 0; z-index: 1; }
        .layer-decoration { position: absolute; z-index: 5; }
        .layer-content { position: relative; z-index: 10; }
    </style>
    <div class="layer-bg">Background Layer</div>
    <div class="layer-decoration">Decoration Layer</div>
    <div class="layer-content">Content Layer</div>
</section>
```

#### Depth Effect

```html
<style>
    .slides { transform-style: preserve-3d; perspective: 1000px; }
    .front { transform: translateZ(50px); }
    .back { transform: translateZ(-50px); opacity: 0.5; }
</style>
```

---

### 3. Polygon Elements (clip-path)

#### Triangle

```css
.triangle {
    clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
}
```

#### Hexagon

```css
.hexagon {
    clip-path: polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%);
}
```

#### Skewed Edge

```css
.skewed {
    clip-path: polygon(0 0, 100% 0, 100% 80%, 0 100%);
}
```

#### Rounded Rectangle

```css
.rounded-box {
    clip-path: inset(0 round 20px);
}
```

---

### 4. Mask Effects

#### Gradient Mask

```css
.mask-gradient {
    -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
    mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
}
```

#### Radial Mask

```css
.mask-radial {
    -webkit-mask-image: radial-gradient(circle, black 30%, transparent 70%);
    mask-image: radial-gradient(circle, black 30%, transparent 70%);
}
```

---

### 5. Animation Effects

#### Auto-Animate (Inter-slide Automatic Animation)

```html
<section data-auto-animate>
    <h1 style="margin-top: 100px;">Title</h1>
</section>
<section data-auto-animate>
    <h1 style="margin-top: 0;">Title</h1>
    <p>New content appears automatically</p>
</section>
```

#### Custom CSS Animation

```html
<style>
    @keyframes float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-10px); }
    }
    .floating { animation: float 3s ease-in-out infinite; }
</style>
<div class="floating">Floating Element</div>
```

#### Pulse Effect

```css
@keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.05); opacity: 0.8; }
}
.pulse { animation: pulse 2s ease-in-out infinite; }
```

---

### 6. Responsive Layout

#### r-stack (Centered Stacking)

```html
<div class="r-stack">
    <img class="fragment" src="1.png">
    <img class="fragment" src="2.png">
    <img class="fragment" src="3.png">
</div>
```

#### r-hstack (Horizontal Arrangement)

```html
<div class="r-hstack">
    <div>Left</div>
    <div>Center</div>
    <div>Right</div>
</div>
```

#### r-vstack (Vertical Arrangement)

```html
<div class="r-vstack">
    <div>Top</div>
    <div>Middle</div>
    <div>Bottom</div>
</div>
```

#### Grid Layout

```css
.grid-2x2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 20px;
    height: 80%;
}
```

---

### 7. Decorative Elements

#### Glowing Dot

```css
.glow-dot {
    width: 200px;
    height: 200px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(233,69,96,0.4) 0%, transparent 70%);
    filter: blur(40px);
    position: absolute;
}
```

#### Gradient Border

```css
.gradient-border {
    border: 3px solid transparent;
    background:
        linear-gradient(#0d1117, #0d1117) padding-box,
        linear-gradient(90deg, #e94560, #58a6ff) border-box;
    border-radius: 12px;
}
```

#### Glassmorphism Effect

```css
.glass {
    background: rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 16px;
}
```

---

## pywebview Limitations

### Key Differences from Standard Browsers

| Category | Limitation | Impact |
|----------|-----------|--------|
| **Rendering Engine** | Platform-specific | macOS uses WebKit, Windows uses Edge, Linux uses GTK WebKit |
| **Debugging Tools** | No DevTools | Cannot debug with F12 |
| **Console** | console.log invisible | Cannot view logs |
| **Hot Reload** | Not supported | Need to exit and restart preview |
| **Script Injection** | Limited | frago view auto-injects required libraries |
| **iframe** | Security restrictions | Cannot embed external pages |
| **Cross-Origin Requests** | Limited | Ajax calls unavailable |
| **External Fonts** | CDN may fail | Use local fonts |

### Workarounds

| Requirement | Workaround |
|-------------|------------|
| Debug CSS/HTML | Debug in Chrome first, then confirm with `frago view` |
| View logs | Use `alert()` or write to page elements |
| Cross-platform consistency | Use standard CSS, avoid experimental features |
| Font consistency | Use system font stack or local web fonts |
| Complex interactions | CSS animations instead of JavaScript |

### Recommended Practices

1. **CSS First**: Implement complex effects with CSS, avoid relying on JavaScript
2. **Local Resources**: Place images and fonts in `images/` and `assets/` directories
3. **Relative Paths**: Use `./images/xxx.png` instead of absolute paths
4. **Standard Features**: Use widely supported CSS features
5. **Static Content**: frago view is suitable for static display, not interactive applications

---

## Color Reference

### Common Color Schemes

| Purpose | Color | Hex |
|---------|-------|-----|
| Accent (Red) | Coral Red | `#e94560` |
| Accent (Blue) | Sky Blue | `#58a6ff` |
| Accent (Purple) | Violet | `#a855f7` |
| Accent (Green) | Emerald Green | `#10b981` |
| Accent (Orange) | Amber Orange | `#f59e0b` |
| Background Dark | Dark Gray | `#0d1117` |
| Background Mid | Medium Gray | `#161b22` |
| Text Primary | Light Gray | `#c9d1d9` |
| Text Secondary | Muted Gray | `#8b949e` |
| Border | Border Gray | `#30363d` |

### Gradient Combinations

```css
/* Purple-Red Gradient */
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

/* Deep Blue Gradient */
background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);

/* Sunset Gradient */
background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);

/* Ocean Gradient */
background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
```

---

## Font Stacks

### System Fonts (Recommended)

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Helvetica Neue", Arial, sans-serif;
```

### Code Fonts

```css
font-family: "SF Mono", "Fira Code", Consolas, "Liberation Mono",
             Menlo, monospace;
```
