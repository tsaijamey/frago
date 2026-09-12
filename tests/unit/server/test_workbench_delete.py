"""删除会话这条通道：动了哪些东西、什么时候拒绝、拒绝之后还剩什么。

盯的是六件会让人误判的事：

1. Claude Code 删的是它自己那份原始记录——JSONL 与会话目录都要走；少删一样，这场改天
   要么还留在清单里，要么在盘上留下没人再读的附属文件；
2. opencode 与 codex **不由我们删**，借的是引擎自己的删除命令；路走错的样子是留下
   引擎那边看不见的残渣，界面上却显示删干净了；
3. 正在跑的会话一律不删：那具壳会把记录接着写到新写出来的同名文件里，人会以为删除
   没生效；
4. 本机已经没有这场会话时回 404 而不是 500——要的结果已经成立，把人引到"失败"上是错的；
5. 引擎拒绝动手时回 500，并把它自己的那句话带出来，NEVER 翻译成我们的说法；
6. 删成之后，分组、置顶里那个编号、以及 frago 这边指着它的身份映射都要摘掉。摘不干净
   要说出来，但**不许把已经删掉的说成没删掉**。

一条铁律：**用例 NEVER 碰真人的东西**——不碰 ``~/.claude/projects``，不碰 ``~/.frago``
下那几份名单与映射，也 NEVER 真的去起一个 opencode / codex 进程。凡是跑外部命令的用例，
跑的替身是 ``sys.executable``。
"""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from frago.server.services import tmux_sessions_service as tsvc
from frago.server.services import workbench_groups as groups
from frago.server.services import workbench_pins as pins
from frago.session import codex_store, engine_cli, opencode_store, record_reader
from frago.session.adapters import claude_code_records

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"
CX_SID = "01a01a98-82e9-7013-b24e-e5e91b03995a"
CC_SID2 = "11b13080-8fc5-6d81-a5bf-978d9392f407"
PROJECT = "-Users-frago-Repos-frago"


@pytest.fixture(autouse=True)
def frago_files(tmp_path, monkeypatch):
    """名单与身份映射一律落临时目录，用例 NEVER 碰真人的 ``~/.frago``。

    映射文件必须一起换掉：删一场引擎侧的会话会顺手摘掉指向它的映射，漏了这一步，
    用例就会去改真人 ``codex-sessions.json`` 里的条目。
    """
    home = tmp_path / ".frago"
    monkeypatch.setattr(groups, "GROUPS_FILE", home / "workbench_groups.json")
    monkeypatch.setattr(pins, "PINS_FILE", home / "workbench_pins.json")
    monkeypatch.setattr(codex_store, "BINDINGS_PATH", home / "codex-sessions.json")
    monkeypatch.setattr(opencode_store, "BINDINGS_PATH", home / "opencode-sessions.json")


@pytest.fixture
def claude_root(tmp_path, monkeypatch):
    """记录根目录换成临时目录。

    只换根目录，删的实现仍是真跑一遍——把整条路都换成替身的话，这个用例就只是在测
    自己写的替身。
    """
    root = tmp_path / "projects"
    root.mkdir()
    real = claude_code_records.delete_session_files
    monkeypatch.setattr(
        claude_code_records, "delete_session_files", lambda sid, _root=None: real(sid, root)
    )
    return root


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def seed_session(root, sid=CC_SID, project=PROJECT):
    """在临时记录根里造一场会话：JSONL 与它的会话目录各一份。"""
    project_dir = root / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{sid}.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    session_dir = project_dir / sid
    session_dir.mkdir(exist_ok=True)
    (session_dir / "custom-title.json").write_text("{}", encoding="utf-8")
    return project_dir


class TestEngineCli:
    """借引擎命令那条路本身。

    跑的都是替身命令，**一个真引擎都没起**。替身一律用 ``sys.executable`` 而不是
    ``/bin/sh`` / ``/bin/echo``：这个仓库的测试在 Windows 上也要跑，而那儿没有
    ``/bin``。
    """

    def test_把命令的话原样收回来(self, monkeypatch):
        monkeypatch.setattr(engine_cli, "find_agent_cli", lambda _a: sys.executable)

        result = engine_cli.run_engine_command("opencode", ["-c", f"print({OC_SID!r})"])

        # 参数原样传下去（替身把它印了出来），它的话原样收回来。
        assert result.argv[-1] == f"print({OC_SID!r})"
        assert result.output == OC_SID

    def test_非零退出抛出来并带上它自己的话(self, monkeypatch):
        monkeypatch.setattr(engine_cli, "find_agent_cli", lambda _a: sys.executable)

        script = "import sys; sys.stderr.write('No active session found\\n'); sys.exit(1)"
        with pytest.raises(engine_cli.EngineCliFailed) as err:
            engine_cli.run_engine_command("codex", ["-c", script])

        # 拒绝的理由只有引擎知道，NEVER 由我们转述。
        assert "No active session found" in str(err.value)
        assert "No active session found" in err.value.output

    def test_颜色码剥掉(self, monkeypatch):
        monkeypatch.setattr(engine_cli, "find_agent_cli", lambda _a: sys.executable)

        result = engine_cli.run_engine_command(
            "opencode", ["-c", r"print('\033[91mError: \033[0mboom')"]
        )

        assert result.output == "Error: boom"

    def test_找不到命令是另一回事(self, monkeypatch):
        """没装这个引擎与引擎拒绝了这次删除，人要做的事完全不同，NEVER 合并。"""
        monkeypatch.setattr(engine_cli, "find_agent_cli", lambda _a: None)

        with pytest.raises(engine_cli.EngineCliMissing):
            engine_cli.run_engine_command("codex", ["delete", CX_SID])


