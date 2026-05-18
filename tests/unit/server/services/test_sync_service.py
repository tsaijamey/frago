"""Tests for frago.server.services.sync_service module.

Tests background session synchronization service.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from frago.server.services.sync_service import SyncService


class TestSyncServiceSingleton:
    """Test SyncService singleton pattern."""

    def test_get_instance_returns_same_instance(self):
        """Multiple calls should return same instance."""
        instance1 = SyncService.get_instance()
        instance2 = SyncService.get_instance()

        assert instance1 is instance2

    def test_fresh_instance_has_no_task(self):
        """Fresh instance should have no running task."""
        instance = SyncService.get_instance()

        assert instance._task is None


class TestSyncServiceStart:
    """Test SyncService.start() async method."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """start() should create background task."""
        service = SyncService.get_instance()

        with patch.object(service, "_sync_loop", new_callable=AsyncMock):
            await service.start()

            assert service._task is not None

            # Cleanup
            await service.stop()

    @pytest.mark.asyncio
    async def test_start_skips_if_already_running(self):
        """start() should skip if already running."""
        service = SyncService.get_instance()

        # Create a fake running task
        service._task = asyncio.create_task(asyncio.sleep(10))

        # Should not raise
        await service.start()

        # Cleanup
        service._task.cancel()
        try:
            await service._task
        except asyncio.CancelledError:
            pass
        service._task = None


class TestSyncServiceStop:
    """Test SyncService.stop() async method."""

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() should cancel running task."""
        service = SyncService.get_instance()

        with patch.object(service, "_sync_loop", new_callable=AsyncMock):
            await service.start()
            await service.stop()

        assert service._task is None or service._task.done()

    @pytest.mark.asyncio
    async def test_stop_noop_if_not_running(self):
        """stop() should be safe when no task running."""
        service = SyncService.get_instance()
        service._task = None

        # Should not raise
        await service.stop()


class TestSyncServiceRequestRefresh:
    """Test SyncService.request_refresh() method."""

    @pytest.mark.asyncio
    async def test_request_refresh_sets_pending(self):
        """request_refresh() should set pending flag."""
        service = SyncService.get_instance()
        service._pending_refresh = False

        await service.request_refresh()

        assert service._pending_refresh is True

    @pytest.mark.asyncio
    async def test_request_refresh_debounces(self):
        """Multiple rapid requests should be debounced."""
        service = SyncService.get_instance()

        # Multiple rapid calls
        await service.request_refresh()
        await service.request_refresh()
        await service.request_refresh()

        # Only one pending
        assert service._pending_refresh is True

        # Cleanup any debounce tasks
        if service._debounce_task:
            service._debounce_task.cancel()
            try:
                await service._debounce_task
            except asyncio.CancelledError:
                pass
            service._debounce_task = None


class TestSyncServiceGetLastResult:
    """Test SyncService.get_last_result() method."""

    def test_returns_none_initially(self):
        """Should return None when no sync has occurred."""
        service = SyncService.get_instance()
        service._last_result = None

        result = service.get_last_result()

        assert result is None

    def test_returns_stored_result(self):
        """Should return last sync result."""
        service = SyncService.get_instance()
        service._last_result = {"synced": 5, "errors": []}

        result = service.get_last_result()

        assert result == {"synced": 5, "errors": []}
