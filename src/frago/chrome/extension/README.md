# frago extension — Python side

This package is the **frago side** of the browser extension bridge:
the native messaging daemon, the stdio relay that Chrome spawns, and
the manifest installer that wires them together. It talks to the
Chrome MV3 extension over Chrome native messaging (length-prefixed
JSON-RPC 2.0 frames).

The MV3 extension itself is an independent project at
`src/frago/_resources/extension_bundle/` (repo root) — distributed via Chrome Web
Store, with its own README. From frago Python's point of view the
extension is just a peer reachable through the daemon socket.

See the spec at `.claude/docs/spec-driven-plan/20260425-browser-extension.md`
for the full design.

## Layout

    src/frago/_resources/extension_bundle/        ← MV3 extension (independent project, own README)
    src/frago/extension/            ← this package: daemon, relay, JSON-RPC types
    src/frago/chrome/backends/      ← CDP and Extension backend adapters
    src/frago/cli/extension_commands.py  ← `frago extension` CLI group
    scripts/dev_launch_extension.py ← dev-only sideloader (not part of agent OS surface)
    tests/extension/                ← unit + parity tests
    tests/extension/e2e/            ← live-Chrome and mock-extension smoke scripts

## Architecture

```
    frago process                   Chrome browser
         │                                │
         │ unix socket                    │ stdio (native messaging)
         │ ~/.frago/chrome/               │
         │   extension.sock               │
         ▼                                ▼
    ┌────────────────────────────────────────┐
    │    native messaging daemon             │
    │    `frago extension daemon`            │
    └────────────────────────────────────────┘
                    ▲
                    │ relay (stdio ↔ uds)
                    │
    ┌──────────────────────────────┐
    │  `frago extension native-host` │
    │  (spawned by Chrome on connect)│
    └──────────────────────────────┘
```

The **daemon** is a singleton. Both frago CLI clients (e.g. recipes
running `frago chrome navigate --backend extension`) and Chrome (via
the relay) connect to the same unix socket. Requests are rewritten
with internal IDs, forwarded to the extension, and the response is
routed back. Events (id=None) are broadcast to all clients.

## Production setup (extension installed from Chrome Web Store)

```bash
# 1. Start the native messaging daemon. Add to autostart for persistence.
uv run frago extension daemon &

# 2. Tell Chrome how to spawn frago's native host. The default extension
#    ID is the published one; pass an ID to override (e.g. for a dev build).
uv run frago extension install

# 3. Verify the bridge is up.
uv run frago extension status

# 4. Use it via the unified chrome CLI:
uv run frago chrome navigate https://example.com --group demo --backend extension
```

## Dev setup (sideload an unpacked bundle)

```bash
uv run frago extension daemon &
uv run python scripts/dev_launch_extension.py
# Read the dev extension ID from chrome://extensions, then:
uv run frago extension install <dev_extension_id>
uv run frago extension status
```

## Status

| Component | State |
|---|---|
| Native messaging protocol (JSON-RPC 2.0, length-prefixed) | ✅ done |
| Daemon + relay (multi-client multiplexer) | ✅ done |
| Backend abstraction `frago.chrome.backends` (CDP + Extension) | ✅ done |
| `frago chrome <cmd> --backend extension` switch | ✅ landed in P1.5 |
| Legacy `frago extension <mvp-cmd>` aliases | ⚠️ deprecated (notice on first use), removal in P2 |
| Unit tests: protocol, daemon roundtrip, backend parity | ✅ passing |
| End-to-end against live Chrome | ⚠️ blocked by Chrome Stable's `--load-extension` policy on this host; mock e2e covers SW-adjacent half |
| Firefox / Edge / Brave support | ❌ not in scope (P2+) |

## FAQ

### Service worker goes to sleep after 30 s — does the bridge die?

The daemon keeps running regardless. When Chrome suspends the service
worker, the native messaging port disconnects; on next activity the SW
reconnects. The daemon queues incoming CLI requests by replying
`EXTENSION_NOT_READY` until the port comes back (client is expected to
retry). The service worker runs a 20 s `system.ping` keepalive while
active. Long-running commands are not currently retried by the client —
that's a P2 improvement.

### Why a separate daemon instead of just letting Chrome spawn the host?

Chrome's native messaging model spawns the host as its child and owns
the stdio pipes. That would make CLI-initiated commands impossible.
The relay is a short-lived stdio ↔ uds bridge; the daemon is the
persistent peer that survives across SW lifecycles.

### Can I run two browsers?

Not in MVP. The daemon rejects a second extension connection with
`INTERNAL_ERROR`.

## Files

| Path | Role |
|---|---|
| `protocol.py` | JSON-RPC types, frame encoding |
| `native_host.py` | Daemon, relay, DaemonClient, manifest installer |
| `../chrome/backends/base.py` | `ChromeBackend` ABC + result dataclasses |
| `../chrome/backends/cdp.py` | Wraps existing `CDPSession` |
| `../chrome/backends/extension.py` | RPC client + (dev-only) browser launcher helper |
| `../cli/extension_commands.py` | `frago extension` CLI group |
| `../../../tests/extension/test_mvp_parity.py` | Protocol + daemon + backend shape tests |
