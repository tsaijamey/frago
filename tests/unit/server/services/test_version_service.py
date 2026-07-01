"""Unit tests for VersionCheckService (Phase 5: 原零覆盖).

以单元测试为准：断言版本比较、PyPI 抓取解析、缓存与 update_available 判定。
网络 / __version__ 全部 mock，不打真实 PyPI。直接实例化（不走单例）。
"""

import asyncio
from unittest.mock import MagicMock, patch

from frago.server.services.version_service import VersionCheckService


def _run(coro):
    return asyncio.run(coro)


def test_compare_versions():
    svc = VersionCheckService()
    assert svc._compare_versions("1.0.0", "1.2.0") is True
    assert svc._compare_versions("2.0.0", "1.9.9") is False
    assert svc._compare_versions("1.0.0", "1.0.0") is False


def test_fetch_latest_version_parses_pypi():
    svc = VersionCheckService()
    resp = MagicMock()
    resp.json.return_value = {"info": {"version": "9.9.9"}}
    resp.raise_for_status.return_value = None
    with patch("frago.server.services.version_service.requests.get", return_value=resp):
        assert svc._fetch_latest_version() == "9.9.9"


def test_get_version_info_triggers_check_when_empty():
    svc = VersionCheckService()
    with patch.object(svc, "_get_current_version", return_value="1.0.0"), \
         patch.object(svc, "_fetch_latest_version", return_value="1.5.0"), \
         patch.object(svc, "_broadcast_update", return_value=None) as bcast:
        info = _run(svc.get_version_info())
    assert info["current_version"] == "1.0.0"
    assert info["latest_version"] == "1.5.0"
    assert info["update_available"] is True
    bcast.assert_awaited_once()  # changed → broadcast


def test_do_check_fetch_error_keeps_current():
    svc = VersionCheckService()
    with patch.object(svc, "_get_current_version", return_value="1.0.0"), \
         patch.object(svc, "_fetch_latest_version", side_effect=RuntimeError("pypi down")):
        _run(svc._do_check())
    assert svc._cache["current_version"] == "1.0.0"
    assert svc._cache["latest_version"] is None
    assert svc._cache["update_available"] is False
    assert svc.get_last_error() == "pypi down"
