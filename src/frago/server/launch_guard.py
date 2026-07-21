"""Launch guards that constrain *how* the frago server may be started.

The only sanctioned server runtime is the system-installed frago (uv tool
install): ``frago server ...``. Running the server out of the repo's ``.venv``
is never allowed — ``uv run frago server start`` in the source checkout first
reinstalls the repo as the system frago and hands over to it (see
``frago.cli.server_command``), so by the time the daemon spawns, the process
must be the system install.

Two independent gates enforce this:

Gate 1 (spawn token): the daemon entry point requires an environment token that
only the sanctioned spawners (``start_daemon``, the restarter, the systemd unit
we generate) set. A raw ``python -m frago.server.runner --daemon`` lacks it and
is rejected. This is a guard against *accidental / habitual* misuse, not against
a deliberate actor who hand-sets the token — code-level guards cannot stop that.

Gate 2 (system install): the daemon spawner must NOT be running from the frago
source checkout's venv. That would make the repo venv the server runtime,
recreating the version split between the running server and the system frago
that hooks hand to agents.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Gate 1 — a fixed sentinel. Secrecy is intentionally not a goal (see module
# docstring): it distinguishes "spawned by a sanctioned path" from "raw module
# exec", which is enough to stop the habitual mistake.
SPAWN_TOKEN_ENV = "FRAGO_DAEMON_SPAWN_TOKEN"
SPAWN_TOKEN_VALUE = "frago-sanctioned-daemon-spawn-v1"


def sanctioned_spawn_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment mapping carrying the daemon spawn token.

    Sanctioned spawners pass this as ``env=`` to ``subprocess.Popen`` so the
    daemon child passes Gate 1. Defaults to a copy of the current environment so
    ``VIRTUAL_ENV`` and friends are preserved.
    """
    env = dict(os.environ if base is None else base)
    env[SPAWN_TOKEN_ENV] = SPAWN_TOKEN_VALUE
    return env


def assert_sanctioned_spawn() -> None:
    """Gate 1: refuse to run the daemon unless spawned by a sanctioned path.

    Called at the very start of the daemon entry point. Exits the process with a
    non-zero status (after logging to the daemon log) when the token is absent or
    wrong, so a raw ``python -m frago.server.runner --daemon`` cannot start a
    server.
    """
    if os.environ.get(SPAWN_TOKEN_ENV) == SPAWN_TOKEN_VALUE:
        return
    msg = (
        "Refusing to start daemon: not launched through a sanctioned entry "
        "point. Start the server with 'frago server start', never via "
        "'python -m frago.server.runner --daemon' directly."
    )
    logger.critical(msg)
    # Also surface to stderr in case logging isn't configured yet.
    print(msg, file=sys.stderr)
    sys.exit(1)


def source_checkout_root() -> Path | None:
    """Return the frago source checkout root if the interpreter runs from its venv.

    Detection relies on ``sys.prefix`` (set by the interpreter itself, unlike
    ``VIRTUAL_ENV`` which only ``activate`` / ``uv run`` set) so a bare
    ``.venv/bin/python`` launch is still recognised. Returns ``None`` for a real
    global / uv-tool install, where ``frago server ...`` is the sanctioned form.
    """
    if sys.prefix == sys.base_prefix:
        return None  # not in a venv at all
    venv_root = Path(sys.prefix)
    for cand in [venv_root.parent, *venv_root.parent.parents]:
        # A frago source checkout has both a pyproject and the package tree.
        if (cand / "pyproject.toml").exists() and (cand / "src" / "frago").exists():
            return cand
    return None


def assert_system_install() -> None:
    """Gate 2: refuse to spawn the daemon from the repo venv.

    No-op for a global / uv-tool install — the only sanctioned server runtime.
    Exits non-zero when the current interpreter belongs to the frago source
    checkout's venv: the repo venv must never be the server runtime.
    ``uv run frago server start`` in the checkout is still fine — the CLI
    reinstalls the repo as the system frago and execs it *before* this gate
    runs (see ``frago.cli.server_command``).
    """
    root = source_checkout_root()
    if root is None:
        return  # system / global install — the sanctioned runtime

    msg = (
        f"Refusing to start: this frago runs from the source checkout venv at "
        f"{root}, which must never be the server runtime. Use "
        f"'uv run frago server start' (it reinstalls the repo as the system "
        f"frago and hands over) or the system 'frago server start' directly."
    )
    print(msg, file=sys.stderr)
    sys.exit(1)
