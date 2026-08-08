[简体中文](browser-support.zh-CN.md)

# Browser Support

frago drives Chromium-based browsers through two backends:

- **extension (default)** — a browser extension + native-messaging bridge
  drives the browser's **own real profile**. No flags needed; this is the
  standard path for all page operations.
- **cdp** — the Chrome DevTools Protocol path, selected explicitly with
  `-b cdp`. This is the fallback when the default backend cannot do the
  job: true headless, a dedicated instance that must not disturb the
  standing browser (e.g. the `agent_os` screen-record rig), or
  `--void` / `--app` / `--profile-dir` startup shapes. Fixed port 9222.

The order is fixed: **default extension > `-b cdp` > launching a browser
yourself (forbidden)**. `chrome --headless`, `--remote-debugging-port`,
and hand-rolled raw-CDP connections are never an option — `-b cdp`
already covers the headless and dedicated-instance needs.

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

## Tab Groups

**A group is a real browser tab group** — the banded, collapsible thing on
the tab strip, with the group's name written on it. Everything an agent
opens lands in its own group, so two agents working at the same time never
touch each other's pages, and a person can see at a glance whose pages
these are.

Every page command takes `--group <name>` (or reads `FRAGO_CURRENT_RUN`).
Four rules govern the whole model:

1. **Five tabs per group.** Opening a sixth fails and lists the five that
   are in the way, so the caller picks one to close. Nothing is evicted
   silently — an agent that believes a page is still open, and finds its
   next command on a different page, has no way to notice.
2. **`navigate` replaces, it does not open.** It replaces the group's
   *current* tab — the last one it navigated or switched to — never the
   tab the browser happens to be showing. A person reading their own page
   keeps it.
3. **`--new` is the only way to open a tab.**
4. **`group-close` when done.** A group with no activity at all for 30
   minutes — no command, no tab activation, no scrolling inside its pages
   — closes itself. That is a backstop, not the workflow.

```bash
frago browser groups                    # every group: tabs used, time left
frago browser group-info <name>         # tab list, current tab, idle time
frago browser group-close <name>        # done with it
frago browser group-cleanup             # drop groups whose tabs are gone
```

## Page Operations

### Navigation

```bash
# Replace the group's current tab
frago browser navigate https://example.com --group research

# Open another tab inside the same group (max 5)
frago browser navigate https://example.com/b --group research --new

# Wait for a selector before returning
frago browser navigate https://example.com --group research --wait-for '.content-loaded'

# Wait N seconds (decimals ok)
frago browser wait --group research 2
```

### Element Interaction

```bash
# Click element
frago browser click --group research "#submit-button"
frago browser click --group research "button[type=submit]" --wait-timeout 15

# Execute JavaScript (return value with --return-value)
frago browser exec-js --group research "document.title"
frago browser exec-js --group research "document.querySelectorAll('a').length" --return-value
```

### Page Content

```bash
# Get page title
frago browser get-title --group research

# Get text content from page or element (selector defaults to body)
frago browser get-content --group research
frago browser get-content --group research "#main-content"
```

### Screenshots

```bash
# Page screenshot (default: current viewport)
frago browser screenshot --group research output.png

# Full-page screenshot
frago browser screenshot --group research page.png --full-page --quality 90
```

### Scrolling

```bash
# Scroll by pixels (positive down, negative up) or alias
frago browser scroll --group research 500
frago browser scroll --group research down
frago browser scroll --group research page-down

# Scroll to element (or by text)
frago browser scroll-to --group research "#footer"
frago browser scroll-to --group research --text "Load more"
```

### Zoom

```bash
# Set zoom level (1.0 = 100%)
frago browser zoom --group research 1.5
```

## Tab Management

Tab commands act **inside** a group. A group only ever sees, and only ever
touches, its own tabs.

```bash
# The group's own tabs; the one marked * is where commands land
frago browser list-tabs --group research

# Point the group at one of its tabs (partial ids match).
# This changes where commands land — not what is on screen.
frago browser switch-tab --group research ABC123

# ...and bring it on screen too
frago browser switch-tab --group research ABC123 --activate

# Close one of the group's own tabs — this is how you make room
frago browser close-tab --group research ABC123
```

The CDP backend enforces the same rules, with one thing it cannot do: CDP
has no access to the browser's tab-group UI, so there a group is
bookkeeping only and its tabs are not banded together on the tab strip.

## Visual Effects

Visual markers for debugging and demonstration; they work on both backends
and `clear-effects` removes effects left by either backend.

```bash
frago browser highlight --group research "#target-element" --color "#FF6B6B"
frago browser pointer --group research "#target-element"
frago browser spotlight --group research "#focus-element" --life-time 5
frago browser annotate --group research "#element" "This is important" --position top
frago browser underline --group research "#text-element"
frago browser clear-effects --group research
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
