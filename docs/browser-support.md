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
  `--headless` / `--app` / `--profile-dir` startup shapes. CDP ports are
  whitelisted to **9222** (default) and **9223** (the agent_os recorder).

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
| **Chrome for Testing** | ✅ Default | frago's own download at `~/.frago/tools/chrome-for-testing/`; fetched on demand |
| **Edge** | ✅ | Stable > Beta > Dev; taken when frago has no CfT of its own |
| **Chromium** | ✅ | Open-source base |
| **Chrome** | ✅ (non-Stable) | Beta/Dev/Canary; Stable is excluded (v137+ silently ignores `--load-extension`) |
| **Brave / Vivaldi** | ✅ | Also auto-detectable |
| **Firefox** | ❌ None | CDP removed in Firefox 141 (2025) |
| **Safari** | ❌ None | No CDP support |

The picker takes the first installed browser in this fixed order:
Chrome for Testing → Edge Stable → Edge Beta → Edge Dev → Chromium →
Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi. Everything
after Chrome for Testing is a browser the user installed, reached only when
frago has none of its own — and in that case `start` fetches Chrome for
Testing first and falls back to that list only if the fetch fails. The CDP
backend keeps its own shorter order, Edge → Chromium → Chrome; there Chrome
for Testing is reachable only by name (`--browser cft`).

**`--browser` belongs to the CDP backend.** Under the default extension
backend it is refused outright: it cannot change which binary launches (the
picker decides), so all it could do is point the profile directory at another
brand and drive one browser against another browser's profile — `--browser
chrome` being the worst case, that being the person's everyday Chrome
profile. Under `-b cdp` it really switches the browser, accepts `chrome` /
`edge` / `chromium` / `cft`, and the profile path follows along (`--browser
chrome` → `~/.frago/profiles/chrome/9222/`). frago itself pins it in exactly
one place: the agent_os stage bringing up its actor and recorder, with
`cft`. Everywhere else, let the picker choose.

## Browser Detection

```bash
# Installed browsers and their paths. Its "default" line follows the CDP
# order (Edge → Chromium → Chrome), not what `start` would pick.
frago browser detect

# Per-browser backend support, running status, and the browser `start`
# would actually pick — Chrome for Testing included.
frago browser check
```

`detect` carries a second meaning: with `--group` it probes that group's
current page for anti-bot challenges (extension backend only) — see
[Anti-Bot](#anti-bot).

## Browser Lifecycle

```bash
# Start: picks a browser, launches the extension bridge, opens its real profile
frago browser start

# Health check
frago browser status

# Stop browser + daemon + socket
frago browser stop

