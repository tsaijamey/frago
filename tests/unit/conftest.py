"""Unit test specific fixtures - heavy mocking for isolation."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_file_io(mock_home):
    """Mock all file I/O operations for complete isolation."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value="{}"),
        patch("pathlib.Path.write_text"),
        patch("pathlib.Path.mkdir"),
        patch("builtins.open", MagicMock()),
    ):
        yield


@pytest.fixture
def mock_registry():
    """Mock RecipeRegistry for service tests."""
    mock_reg = MagicMock()
    mock_reg.list_all.return_value = []
    mock_reg.needs_rescan.return_value = False
    mock_reg.get.return_value = None

    with patch("frago.recipes.registry.get_registry", return_value=mock_reg):
        yield mock_reg


@pytest.fixture
def mock_websocket_manager():
    """Mock WebSocket broadcast manager."""
    mock_manager = AsyncMock()
    mock_manager.broadcast = AsyncMock()
    mock_manager.connection_count = 0

    with patch("frago.server.websocket.manager", mock_manager):
        yield mock_manager


@pytest.fixture
def mock_session_storage():
    """Mock session storage functions."""
    with (
        patch("frago.session.storage.list_sessions", return_value=[]),
        patch("frago.session.storage.read_metadata", return_value=None),
        patch("frago.session.storage.read_steps_paginated", return_value=([], False)),
        patch("frago.session.storage.read_summary", return_value=None),
    ):
        yield
