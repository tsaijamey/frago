"""Background executor for async recipe execution.

Provides a global ThreadPoolExecutor for running recipes in background threads.
Used by RecipeRunner.run_async() to execute recipes without blocking the caller.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Global singleton, similar to _active_processes in runner.py —
# Server may create new RecipeRunner per request, but the executor is shared.
_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()

MAX_WORKERS = 4  # Max concurrent background recipe executions


def get_executor() -> ThreadPoolExecutor:
    """Get or create the global thread pool."""
    global _executor
    with _executor_lock:
        if _executor is None or _executor._shutdown:
            _executor = ThreadPoolExecutor(
                max_workers=MAX_WORKERS,
                thread_name_prefix="recipe-bg",
            )
        return _executor


def shutdown_executor(wait: bool = True) -> None:
    """Shut down the thread pool. Called on server exit."""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait)
            _executor = None


# Runs a visitor asked for get their own, smaller pool. Sharing the one above
# would mean a handful of signed-in strangers can fill every slot and the owner's
# own machine stops answering — the server's first duty is to the person whose
# machine it is, so visitors get a bounded share rather than an equal claim.
#
# Bounded by a semaphore rather than a second executor's queue: a queue accepts
# work it cannot start, and a visitor waiting behind four long scans would sit on
# an HTTP request that has already been answered with 202. Refusing outright is
# the honest answer, and the page can offer to try again.
MAX_VISITOR_WORKERS = 2

_visitor_executor: ThreadPoolExecutor | None = None
_visitor_slots: threading.Semaphore | None = None


class VisitorPoolBusy(RuntimeError):
    """Every visitor slot is taken. Not an error — a limit doing its job."""


def _visitor_pool() -> tuple[ThreadPoolExecutor, threading.Semaphore]:
    global _visitor_executor, _visitor_slots
    with _executor_lock:
        if _visitor_executor is None or _visitor_executor._shutdown:
            _visitor_executor = ThreadPoolExecutor(
                max_workers=MAX_VISITOR_WORKERS,
                thread_name_prefix="recipe-visitor",
            )
            _visitor_slots = threading.Semaphore(MAX_VISITOR_WORKERS)
        assert _visitor_slots is not None
        return _visitor_executor, _visitor_slots


def submit_visitor_run(work) -> None:
    """Run `work` on the visitor pool, or raise if there is no room.

    The slot is taken before submitting and released by the worker itself, so a
    slot is held for exactly as long as the work runs.
    """
    executor, slots = _visitor_pool()
    if not slots.acquire(blocking=False):
        raise VisitorPoolBusy("all visitor run slots are in use")

    def _wrapped():
        try:
            work()
        finally:
            slots.release()

    try:
        executor.submit(_wrapped)
    except Exception:
        slots.release()
        raise


def shutdown_visitor_executor(wait: bool = True) -> None:
    global _visitor_executor, _visitor_slots
    with _executor_lock:
        if _visitor_executor is not None:
            _visitor_executor.shutdown(wait=wait)
            _visitor_executor = None
            _visitor_slots = None
