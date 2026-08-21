"""数据仓库页面的接口契约。

这几条接口读的是主人整个工作目录，还能在他机器上起 agent。所以除了「返回值对不对」，
还要锁住两个边界：清单长度必须有上限（不然一次响应就是几 MB），备份模式只认两个值
（别的字符串会顺着 prompt 一路走到 agent 手里）。
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.server.routes import data_repo as routes


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


STATUS = {
    "configured": True,
    "repo_path": "/home/someone/.frago",
    "remote_url": "https://github.com/someone/frago-working-dir",
    "branch": "main",
    "ahead": 4,
    "behind": 0,
    "pending_total": 26062,
    "counts": {"modified": 351, "deleted": 23710, "untracked": 2001},
    "rollup": [{"area": "sessions/", "count": 23700}, {"area": "data/", "count": 1915}],
    "files": [{"path": "books/registry.json", "status": "modified"}],
    "truncated": True,
    "last_commit": {"sha": "4fddfa097", "subject": "chore(data): 上一次", "committed_at": "2026-08-20T23:49:52+08:00"},
    "error": None,
}


class TestStatus:
    def test_hands_back_totals_rollup_and_a_sample(self, client):
        with patch.object(routes, "get_status", return_value=STATUS):
            body = client.get("/api/data-repo/status").json()

        assert body["pending_total"] == 26062
        assert body["rollup"][0]["area"] == "sessions/"
        assert body["truncated"] is True
        assert body["files"][0]["path"] == "books/registry.json"

    def test_the_list_length_is_capped(self, client):
        """没有上限，一次请求就能把整份索引搬进浏览器。"""
        assert client.get("/api/data-repo/status?limit=99999").status_code == 422

    def test_zero_is_allowed_for_callers_that_only_want_the_numbers(self, client):
        captured = {}

        def fake(limit):
            captured["limit"] = limit
            return STATUS

        with patch.object(routes, "get_status", fake):
            assert client.get("/api/data-repo/status?limit=0").status_code == 200
        assert captured["limit"] == 0

    def test_an_uninitialized_repo_is_a_200_not_a_500(self, client):
        """还没建仓库是要在页面上解释的状态，不是要抛给用户的错误。"""
        blank = {**STATUS, "configured": False, "pending_total": 0, "rollup": [], "files": []}
        with patch.object(routes, "get_status", return_value=blank):
            response = client.get("/api/data-repo/status")

        assert response.status_code == 200
        assert response.json()["configured"] is False


class TestPolicy:
    def test_returns_both_halves(self, client):
        body = client.get("/api/data-repo/policy").json()
        assert body["excluded"] and body["included"]


class TestSyncStart:
    def test_launches_and_reports_the_task(self, client):
        with patch.object(
            routes.DataRepoSync,
            "start",
            return_value={
                "status": "ok",
                "already_running": False,
                "task": {"task_id": "t1", "session_id": "s1", "pid": 42, "mode": "all"},
            },
        ):
            body = client.post("/api/data-repo/sync", json={"mode": "all"}).json()

        assert body["status"] == "ok"
        assert body["task"]["session_id"] == "s1"

    def test_selective_carries_the_users_words_through(self, client):
        captured = {}

        def fake(mode, instruction):
            captured["mode"], captured["instruction"] = mode, instruction
            return {"status": "ok", "already_running": False, "task": None}

        with patch.object(routes.DataRepoSync, "start", fake):
            client.post(
                "/api/data-repo/sync",
                json={"mode": "selective", "instruction": "只传今天改的配方"},
            )

        assert captured["mode"] == "selective"
        assert captured["instruction"] == "只传今天改的配方"

    def test_an_unknown_mode_is_refused_at_the_door(self, client):
        """模式字符串会一路走进 agent 的任务书，不能什么都放行。"""
        assert client.post("/api/data-repo/sync", json={"mode": "everything"}).status_code == 422

    def test_a_second_press_reports_the_run_already_going(self, client):
        with patch.object(
            routes.DataRepoSync,
            "start",
            return_value={"status": "error", "already_running": True, "error": "已经有一次同步在跑了"},
        ):
            body = client.post("/api/data-repo/sync", json={"mode": "all"}).json()

        assert body["already_running"] is True
        assert body["status"] == "error"


class TestSyncStatusAndPrompt:
    def test_reports_whether_a_run_is_alive(self, client):
        with patch.object(
            routes.DataRepoSync,
            "get",
            return_value={"running": True, "task": {"task_id": "t1", "mode": "all"}},
        ):
            body = client.get("/api/data-repo/sync/status").json()

        assert body["running"] is True
        assert body["task"]["mode"] == "all"

    def test_the_brief_can_be_read_without_starting_anything(self, client):
        """要把整个工作目录交出去的人，有权先看清交出去的是什么指令。"""
        with patch.object(routes.DataRepoSync, "start") as started:
            body = client.get("/api/data-repo/sync/prompt?mode=all").json()

        started.assert_not_called()
        assert "分组提交" in body["prompt"]
