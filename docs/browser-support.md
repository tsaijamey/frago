[简体中文](browser-support.zh-CN.md)

# Browser Support

frago drives Chromium-based browsers through two backends:

- **extension (default)** — a browser extension + native-messaging bridge
  drives the browser's **own real profile**. No flags needed; this is the
  standard path for all page operations.
- **cdp** — the legacy Chrome DevTools Protocol path, selected explicitly
  with `-b cdp`. Kept for headless/recording workflows (e.g. the
  `agent_os` screen-record rig) that need a dedicated CDP instance on the
  fixed port 9222.

This document covers the default extension backend unless stated otherwise.
Full command reference and anti-bot guidance live in the built-in books:
`frago book browser-usage`, `frago book browser-backend-choice`,
`frago book browser-anti-bot`.

## Supported Browsers

| Browser | Support | Notes |
|---------|---------|-------|
| **Edge** | ✅ Default | Picked first when installed (Stable > Beta > Dev) |
| **Chromium** | ✅ | Open-source base |
| **Chrome** | ✅ (non-Stable) | Beta/Dev/Canary; Stable is excluded (v137+ silently ignores `--load-extension`) |
| **Brave / Vivaldi** | ✅ | Also auto-detectable |
| **Firefox** | ❌ None | CDP removed in Firefox 141 (2025) |
| **Safari** | ❌ None | No CDP support |

The picker takes the first installed browser in this fixed order:
Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev →
Chrome Canary → Brave → Vivaldi. Do **not** pass `--browser`: it does not
change which browser launches, only which profile directory is used.

## Browser Detection

```bash
# List installed browsers and which one frago would pick
frago browser detect

# Per-browser capability + running status
frago browser check
```

## Browser Lifecycle

```bash
# Start: picks a browser, launches the extension bridge, opens its real profile
frago browser start

# Health check
frago browser status

# Stop browser + daemon + socket
frago browser stop
```

`start` runs the whole chain: pick browser → launch native-messaging
daemon → write manifest → launch browser with the extension → wait for the
bridge handshake. No manual preparation needed.

The browser runs on its **own default profile** (logins, saved passwords and
cookies are visible to the agent, and vice versa). One instance per profile —
if `start` hits a lock it errors and tells you to `stop` first.

### CDP-only launch options

`--headless`, `--void`, `--app/--app-url`, `--width`, `--height`, `--port`,
`--profile-dir`, `--no-kill`, `--keep-alive` and `--reseed-profile` are
**CDP-backend options**. Under the default extension backend they are silently
dropped. To use them, select CDP explicitly:

```bash
frago browser -b cdp start --headless          # headless CDP instance (port 9222)
frago browser -b cdp start --void --keep-alive # off-screen, keep running
```

CDP port is fixed at **9222** — the only whitelisted port. Any other value is
rejected; never invent ports (see `frago book` CDP-port-whitelist).

## Page Operations

All page operations work on the default backend; `--group <name>` scopes a
tab group for isolation (`FRAGO_CURRENT_RUN` is read when omitted).

### Navigation

```bash
# Navigate to URL and wait for load
frago browser navigate https://example.com

# Wait for a selector before returning
frago browser navigate https://example.com --wait-for '.content-loaded'

# Wait N seconds (decimals ok)
frago browser wait 2
```

### Element Interaction

```bash
# Click element
frago browser click "#submit-button"
frago browser click "button[type=submit]" --wait-timeout 15

# Execute JavaScript (return value with --return-value)
frago browser exec-js "document.title"
frago browser exec-js "return document.querySelectorAll('a').length" --return-value
```

### Page Content

```bash
# Get page title
frago browser get-title

# Get text content from page or element (selector defaults to body)
frago browser get-content
frago browser get-content "#main-content"
```

### Screenshots

```bash
# Page screenshot (default: current viewport)
frago browser screenshot output.png

# Full-page screenshot
frago browser screenshot page.png --full-page --quality 90
```

### Scrolling

```bash
# Scroll by pixels (positive down, negative up) or alias
frago browser scroll 500
frago browser scroll down
frago browser scroll page-down

# Scroll to element (or by text)
frago browser scroll-to "#footer"
frago browser scroll-to --text "Load more"
```

### Zoom

```bash
# Set zoom level (1.0 = 100%)
frago browser zoom 1.5
```

## Tab Management

```bash
# List all tabs
frago browser list-tabs

# Switch to a tab by id (partial ids match)
frago browser switch-tab ABC123

# Close a tab
frago browser close-tab ABC123

# Tab groups
frago browser groups
frago browser group-info <group_name>
frago browser group-close <group_name>
frago browser group-cleanup
```

## Visual Effects

Visual markers for debugging and demonstration; they work on both backends
and `clear-effects` removes effects left by either backend.

```bash
frago browser highlight "#target-element" --color "#FF6B6B"
frago browser pointer "#target-element"
frago browser spotlight "#focus-element" --life-time 5
frago browser annotate "#element" "This is important" --position top
frago browser underline "#text-element"
frago browser clear-effects
```

## Profile Management

- **extension backend** — uses the browser's own default profile. frago does
  not copy, isolate or clean it.
- **cdp backend** — uses a dedicated profile per browser per port:
  `~/.frago/profiles/<browser>/<port>/` (e.g. `~/.frago/profiles/edge/9222`),
  seeded from the system browser profile. Port is always explicit in the path.

```bash
# CDP instance against a custom profile (port stays 9222)
frago browser -b cdp start --profile-dir /path/to/custom/profile
```

## Anti-Bot

The extension backend runs a real browser environment, so it passes
Cloudflare/Datadome/Akamai checks naturally. Probe a group's current page for
challenges:

```bash
frago browser detect --group research
```

See `frago book browser-anti-bot` for the interactive / invisible / blocked
three-tier handling.

## Platform-Specific Notes

### Linux

- Wayland sessions automatically use XWayland for void mode.
- Root user automatically disables sandbox (`--no-sandbox`).

### Windows

- Browser detection includes a registry lookup for non-standard installations.
- Edge is pre-installed on Windows 10/11.

### macOS

- Browsers are detected in `/Applications/`.
- Edge may need manual installation.

## Troubleshooting

### Browser Not Found

```bash
# Check available browsers and what would be picked
frago browser detect
frago browser check

# Verify browser binary is in PATH
which microsoft-edge
which google-chrome
```

### Bridge Not Connected

```bash
# Status first — if not connected, start and retry
frago browser status
frago browser start

# Bridge errors are structured JSON with a hint: {"ok": false, "code": ..., "hint": "run: frago browser start"}
```

### CDP Connection Failed

```bash
# CDP port is fixed at 9222 — check who owns it
lsof -i :9222   # Linux/macOS
netstat -an | findstr 9222   # Windows

# Stop the existing CDP instance and restart
frago browser -b cdp stop
frago browser -b cdp start
```

### Permission Denied (Linux)

Running as root requires disabling the sandbox — frago handles this
automatically, but you can set it explicitly:

```bash
export FRAGO_NO_SANDBOX=1
frago browser -b cdp start
```
