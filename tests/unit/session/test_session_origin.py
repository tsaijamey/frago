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
from datetime import UTC, datetime

import pytest

from frago.agent_driver.drivers.claude import claude_session_uuid
from frago.session import session_origin

# 人自己开的会话：claude 自己分配的编号，第 4 版。
HUMAN_SID = "7f55e46e-0cc5-4e80-8f4f-1debd649d7b0"
# frago 那一侧的编号，worker 的 claude 编号由它派生。
FRAGO_SID = "d5813c9e-ee2f-48ae-9bb3-f3002134ff2b"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """把账本与扫描缓存挪到临时目录，用例之间互不干扰。

    CoreAgent 那一侧的会话根也一并掐掉：单测不该去读本机真实的会话库，那里有多少条
    父子关系全看这台机器用过什么。要测那一侧的扫描时，用例自己把它换掉。
    """
    monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
    monkeypatch.setattr(session_origin, "PARENT_SCAN_CACHE", tmp_path / "agent-parent-scan.json")
    monkeypatch.setattr(session_origin, "_coreagent_scan_root", lambda: None)
    return tmp_path


@pytest.fixture
def empty_projects(tmp_path):
    """一个空的会话库：不想让扫描那一条掺进来的用例用它。"""
    root = tmp_path / "projects"
    root.mkdir()
    return root


def _index(projects_root):
    return session_origin.load_origin_index(projects_root=projects_root, use_memo=False)


# 时序判据靠文件系统的创建时刻。Linux 的 os.stat 不提供 st_birthtime，实现那边按设计
# 「判不了就放行」，所以断言「引用被剔除」的用例在这类机器上测不到东西。
_HAS_BIRTHTIME = hasattr(os.stat(__file__), "st_birthtime")


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

    def test_多进程同时派活不丢账(self, ledger, empty_projects):
        # 主会话在一行命令里用 `&` 并行起多个 `frago agent` 时，多个子进程会在同一毫秒
        # 各自跑「读账本 → 追加 → replace 写回」。只靠进程内 threading.Lock 会互相冲掉先写
        # 的那条，导致其中一个 worker 在左栏掉出父会话、散成顶层独立会话。
        import multiprocessing

        ctx = multiprocessing.get_context("spawn")
        ledger_path = str(session_origin.LAUNCH_LEDGER)
        barrier = ctx.Barrier(6)

        with ctx.Pool(
            6,
            initializer=_mp_init_worker,
            initargs=(barrier, ledger_path),
        ) as pool:
            pool.map(_mp_record_one, [f"core_worker_{i}" for i in range(6)])

        entries = json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8"))
        assert {e["child"] for e in entries} == {f"core_worker_{i}" for i in range(6)}
        index = _index(empty_projects)
        for i in range(6):
            assert index.parent_of(f"core_worker_{i}") == HUMAN_SID
            assert index.origin_of(f"core_worker_{i}") == "worker"


_MP_BARRIER = None
_MP_LEDGER_PATH = None


def _mp_init_worker(barrier, ledger_path: str) -> None:
    global _MP_BARRIER, _MP_LEDGER_PATH
    _MP_BARRIER = barrier
    _MP_LEDGER_PATH = ledger_path


