"""会话出身判定的用例：这场是人开的还是 frago 派的 worker，以及谁派的。

盯四件事：编号形状认得出派生编号、起 worker 那一刻记的账认得出父子、旧会话记录里的
启动回显捞得回父子、以及**认不出来一律算人开的**——最后这条是这套判据的安全边，
判错方向的代价不对称：多显示几场 worker 只是碍眼，把人自己谈了半天的会话折进 worker
堆里，人会以为它没了。
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid

import pytest

from frago.agent_driver.drivers.claude import claude_session_uuid
from frago.session import session_origin

# 人自己开的会话：claude 自己分配的编号，第 4 版。
HUMAN_SID = "7f55e46e-0cc5-4e80-8f4f-1debd649d7b0"
# frago 那一侧的编号，worker 的 claude 编号由它派生。
FRAGO_SID = "d5813c9e-ee2f-48ae-9bb3-f3002134ff2b"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """把账本与扫描缓存挪到临时目录，用例之间互不干扰。"""
    monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
    monkeypatch.setattr(session_origin, "PARENT_SCAN_CACHE", tmp_path / "agent-parent-scan.json")
    return tmp_path


@pytest.fixture
def empty_projects(tmp_path):
    """一个空的会话库：不想让扫描那一条掺进来的用例用它。"""
    root = tmp_path / "projects"
    root.mkdir()
    return root


def _index(projects_root):
    return session_origin.load_origin_index(projects_root=projects_root, use_memo=False)


class TestWorkerShape:
    """判据三：编号形状。"""

    def test_派生出来的编号是第五版(self):
        assert session_origin.is_worker_shape(claude_session_uuid(FRAGO_SID))

    def test_claude自己分配的编号不是(self):
        assert not session_origin.is_worker_shape(HUMAN_SID)

    def test_不是uuid的编号一律不是(self):
        # opencode 的编号带 ses_ 前缀，形状上根本不是 UUID。判不出来要安静走掉，
        # 抛异常会让整份清单取不出来。
        assert not session_origin.is_worker_shape("ses_058288655ffeYMxYC1AZKCcv56")
        assert not session_origin.is_worker_shape("")


class TestLedger:
    """判据一：起 worker 那一刻记的账。"""

    def test_记下的子会话认得出父亲(self, ledger, empty_projects):
        session_origin.record_launch(
            child_session_id="child-1",
            parent_session_id=HUMAN_SID,
            agent_type="claude",
            cwd="/tmp",
            prompt_head="去把 A 做了",
        )
        index = _index(empty_projects)
        assert index.parent_of("child-1") == HUMAN_SID
        assert index.origin_of("child-1") == "worker"

    def test_没有父亲也算worker(self, ledger, empty_projects):
        # 服务端常驻会话、定时任务派的活都没有上级会话可指。它们仍是 frago 起的，
        # 只是没地方可挂。
        session_origin.record_launch(
            child_session_id="child-2",
            parent_session_id=None,
            agent_type="claude",
            cwd="/tmp",
        )
        index = _index(empty_projects)
        assert index.origin_of("child-2") == "worker"
        assert index.parent_of("child-2") is None

    def test_自己不能是自己的父亲(self, ledger, empty_projects):
        session_origin.record_launch(
            child_session_id="child-3",
            parent_session_id="child-3",
            agent_type="claude",
            cwd="/tmp",
        )
        assert _index(empty_projects).parent_of("child-3") is None

    def test_账本写坏了不影响判定(self, ledger, empty_projects):
        session_origin.LAUNCH_LEDGER.write_text("{ 这不是 JSON", encoding="utf-8")
        index = _index(empty_projects)
        assert index.origin_of(HUMAN_SID) == "human"

    def test_账本只留最近那些(self, ledger, empty_projects, monkeypatch):
        monkeypatch.setattr(session_origin, "LEDGER_LIMIT", 3)
        for i in range(5):
            session_origin.record_launch(
                child_session_id=f"child-{i}",
                parent_session_id=HUMAN_SID,
                agent_type="claude",
                cwd="/tmp",
            )
        entries = json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8"))
        assert [e["child"] for e in entries] == ["child-2", "child-3", "child-4"]


class TestOriginFallback:
    """判不出来的时候站哪一边。"""

    def test_一无所知时算人开的(self, ledger, empty_projects):
        assert _index(empty_projects).origin_of(HUMAN_SID) == "human"

    def test_只凭形状也认得出worker(self, ledger, empty_projects):
        # 账本里没有这一条（账本上线之前起的那些会话都是这样），仍要认出来。
        derived = claude_session_uuid("some-old-frago-session")
        assert _index(empty_projects).origin_of(derived) == "worker"


@pytest.mark.skipif(shutil.which("rg") is None, reason="没装 ripgrep，这条路本来就走不了")
class TestRetroactiveScan:
    """判据二：从旧会话记录里的启动回显捞父子关系。"""

    def test_从启动回显里认出父子(self, ledger, tmp_path):
        root = tmp_path / "projects"
        proj = root / "-Users-frago-Repos-frago"
        proj.mkdir(parents=True)
        # 主会话的记录里躺着那条命令回显：worker 是在这场会话里派出去的。
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": f"[OK] tmux driver: agent=claude session={FRAGO_SID}"},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        child = claude_session_uuid(FRAGO_SID)
        index = _index(root)
        assert index.parent_of(child) == HUMAN_SID
        assert index.origin_of(child) == "worker"

    def test_常驻会话从起会话命令里认出来(self, ledger, tmp_path):
        # 常驻那条路（frago agent start --name w1）不打编号回显，只回一个名字，
        # 编号是从名字推出来的。只认回显的话，这一整批 worker 会一个都挂不上。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            "frago agent start claude --name w1\n", encoding="utf-8"
        )
        assert _index(root).parent_of(claude_session_uuid("w1")) == HUMAN_SID

    def test_常驻会话从驱动命令里认出来(self, ledger, tmp_path):
        # 起会话那条常写成 shell 循环（--name $n），名字在变量里捕获不到；
        # 而驱动命令里的名字是字面量，这一条因此不能少。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            'frago agent send w3 "读取任务书"\n', encoding="utf-8"
        )
        assert _index(root).parent_of(claude_session_uuid("w3")) == HUMAN_SID

    def test_选项不会被当成会话名(self, ledger, tmp_path):
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            "frago agent send --help\nfrago agent start --help\n", encoding="utf-8"
        )
        assert _index(root).parents == {}

    def test_同名归时刻最贴近的那场(self, ledger, tmp_path):
        # 会话名是全局的，谁都可以叫 w1。判据是「哪场主会话离这个 worker 的活动时刻最近」，
        # 取「最近活动的那场」会把一个上周干完活的 worker 判给今天碰巧同名的会话。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        old_parent = HUMAN_SID
        new_parent = "11111111-2222-4333-8444-555555555555"
        child = claude_session_uuid("w1")
        for sid in (old_parent, new_parent):
            (proj / f"{sid}.jsonl").write_text("frago agent send w1 x\n", encoding="utf-8")
        (proj / f"{child}.jsonl").write_text("{}\n", encoding="utf-8")
        # 时刻：worker 与旧主会话同一天，新主会话晚了一周。
        base = 1_757_000_000
        os.utime(proj / f"{child}.jsonl", (base, base))
        os.utime(proj / f"{old_parent}.jsonl", (base + 600, base + 600))
        os.utime(proj / f"{new_parent}.jsonl", (base + 7 * 86400, base + 7 * 86400))
        assert _index(root).parent_of(child) == old_parent

    def test_隔几分钟只补扫动过的那几个(self, ledger, tmp_path, monkeypatch):
        # 关系不能落后太多：人一直在用、会话一直在新建。所以缓存稍旧时走增量——
        # 只扫上次之后动过的那几个文件，把新认到的并进已有的那份，而不是整库重扫。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        # 缓存里躺着一条老关系，它的主会话记录早已不在库里——整库重扫绝对认不回它。
        session_origin.PARENT_SCAN_CACHE.write_text(
            json.dumps({"at": int(time.time()) - 600, "pairs": {"老 worker": "老主会话"}}),
            encoding="utf-8",
        )
        # 新出现的一场主会话，刚刚派了活。
        (proj / f"{HUMAN_SID}.jsonl").write_text("frago agent send w9 x\n", encoding="utf-8")
        index = _index(root)
        assert index.parent_of(claude_session_uuid("w9")) == HUMAN_SID  # 新的认到了
        assert index.parent_of("老 worker") == "老主会话"  # 老的没被冲掉

    def test_缓存还新鲜时一个文件都不扫(self, ledger, tmp_path, monkeypatch):
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        (proj / f"{HUMAN_SID}.jsonl").write_text("frago agent send w9 x\n", encoding="utf-8")
        session_origin.PARENT_SCAN_CACHE.write_text(
            json.dumps({"at": int(time.time()), "pairs": {}}), encoding="utf-8"
        )
        monkeypatch.setattr(
            session_origin,
            "_run_rg",
            lambda *a, **k: pytest.fail("缓存还新鲜的时候不该再去扫盘"),
        )
        assert _index(root).parents == {}

    def test_扫过一遍就存下来(self, ledger, tmp_path):
        root = tmp_path / "projects"
        root.mkdir()
        _index(root)
        cached = json.loads(session_origin.PARENT_SCAN_CACHE.read_text(encoding="utf-8"))
        assert "at" in cached and cached["pairs"] == {}

    def test_账本压过扫描结果(self, ledger, tmp_path):
        # 同一场会话两边都说了话时以账本为准：账本记的是当场看见的事实。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            f"tmux driver: agent=claude session={FRAGO_SID}\n", encoding="utf-8"
        )
        child = claude_session_uuid(FRAGO_SID)
        other = str(uuid.uuid4())
        session_origin.record_launch(
            child_session_id=child,
            parent_session_id=other,
            agent_type="claude",
            cwd="/tmp",
        )
        assert _index(root).parent_of(child) == other


class TestRelationKinds:
    """会话关系账：带种类记账、读老格式、出身按种类判（spec 20260928-webui-session-branch）。"""

    def test_老格式记录缺种类当派活(self, ledger, empty_projects):
        # 升级之前写下的记录没有 kind。每台机器上都躺着这种账，不做迁移也要读对。
        session_origin.LAUNCH_LEDGER.write_text(
            json.dumps(
                [
                    {
                        "child": "old-child",
                        "parent": HUMAN_SID,
                        "agent_type": "claude",
                        "cwd": "/tmp",
                        "prompt_head": "",
                        "at": 1,
                    }
                ]
            ),
            encoding="utf-8",
        )
        index = _index(empty_projects)
        assert index.origin_of("old-child") == "worker"
        assert index.parent_of("old-child") == HUMAN_SID
        assert index.relation_of("old-child") == session_origin.SessionRelation("dispatch")

    def test_派活显式写种类(self, ledger, empty_projects):
        session_origin.record_launch(
            child_session_id="child-d",
            parent_session_id=HUMAN_SID,
            agent_type="claude",
            cwd="/tmp",
        )
        entries = json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8"))
        assert entries[0]["kind"] == "dispatch"
        assert "anchor" not in entries[0]

    def test_分支算人开的但折到原会话下(self, ledger, empty_projects):
        # 分支是人亲自在谈的一场：算 worker 的话它等你时就不挂 For you 了。
        child = str(uuid.uuid4())
        assert session_origin.record_relation(
            kind="branch",
            child_session_id=child,
            parent_session_id=HUMAN_SID,
            agent_type="claude",
            cwd="/tmp",
            anchor={"record_id": "r1", "text": "那个报错", "occurrence": 0, "mark_id": "mk_1"},
            note="这个报错要不要查",
        )
        index = _index(empty_projects)
        assert index.origin_of(child) == "human"
        assert index.parent_of(child) == HUMAN_SID
        assert index.relation_of(child) == session_origin.SessionRelation("branch", closed=False)
        entry = session_origin.find_relation(child)
        assert entry["anchor"]["text"] == "那个报错"
        assert entry["note"] == "这个报错要不要查"
        assert entry["closed_at"] is None

    def test_交接认得但不折叠也不算worker(self, ledger, empty_projects):
        # 交接本次只在读取侧认得。它不进父子表：交接的两场是并排的，不是谁挂谁。
        child = str(uuid.uuid4())
        session_origin.LAUNCH_LEDGER.write_text(
            json.dumps([{"child": child, "parent": HUMAN_SID, "kind": "handoff"}]),
            encoding="utf-8",
        )
        index = _index(empty_projects)
        assert index.relation_of(child) == session_origin.SessionRelation("handoff")
        assert index.parent_of(child) is None
        assert index.origin_of(child) == "human"

    def test_读不懂的单条跳过_其余照读(self, ledger, empty_projects):
        session_origin.LAUNCH_LEDGER.write_text(
            json.dumps(
                [
                    "不是对象",
                    {"child": 42, "parent": HUMAN_SID},
                    {"child": "weird", "parent": HUMAN_SID, "kind": "adopt"},
                    {"child": "bad-parent", "parent": ["x"]},
                    {"child": "good", "parent": HUMAN_SID},
                ]
            ),
            encoding="utf-8",
        )
        index = _index(empty_projects)
        assert index.parents == {"good": HUMAN_SID}
        assert index.workers == frozenset({"good"})
        assert index.relation_of("weird") is None

    def test_没有父亲的派活也有关系种类(self, ledger, empty_projects):
        session_origin.record_launch(
            child_session_id="lonely", parent_session_id=None, agent_type="claude", cwd="/tmp"
        )
        assert _index(empty_projects).relation_of("lonely") == session_origin.SessionRelation(
            "dispatch"
        )

    def test_不认得的种类不记(self, ledger):
        assert not session_origin.record_relation(
            kind="adopt",  # type: ignore[arg-type]
            child_session_id="x",
            parent_session_id=None,
            agent_type="claude",
            cwd="/tmp",
        )
        assert not session_origin.LAUNCH_LEDGER.exists()

    def test_记完立刻看得见_不等进程内那份过期(self, ledger, empty_projects):
        session_origin.load_origin_index(projects_root=empty_projects)
        child = str(uuid.uuid4())
        session_origin.record_relation(
            kind="branch",
            child_session_id=child,
            parent_session_id=HUMAN_SID,
            agent_type="claude",
            cwd="/tmp",
        )
        index = session_origin.load_origin_index(projects_root=empty_projects)
        assert index.parent_of(child) == HUMAN_SID
        session_origin.clear_cache()


class TestCloseRelation:
    """收口写入：改的只有那一条分支，别的记录一字不动。"""

    def _branch(self, child, parent=HUMAN_SID):
        session_origin.record_relation(
            kind="branch",
            child_session_id=child,
            parent_session_id=parent,
            agent_type="claude",
            cwd="/tmp",
            note="旁支",
        )

    def test_收口写入不丢别的记录(self, ledger, empty_projects):
        # 老记录里带着这里不认得的字段，也要原样留着。
        session_origin.LAUNCH_LEDGER.write_text(
            json.dumps([{"child": "old", "parent": HUMAN_SID, "extra": "留着"}]),
            encoding="utf-8",
        )
        self._branch("b1")
        session_origin.record_launch(
            child_session_id="w1", parent_session_id=HUMAN_SID, agent_type="claude", cwd="/tmp"
        )
        before = json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8"))

        closed = session_origin.close_relation(
            child_session_id="b1", parent_session_id=HUMAN_SID, closed_by="manual"
        )
        assert closed is not None and closed["closed_by"] == "manual"

        after = json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8"))
        assert len(after) == len(before) == 3
        assert after[0] == before[0]
        assert after[2] == before[2]
        assert after[1]["closed_at"] is not None
        assert after[1]["closed_by"] == "manual"
        assert _index(empty_projects).relation_of("b1") == session_origin.SessionRelation(
            "branch", closed=True
        )

    def test_第一次收口才算数(self, ledger):
        self._branch("b2")
        first = session_origin.close_relation(
            child_session_id="b2", parent_session_id=HUMAN_SID, closed_by="bring-back"
        )
        again = session_origin.close_relation(
            child_session_id="b2", parent_session_id=HUMAN_SID, closed_by="manual"
        )
        assert again["closed_by"] == "bring-back"
        assert again["closed_at"] == first["closed_at"]

    def test_不是这个父会话的分支不收(self, ledger):
        self._branch("b3")
        assert (
            session_origin.close_relation(
                child_session_id="b3", parent_session_id="别的会话", closed_by="manual"
            )
            is None
        )

    def test_派活不能收口(self, ledger):
        session_origin.record_launch(
            child_session_id="w2", parent_session_id=HUMAN_SID, agent_type="claude", cwd="/tmp"
        )
        assert (
            session_origin.close_relation(
                child_session_id="w2", parent_session_id=HUMAN_SID, closed_by="manual"
            )
            is None
        )

    def test_写不进去要抛(self, ledger, monkeypatch):
        self._branch("b4")
        monkeypatch.setattr(session_origin, "_write_json", lambda *a, **k: False)
        with pytest.raises(OSError):
            session_origin.close_relation(
                child_session_id="b4", parent_session_id=HUMAN_SID, closed_by="manual"
            )