class TestDeleteFiles:
    def test_记录文件与会话目录一起删(self, claude_root):
        project_dir = seed_session(claude_root)

        removed = claude_code_records.delete_session_files(CC_SID, claude_root)

        assert removed is not None
        assert not (project_dir / f"{CC_SID}.jsonl").exists()
        assert not (project_dir / CC_SID).exists()
        assert removed.directory_removed is True
        assert removed.freed_bytes > 0
        assert removed.problems == []

    def test_没有会话目录时文件照样删掉(self, claude_root):
        project_dir = claude_root / PROJECT
        project_dir.mkdir(parents=True)
        (project_dir / f"{CC_SID}.jsonl").write_text("{}\n", encoding="utf-8")

        removed = claude_code_records.delete_session_files(CC_SID, claude_root)

        assert removed is not None and removed.directory_removed is False
        assert removed.problems == []
        assert not (project_dir / f"{CC_SID}.jsonl").exists()

    def test_只删这一场_同目录下别人的一个都不动(self, claude_root):
        project_dir = seed_session(claude_root)
        seed_session(claude_root, sid=CC_SID2)

        claude_code_records.delete_session_files(CC_SID, claude_root)

        assert (project_dir / f"{CC_SID2}.jsonl").exists()
        assert (project_dir / CC_SID2).is_dir()
        # 项目目录本身要留着：它装着同一个工作目录下的其余会话。
        assert project_dir.is_dir()

    def test_本机已经没有这场时返回_None(self, claude_root):
        """删不动与本来就没了是两回事，由调用方各说各话，这里只回 None。"""
        assert claude_code_records.delete_session_files(CC_SID, claude_root) is None


class TestDeleteSession:
    def test_不认识的编号照旧抛(self):
        with pytest.raises(record_reader.UnknownSessionFamily):
            record_reader.delete_session("不像任何一家")

    def test_claude_code_那条路不起进程(self, claude_root, monkeypatch):
        """它的记录就是一个文件加一个目录，没有理由为它开一个进程。"""
        seed_session(claude_root)

        def boom(*_a, **_k):
            raise AssertionError("Claude Code 不该走引擎命令那条路")

        monkeypatch.setattr(engine_cli, "run_engine_command", boom)

        removed = record_reader.delete_session(CC_SID)

        assert removed.family == "claude-code"
        assert any("原始记录" in line for line in removed.removed)

    def test_opencode_借它的命令删_并摘掉指着它的映射(self, monkeypatch):
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: True)
        monkeypatch.setattr(opencode_store, "delete_session", lambda sid: f"deleted {sid}")
        opencode_store.put_binding("frago-1", OC_SID, "/tmp/x")

        removed = record_reader.delete_session(OC_SID)

        assert removed.family == "opencode"
        assert removed.removed == [f"deleted {OC_SID}"]
        assert removed.problems == []
        # 引擎侧那一场没了，frago 这边指着它的那条映射就不该再留着。
        assert opencode_store.get_binding("frago-1") is None

    def test_codex_同上(self, monkeypatch, tmp_path):
        rollout = tmp_path / "rollout-x.jsonl"
        monkeypatch.setattr(codex_store, "find_rollout", lambda _sid: rollout)
        monkeypatch.setattr(codex_store, "delete_session", lambda sid: f"deleted {sid}")
        codex_store.put_binding("frago-1", CX_SID, "/tmp/x")

        removed = record_reader.delete_session(CX_SID)

        assert removed.family == "codex"
        assert removed.removed == [f"deleted {CX_SID}"]
        assert codex_store.get_binding("frago-1") is None

    def test_映射摘不干净不算整件事失败但要说出来(self, monkeypatch):
        """要的结果（清单里不再有它）已经达成，NEVER 把做成的事说成没做成。"""
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: True)
        monkeypatch.setattr(opencode_store, "delete_session", lambda _sid: "deleted")

        def boom(_sid):
            raise OSError("盘写不进去")

        monkeypatch.setattr(opencode_store, "drop_bindings_pointing_at", boom)

        removed = record_reader.delete_session(OC_SID)

        assert any("映射" in line for line in removed.problems)

    def test_opencode_库里没有这场就照实说(self, monkeypatch):
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: False)

        with pytest.raises(record_reader.SessionFilesMissing):
            record_reader.delete_session(OC_SID)

    def test_claude_code_找不到了也照实说(self, monkeypatch):
        monkeypatch.setattr(
            claude_code_records, "delete_session_files", lambda sid, root=None: None
        )
        with pytest.raises(record_reader.SessionFilesMissing):
            record_reader.delete_session(CC_SID)