def _mp_record_one(child_id: str) -> None:
    from pathlib import Path

    session_origin.LAUNCH_LEDGER = Path(_MP_LEDGER_PATH)
    _MP_BARRIER.wait(timeout=10)
    session_origin.record_launch(
        child_session_id=child_id,
        parent_session_id=HUMAN_SID,
        agent_type="coreagent",
        cwd="/tmp",
        prompt_head=f"# Worker Task: {child_id}",
    )


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

    def test_内核派活的回显里认出父子(self, ledger, tmp_path):
        # 内核后端（CoreAgent）派活打的是另一句回显，编号是 frago 现发的 core_ 前缀，
        # 落盘的就是它，不派生。只认 tmux 那一句的话，换了默认内核之后新增的这批
        # worker 一个都挂不上——它们全散在主干上。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        core_sid = "core_0123456789abcdef0123456789abcdef"
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            f"[OK] kernel driver: session={core_sid}\n", encoding="utf-8"
        )
        index = _index(root)
        assert index.parent_of(core_sid) == HUMAN_SID
        assert index.origin_of(core_sid) == "worker"

    def test_内核主会话派出的活也认(self, ledger, tmp_path, monkeypatch):
        # 主会话自己就是 CoreAgent 那场常驻会话时，它的记录落在另一处根下。只看
        # Claude Code 那一处的话，它派出去的 worker 会一个都挂不上。
        core_root = tmp_path / "coreagent"
        (core_root / "-p").mkdir(parents=True)
        core_parent = "core_fedcba9876543210fedcba9876543210"
        (core_root / "-p" / f"{core_parent}.jsonl").write_text(
            f"[OK] tmux driver: agent=claude session={FRAGO_SID}\n", encoding="utf-8"
        )
        monkeypatch.setattr(session_origin, "_coreagent_scan_root", lambda: core_root)
        empty = tmp_path / "projects"
        empty.mkdir()
        assert _index(empty).parent_of(claude_session_uuid(FRAGO_SID)) == core_parent

    def test_命令行不算证据(self, ledger, tmp_path):
        # 从前认两条命令行（frago agent start … --name w1、frago agent send w1），理由是常驻
        # 会话的名字常写在 shell 变量里。可命令行**可以被人原样引用**：一场会话读别人的记录、
        # 把排查用的命令抄进回复，下一趟扫描就把引用者当成了驱动者。2026-10-15 实测：我这场
        # 因为引用了 `frago agent send w1`，w1 / w3 / w9 / mywork 四场常驻会话全被挂到我名下。
        # 宁可少认几场常驻会话，也不要凭空多出几对父子。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            "frago agent start claude --name w1\n"
            'frago agent send w3 "读取任务书"\n'
            "frago agent peek w9\n",
            encoding="utf-8",
        )
        assert _index(root).parents == {}

    @pytest.mark.skipif(
        not _HAS_BIRTHTIME, reason="文件系统不记创建时刻，时序判据按设计放行"
    )
    def test_引用别人的回显不算证据(self, ledger, tmp_path):
        # 回显本身也会被引用：一场会话读别人的记录、把回显抄进回复，那句回显就落进了引用者
        # 的记录。区分它们看时序——被引用的那场 worker 早已收场，引用者还在写。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        child = claude_session_uuid(FRAGO_SID)
        (proj / f"{child}.jsonl").write_text("{}\n", encoding="utf-8")
        # 子会话九月八号收的场。
        old = datetime(2026, 9, 8, 13, 0, tzinfo=UTC).timestamp()
        os.utime(proj / f"{child}.jsonl", (old, old))
        # 引用者十月十五号才把这句话抄进自己的记录。
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-10-15T10:04:04.099Z",
                    "message": {"content": f"[OK] tmux driver: agent=claude session={FRAGO_SID}"},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        assert _index(root).parent_of(child) is None

    def test_回显落在子会话还活着的时候就算数(self, ledger, tmp_path):
        # 时序判据的另一半：真的那一次，子会话是主会话开场之后才起来的，之后它还会写。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        child = claude_session_uuid(FRAGO_SID)
        (proj / f"{child}.jsonl").write_text("{}\n", encoding="utf-8")
        now = time.time()
        os.utime(proj / f"{child}.jsonl", (now + 120, now + 120))
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            f"[OK] tmux driver: agent=claude session={FRAGO_SID}\n", encoding="utf-8"
        )
        assert _index(root).parent_of(child) == HUMAN_SID

    def test_同一句回显出现在好几场时归时刻最贴近的那场(self, ledger, tmp_path):
        # 真的那场写过一次，读过它记录的几场也抄过。判据是「哪场主会话的活动时刻离这场
        # worker 最近」，取「最近活动的那场」会把刚干完活的 worker 判给今天抄过同一句的会话。
        #
        # 时刻一律相对当下取：判据拿「子会话最后动过的时刻」跟「主会话记录建好的时刻」比，
        # 而文件的创建时刻改不了——造一个远在过去的时间戳，会让子会话看着比主会话的记录
        # 还早，被时序判据直接剔掉，这条用例就测不到决胜那一步了。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        old_parent = HUMAN_SID
        new_parent = "11111111-2222-4333-8444-555555555555"
        child = claude_session_uuid(FRAGO_SID)
        echo = f"[OK] tmux driver: agent=claude session={FRAGO_SID}\n"
        for sid in (old_parent, new_parent):
            (proj / f"{sid}.jsonl").write_text(echo, encoding="utf-8")
        (proj / f"{child}.jsonl").write_text("{}\n", encoding="utf-8")
        now = time.time()
        os.utime(proj / f"{child}.jsonl", (now, now))
        os.utime(proj / f"{old_parent}.jsonl", (now - 600, now - 600))
        os.utime(proj / f"{new_parent}.jsonl", (now + 7 * 86400, now + 7 * 86400))
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
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            f"[OK] tmux driver: agent=claude session={FRAGO_SID}\n", encoding="utf-8"
        )
        index = _index(root)
        assert index.parent_of(claude_session_uuid(FRAGO_SID)) == HUMAN_SID  # 新的认到了
        assert index.parent_of("老 worker") == "老主会话"  # 老的没被冲掉

    def test_增量那一趟不推翻全扫认下的(self, ledger, tmp_path):
        # **这一条是 2026-10-15 那次错挂的根因。** 增量只扫动过的那几个文件，候选集是残缺的：
        # 同一句回显在整库里可能好几场都有（真的那场 + 引用它的那几场），只扫一个文件时它就
        # "只剩一个候选"，决胜那一步等于没跑。让残档盖住全扫的结果，等于每三分钟拿最近在写的
        # 那场会话覆盖一遍正确值——我这场一直在写，于是 8 场不相干的会话全挂到了我名下。
        root = tmp_path / "projects"
        proj = root / "-p"
        proj.mkdir(parents=True)
        child = claude_session_uuid(FRAGO_SID)
        (proj / f"{child}.jsonl").write_text("{}\n", encoding="utf-8")
        (proj / f"{HUMAN_SID}.jsonl").write_text(
            f"[OK] tmux driver: agent=claude session={FRAGO_SID}\n", encoding="utf-8"
        )
        session_origin.PARENT_SCAN_CACHE.write_text(
            json.dumps({"at": int(time.time()) - 600, "pairs": {child: "老主会话"}}),
            encoding="utf-8",
        )
        assert _index(root).parent_of(child) == "老主会话"

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


