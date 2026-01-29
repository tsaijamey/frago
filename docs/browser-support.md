[简体中文](browser-support.zh-CN.md)

# Browser Support

frago uses the Chrome DevTools Protocol (CDP) to control Chromium-based browsers. This document describes supported browsers and how to use them.

## Supported Browsers

| Browser | Support | Notes |
|---------|---------|-------|
| **Chrome** | ✅ Full | Default choice, recommended |
| **Edge** | ✅ Full | Same CDP protocol as Chrome |
| **Chromium** | ✅ Full | Open-source base |
| **Firefox** | ❌ None | CDP removed in Firefox 141 (2025) |
| **Safari** | ❌ None | No CDP support |

All supported browsers use the same CDP protocol, so commands work identically across Chrome, Edge, and Chromium.

---

## Browser Detection

frago automatically detects installed browsers using a three-layer strategy:

1. **PATH lookup** - Checks if browser command exists in system PATH (highest priority)
2. **Default paths** - Checks platform-specific installation locations
3. **Registry query** - Windows only, queries App Paths registry for non-standard installations

### Check Available Browsers

```bash
frago chrome detect
```

Example output:
```
Available browsers:

  Chrome     ✓  /usr/bin/google-chrome
  Edge       ✓  /usr/bin/microsoft-edge
  Chromium   ✗  not found

Default: chrome (first available)
```

---

## Browser Lifecycle Commands

### Start Browser

```bash
# Auto-detect browser (priority: Chrome > Edge > Chromium)
frago chrome start

# Specify browser explicitly
frago chrome start --browser chrome
frago chrome start --browser edge
frago chrome start -b chromium
```

**Launch Modes**:

| Mode | Flag | Description |
|------|------|-------------|
| Normal | (default) | Standard browser window |
| Headless | `--headless` | No UI, for server-side automation |
| Void | `--void` | Window moved off-screen |
| App | `--app --app-url URL` | Borderless window for specific URL |

```bash
# Headless mode (no window)
frago chrome start --headless

# Void mode (window hidden off-screen)
frago chrome start --void

# App mode (borderless window)
frago chrome start --app --app-url http://localhost:8080
```

**Additional Options**:

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | 9222 | CDP debugging port |
| `--width` | 1280 | Window width |
| `--height` | 960 | Window height |
| `--profile-dir` | auto | User data directory |
| `--no-kill` | false | Don't kill existing CDP processes |
| `--keep-alive` | false | Keep running until Ctrl+C |

### Check Status

```bash
frago chrome status
```

### Stop Browser

```bash
frago chrome stop

# Stop browser on specific port
frago chrome stop --port 9333
```

---

## Page Operations

All page operations work identically across supported browsers.

### Navigation

```bash
# Navigate to URL
frago chrome navigate https://example.com

# Wait for page load
frago chrome wait 2000
```

### Element Interaction

```bash
# Click element
frago chrome click "#submit-button"
frago chrome click "button[type=submit]"

# Execute JavaScript
frago chrome exec-js "document.title"
frago chrome exec-js "return document.querySelectorAll('a').length"
```

### Page Content

```bash
# Get page title
frago chrome get-title

# Get page content (HTML or text)
frago chrome get-content
frago chrome get-content --format text
```

### Screenshots

```bash
# Full page screenshot
frago chrome screenshot output.png

# Element screenshot
frago chrome screenshot element.png --selector "#main-content"
```

### Scrolling

```bash
# Scroll by pixels
frago chrome scroll 500

# Scroll to element
frago chrome scroll-to "#footer"
```

### Zoom

```bash
# Set zoom level (1.0 = 100%)
frago chrome zoom 1.5
```

---

## Tab Management

```bash
# List all tabs
frago chrome list-tabs

# Switch to specific tab
frago chrome switch-tab 0
```

---

## Visual Effects

These commands add visual markers for debugging and demonstration purposes.

```bash
# Highlight element
frago chrome highlight "#target-element"

# Add pointer indicator
frago chrome pointer 100 200

# Spotlight element (dim everything else)
frago chrome spotlight "#focus-element"

# Add text annotation
frago chrome annotate "#element" "This is important"

# Underline text
frago chrome underline "#text-element"

# Clear all visual effects
frago chrome clear-effects
```

---

## Profile Management

Each browser type uses a separate profile directory:

| Browser | Profile Directory |
|---------|------------------|
| Chrome | `~/.frago/chrome_profile` |
| Edge | `~/.frago/edge_profile` |
| Chromium | `~/.frago/chromium_profile` |

Profiles are automatically initialized from system browser profiles (bookmarks, extensions, cookies, etc.).

**Custom Profile**:
```bash
frago chrome start --profile-dir /path/to/custom/profile
```

**Port-specific Profile** (for running multiple instances):
```bash
frago chrome start --port 9333
# Uses ~/.frago/chrome_profile_9333
```

---

## Platform-Specific Notes

### Linux

- Wayland sessions automatically use XWayland for void mode
- Root user automatically disables sandbox (`--no-sandbox`)

### Windows

- Browser detection includes registry lookup for non-standard installations
- Edge is pre-installed on Windows 10/11

### macOS

- Browsers detected in `/Applications/` directory
- Edge requires manual installation

---

## Troubleshooting

### Browser Not Found

```bash
# Check available browsers
frago chrome detect

# Verify browser is in PATH
which google-chrome
which microsoft-edge
```

### CDP Connection Failed

```bash
# Check if CDP port is in use
lsof -i :9222  # Linux/macOS
netstat -an | findstr 9222  # Windows

# Stop existing browser and restart
frago chrome stop
frago chrome start
```

### Permission Denied (Linux)

Running as root requires disabling sandbox:
```bash
# frago handles this automatically, but you can also set:
export FRAGO_NO_SANDBOX=1
frago chrome start
```
