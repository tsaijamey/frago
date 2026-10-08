"""无人应答的拍板卡片：收下来、下次先查、超期降级。

盯四件事：

1. 答复里挂着的卡片要收下来（YAML 写坏了也照样算一张等在等人的卡片）；
2. **同一个问题反复提出，起算时刻不动**——不然每跑一趟都把钟拨回零点，这张卡片永远
   降不了级，正是「逐日重现」的成因；
3. 人答了就照答复办；没人答、挂了三天，就不再问第二遍，按推荐项办并注明是默认取值；
4. 这一趟没再问，说明上一张已经有了下文，把账清掉。

不碰真的 frago-core、真的会话记录和真的家目录。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from frago.server.services import schedule_executor as ex
from frago.server.services import schedule_pending as sp

CARD = """```answer-needed-by-human
type: single-choice
question: 索引已经 4.1 万字符，超了 6000 字的上限，接下来怎么办？
options:
  - label: 分域拆成多份
    recommended: true
  - label: 就地压缩到 6000 字以内
  - label: 先不动，只补缺失字段
```"""


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "ROOT", tmp_path / "pending")
    monkeypatch.setattr(sp, "OPEN_AFTER_S", 3 * 24 * 3600)
    return tmp_path


def record(tmp_path: Path, session_id: str, lines: list[dict]) -> Path:
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in lines), encoding="utf-8"
    )
    return path


def human(text: str, ts_ms: int) -> dict:
    """一条用户发言，形状照真记录：``timestamp`` 是 UTC 的 ISO 串。"""
    stamp = datetime.fromtimestamp(ts_ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    return {
        "type": "user",
        "timestamp": f"{stamp}Z",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def outcome(*, stdout: str = "", session_id: str | None = "core_x", ok: bool = True):
    return ex.RunOutcome(ok=ok, kind="prompt", stdout=stdout, session_id=session_id)


def schedule(**kw) -> dict:
    base = {"id": "sch_index", "name": "整理 agent-failure-modes", "kind": "prompt", "prompt": "整理索引"}
    base.update(kw)
    return base


class TestCardIn:
    def test_答复里有卡片就取出来(self):
        card = sp.card_in(f"整理完了。\n\n{CARD}\n")
        assert card is not None
        assert "索引已经 4.1 万字符" in card["question"]
        assert card["options"] == ["分域拆成多份", "就地压缩到 6000 字以内", "先不动，只补缺失字段"]
        assert card["recommended"] == "分域拆成多份"

    def test_没挂卡片就是_none(self):
        assert sp.card_in("整理完了，没有要人拍板的事。") is None

    def test_yaml_写坏了照样算一张等人答的卡片(self):
        # 语料里真有一批这样的手写卡片：`Q1: …… / A: ……（推荐）` 几行，压根不是 YAML。
        card = sp.card_in(
            "```answer-needed-by-human\n"
            "Q1: 仓库根 skills/ 目录怎么处置？\n"
            "A: 按原样提交进本仓库（483 个第三方 skill 全量镜像入库）— 推荐\n"
            "```"
        )
        assert card is not None
        assert card["question"] == "Q1: 仓库根 skills/ 目录怎么处置？", "问句退而取原文首行"
        assert card["recommended"] is None
        assert "483 个第三方 skill" in card["raw"], "原文一个字不能丢"

    def test_有多张取最后一张(self):
        card = sp.card_in(CARD.replace("索引已经 4.1 万字符", "第一问") + "\n" + CARD.replace("索引已经 4.1 万字符", "第二问"))
        assert card is not None and "第二问" in card["question"]


class TestCollect:
    def test_挂了卡片就收下来(self):
        sp.collect(schedule(), outcome(stdout=f"整理完了。\n{CARD}"))

        card = sp.load("sch_index")
        assert card is not None
        assert card["session_id"] == "core_x"
        assert card["raised_at"] > 0
        assert card["asked_times"] == 1

    def test_同一个问题再问一遍_起算时刻不动(self):
        sp.collect(schedule(), outcome(stdout=CARD))
        first = sp.load("sch_index")
        assert first is not None

        sp.collect(schedule(), outcome(stdout=f"又整理了一遍，还是同一个问题：\n{CARD}"))

        again = sp.load("sch_index")
        assert again is not None
        assert again["raised_at"] == first["raised_at"], "每跑一趟都把钟拨回零点，这张卡片就永远降不了级"
        assert again["asked_times"] == 2, "问了几遍要数得出来"

    def test_换了问题就重新起算(self):
        sp.collect(schedule(), outcome(stdout=CARD))
        first = sp.load("sch_index")
        assert first is not None

        sp.collect(schedule(), outcome(stdout=CARD.replace("索引已经 4.1 万字符", "另一个问题")))

        again = sp.load("sch_index")
        assert again is not None
        assert again["raised_at"] > first["raised_at"]
        assert again["asked_times"] == 1

    def test_这一趟没再问就把账清掉(self):
        sp.collect(schedule(), outcome(stdout=CARD))
        assert sp.load("sch_index") is not None

        sp.collect(schedule(), outcome(stdout="这一趟没什么要问的，整理完了。"))

        assert sp.load("sch_index") is None, "上一张已经有了下文，不该再拿出来问一遍"

    def test_配方任务不记卡片(self):
        sp.collect(schedule(kind="recipe"), outcome(stdout=CARD))
        assert sp.load("sch_index") is None

    def test_存不下不影响任务本身(self, monkeypatch):
        def boom(sid, card):
            raise OSError("盘满了")

        monkeypatch.setattr(sp, "save", boom)
        sp.collect(schedule(), outcome(stdout=CARD))  # 不该抛


class TestNote:
    def _raise(self, monkeypatch, tmp_path, *, age_s: float, reply: str | None):
        """挂一张卡片（raised_at 拨到 age_s 秒前），可选地在它之后放一句人的话。"""
        sp.collect(schedule(), outcome(stdout=CARD))
        card = sp.load("sch_index")
        assert card is not None
        card["raised_at"] = 1_800_000_000.0 - age_s
        sp.save("sch_index", card)

        rows = []
        if reply is not None:
            rows.append(human(reply, int((card["raised_at"] + 60) * 1000)))
        path = record(tmp_path, "core_x", rows)
        monkeypatch.setattr(
            _store(), "find_session_file", lambda sid, root=None: path if sid == "core_x" else None
        )
        return card

    def test_挂了不久就照旧等_不塞东西(self, monkeypatch, tmp_path):
        self._raise(monkeypatch, tmp_path, age_s=3600, reply=None)
        assert sp.note("sch_index", now=1_800_000_000.0) is None

    def test_人答了就照答复办(self, monkeypatch, tmp_path):
        self._raise(monkeypatch, tmp_path, age_s=3600, reply="A · 分域拆成多份 —— 拆开之后每个域各自量体积")

        text = sp.note("sch_index", now=1_800_000_000.0)

        assert text is not None
        assert "人已经作答" in text
        assert "拆开之后每个域各自量体积" in text, "人的原话要原样带过去"
        assert "不要再问" not in text, "答了就不该再按默认取值走"

    def test_超期没人答就按推荐项降级(self, monkeypatch, tmp_path):
        self._raise(monkeypatch, tmp_path, age_s=4 * 24 * 3600, reply=None)

        text = sp.note("sch_index", now=1_800_000_000.0)

        assert text is not None
        assert "不要再问第二遍" in text, "最坏的是同一张卡片逐日重现"
        assert "分域拆成多份" in text, "按推荐项办"
        assert "默认取值" in text, "结论里要注明这是默认取值，不是人拍的板"

    def test_超期且没有推荐项就自己挑一条稳妥的并注明(self, monkeypatch, tmp_path):
        sp.collect(schedule(), outcome(stdout=CARD.replace("    recommended: true\n", "")))
        card = sp.load("sch_index")
        assert card is not None
        card["raised_at"] = 1_800_000_000.0 - 4 * 24 * 3600
        sp.save("sch_index", card)
        path = record(tmp_path, "core_x", [])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        text = sp.note("sch_index", now=1_800_000_000.0)

        assert text is not None
        assert "自己定" in text and "还没有人拍板" in text

    def test_手写的老式卡片超期时_选项原文照样带过去(self, monkeypatch, tmp_path):
        """老式卡片解析不出选项，那就把原文整段摆上去——人当时给的几条路不能丢。"""
        legacy = "```answer-needed-by-human\nQ1: 476 个未同步文件怎么处置？\nA: 按 workspaces 惯例 collect — 推荐\nB: 加 .gitignore 挡住\n```"
        sp.collect(schedule(), outcome(stdout=legacy))
        card = sp.load("sch_index")
        assert card is not None
        card["raised_at"] = 1_800_000_000.0 - 4 * 24 * 3600
        sp.save("sch_index", card)
        path = record(tmp_path, "core_x", [])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        text = sp.note("sch_index", now=1_800_000_000.0)

        assert text is not None
        assert "476 个未同步文件怎么处置" in text
        assert "B: 加 .gitignore 挡住" in text, "当时给的几条路要原样摆着"

    def test_没有挂着的卡片就交回_none(self):
        assert sp.note("sch_index") is None

    def test_答复被埋在前面时也找得到(self, monkeypatch, tmp_path):
        """卡片挂出之后那一场又跑了一整天，人的答复早被后来的记录埋到前面去了。
        只看文件尾巴会当成没人答，于是一张已经拍过板的卡片又被当成默认取值办一遍。"""
        raised = 1_800_000_000.0 - 4 * 24 * 3600
        rows = [human("A · 分域拆成多份 —— 就这么定", int((raised + 60) * 1000))]
        rows += [
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "好的" * 300}]}}
            for _ in range(1500)
        ]
        path = record(tmp_path, "core_x", rows)
        assert path.stat().st_size > sp.TAIL_BYTES * 2, "这一条用例要的是「答复落在尾巴窗口之外」"
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        got = sp.reply_since("core_x", raised)

        assert got is not None and "分域拆成多份" in got

    def test_卡片之前人说的话不算答复(self, monkeypatch, tmp_path):
        """那一场自己的任务原文也是用户发言，不能把它当成人的答复。"""
        sp.collect(schedule(), outcome(stdout=CARD))
        card = sp.load("sch_index")
        assert card is not None
        card["raised_at"] = 1_800_000_000.0 - 3600
        sp.save("sch_index", card)
        path = record(tmp_path, "core_x", [human("整理索引", int((card["raised_at"] - 600) * 1000))])
        monkeypatch.setattr(_store(), "find_session_file", lambda sid, root=None: path)

        assert sp.note("sch_index", now=1_800_000_000.0) is None


class TestWiring:
    def test_两块上一趟的东西套同一个壳(self):
        block = ex.previous_block(["【上一趟问的那件事有人答了】……", "【上一趟没跑完，留下的交接】……"])
        assert block.count("下面是这一次的任务") == 1, "两段各自带一个结尾，读起来像两次收尾"
        assert block.index("有人答了") < block.index("没跑完"), "人的答复摆在最前面"

    def test_只有一块时也套得上(self):
        block = ex.previous_block(["【上一趟问的那件事有人答了】……"])
        assert block.startswith("【上一趟留了东西给你】")
        assert block.endswith("下面是这一次的任务：\n")

    def test_起任务前查卡片_跑完再记一笔(self, monkeypatch):
        monkeypatch.setattr(sp, "ROOT", __import__("pathlib").Path("/nonexistent/pending"))
        monkeypatch.setattr(sp, "note", lambda sid, now=None: "【上一趟问的那件事有人答了】……")
        collected: list[str] = []
        monkeypatch.setattr(sp, "collect", lambda s, o: collected.append(s["id"]))
        from frago.server.services import schedule_resume as sr

        monkeypatch.setattr(sr, "load", lambda sid, now=None: None)
        monkeypatch.setattr(sr, "record", lambda s, o: None)

        captured: list[dict] = []

        def fake_execute(prompt, timeout, instructions=None, allowed=None, disallowed=None, cwd=None, title=None, resume=None, pending=None):
            captured.append({"pending": pending})
            return outcome(ok=True)

        monkeypatch.setattr(ex, "execute_prompt", fake_execute)

        import asyncio

        asyncio.run(ex.run_scheduled(schedule()))

        assert captured[0]["pending"] == "【上一趟问的那件事有人答了】……", "查到的卡片要交到执行器手上"
        assert collected == ["sch_index"], "跑完要按这一趟的答复重新记一笔"


def _store():
    from frago.session import coreagent_store

    return coreagent_store
