"""8093 页面自己把 gh 装上、登进去，靠的是这几个接口。

访客看到的是一条横幅上的两个按钮：装 / 登录。按钮背后必须满足两件事，否则
用户会卡在半路而且看不出卡在哪：装这一步要能立刻返回、之后靠轮询看进度（brew
装一次好几分钟，同步等的话浏览器先超时）；登录这一步要把 GitHub 给的一次性配对
码原样交到页面上（人得照着它在 github.com 上敲）。这里锁的就是这两条。
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.server.routes import settings as settings_routes
from frago.server.services.gh_install_service import GhInstallService
from frago.server.services.github_service import GitHubService


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api")
    return TestClient(app)


class TestInstallPlan:
    def test_says_which_route_this_machine_gets(self, client):
        plan = {
            "method": "brew",
            "command": "brew install gh",
            "needs_path_hint": False,
            "manual_url": "https://cli.github.com/",
        }
        with patch.object(settings_routes, "detect_install_plan", return_value=plan):
            body = client.get("/api/settings/gh-cli/install-plan").json()

        assert body == plan


class TestInstallLifecycle:
    def test_start_returns_immediately_rather_than_waiting_out_the_install(self, client):
        """A brew install runs for minutes; the request must not hold that long."""
        with patch.object(
            GhInstallService,
            "start",
            return_value={"status": "ok", "already_running": False, "method": "brew"},
        ) as started:
            body = client.post("/api/settings/gh-cli/install").json()

        started.assert_called_once()
        assert body["status"] == "ok"
        assert body["already_running"] is False
        assert body["method"] == "brew"

    def test_a_second_press_does_not_start_a_second_install(self, client):
        with patch.object(
            GhInstallService,
            "start",
            return_value={"status": "ok", "already_running": True, "method": "brew"},
        ):
            body = client.post("/api/settings/gh-cli/install").json()

        assert body["already_running"] is True

    def test_status_carries_the_output_the_page_shows(self, client):
        status = {
            "status": "running",
            "method": "brew",
            "message": "Running brew install",
            "error": None,
            "log": ["$ brew install gh", "==> Downloading"],
            "path_hint": None,
        }
        with patch.object(GhInstallService, "get_status", return_value=status):
            body = client.get("/api/settings/gh-cli/install/status").json()

        assert body["status"] == "running"
        assert body["log"] == ["$ brew install gh", "==> Downloading"]

    def test_archive_install_hands_back_the_path_line(self, client):
        """That copy is off PATH, so the user needs the line to fix it."""
        status = {
            "status": "success",
            "method": "binary",
            "message": "GitHub CLI 2.63.2",
            "error": None,
            "log": [],
            "path_hint": 'echo \'export PATH="/home/u/.frago/tools/gh/bin:$PATH"\' >> ~/.zshrc',
        }
        with patch.object(GhInstallService, "get_status", return_value=status):
            body = client.get("/api/settings/gh-cli/install/status").json()

        assert ".frago/tools/gh/bin" in body["path_hint"]


class TestDeviceLogin:
    def test_the_pairing_code_reaches_the_page(self, client):
        """Without the code on screen there is nothing for the user to type."""
        with patch.object(
            GitHubService,
            "auth_login_web",
            return_value={
                "status": "ok",
                "code": "2741-EE59",
                "url": "https://github.com/login/device",
            },
        ):
            body = client.post("/api/settings/gh-cli/login/web").json()

        assert body["status"] == "ok"
        assert body["code"] == "2741-EE59"
        assert body["url"] == "https://github.com/login/device"

    def test_a_failure_to_start_says_why(self, client):
        with patch.object(
            GitHubService,
            "auth_login_web",
            return_value={"status": "error", "error": "gh CLI not found."},
        ):
            body = client.post("/api/settings/gh-cli/login/web").json()

        assert body["status"] == "error"
        assert "gh CLI not found." in body["error"]

    def test_polling_reports_who_logged_in(self, client):
        with patch.object(
            GitHubService,
            "check_auth_login_complete",
            return_value={
                "status": "ok",
                "completed": True,
                "authenticated": True,
                "username": "octocat",
            },
        ):
            body = client.get("/api/settings/gh-cli/login/web/status").json()

        assert body["authenticated"] is True
        assert body["username"] == "octocat"

    def test_polling_while_the_user_is_still_on_github(self, client):
        with patch.object(
            GitHubService,
            "check_auth_login_complete",
            return_value={
                "status": "ok",
                "completed": False,
                "authenticated": False,
                "username": None,
            },
        ):
            body = client.get("/api/settings/gh-cli/login/web/status").json()

        assert body["completed"] is False
        assert body["authenticated"] is False

    def test_cancel_stops_the_waiting_subprocess(self, client):
        """Left alone, gh polls GitHub until the code expires."""
        with patch.object(GitHubService, "cancel_auth_login") as cancelled:
            body = client.post("/api/settings/gh-cli/login/web/cancel").json()

        cancelled.assert_called_once()
        assert body["status"] == "ok"
