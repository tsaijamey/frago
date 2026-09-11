"""The WorkBuddy model list the connection form picks from."""

import json
import os
import time
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_the_probe_time_is_the_local_time_the_list_was_written(tmp_path):
    """frago-core stamps the probe in UTC; the page shows local time everywhere else."""
    from frago.server.routes.settings import get_workbuddy_models

    path = tmp_path / "workbuddy-models.json"
    path.write_text(
        json.dumps(
            {
                "probed_at": "2026-09-11T05:30:19.001591",
                "models": [
                    {"id": "deepseek-v4-flash", "ok": True, "wire": "openai"},
                    {"id": "hy3", "ok": False, "thinks": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    local = time.mktime((2026, 9, 11, 13, 30, 19, 0, 0, -1))
    os.utime(path, (local, local))
    with (
        patch("frago.init.profile_manager.WORKBUDDY_MODELS_PATH", path),
        patch("frago.init.profile_manager.workbuddy_login_path", return_value=tmp_path / "none"),
    ):
        resp = await get_workbuddy_models()

    assert resp.probed_at == "2026-09-11T13:30:19"
    assert resp.logged_in is False
    assert [(m.id, m.ok) for m in resp.models] == [("deepseek-v4-flash", True), ("hy3", False)]


@pytest.mark.asyncio
async def test_no_probe_yet_is_an_empty_list_not_an_error(tmp_path):
    from frago.server.routes.settings import get_workbuddy_models

    with (
        patch("frago.init.profile_manager.WORKBUDDY_MODELS_PATH", tmp_path / "none.json"),
        patch("frago.init.profile_manager.workbuddy_login_path", return_value=tmp_path / "none"),
    ):
        resp = await get_workbuddy_models()

    assert resp.probed_at is None
    assert resp.models == []
