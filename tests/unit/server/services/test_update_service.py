"""Unit tests for UpdateService and UpdateStatus."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.update_service import UpdateService, UpdateStatus


@pytest.fixture
def service():
    """Provide a fresh (non-singleton) UpdateService instance."""
    return UpdateService()


def test_initial_status_is_idle(service):
    status = service.get_status()
    assert status == {
        "status": UpdateStatus.IDLE,
        "progress": 0,
        "message": "",
        "error": None,
    }


def test_is_updating_false_when_idle(service):
    assert service.is_updating() is False


def test_is_updating_true_when_updating(service):
    service._status = UpdateStatus.UPDATING
    assert service.is_updating() is True


def test_is_updating_true_when_restarting(service):
    service._status = UpdateStatus.RESTARTING
    assert service.is_updating() is True


def test_is_updating_false_when_completed(service):
    service._status = UpdateStatus.COMPLETED
    assert service.is_updating() is False


def test_is_updating_false_when_error(service):
    service._status = UpdateStatus.ERROR
    assert service.is_updating() is False


@pytest.mark.asyncio
async def test_start_update_kicks_off_task(service):
    with patch.object(service, "_broadcast_status", return_value=None) as bc, \
            patch.object(service, "_do_update", return_value=None), \
            patch("asyncio.create_task") as create_task:
        result = await service.start_update()

    assert result == {"status": "ok", "message": "Update started"}
    assert service._status == UpdateStatus.UPDATING
    assert service._progress == 0
    assert service._message == "Starting update..."
    assert service._error is None
    bc.assert_awaited_once()
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_start_update_rejects_concurrent(service):
    service._status = UpdateStatus.UPDATING

    with patch.object(service, "_broadcast_status", return_value=None) as bc, \
            patch("asyncio.create_task") as create_task:
        result = await service.start_update()

    assert result == {"status": "error", "error": "Update already in progress"}
    bc.assert_not_called()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_start_update_rejects_when_restarting(service):
    service._status = UpdateStatus.RESTARTING

    with patch("asyncio.create_task") as create_task:
        result = await service.start_update()

    assert result == {"status": "error", "error": "Update already in progress"}
    create_task.assert_not_called()


def test_reset_returns_to_idle(service):
    service._status = UpdateStatus.ERROR
    service._progress = 90
    service._message = "boom"
    service._error = "some error"
    service._update_task = MagicMock()

    service.reset()

    assert service.get_status() == {
        "status": UpdateStatus.IDLE,
        "progress": 0,
        "message": "",
        "error": None,
    }
    assert service._update_task is None


def test_run_upgrade_command_success(service):
    completed = subprocess.CompletedProcess(
        args=["uv"], returncode=0, stdout="installed ok", stderr=""
    )
    with patch("subprocess.run", return_value=completed) as run:
        success, output = service._run_upgrade_command()

    assert success is True
    assert output == "installed ok"
    run.assert_called_once()


def test_run_upgrade_command_failure_uses_stderr(service):
    completed = subprocess.CompletedProcess(
        args=["uv"], returncode=1, stdout="", stderr="boom on stderr"
    )
    with patch("subprocess.run", return_value=completed):
        success, output = service._run_upgrade_command()

    assert success is False
    assert output == "boom on stderr"


def test_run_upgrade_command_failure_falls_back_to_stdout(service):
    completed = subprocess.CompletedProcess(
        args=["uv"], returncode=1, stdout="stdout error", stderr=""
    )
    with patch("subprocess.run", return_value=completed):
        success, output = service._run_upgrade_command()

    assert success is False
    assert output == "stdout error"


def test_run_upgrade_command_timeout(service):
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="uv", timeout=300),
    ):
        success, output = service._run_upgrade_command()

    assert success is False
    assert output == "Update timed out after 5 minutes"


def test_run_upgrade_command_uv_not_found(service):
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        success, output = service._run_upgrade_command()

    assert success is False
    assert output == "uv command not found. Please install uv first."


def test_run_upgrade_command_generic_exception(service):
    with patch("subprocess.run", side_effect=RuntimeError("weird")):
        success, output = service._run_upgrade_command()

    assert success is False
    assert output == "weird"


def test_get_instance_is_singleton():
    UpdateService._instance = None
    try:
        a = UpdateService.get_instance()
        b = UpdateService.get_instance()
        assert a is b
    finally:
        UpdateService._instance = None