class TestRoutes:
    @pytest.fixture(autouse=True)
    def no_tmux(self, monkeypatch):
        """不碰真 tmux：这一场默认没在跑，各用例按需改成有。"""
        monkeypatch.setattr(tsvc, "find_for_session", lambda sid: None)

    def test_删成之后分组与置顶里都没有它了(self, client, claude_root):
        seed_session(claude_root)
        state = groups.create_tag("甲")
        groups.assign(CC_SID, state["tags"][0]["id"])
        pins.pin(CC_SID)

        body = client.delete(f"/api/workbench/sessions/{CC_SID}").json()

        assert body["sid"] == CC_SID
        assert body["family"] == "claude-code"
        assert any("原始记录" in line for line in body["removed"])
        assert body["warnings"] == []
        assert groups.load()["sessions"][state["tags"][0]["id"]] == []
        assert pins.list_pins() == []

    def test_标签本身不被删掉_只摘掉那个编号(self, client, claude_root):
        seed_session(claude_root)
        state = groups.create_tag("甲")
        tag = state["tags"][0]["id"]
        groups.assign(CC_SID, tag)
        groups.assign(CC_SID2, tag)

        client.delete(f"/api/workbench/sessions/{CC_SID}")

        assert groups.load()["sessions"][tag] == [CC_SID2]

    def test_在跑的会话不删_回_409(self, client, claude_root, monkeypatch):
        project_dir = seed_session(claude_root)
        alive = tsvc.TmuxSessionLink(
            name=f"frago-agent-{CC_SID}", label=CC_SID, busy=False, managed=True, memory_mb=310
        )
        monkeypatch.setattr(tsvc, "find_for_session", lambda sid: alive)

        response = client.delete(f"/api/workbench/sessions/{CC_SID}")

        assert response.status_code == 409
        assert "先结束运行" in response.json()["detail"]
        # 拒绝就是真的什么都没动。
        assert (project_dir / f"{CC_SID}.jsonl").exists()
        assert (project_dir / CC_SID).is_dir()

    def test_opencode_的会话也删得掉(self, client, monkeypatch):
        """三家都能删：这条路以前回 400，现在要真的走通。"""
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: True)
        monkeypatch.setattr(opencode_store, "delete_session", lambda sid: f"deleted {sid}")

        response = client.delete(f"/api/workbench/sessions/{OC_SID}")

        assert response.status_code == 200
        assert response.json()["family"] == "opencode"

    def test_codex_的会话也删得掉(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(codex_store, "find_rollout", lambda _sid: tmp_path / "r.jsonl")
        monkeypatch.setattr(codex_store, "delete_session", lambda sid: f"deleted {sid}")

        response = client.delete(f"/api/workbench/sessions/{CX_SID}")

        assert response.status_code == 200
        assert response.json()["family"] == "codex"

    def test_引擎拒绝时回_500_并带上它的话(self, client, monkeypatch):
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: True)

        def refuse(_sid):
            raise engine_cli.EngineCliFailed("opencode 没删掉：Session not found")

        monkeypatch.setattr(opencode_store, "delete_session", refuse)

        response = client.delete(f"/api/workbench/sessions/{OC_SID}")

        assert response.status_code == 500
        assert "Session not found" in response.json()["detail"]

    def test_没装那个引擎时回_500_说清是没装(self, client, monkeypatch):
        monkeypatch.setattr(opencode_store, "session_exists", lambda _sid: True)

        def missing(_sid):
            raise engine_cli.EngineCliMissing("这台机器上找不到 opencode 命令，删不了它的会话")

        monkeypatch.setattr(opencode_store, "delete_session", missing)

        response = client.delete(f"/api/workbench/sessions/{OC_SID}")

        assert response.status_code == 500
        assert "找不到 opencode 命令" in response.json()["detail"]

    def test_不认识的编号回_404(self, client):
        assert client.delete("/api/workbench/sessions/不像任何一家").status_code == 404

    def test_本机已经没有这场时回_404_而不是_500(self, client, claude_root):
        """要的结果已经成立，把人引到"失败"上是错的。"""
        assert client.delete(f"/api/workbench/sessions/{CC_SID}").status_code == 404

    def test_分组摘不干净时照样算删成了并说出来(self, client, claude_root, monkeypatch):
        seed_session(claude_root)

        def boom(sid):
            raise OSError("盘写不进去")

        monkeypatch.setattr(groups, "remove_session", boom)

        body = client.delete(f"/api/workbench/sessions/{CC_SID}").json()

        assert body["sid"] == CC_SID
        assert any("分组" in w for w in body["warnings"])