class TestAttributedDispatch:
    """给三家 CLI 的驱动用的那一版记账：认不出派活者就当这场没被谁派过。

    驱动走到「认到真编号」那一步时，主会话派活与人在网页上自己开一场**长得一模一样**。
    只认得出父亲这一条判据，所以认不出父亲就不能记——把网页起的那场记成 worker，它就会
    落进「认不出出处的 worker」那一格，而那格里本该只有真被人派出去、只是没记住是谁派的活。
    """

    def test_认得出派活者就记(self, ledger, empty_projects, monkeypatch):
        child = str(uuid.uuid4())
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", HUMAN_SID)
        assert session_origin.record_attributed_dispatch(
            child, agent_type="agy", cwd="/tmp"
        )
        index = _index(empty_projects)
        assert index.parent_of(child) == HUMAN_SID
        assert index.origin_of(child) == "worker"

    def test_agy会话自报编号时认得出派活者(self, ledger, empty_projects, monkeypatch):
        child = "core_1234567890abcdef1234567890abcdef"
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.delenv("FRAGO_SESSION_ID", raising=False)
        monkeypatch.setenv("ANTIGRAVITY_CONVERSATION_ID", HUMAN_SID)
        assert session_origin.record_dispatch(
            child, agent_type="coreagent", cwd="/tmp"
        )
        index = _index(empty_projects)
        assert index.parent_of(child) == HUMAN_SID
        assert index.origin_of(child) == "worker"

    def test_认不出派活者就不记(self, ledger, empty_projects, monkeypatch):
        child = str(uuid.uuid4())
        monkeypatch.setattr(session_origin, "parent_from_env", lambda: None)
        assert not session_origin.record_attributed_dispatch(
            child, agent_type="agy", cwd="/tmp"
        )
        assert session_origin.find_relation(child) is None
        assert _index(empty_projects).origin_of(child) == "human"

    def test_网页新建会话就算环境里残留了父会话编号也绝不记派活(
        self, ledger, empty_projects, monkeypatch
    ):
        """2026-10-23：服务端环境残留 ANTIGRAVITY_CONVERSATION_ID 时，网页新建会话也不得记为 worker。"""
        monkeypatch.setenv("ANTIGRAVITY_CONVERSATION_ID", HUMAN_SID)
        child_by_origin = str(uuid.uuid4())
        assert not session_origin.record_attributed_dispatch(
            child_by_origin,
            agent_type="agy",
            cwd="/tmp",
            origin="human",
        )
        assert session_origin.find_relation(child_by_origin) is None
        assert _index(empty_projects).origin_of(child_by_origin) == "human"

        child_by_handle = str(uuid.uuid4())
        assert not session_origin.record_attributed_dispatch(
            child_by_handle,
            agent_type="agy",
            cwd="/tmp",
            handle=f"webui-{uuid.uuid4()}",
        )
        assert session_origin.find_relation(child_by_handle) is None
        assert _index(empty_projects).origin_of(child_by_handle) == "human"

    def test_命令行那一版认不出父亲也记(self, ledger, empty_projects, monkeypatch):
        # 两条路的分水岭就在这里：`frago agent <任务>` 敲下去本身就是派活，父亲认不出来
        # 只是「不知道是谁派的」，这一场仍然是 worker，该进「认不出出处的 worker」。
        child = str(uuid.uuid4())
        monkeypatch.setattr(session_origin, "parent_from_env", lambda: None)
        assert session_origin.record_dispatch(child, agent_type="claude", cwd="/tmp")
        index = _index(empty_projects)
        assert index.origin_of(child) == "worker"
        assert index.parent_of(child) is None


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
