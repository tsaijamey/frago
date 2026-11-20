"""Cross-process file locking, atomic fsync replacement, and anti-reset LKG guardrails.

Protects critical configuration, ontology store, origin ledger, and employee files
from two failure modes:
1. Partial/non-atomic writes or cross-process race conditions.
2. Transient lock/read/parse failures silently falling back to empty/default objects
   and then overwriting the real file on disk.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

if os.name == "nt":  # pragma: no cover - Windows fallback
    import msvcrt
else:
    import fcntl


class FileGuardError(RuntimeError):
    """Base error for guarded file lock / read / anti-reset operations."""


class FileLockTimeoutError(FileGuardError):
    """Raised when an advisory file lock cannot be acquired within timeout."""


class ProtectedFileReadError(FileGuardError):
    """Raised when an existing non-empty file cannot be safely read/parsed."""


_REGISTRY_LOCK = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_THREAD_HOLD_COUNTS = threading.local()


def _get_thread_locks(path_key: str) -> threading.RLock:
    with _REGISTRY_LOCK:
        lock = _PATH_LOCKS.get(path_key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[path_key] = lock
        return lock


def _hold_map() -> dict[str, tuple[int, bool]]:
    held = getattr(_THREAD_HOLD_COUNTS, "held", None)
    if held is None:
        held = {}
        _THREAD_HOLD_COUNTS.held = held
    return held


def lock_path_for(path: Path) -> Path:
    """Return the hidden advisory lock file path for ``path``."""
    return path.with_name(f".{path.name}.lock")


def lkg_path_for(path: Path) -> Path:
    """Return the hidden Last-Known-Good backup path for ``path``."""
    return path.with_name(f".{path.name}.lkg")


def _try_flock(fd: int, *, exclusive: bool) -> bool:
    if os.name == "nt":  # pragma: no cover
        try:
            mode = msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK
            msvcrt.locking(fd, mode, 1)
            return True
        except OSError:
            return False
    flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, flag | fcntl.LOCK_NB)
        return True
    except (BlockingIOError, OSError):
        return False


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":  # pragma: no cover
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked_file(
    path: Path,
    *,
    timeout_s: float = 5.0,
    exclusive: bool = True,
) -> Iterator[None]:
    """Acquire an in-process reentrant + cross-process advisory file lock for ``path``."""
    target = Path(path)
    lock_file = lock_path_for(target)
    key = os.path.abspath(str(lock_file))
    thread_lock = _get_thread_locks(key)
    holds = _hold_map()

    with thread_lock:
        held_state = holds.get(key)
        if held_state is not None:
            depth, held_exclusive = held_state
            if exclusive and not held_exclusive:
                raise FileGuardError(
                    f"Cannot upgrade shared file lock to exclusive lock on {target} in the same thread"
                )
            holds[key] = (depth + 1, held_exclusive)
            try:
                yield
            finally:
                holds[key] = (depth, held_exclusive)
            return

        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            deadline = time.monotonic() + max(0.0, float(timeout_s))
            delay = 0.01
            acquired = False
            while True:
                if _try_flock(fd, exclusive=exclusive):
                    acquired = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(delay, remaining))
                delay = min(delay * 1.5, 0.1)

            if not acquired:
                raise FileLockTimeoutError(
                    f"Timed out waiting for {'exclusive' if exclusive else 'shared'} lock on {target}"
                )

            holds[key] = (1, bool(exclusive))
            try:
                yield
            finally:
                holds.pop(key, None)
                _unlock_fd(fd)
        finally:
            os.close(fd)


def _atomic_replace_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        with contextlib.suppress(OSError):
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        raise


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    save_lkg: bool = True,
) -> None:
    """Atomically write ``content`` to ``path`` using temp-file + fsync + os.replace."""
    target = Path(path)
    raw = content.encode(encoding)
    _atomic_replace_bytes(target, raw)
    if save_lkg:
        with contextlib.suppress(OSError):
            _atomic_replace_bytes(lkg_path_for(target), raw)


def has_nonempty_file(path: Path) -> bool:
    """Return True if ``path`` exists and is non-empty on disk."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def backup_corrupted_file(path: Path, reason: str = "corrupt") -> Path | None:
    """Preserve a timestamped copy of ``path`` before any recovery attempt."""
    if not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_reason = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in reason)[:32]
    bak = path.with_name(f"{path.name}.{safe_reason}.{stamp}.bak")
    try:
        data = path.read_bytes()
        _atomic_replace_bytes(bak, data)
        return bak
    except OSError:
        return None
