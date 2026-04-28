"""frago browser extension — Python side (daemon, relay, JSON-RPC).

The MV3 extension bundle ships *with* frago as package data at
``frago/_resources/extension_bundle/`` (sibling of this Python package).
Resolve its path through :func:`bundle_path` — never hardcode the
filesystem location, so pip-installed users and editable installs both
work.

Architecture (P1):

    CLI process           Chrome browser
         │                      │
         │ unix socket          │ stdio (native messaging)
         ▼                      ▼
    ┌───────────────────────────────┐
    │   native host daemon          │ ~/.frago/chrome/extension.sock
    │   (frago extension daemon)    │
    └───────────────────────────────┘
              ▲
              │ relay (stdio ↔ uds)
              │
    ┌──────────────────┐
    │  native-host     │ spawned by Chrome once per connect
    │  (relay script)  │
    └──────────────────┘

The daemon is singleton; both Chrome-side relay and CLI-side clients connect
to it. See the README next to this module for setup.
"""

from importlib.resources import files
from pathlib import Path

from .protocol import RpcRequest, RpcResponse, RpcError, RPC_ERROR_CODES


def bundle_path() -> Path:
    """Return the absolute path of the bundled MV3 extension.

    Uses :mod:`importlib.resources` so it resolves correctly in editable
    installs (file lives in the repo) and in pip installs (file lives in
    site-packages). Callers pass the returned path to ``--load-extension``
    or write a ``NativeMessagingHosts`` manifest pointing at it.
    """
    res = files("frago") / "_resources" / "extension_bundle"
    return Path(str(res))


__all__ = [
    "RpcRequest", "RpcResponse", "RpcError", "RPC_ERROR_CODES",
    "bundle_path",
]
