"""定时任务的续跑包：这一趟没跑完，下一趟接得上。

盯四件事：

1. 交接是从**会话记录尾巴**上取出来的（内核终止前留下的那一段），记录了就在、没记录
   就没有，取不着不许抛；
2. 跑成了要把续跑包清掉——留着的话下一趟会去接着一件已经做完的事；
3. 隔太久的不接（世界变了，那段交接只会把这一趟带偏）；
4. 接线：调度器起任务前把包读出来交给它，跑完按成败记账。

不碰真的 frago-core、真的会话记录和真的家目录。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.server.services import schedule_executor as ex
from frago.server.services import schedule_resume as sr

MARK = sr.MARKER


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """续跑包、挂着的卡片与「会话记录」都落在临时目录里。"""
    from frago.server.services import schedule_pending as sp

    monkeypatch.setattr(sr, "ROOT", tmp_path / "resume")
    monkeypatch.setattr(sp, "ROOT", tmp_path / "pending")
    return tmp_path


def record(tmp_path: Path, session_id: str, lines: list[dict]) -> Path:
    """一份 CoreAgent 会话记录（Claude Code 那个形状）。"""
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in lines), encoding="utf-8"
    )
    return path


def say(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def outcome(*, ok: bool, session_id: str | None = "core_x", error: str = ""):
    return ex.RunOutcome(ok=ok, kind="prompt", exit_code=0 if ok else 1, error=error, session_id=session_id)


def schedule(**kw) -> dict:
    base = {"id": "sch_gitpush", "name": "每日 git-push 提交", "kind": "prompt", "prompt": "把今天的改动提交并推送"}
    base.update(kw)
    return base


class TestHandover:
    def test_交接从会话记录里取出来(self, tmp_path, monkeypatch):
        path = record(tmp_path, "core_x", [
            say("先看看有哪些改动"),
            say(f"{MARK}这一场没能正常收尾。\n- 为什么停（timeout）：时限到了\n- 走到第 27 轮。"),
        ])
        monkeypatch.setattr(
            _store(), "find_session_file", lambda sid, root=None: path if sid == "core_x" else None
        )

        got = sr.handover_of("core_x")

        assert got is not None and got.startswith(MARK)
        assert "走到第 27 轮" in got

    def test_记了多遍就取最后那遍(self, tmp_path, monkeypatch):
        path = record(tmp_path, "core_x", [say(f"{MARK}旧的"), say("中间又说了一句话"), say(f"{MARK}新的")])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        assert sr.handover_of("core_x") == f"{MARK}新的"

    def test_没有这场会话就交回_none(self, monkeypatch):
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: None)
        assert sr.handover_of("core_missing") is None

    def test_记录里没有交接也交回_none(self, tmp_path, monkeypatch):
        path = record(tmp_path, "core_x", [say("我还在想"), say("换个法子")])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)
        assert sr.handover_of("core_x") is None

    def test_记录很长时从尾巴上找(self, tmp_path, monkeypatch):
        """整场记录可能有几兆，交接就在最后那一段——不该为此读整份。"""
        filler = [say("读了一点东西" * 40) for _ in range(4000)]
        path = record(tmp_path, "core_x", [*filler, say(f"{MARK}走到第 88 轮")])
        assert path.stat().st_size > sr.TAIL_BYTES * 2, "这一条用例要的是「记录比尾巴窗口大」"
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        assert sr.handover_of("core_x") == f"{MARK}走到第 88 轮"

    def test_读记录时出错不许抛(self, monkeypatch):
        def boom(sid, root=None):
            raise OSError("盘没了")

        monkeypatch.setattr(_store(), "find_session_file", boom)
        assert sr.handover_of("core_x") is None


class TestBuildAndRecord:
    def test_没跑完就把交接收成续跑包(self, tmp_path, monkeypatch):
        path = record(tmp_path, "core_x", [say(f"{MARK}改过 .gitignore，还有 476 个未跟踪文件没处理")])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        sr.record(schedule(), outcome(ok=False, error="HTTP 500"))

        text = sr.load("sch_gitpush")
        assert text is not None
        assert "把今天的改动提交并推送" in text, "任务原文要在里面"
        assert "core_x" in text, "会话编号要在里面，人从那儿点进去看"
        assert "476 个未跟踪文件" in text, "内核留下的交接要在里面"

    def test_跑成了就把续跑包清掉(self, tmp_path, monkeypatch):
        path = record(tmp_path, "core_x", [say(f"{MARK}改过 .gitignore")])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)
        sr.record(schedule(), outcome(ok=False))

        assert sr.path_for("sch_gitpush").exists()
        sr.record(schedule(), outcome(ok=True))

        assert sr.load("sch_gitpush") is None, "办完了还留着，下一趟会去接着一件已经做完的事"

    def test_内核没留下交接就不攒(self, monkeypatch):
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: None)
        sr.record(schedule(), outcome(ok=False, error="连模型都没问上"))
        assert sr.load("sch_gitpush") is None, "只有错误码的续跑包没有意义，执行记录里已经有了"

    def test_配方任务不攒续跑包(self, tmp_path, monkeypatch):
        path = record(tmp_path, "core_x", [say(f"{MARK}改过 .gitignore")])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)
        sr.record(schedule(kind="recipe"), outcome(ok=False))
        assert sr.load("sch_gitpush") is None


class TestLoad:
    def test_隔了一周的不接(self, monkeypatch):
        sr.save("sch_gitpush", "## 上一趟跑到这里\n……", "core_x")
        data = json.loads(sr.path_for("sch_gitpush").read_text(encoding="utf-8"))
        data["saved_at"] -= sr.MAX_AGE_S + 60
        sr.path_for("sch_gitpush").write_text(json.dumps(data), encoding="utf-8")

        assert sr.load("sch_gitpush") is None
        assert not sr.path_for("sch_gitpush").exists(), "过期的顺手清掉，别留着下次再判一遍"

    def test_昨天的接得上(self):
        sr.save("sch_gitpush", "## 上一趟跑到这里\n……", "core_x")
        assert sr.load("sch_gitpush") is not None

    def test_没有包就交回_none(self):
        assert sr.load("sch_never") is None

    def test_写坏了就当没有_不抛(self, tmp_path):
        path = sr.path_for("sch_gitpush")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{不是 JSON", encoding="utf-8")
        assert sr.load("sch_gitpush") is None


class TestPreamble:
    def test_续跑包摆在任务原文前面(self):
        block = ex.previous_block([sr.section("## 上一趟跑到这里\n- 到第 27 轮")])
        assert block.startswith("【上一趟留了东西给你】")
        assert "别把已经做过的事重做一遍" in block
        assert block.index("到第 27 轮") < block.index("下面是这一次的任务"), "包在任务原文前面"


class TestWiring:
    def test_起任务前读包_跑完按成败记账(self, monkeypatch):
        """接线：读出来的包交给执行器，执行器交回的结果决定下一条包留不留。"""
        monkeypatch.setattr(sr, "load", lambda sid, now=None: "## 上一趟跑到这里")
        seen: list[dict] = []
        monkeypatch.setattr(sr, "record", lambda s, o: seen.append({"id": s["id"], "ok": o.ok}))
        from frago.server.services import schedule_pending as sp

        monkeypatch.setattr(sp, "note", lambda sid, now=None: None)

        captured: list[dict] = []

        def fake_execute(prompt, timeout, instructions=None, allowed=None, disallowed=None, cwd=None, title=None, resume=None, pending=None):
            captured.append({"prompt": prompt, "resume": resume, "pending": pending})
            return outcome(ok=False)

        monkeypatch.setattr(ex, "execute_prompt", fake_execute)

        import asyncio

        result = asyncio.run(ex.run_scheduled(schedule()))

        sent = captured[0]["resume"] or ""
        assert "## 上一趟跑到这里" in sent, "读出来的包要交到执行器手上"
        assert sent.startswith("【上一趟没跑完"), "交出去的是套好壳的那一段"
        assert result.ok is False
        assert seen == [{"id": "sch_gitpush", "ok": False}], "跑完要按成败记一笔"


def _store():
    from frago.session import coreagent_store

    return coreagent_store
