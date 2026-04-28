# frago-bridge — Chrome extension

Manifest V3 Chrome extension that frago talks to over Chrome native
messaging. This is an **independent project** within the frago repo:
it has its own release cadence (Chrome Web Store) and does not depend
on the Python package at runtime.

End users install this extension from the Chrome Web Store. Frago
talks to it through a native messaging daemon — see
`src/frago/extension/README.md` for the Python side.

## Layout

    manifest.json                   ← MV3 manifest
    background/service_worker.js    ← request router, tab/group mapping, keepalive
    content/content_script.js       ← per-tab execution context (P1: minimal)
    popup/index.html                ← diagnostic popup
    keys/                           ← signing key + derivation tooling

## Communication

The extension speaks length-prefixed JSON-RPC 2.0 frames over Chrome
native messaging. The wire format and method registry are defined by
`src/frago/extension/protocol.py`. Both halves must agree on the
protocol version — keep them in lockstep when iterating.

## Dev workflow

For local iteration before a Web Store release, sideload the unpacked
bundle:

```bash
# 1. Start the frago daemon.
uv run frago extension daemon &

# 2. Launch a fresh Chrome with this bundle loaded as unpacked.
uv run python scripts/dev_launch_extension.py

# 3. Read the dev extension ID from chrome://extensions and register
#    the native messaging manifest with that ID:
uv run frago extension install <dev_extension_id>

# 4. Verify the bridge is up.
uv run frago extension status
```

## Stable extension ID

The pinned RSA pubkey in `manifest.json` makes the extension ID
deterministic across machines (`STABLE_EXTENSION_ID` in
`src/frago/extension/native_host.py`). Regenerate keys + ID with:

```bash
uv run python scripts/generate_extension_id.py
```

## Releasing to the Chrome Web Store

(P2 work, not covered yet.)
