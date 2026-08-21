"""发送这条通道：三家的会话都发得出去，且各回各家。

这份用例盯的是一件事——**发给谁**。从前这条路背后写死了一个 claude，codex 与
opencode 的会话编号发过去不报错，claude 拿它当没见过的 ``--session-id`` 当场开一场
空白会话，原来那场一个字没动。所以这里的核心断言不是"返回 200"，而是"这一轮交给
哪个 driver、在哪个目录起"。

不碰真 tmux：会话池换成替身，只记下每轮收到的 (agent_type, cwd)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.server.services import session_send
from frago.session import claude_sessions as claude_svc
from frago.session import codex_store, opencode_store
from frago.session import transcript_completion as tc

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CODEX_SID = "01a01a98-82e9-7013-b24e-e5e91b03995a"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"


class StubRunner:
    """UiSessionRunner 替身：只记账，不起 tmux。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, session_id, text, *, agent_type=None, cwd=None, timeout_s=180.0):
        from frago.server.services.ui_session_runner import SessionActivation

        self.calls.append(
            {"sid": session_id, "text": text, "agent_type": agent_type, "cwd": cwd}
        )
        return SessionActivation(session_id=session_id, status="activating", text="收到")


@pytest.fixture
def runner(monkeypatch):
    stub = StubRunner()
    monkeypatch.setattr(
        "frago.server.services.ui_session_runner.get_runner", lambda: stub
    )
    return stub


@pytest.fixture
def three_families(monkeypatch, tmp_path):
    """把三家的档案换成可控的替身，家族判定仍走真实的 ``detect_family``。"""
    # codex：只有 CODEX_SID 那一场在 rollout 目录里，家族判定据此把它与 claude 分开。
    sessions_root = tmp_path / "codex-sessions"
    sessions_root.mkdir()
    rollout = tmp_path / f"rollout-2026-{CODEX_SID}.jsonl"
    rollout.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(codex_store, "sessions_root", lambda: sessions_root)
    monkeypatch.setattr(
        codex_store, "find_rollout", lambda sid: rollout if sid == CODEX_SID else None
    )
    monkeypatch.setattr(
        codex_store,
        "session_meta",
        lambda sid: codex_store.RolloutMeta(
            session_id=sid,
            path=rollout,
            cwd="/repos/codex-repo",
            started_at=None,
            mtime=0.0,
        )
        if sid == CODEX_SID
        else None,
    )
    # opencode：库里有这一场，跑在这个目录。
    monkeypatch.setattr(opencode_store, "session_exists", lambda sid: sid == OC_SID)
    monkeypatch.setattr(
        opencode_store,
        "session_directory",
        lambda sid: "/repos/opencode-repo" if sid == OC_SID else None,
    )
    # claude：CC_SID 的 jsonl 在，首条记录里记着 cwd。
    transcript = tmp_path / f"{CC_SID}.jsonl"
    transcript.write_text('{"cwd": "/repos/claude-repo"}\n', encoding="utf-8")
    monkeypatch.setattr(
        tc, "locate_transcript", lambda sid, **_: transcript if sid == CC_SID else None
    )
    return tmp_path


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestResolveTarget:
    """判家族与查目录：一处判完，谁都不再猜第二遍。"""

    def test_claude_session_keeps_the_cwd_from_its_transcript(self, three_families):
        target = session_send.resolve_target(CC_SID)
        assert (target.family, target.agent_type) == ("claude-code", "claude")
        assert target.cwd == "/repos/claude-repo"
        assert target.is_new is False

    def test_codex_session_goes_to_the_codex_driver(self, three_families):
        target = session_send.resolve_target(CODEX_SID)
        assert (target.family, target.agent_type) == ("codex", "codex")
        assert target.cwd == "/repos/codex-repo"

    def test_opencode_session_goes_to_the_opencode_driver(self, three_families):
        target = session_send.resolve_target(OC_SID)
        assert (target.family, target.agent_type) == ("opencode", "opencode")
        assert target.cwd == "/repos/opencode-repo"

    def test_brand_new_claude_id_takes_the_directory_the_page_picked(self, three_families):
        """页面新建会话时自己 mint 的编号：档案里还没有它，目录只能由页面给。"""
        fresh = "11111111-2222-4333-8444-555555555555"
        target = session_send.resolve_target(fresh, cwd_hint="/repos/new-one")
        assert target.is_new is True
        assert target.cwd == "/repos/new-one"

    def test_a_page_supplied_directory_never_overrides_the_recorded_one(self, three_families):
        """同一场会话换个目录续接，等于把 agent 挪进另一个仓库。档案里的目录说了算。"""
        target = session_send.resolve_target(CC_SID, cwd_hint="/somewhere/else")
        assert target.cwd == "/repos/claude-repo"

    def test_deleted_codex_session_is_refused_not_silently_restarted(
        self, three_families, monkeypatch
    ):
        """记录没了就明说续不上。驱动层遇到续不上的目标会自愈成裸起一场新的——
        那正是页面上最不该发生的事：人以为在跟原来那场说话。"""
        monkeypatch.setattr(codex_store, "session_meta", lambda _sid: None)
        with pytest.raises(session_send.SessionGone):
            session_send.resolve_target(CODEX_SID)

    def test_deleted_opencode_session_is_refused(self, three_families, monkeypatch):
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: False)
        with pytest.raises(session_send.SessionGone):
            session_send.resolve_target(OC_SID)

    def test_unknown_directory_is_refused(self, three_families, monkeypatch):
        """目录问不出来就不发：续接命令本身不带目录，猜一个等于换个仓库开工。"""
        monkeypatch.setattr(opencode_store, "session_directory", lambda _sid: None)
        with pytest.raises(session_send.SessionDirectoryUnknown):
            session_send.resolve_target(OC_SID)

    def test_every_family_has_a_driver(self):
        """少一家就等于那一家的会话在页面上发不出去。"""
        assert set(session_send.AGENT_TYPE_BY_FAMILY) == {
            "claude-code",
            "opencode",
            "codex",
        }


