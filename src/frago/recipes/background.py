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
