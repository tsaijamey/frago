"""没登录 GitHub 时，把配额说给人听。

匿名调 GitHub 是 60 次/小时、按 IP 共用；跑光了的表现是「社区配方列表空了」，
跟真正的原因（额度用尽）长得一点都不像。这里锁住两件事：没登录时接口把剩余
次数一并返回，已登录时不多打一次 GitHub 去问一个不影响任何人的数字。
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.server.routes import settings as settings_routes
from frago.server.services.github_service import GitHubService


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api")
    return TestClient(app)


def _state_manager(gh_status: dict) -> MagicMock:
    manager = MagicMock()

    async def _noop(*args, **kwargs):
        return None

    manager.refresh_gh_status = _noop
    manager.get_gh_status = MagicMock(return_value=gh_status)
    return manager


class TestGhCliQuotaVisibility:
    def test_logged_out_response_carries_the_anonymous_quota(self, client):
        quota = {
            "limit": 60,
            "remaining": 7,
            "used": 53,
            "reset_in_seconds": 1800,
            "authenticated": False,
        }
        state = _state_manager({"installed": True, "authenticated": False})

        with patch.object(
            settings_routes.StateManager, "get_instance", return_value=state
        ), patch.object(GitHubService, "get_rate_limit", return_value=quota):
            body = client.get("/api/settings/gh-cli").json()

        assert body["authenticated"] is False
        assert body["rate_limit"] == quota

    def test_logged_in_does_not_spend_a_call_asking(self, client):
        state = _state_manager(
            {"installed": True, "authenticated": True, "username": "someone"}
        )

        with patch.object(
            settings_routes.StateManager, "get_instance", return_value=state
        ), patch.object(GitHubService, "get_rate_limit") as asked:
            body = client.get("/api/settings/gh-cli").json()

        assert body["rate_limit"] is None
        asked.assert_not_called()

    def test_unreachable_github_shows_no_numbers_rather_than_wrong_ones(self, client):
        state = _state_manager({"installed": False, "authenticated": False})

        with patch.object(
            settings_routes.StateManager, "get_instance", return_value=state
        ), patch.object(GitHubService, "get_rate_limit", return_value=None):
            body = client.get("/api/settings/gh-cli").json()

        assert body["rate_limit"] is None


class TestGetRateLimit:
    def test_reads_the_core_bucket(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "resources": {
                "core": {"limit": 60, "remaining": 12, "used": 48, "reset": 0}
            }
        }

        with patch("requests.get", return_value=response):
            result = GitHubService.get_rate_limit()

        assert result["limit"] == 60
        assert result["remaining"] == 12
        assert result["used"] == 48
        # A 60-per-hour bucket is what GitHub hands callers with no token.
        assert result["authenticated"] is False
        assert result["reset_in_seconds"] == 0

    def test_a_bigger_bucket_means_a_token_was_accepted(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "resources": {
                "core": {"limit": 5000, "remaining": 4999, "used": 1, "reset": 0}
            }
        }

        with patch("requests.get", return_value=response):
            assert GitHubService.get_rate_limit()["authenticated"] is True

    def test_network_failure_returns_nothing(self):
        with patch("requests.get", side_effect=OSError("no route to host")):
            assert GitHubService.get_rate_limit() is None
