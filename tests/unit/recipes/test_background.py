"""Tests for background executor (ThreadPoolExecutor singleton)."""

import threading
import time

import pytest

from frago.recipes.background import (
    MAX_WORKERS,
    get_executor,
    shutdown_executor,
)


@pytest.fixture(autouse=True)
def clean_executor():
    """Ensure executor is shut down after each test."""
    yield
    shutdown_executor(wait=True)


class TestGetExecutor:
    def test_returns_thread_pool(self):
        executor = get_executor()
        assert executor is not None
        assert executor._max_workers == MAX_WORKERS

    def test_returns_same_instance(self):
        e1 = get_executor()
        e2 = get_executor()
        assert e1 is e2

    def test_recreates_after_shutdown(self):
        e1 = get_executor()
        shutdown_executor(wait=True)
        e2 = get_executor()
        assert e2 is not e1


class TestShutdownExecutor:
    def test_shutdown_when_none(self):
        """Should not raise when no executor exists."""
        shutdown_executor(wait=True)

    def test_shutdown_twice(self):
        """Should not raise on double shutdown."""
        get_executor()
        shutdown_executor(wait=True)
        shutdown_executor(wait=True)


class TestConcurrencyLimit:
    def test_max_workers_limit(self):
        """Should not exceed MAX_WORKERS concurrent tasks."""
        executor = get_executor()
        running_count = threading.Semaphore(0)
        barrier = threading.Event()

        def worker():
            running_count.release()
            barrier.wait(timeout=5)

        # Submit more tasks than MAX_WORKERS
        futures = []
        for _ in range(MAX_WORKERS + 2):
            futures.append(executor.submit(worker))

        # Wait for MAX_WORKERS threads to start
        for _ in range(MAX_WORKERS):
            assert running_count.acquire(timeout=5)

        # Give a moment for any extra threads to start (they shouldn't)
        time.sleep(0.1)

        # The semaphore should NOT be acquirable again (no extra workers)
        acquired = running_count.acquire(timeout=0.2)
        assert not acquired, "More workers than MAX_WORKERS are running"

        # Release all workers
        barrier.set()
        for f in futures:
            f.result(timeout=5)
