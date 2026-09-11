"""会话分组：存盘那一层、AI 分组那一趟、几条接口。

盯的是分组自己的承诺：一场只在一个组里、编号不与清单核对、删标签不动会话、AI 只动
还没分组的、AI 只建一轮标签、人搬过的以人为准。模型一律换成替身，用例 NEVER 真的去
拉起一场 agent 会话。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from frago.server.services import workbench_groups as groups

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CC_SID2 = "11b13080-8fc5-6d81-a5bf-978d9392f407"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"


@pytest.fixture(autouse=True)
def groups_file(tmp_path, monkeypatch):
    """分组落在临时目录，用例 NEVER 碰真人的 ``~/.frago/workbench_groups.json``。"""
    path = tmp_path / ".frago" / "workbench_groups.json"
    monkeypatch.setattr(groups, "GROUPS_FILE", path)
    monkeypatch.setattr(groups, "_JOB", groups.AiJob())
    return path


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


@dataclass
class Card:
    session_id: str
    title: str
    directory: str = "/Users/frago/Repos/frago"
    origin: str = "human"


def tag_id(state, name):
    return next(t["id"] for t in state["tags"] if t["name"] == name)


class TestStore:
    def test_一开始没有任何标签(self):
        assert groups.load() == {"tags": [], "sessions": {}, "ai_tags_created": False}

    def test_人建的标签记成人建的(self):
        state = groups.create_tag("会话页")
        assert [(t["name"], t["source"]) for t in state["tags"]] == [("会话页", "human")]

    def test_重名的标签不受理(self):
        groups.create_tag("K线配方")
        with pytest.raises(FileExistsError):
            groups.create_tag("k线配方")

    def test_空标签名与过长的标签名不受理(self):
        with pytest.raises(ValueError):
            groups.create_tag("   ")
        with pytest.raises(ValueError):
            groups.create_tag("长" * (groups.MAX_TAG_NAME + 1))

    def test_放进另一个组就是从原来那组搬走(self):
        """一场只在一个组里：挂两处的话左栏同一场摆两遍，人会以为是两场。"""
        groups.create_tag("甲")
        state = groups.create_tag("乙")
        a, b = tag_id(state, "甲"), tag_id(state, "乙")
        groups.assign(CC_SID, a)
        state = groups.assign(CC_SID, b)
        assert state["sessions"] == {a: [], b: [CC_SID]}

    def test_移出分组(self):
        state = groups.create_tag("甲")
        a = tag_id(state, "甲")
        groups.assign(CC_SID, a)
        assert groups.assign(CC_SID, None)["sessions"] == {a: []}

    def test_放进一个不存在的标签报错(self):
        with pytest.raises(KeyError):
            groups.assign(CC_SID, "tag_不存在")

    def test_删标签只删这件事_会话回到未分组(self):
        state = groups.create_tag("甲")
        a = tag_id(state, "甲")
        groups.assign(CC_SID, a)
        state = groups.delete_tag(a)
        assert state["tags"] == [] and state["sessions"] == {}

    def test_删一个本来就没有的标签不算失败(self):
        groups.create_tag("甲")
        assert len(groups.delete_tag("tag_没有")["tags"]) == 1

    def test_文件坏了当作没分过组而不是抛(self, groups_file):
        groups_file.parent.mkdir(parents=True, exist_ok=True)
        groups_file.write_text("{ 这不是 JSON", encoding="utf-8")
        assert groups.load()["tags"] == []

    def test_盘上同一场出现在两个组里时只留前一个(self, groups_file):
        groups_file.parent.mkdir(parents=True, exist_ok=True)
        groups_file.write_text(
            json.dumps(
                {
                    "tags": [{"id": "t1", "name": "甲"}, {"id": "t2", "name": "乙", "source": "ai"}],
                    "sessions": {"t1": [CC_SID], "t2": [CC_SID, OC_SID, None]},
                }
            ),
            encoding="utf-8",
        )
        state = groups.load()
        assert state["sessions"] == {"t1": [CC_SID], "t2": [OC_SID]}
        assert [t["source"] for t in state["tags"]] == ["human", "ai"]

    def test_落盘就是两部分外加一个开关(self, groups_file):
        state = groups.create_tag("甲")
        groups.assign(CC_SID, tag_id(state, "甲"))
        on_disk = json.loads(groups_file.read_text(encoding="utf-8"))
        assert set(on_disk) == {"tags", "sessions", "ai_tags_created"}


class TestCandidates:
    def test_只挑还没分组的人开的主会话(self):
        state = groups.create_tag("甲")
        groups.assign(CC_SID, tag_id(state, "甲"))
        cards = [
            Card(CC_SID, "已经分过组的"),
            Card(CC_SID2, "还没分组的"),
            Card(OC_SID, "派出去的 worker", origin="worker"),
        ]
        picked = groups.candidates(cards, groups.load())
        assert [c.session_id for c in picked] == [CC_SID2]

    def test_标题只剩会话编号的不交给模型(self):
        cards = [Card(CC_SID, CC_SID), Card(CC_SID2, ""), Card(OC_SID, "有内容的标题")]
        assert [c.session_id for c in groups.candidates(cards, groups.load())] == [OC_SID]


def fake_model(tags_reply, assign_reply):
    """替身模型：拟标签那一轮回 ``tags_reply``，归组那几轮回 ``assign_reply``。

    两步靠说明书的文件名区分——规矩在说明书里，问话里只有数据。
    """
    calls = []
    replies = {groups.TAGS_INSTRUCTIONS: tags_reply, groups.ASSIGN_INSTRUCTIONS: assign_reply}

    def ask(instructions, prompt):
        calls.append((instructions, prompt))
        return json.dumps(replies[instructions], ensure_ascii=False)

    ask.calls = calls
    return ask


def seed(groups_file, tags, sessions, ai_tags_created=True):
    """直接把一份分组写到盘上。``tags`` 是 ``[(编号, 名字, 谁建的)]``。"""
    groups_file.parent.mkdir(parents=True, exist_ok=True)
    groups_file.write_text(
        json.dumps(
            {
                "tags": [{"id": i, "name": n, "source": s} for i, n, s in tags],
                "sessions": sessions,
                "ai_tags_created": ai_tags_created,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def names(state=None):
    state = state or groups.load()
    return {t["name"]: state["sessions"][t["id"]] for t in state["tags"]}


class TestAiGrouping:
    def test_第一次先拟标签再归组(self):
        cards = [Card(CC_SID, "会话页左栏分页"), Card(CC_SID2, "K线看板配方")]
        ask = fake_model({"tags": ["会话页", "K线配方"]}, {"assign": {"1": "会话页", "2": "K线配方"}})
        groups.run_ai_grouping(cards, ask)
        state = groups.load()
        assert [(t["name"], t["source"]) for t in state["tags"]] == [("会话页", "ai"), ("K线配方", "ai")]
        assert state["sessions"][tag_id(state, "会话页")] == [CC_SID]
        assert state["ai_tags_created"] is True
        job = groups.job_state()
        assert job["assigned"] == 2 and job["created_tags"] == 2 and job["error"] is None

    def test_已经有人建的标签时不从零拟(self):
        """标签越少越好：已经有标签就在它们上面归组，不再另拟一整套。"""
        groups.create_tag("人建的")
        ask = fake_model({"tags": ["不该出现"]}, {"assign": {"1": "人建的"}})
        groups.run_ai_grouping([Card(CC_SID, "会话页左栏分页")], ask)
        assert list(names()) == ["人建的"]
        assert not any(i == groups.TAGS_INSTRUCTIONS for i, _ in ask.calls)

    def test_AI_只建一轮标签_人把它们删光也不再建(self):
        cards = [Card(CC_SID, "会话页左栏分页")]
        groups.run_ai_grouping(cards, fake_model({"tags": ["会话页"]}, {"assign": {"1": None}}))
        for tag in groups.load()["tags"]:
            groups.delete_tag(tag["id"])
        groups.create_tag("人建的")
        ask = fake_model({"tags": ["不该出现"]}, {"assign": {"1": "人建的"}})
        groups.run_ai_grouping(cards, ask)
        assert [t["name"] for t in groups.load()["tags"]] == ["人建的"]
        assert not any(i == groups.TAGS_INSTRUCTIONS for i, _ in ask.calls)

    def test_模型给的标签名对不上就不放_也不新建(self):
        groups.run_ai_grouping(
            [Card(CC_SID, "会话页左栏分页")],
            fake_model({"tags": ["会话页"]}, {"assign": {"1": "编出来的标签"}}),
        )
        state = groups.load()
        assert [t["name"] for t in state["tags"]] == ["会话页"]
        assert state["sessions"][tag_id(state, "会话页")] == []

    def test_判为不合适的留在未分组(self):
        groups.run_ai_grouping(
            [Card(CC_SID, "say ok")], fake_model({"tags": ["会话页"]}, {"assign": {"1": None}})
        )
        assert groups.load()["sessions"][tag_id(groups.load(), "会话页")] == []

    def test_AI_分完写盘前人已经搬走的以人为准(self, groups_file):
        seed(groups_file, [("t1", "会话页", "ai"), ("t2", "人挑的", "human")], {"t1": [], "t2": []})
        human_tag = "t2"

        def ask(instructions, prompt):
            # 模型在想的时候，人在页面上把这场放进了自己挑的组。
            groups.assign(CC_SID, human_tag)
            return json.dumps({"assign": {"1": "会话页"}}, ensure_ascii=False)

        groups.run_ai_grouping([Card(CC_SID, "会话页左栏分页")], ask)
        state = groups.load()
        assert state["sessions"][human_tag] == [CC_SID]
        assert state["sessions"][tag_id(state, "会话页")] == []

    def test_模型没跑成就报出来_不写任何东西(self):
        groups.run_ai_grouping([Card(CC_SID, "会话页左栏分页")], lambda instructions, prompt: None)
        job = groups.job_state()
        assert job["error"] and job["running"] is False
        assert groups.load() == {"tags": [], "sessions": {}, "ai_tags_created": False}

    def test_没问到时把原因报给人(self):
        def ask(instructions, prompt):
            raise groups.AskFailed("轻量 ai 超时没回来")

        groups.run_ai_grouping([Card(CC_SID, "会话页左栏分页")], ask)
        assert "轻量 ai 超时没回来" in groups.job_state()["error"]

    def test_没有要分的会话时不调模型(self):
        calls = []
        groups.run_ai_grouping(
            [Card(OC_SID, "worker", origin="worker")], lambda i, p: calls.append(p)
        )
        assert calls == [] and groups.job_state()["total"] == 0

    def test_分批交给模型(self, monkeypatch):
        monkeypatch.setattr(groups, "ASSIGN_BATCH", 2)
        cards = [Card(f"ses_{i:026d}", f"会话页第 {i} 场") for i in range(5)]
        ask = fake_model({"tags": ["会话页"]}, {"assign": {"1": "会话页", "2": "会话页"}})
        groups.run_ai_grouping(cards, ask)
        assert sum(i == groups.ASSIGN_INSTRUCTIONS for i, _ in ask.calls) == 3
        assert groups.job_state()["done"] == 5

    def test_问话里只有数据_标题和标签都在(self):
        cards = [Card(CC_SID, "会话页左栏分页", directory="/Users/frago/Repos/frago")]
        ask = fake_model({"tags": ["会话页"]}, {"assign": {"1": "会话页"}})
        groups.run_ai_grouping(cards, ask)
        (_, tags_prompt), (_, assign_prompt) = ask.calls
        assert "会话页左栏分页" in tags_prompt
        assert "- 会话页" in assign_prompt and "1. 会话页左栏分页 ｜ Repos/frago" in assign_prompt


class TestNewTagsWhileAssigning:
    """归组时尽量放进现有标签；新标签要过门槛才建。"""

    def test_同一批里够三场才新建(self, groups_file):
        seed(groups_file, [("t1", "联想工作", "human")], {"t1": []})
        cards = [Card(f"ses_{i:026d}", f"配音第 {i} 场") for i in range(3)]
        reply = {"assign": {"1": "配音", "2": "配音", "3": "配音"}, "new_tags": ["配音"]}
        groups.run_ai_grouping(cards, fake_model({}, reply))
        assert names()["配音"] == [c.session_id for c in cards]
        assert groups.job_state()["created_tags"] == 1

    def test_不够三场的新标签不建_那几场留在未分组(self, groups_file):
        seed(groups_file, [("t1", "联想工作", "human")], {"t1": []})
        cards = [Card(f"ses_{i:026d}", f"配音第 {i} 场") for i in range(3)]
        reply = {"assign": {"1": "配音", "2": "配音", "3": "联想工作"}, "new_tags": ["配音"]}
        groups.run_ai_grouping(cards, fake_model({}, reply))
        assert names() == {"联想工作": [cards[2].session_id]}

    def test_没写进_new_tags_的名字不算新建(self, groups_file):
        seed(groups_file, [("t1", "联想工作", "human")], {"t1": []})
        cards = [Card(f"ses_{i:026d}", f"配音第 {i} 场") for i in range(3)]
        reply = {"assign": {"1": "配音", "2": "配音", "3": "配音"}, "new_tags": []}
        groups.run_ai_grouping(cards, fake_model({}, reply))
        assert list(names()) == ["联想工作"]

    def test_前一批新建的标签后一批能用(self, groups_file, monkeypatch):
        monkeypatch.setattr(groups, "ASSIGN_BATCH", 3)
        seed(groups_file, [("t1", "联想工作", "human")], {"t1": []})
        cards = [Card(f"ses_{i:026d}", f"配音第 {i} 场") for i in range(4)]
        seen = []

        def ask(instructions, prompt):
            seen.append(prompt)
            if len(seen) == 1:
                return json.dumps(
                    {"assign": {"1": "配音", "2": "配音", "3": "配音"}, "new_tags": ["配音"]},
                    ensure_ascii=False,
                )
            return json.dumps({"assign": {"1": "配音"}}, ensure_ascii=False)

        groups.run_ai_grouping(cards, ask)
        assert "- 配音" in seen[1]
        assert len(names()["配音"]) == 4


FAKE_CORE = """#!/bin/sh
if [ "$1" = "--help" ]; then echo "{help}"; exit 0; fi
echo "$@" > "{dir}/argv.txt"
cat > "{dir}/stdin.txt"
printf '%s\\n' '{{"ok": true, "text": "{{\\"tags\\": [\\"甲\\"]}}", "model": "fake"}}'
"""


@pytest.fixture
def fake_core(tmp_path, monkeypatch):
    """一个假的 frago-core：记下收到的参数与问话，回一行约定形状的 JSON。"""
    from frago.init import hook_binary

    def make(help_text="frago-core ask --role <lightagent|observer>"):
        binary = tmp_path / "frago-core"
        binary.write_text(FAKE_CORE.format(help=help_text, dir=tmp_path), encoding="utf-8")
        binary.chmod(0o755)
        monkeypatch.setattr(hook_binary, "get_hook_binary_path", lambda: str(binary))
        monkeypatch.setattr(groups, "HOOK_DIR", tmp_path / "home" / ".frago" / "hook")
        groups._ask_support.clear()
        return tmp_path

    return make


class TestAskFragoCore:
    def test_走轻量_ai_那一格_说明书按文件名给(self, fake_core):
        where = fake_core()
        assert groups._ask_model(groups.TAGS_INSTRUCTIONS, "问话正文") == '{"tags": ["甲"]}'
        argv = (where / "argv.txt").read_text(encoding="utf-8").split()
        assert argv[:5] == ["ask", "--role", "lightagent", "--instructions", "group-tags.md"]
        assert (where / "stdin.txt").read_text(encoding="utf-8") == "问话正文"

    def test_说明书没铺到就先铺一份(self, fake_core):
        fake_core()
        groups._ask_model(groups.ASSIGN_INSTRUCTIONS, "问话")
        assert (groups.HOOK_DIR / "group-assign.md").exists()
        assert (groups.HOOK_DIR / "group-tags.md").exists()

    def test_没有_ask_入口的旧版一律不调(self, fake_core):
        """旧版会把不认识的参数当成提示词，起一个会动手的完整 agent。"""
        where = fake_core(help_text="frago-core [options]")
        with pytest.raises(groups.AskFailed):
            groups._ask_model(groups.TAGS_INSTRUCTIONS, "问话")
        assert not (where / "argv.txt").exists()


class TestRoutes:
    def test_没分过组时回一份空分组(self, client):
        body = client.get("/api/workbench/groups").json()
        assert body["tags"] == [] and body["sessions"] == {} and body["ai_job"]["running"] is False

    def test_建标签_放会话_删标签(self, client):
        state = client.post("/api/workbench/groups/tags", json={"name": "会话页"}).json()
        tid = state["tags"][0]["id"]
        state = client.put(f"/api/workbench/groups/sessions/{CC_SID}", json={"tag_id": tid}).json()
        assert state["sessions"][tid] == [CC_SID]
        state = client.delete(f"/api/workbench/groups/tags/{tid}").json()
        assert state["tags"] == []

    def test_重名标签回_409(self, client):
        client.post("/api/workbench/groups/tags", json={"name": "会话页"})
        assert client.post("/api/workbench/groups/tags", json={"name": "会话页"}).status_code == 409

    def test_放进不存在的标签回_404(self, client):
        response = client.put(f"/api/workbench/groups/sessions/{CC_SID}", json={"tag_id": "tag_没有"})
        assert response.status_code == 404

    def test_不像任何一家的编号放不进组(self, client):
        state = client.post("/api/workbench/groups/tags", json={"name": "会话页"}).json()
        tid = state["tags"][0]["id"]
        response = client.put("/api/workbench/groups/sessions/不像任何一家", json={"tag_id": tid})
        assert response.status_code == 404

    def test_启动_AI_分组立刻返回进度(self, client, monkeypatch):
        from frago.session import record_reader

        started = []
        monkeypatch.setattr(record_reader, "list_sessions", lambda: [])
        monkeypatch.setattr(
            groups, "start_ai_grouping", lambda cards: started.append(cards) or {"running": True}
        )
        body = client.post("/api/workbench/groups/ai").json()
        assert body["ai_job"] == {"running": True} and started == [[]]