class TestSendRoute:
    def _send(self, client, sid, **body):
        return client.post(f"/api/workbench/sessions/{sid}/send", json={"text": "接着干", **body})

    def test_claude_session_is_driven_by_claude(self, client, runner, three_families):
        assert self._send(client, CC_SID).status_code == 200
        assert runner.calls[0]["agent_type"] == "claude"
        assert runner.calls[0]["cwd"] == "/repos/claude-repo"

    def test_codex_session_is_driven_by_codex(self, client, runner, three_families):
        assert self._send(client, CODEX_SID).status_code == 200
        assert runner.calls[0]["agent_type"] == "codex"
        assert runner.calls[0]["cwd"] == "/repos/codex-repo"

    def test_opencode_session_is_driven_by_opencode(self, client, runner, three_families):
        assert self._send(client, OC_SID).status_code == 200
        assert runner.calls[0]["agent_type"] == "opencode"
        assert runner.calls[0]["cwd"] == "/repos/opencode-repo"

    def test_activation_state_comes_back(self, client, runner, three_families):
        body = self._send(client, OC_SID).json()
        assert body["sid"] == OC_SID
        assert body["status"] == "activating"

    def test_images_reach_the_prompt_as_paths(self, client, runner, three_families):
        """tmux 注入端粘不了剪贴板图像，图片以落盘路径进提示词。"""
        one_px = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
            "C0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        response = client.post(
            f"/api/workbench/sessions/{OC_SID}/send",
            json={"text": "看这张", "images": [one_px]},
        )
        assert response.status_code == 200
        prompt = runner.calls[0]["text"]
        assert "看这张" in prompt
        path = prompt.strip().splitlines()[-1]
        assert Path(path).is_file()
        Path(path).unlink()

    def test_a_new_claude_session_is_registered_as_started_from_the_page(
        self, client, runner, three_families, monkeypatch
    ):
        """编号是页面 mint 的，claude 不给它派 slug，扫描那侧只能靠这次登记认出来。"""
        registered: list[str] = []
        monkeypatch.setattr(claude_svc, "register_webui_session", registered.append)
        fresh = "11111111-2222-4333-8444-555555555555"
        response = client.post(
            f"/api/workbench/sessions/{fresh}/send",
            json={"text": "开工", "cwd": "/repos/new-one"},
        )
        assert response.status_code == 200
        assert registered == [fresh]
        assert runner.calls[0]["cwd"] == "/repos/new-one"

    def test_nothing_to_say_is_refused(self, client, runner, three_families):
        response = client.post(f"/api/workbench/sessions/{OC_SID}/send", json={"text": "  "})
        assert response.status_code == 400
        assert runner.calls == []

    def test_unknown_id_shape_is_not_found(self, client, runner, three_families):
        response = self._send(client, "不像任何一家")
        assert response.status_code == 404
        assert runner.calls == []

    def test_a_session_whose_records_are_gone_is_a_conflict(
        self, client, runner, three_families, monkeypatch
    ):
        """409 而不是 500：这不是通道坏了，是那场会话已经不在了。"""
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: False)
        response = self._send(client, OC_SID)
        assert response.status_code == 409
        assert runner.calls == []

    def test_drive_failure_says_so(self, client, runner, three_families, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("tmux 没起来")

        monkeypatch.setattr(runner, "send", boom)
        response = self._send(client, OC_SID)
        assert response.status_code == 500
        assert "tmux 没起来" in response.json()["detail"]
