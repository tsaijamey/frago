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
from frago.session import store as store_module
from frago.session.store import SessionOntologyStore

# 人自己开的会话：claude 自己分配的编号，第 4 版。
HUMAN_SID = "7f55e46e-0cc5-4e80-8f4f-1debd649d7b0"
# frago 那一侧的编号，worker 的 claude 编号由它派生。
FRAGO_SID = "d5813c9e-ee2f-48ae-9bb3-f3002134ff2b"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """把账本、扫描缓存与本体存储都挪到临时目录，用例之间互不干扰。

    CoreAgent 那一侧的会话根也一并掐掉：单测不该去读本机真实的会话库，那里有多少条
    父子关系全看这台机器用过什么。要测那一侧的扫描时，用例自己把它换掉。

    **本体存储也必须换掉。** 记账时会顺带往它写一份；它默认指向 ``~/.frago/workbench/``，
    不换的话每个用例都在往宿主机真实数据上写。套件那道守门人拦得住，但拦法是抛异常，
    而记账那一步把异常吞了——结果是「同步写进本体存储」这条路径在单测里根本没跑过，
    用例看着全绿，其实什么都没验到。
    """
    monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
    monkeypatch.setattr(session_origin, "PARENT_SCAN_CACHE", tmp_path / "agent-parent-scan.json")
    monkeypatch.setattr(session_origin, "_coreagent_scan_root", lambda: None)
    monkeypatch.setattr(session_origin, "_memo", None)
    store = SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    monkeypatch.setattr(store_module, "_DEFAULT_SESSION_STORE", store)
    monkeypatch.setattr(session_origin, "get_default_session_store", lambda: store)
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
        # 两边上限一起改：记账那一步截断到 N 条，本体存储回写老账本时按它自己的上限再来一遍。
        # 只改一边的话，本体的那份会把刚截掉的老记录又写回来，用例测的就不是截断了。
        monkeypatch.setattr(session_origin, "LEDGER_LIMIT", 3)
        monkeypatch.setattr(store_module, "LEDGER_LIMIT", 3)
        # 时刻逐条递增：本体存储回写时按记录时刻排序取最近若干条，同一秒里的几条谁前谁后
        # 没有定数，断言「留下的正是最近那三条」会变成撞运气。
        ticks = iter(1_700_000_000 + i for i in range(100))
        monkeypatch.setattr(session_origin, "_now", lambda: next(ticks))
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
        store_path = str(session_origin.get_default_session_store().store_path)
        barrier = ctx.Barrier(6)

        with ctx.Pool(
            6,
            initializer=_mp_init_worker,
            initargs=(barrier, ledger_path, store_path),
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
_MP_STORE_PATH = None


def _mp_init_worker(barrier, ledger_path: str, store_path: str) -> None:
    global _MP_BARRIER, _MP_LEDGER_PATH, _MP_STORE_PATH
    _MP_BARRIER = barrier
    _MP_LEDGER_PATH = ledger_path
    _MP_STORE_PATH = store_path


def _mp_record_one(child_id: str) -> None:
    from pathlib import Path

    # 子进程是另起的一份解释器，用例里那些 monkeypatch 一个都没跟过来。**本体存储也要在这里
    # 指到临时目录**：它默认落在 ~/.frago/workbench/，不指的话这几条记录会写进真人账本。
    session_origin.LAUNCH_LEDGER = Path(_MP_LEDGER_PATH)
    store = SessionOntologyStore(Path(_MP_STORE_PATH), legacy_ledger_path=Path(_MP_LEDGER_PATH))
    store_module._DEFAULT_SESSION_STORE = store
    session_origin.get_default_session_store = lambda: store
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

    def test_交接算人开的且认得原会话父亲(self, ledger, empty_projects):
        # 交接是人换一场继续谈，算 human，同时记下原会话 parent_session_id 供左栏同组向上排列。
        child = str(uuid.uuid4())
        session_origin.LAUNCH_LEDGER.write_text(
            json.dumps([{"child": child, "parent": HUMAN_SID, "kind": "handoff"}]),
            encoding="utf-8",
        )
        index = _index(empty_projects)
        assert index.relation_of(child) == session_origin.SessionRelation("handoff")
        assert index.parent_of(child) == HUMAN_SID
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

    def test_别人改了账本_进程内那份当场作废(self, ledger, empty_projects):
        """账本不只本模块在写，本体存储那边也会回写同一份文件。

        缓存只按「离上次读够不够近」判新不新的话，别人刚写进去的关系要等满 30 秒才出现
        在清单上。这条用例绕过 record_relation 直接改文件，模拟的就是那条路。
        """
        session_origin.load_origin_index(projects_root=empty_projects)
        assert session_origin.load_origin_index(projects_root=empty_projects).parents == {}

        child = str(uuid.uuid4())
        entries = json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8")) if session_origin.LAUNCH_LEDGER.exists() else []
        entries.append({"child": child, "parent": HUMAN_SID, "kind": "dispatch", "at": 1})
        session_origin.LAUNCH_LEDGER.write_text(json.dumps(entries), encoding="utf-8")

        index = session_origin.load_origin_index(projects_root=empty_projects)
        assert index.parent_of(child) == HUMAN_SID
        assert index.origin_of(child) == "worker"
        session_origin.clear_cache()


class TestStoreConvergence:
    """`session_origin` 与 `SessionOntologyStore` 两处记的是同一件事，口径必须一致。"""

    def test_无父节点的派活在两处都算worker(self, ledger, empty_projects):
        """认不出谁派的活，仍然是 worker——老账本与本体存储不能各说一套。

        服务端的常驻会话、定时任务派出去的活本来就没有上级会话可指。老账本按「派活即
        worker」判它，本体存储若按「有父亲才算 worker」判，同一场会话两处互斥；员工账本
        与列表投影分别读这两处，就会拿到互相矛盾的出身。
        """
        session_origin.record_launch(
            child_session_id="orphan-w",
            parent_session_id=None,
            agent_type="claude",
            cwd="/tmp",
        )
        store = session_origin.get_default_session_store()

        index = _index(empty_projects)
        assert index.origin_of("orphan-w") == "worker"
        assert index.parent_of("orphan-w") is None

        rec = store.get("orphan-w")
        assert rec is not None
        assert rec.is_worker is True
        assert rec.origin == "worker"
        assert rec.relation_kind == "dispatch"
        assert rec.parent_session_id is None

    def test_收口之后别的会话再落盘也不回退(self, ledger, empty_projects):
        """收口过的不许被后来的任意一次落盘冲回未收口。

        收口原先只写老账本。收口之后随便哪一场会话落盘，老账本都会被按本体存储那一份
        整份重写回去，已收口的分支重新变实——人点的那一下看起来根本没生效。
        """
        child = str(uuid.uuid4())
        store = session_origin.get_default_session_store()
        session_origin.record_relation(
            kind="branch",
            child_session_id=child,
            parent_session_id=HUMAN_SID,
            agent_type="claude",
            cwd="/tmp",
            note="旁支",
        )
        closed = session_origin.close_relation(
            child_session_id=child, parent_session_id=HUMAN_SID, closed_by="manual"
        )
        assert closed is not None
        assert closed["closed_at"] is not None

        rec = store.get(child)
        assert rec is not None
        assert rec.extra.get("closed_at") == closed["closed_at"]
        assert rec.extra.get("closed_by") == "manual"

        # 别的会话接着落盘：收口状态必须还在，老账本里也不能变回未收口。
        assert store.increment_step(child) == 1
        store.update_lifecycle_state(child, "awaiting_input", waiting_reason="等回话")

        again = store.get(child)
        assert again is not None
        assert again.extra.get("closed_at") == closed["closed_at"]
        assert _index(empty_projects).relation_of(child) == session_origin.SessionRelation(
            "branch", closed=True
        )

    def test_收口时本体里没有这条分支也不报错(self, ledger):
        """本体存储缺这条记录只是少同步一处，不该把收口这个动作判成失败。"""
        child = str(uuid.uuid4())
        session_origin.record_relation(
            kind="branch",
            child_session_id=child,
            parent_session_id=HUMAN_SID,
            agent_type="claude",
            cwd="/tmp",
        )
        # 把本体存储里那条抹掉，模拟它先于老账本被清理过。
        store = session_origin.get_default_session_store()
        raw = json.loads(store.store_path.read_text(encoding="utf-8"))
        raw["sessions"].pop(child, None)
        store.store_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

        closed = session_origin.close_relation(
            child_session_id=child, parent_session_id=HUMAN_SID, closed_by="manual"
        )
        assert closed is not None and closed["closed_at"] is not None


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

    def test_异步派发把手预记账在认领时过户真实父亲_绝不认把手自己当父亲(
        self, ledger, empty_projects, tmp_path, monkeypatch
    ):
        """回归（e875e9e1 / c69c589f）：异步 watcher 进程环境里即便带了 FRAGO_SESSION_ID=<handle>，
        认领到真会话编号 child 时，record_attributed_dispatch 与 _ledger_pairs 都必须继承 handle
        预记下的真实 caller_sid，绝不能把临时把手 handle 当作父会话导致左栏掉进『不知道谁派的 WORKER』。
        """
        from frago.session import agy_store

        monkeypatch.setattr(agy_store, "BINDINGS_PATH", tmp_path / "agy-sessions.json")
        caller_sid = "daeec834-e3d5-4ac6-ab35-9fd7981a6972"
        handle = "c69c589f-670c-481c-af79-ac870f4f7598"
        claimed_cid = "e875e9e1-0fc7-4f18-ab22-cc596d1883e9"

        # 1. 派发入口先按临时把手记账
        session_origin.record_relation(
            kind="dispatch",
            child_session_id=handle,
            parent_session_id=caller_sid,
            agent_type="agy",
            cwd="/tmp",
            prompt_head="修复认领型内核父会话挂接",
        )
        agy_store.put_binding(handle, claimed_cid, "/tmp")

        # 即使尚未写第二条账，_ledger_pairs 已能通过把手绑定解析出 claimed_cid 的真实父亲
        early_index = _index(empty_projects)
        assert early_index.origin_of(claimed_cid) == "worker"
        assert early_index.parent_of(claimed_cid) == caller_sid

        # 2. 模拟后台 watcher 环境（FRAGO_SESSION_ID=handle）下驱动调用 record_attributed_dispatch
        monkeypatch.setenv("FRAGO_SESSION_ID", handle)
        assert session_origin.record_attributed_dispatch(
            claimed_cid,
            agent_type="agy",
            cwd="/tmp",
            handle=handle,
        )
        entry = session_origin.find_relation(claimed_cid)
        assert entry is not None
        assert entry["parent"] == caller_sid
        assert entry["prompt_head"] == "修复认领型内核父会话挂接"

        # 3. 哪怕历史账本里曾误写入一条 parent=handle 的脏记录，_ledger_pairs 也会将其还原为 caller_sid
        session_origin.record_relation(
            kind="dispatch",
            child_session_id=claimed_cid,
            parent_session_id=handle,
            agent_type="agy",
            cwd="/tmp",
        )
        final_index = _index(empty_projects)
        assert final_index.origin_of(claimed_cid) == "worker"
        assert final_index.parent_of(claimed_cid) == caller_sid


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
        # 收口只该动那一条分支：同一本账里别的会话的记录一条不少。
        session_origin.LAUNCH_LEDGER.write_text(
            json.dumps([{"child": "old", "parent": HUMAN_SID, "kind": "dispatch", "at": 1}]),
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
        by_child = {e["child"]: e for e in after}
        assert set(by_child) == {"old", "b1", "w1"}
        # 那两条一个字没动：收口只碰它自己那一条。
        assert by_child["old"]["at"] == 1
        assert by_child["old"]["kind"] == "dispatch"
        assert by_child["w1"]["kind"] == "dispatch"
        assert by_child["w1"].get("closed_at") is None
        assert by_child["b1"]["closed_at"] is not None
        assert by_child["b1"]["closed_by"] == "manual"
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