# Fetch frago's own browser ahead of time, or upgrade it with --force
frago browser install
```

`start` runs the whole chain: fetch Chrome for Testing if the machine has none
yet → pick browser → launch native-messaging daemon → write manifest → launch
browser with the extension → wait for the bridge handshake. No manual
preparation needed.

The browser runs on its **own default profile** (logins, saved passwords and
cookies are visible to the agent, and vice versa). Chrome for Testing has no
vendor profile to use, so frago owns one for it at
`~/.frago/profiles/cft/extension/` — still one real profile, nothing copied
or branched. One instance per profile — if `start` hits a live lock it errors
and tells you to `stop` first.

### CDP-only launch options

`--headless`, `--width`, `--height`, `--window-x`, `--window-y`, `--port`,
`--profile-dir`, `--no-kill` and `--keep-alive` are **CDP-backend options**.
Under the default extension backend they are silently dropped. To use them,
select CDP explicitly:

```bash
frago browser -b cdp start --headless   # headless CDP instance (port 9222)
```

Two footnotes on that option set:

- `--void` is gone (removed 2026-08-23). It only parked the window at
  -32000,-32000, which macOS honours for the first window a process opens and
  nothing after it, so the window came back on screen. Passing it now fails
  with that explanation; pick an ordinary window (real GPU/WebGL) or
  `--headless` (no window, no WebGL).
- `--reseed-profile` is obsolete and ignored: the default backend drives the
  browser's own profile, so there is nothing left to re-seed.

`--app` / `--app-url` are the exception — **both backends honour them**, and
the browser opens that page as a borderless app window instead of a blank tab.

CDP ports are whitelisted to **9222** (default) and **9223** (the agent_os
recorder). Any other value is rejected; never invent ports. **9222 is
shared**: while the virtual desktop stage is running, its actor lives on
that port, working out of the same `~/.frago/profiles/cft/9222/` profile —
and `-b cdp start` kills whatever is already there unless you pass
`--no-kill`. Check `frago desktop status` before starting (see
`frago book browser-backend-choice`).

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

`--wait-for` is CDP-only. The default backend returns as soon as the tab
reports loaded, dropping the selector wait — poll for the selector yourself
with `exec-js ... --return-value` if the page needs it to exist first.

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

`--full-page` and `--quality` are CDP-only too: the default backend always
captures the current viewport as a PNG and ignores both.

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
  not copy, isolate or clean it. Chrome for Testing is the one browser with no
  vendor profile: frago keeps its profile at
  `~/.frago/profiles/cft/extension/`.
- **cdp backend** — uses a dedicated profile per browser per port:
  `~/.frago/profiles/<browser>/<port>/` (e.g. `~/.frago/profiles/edge/9222`),
  seeded once from that browser's system profile — the first launch copies
  the tree, later launches leave it alone. Port is always explicit in the
  path. Chrome for Testing has no system profile to seed from, so
  `~/.frago/profiles/cft/<port>/` starts empty and its logins are made there
  once.

```bash
# CDP instance against a custom profile (port stays 9222)
frago browser -b cdp start --profile-dir /path/to/custom/profile
```

## Virtual Desktop Stage

`frago desktop` drives a scriptable fake desktop (a real tmux session, a real
browser tab, and a local image) used by the `agent_os` workflow to record
replays. It owns both CDP ports while it is up:

- **9222** — the stage **actor**, a headless Chrome for Testing browser
  working out of `~/.frago/profiles/cft/9222/`. That profile is frago's own,
  not seeded from anyone's Edge or Chrome. It is the same instance a
  standalone `frago browser -b cdp start` would target, so do not start or
  stop a CDP instance while the stage is running.
- **9223** — the **recorder**, also Chrome for Testing, created when the
  camera comes up (`camera up` or `rec start`) and torn down by `rec stop` /
  `camera down`.

Both are Chrome for Testing and nothing else. When the machine has none, the
stage fetches it on the spot; when that fetch fails the stage does not come up
at all, rather than occupying the Edge or Chrome a person browses with. It
also puts up a visible Chrome for Testing window (app window, through the
extension backend) before the headless pair starts: macOS hands icon clicks
to whichever instance of an app registered first, so a headless one first
would leave a person clicking the icon and seeing nothing.

Always check first: `frago desktop status`. Full usage lives in
`frago book desktop-usage`.

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

- The sandbox is disabled (`--no-sandbox`) automatically when running as
  root, and on Ubuntu 23.10+ when AppArmor blocks unprivileged user
  namespaces for a binary with no AppArmor profile — the usual case for
  Chrome for Testing unpacked under `~/.frago/tools/`. `FRAGO_NO_SANDBOX=1`
  forces it.
- Chrome for Testing may need system libraries (e.g. `libnss3`,
  `libatk-1.0-0`) that a desktop install already has. When they are missing,
  the fetch reports which library and the command that installs it; that
  install needs sudo and frago does not do it for you.

### Windows

- Browser detection includes a registry lookup for non-standard installations.
- Edge is pre-installed on Windows 10/11, which makes it the first fallback
  when Chrome for Testing cannot be fetched.

### macOS

- Browsers are detected in `/Applications/`.
- Chrome for Testing is not in `/Applications/` — it lives under
  `~/.frago/tools/chrome-for-testing/`, not registered as a system browser.
- Edge may need manual installation.

## Troubleshooting

### Browser Not Found

```bash
# What `start` would pick, and what else is installed
frago browser check
frago browser detect

# No Chrome for Testing on this machine yet — fetch frago's own browser
frago browser install

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
# Ports are whitelisted: 9222 (default) and 9223 (agent_os recorder)
lsof -i :9222 -i :9223   # Linux/macOS
netstat -an | findstr 9222   # Windows

# If the virtual desktop stage is up, its actor owns 9222 — leave it alone
frago desktop status

# Otherwise stop the existing CDP instance and restart
frago browser -b cdp stop
frago browser -b cdp start
```

### Permission Denied (Linux)

Running as root, or on a kernel where AppArmor blocks unprivileged user
namespaces for a binary without an AppArmor profile, requires disabling the
sandbox — frago handles both cases automatically, but you can force it:

```bash
export FRAGO_NO_SANDBOX=1
frago browser -b cdp start
```
