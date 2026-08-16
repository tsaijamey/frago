"""统一记录类型的约束测试（spec 20260729-session-workbench-webui Phase 1）。

这里验的不是"能不能建出对象"，而是三条纪律有没有真的被类型挡住：报错只留三个字段
且不给原文入口、截断是三值枚举不是布尔、工具按大类分支不按工具名穷举。纪律靠人自
觉守不住，得让写错的代码在建对象那一刻就炸。
"""

from __future__ import annotations

import pytest

from frago.session.adapters import (
    AdapterNotRegistered,
    RecordAdapter,
    get_adapter,
    list_adapters,
    register_adapter,
)
from frago.session.record_reader import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    UnknownSessionFamily,
    detect_family,
)
from frago.session.unified_record import (
    ERROR_SCOPES,
    RECORD_FAMILIES,
    RECORD_KINDS,
    TOOL_FAMILIES,
    TRUNCATION_STATES,
    ErrorPayload,
    UnifiedRecord,
)


def make_record(**overrides: object) -> UnifiedRecord:
    """建一条最小可用的统一记录，用例只覆盖自己关心的字段。"""
    base: dict[str, object] = {
        "id": "rec-1",
        "session_id": "00a02979-7eb4-5c70-94ae-867c8281e3f6",
        "group_id": None,
        "seq": 0,
        "ts": 1_753_000_000_000,
        "kind": "user.say",
    }
    base.update(overrides)
    return UnifiedRecord(**base)  # type: ignore[arg-type]


# ── 十五种形态 ──────────────────────────────────────────────────────
class TestRecordKind:
    def test_十五种形态一个不多一个不少(self) -> None:
        assert {
            "user.say",
            "agent.say",
            "agent.think",
            "tool.call",
            "tool.result",
            "subagent.dispatch",
            "context.inject",
            "media.attach",
            "todo.snapshot",
            "permission.outcome",
            "error",
            "interrupt",
            "context.compact",
            "session.state",
            "call.envelope",
        } == RECORD_KINDS
        assert len(RECORD_KINDS) == 15

    @pytest.mark.parametrize("kind", sorted(RECORD_KINDS))
    def test_每一种形态都建得出记录(self, kind: str) -> None:
        record = make_record(kind=kind, raw_available=kind != "error")
        assert record.kind == kind

    def test_形态之外的取值当场炸(self) -> None:
        with pytest.raises(ValueError, match="未知的记录形态"):
            make_record(kind="assistant")

    def test_没有发言人字段(self) -> None:
        """身份由形态表达。留了 role/speaker 就等于给二次判断开口子。"""
        names = set(UnifiedRecord.__dataclass_fields__)
        assert "role" not in names
        assert "speaker" not in names
        assert names == {
            "id",
            "session_id",
            "group_id",
            "seq",
            "ts",
            "kind",
            "agent_path",
            "payload",
            "raw_available",
        }


# ── 纪律一：报错只留三个字段 ────────────────────────────────────────
class TestErrorDiscipline:
    def test_报错载荷只有三个字段(self) -> None:
        assert set(ErrorPayload.__dataclass_fields__) == {"scope", "code", "message"}

    def test_报错来源限四层(self) -> None:
        assert {"api", "engine", "model", "tool"} == ERROR_SCOPES

    def test_报错载荷不可变(self) -> None:
        payload = ErrorPayload(scope="api", code="429", message="rate limited")
        with pytest.raises(AttributeError):
            payload.message = "改一下"  # type: ignore[misc]

    def test_报错记录不许挂原文入口(self) -> None:
        """响应头里带 Cloudflare 登录凭据，展开即泄露。"""
        with pytest.raises(ValueError, match="原文入口"):
            make_record(kind="error", raw_available=True)

    def test_报错记录默认就取不到原文(self) -> None:
        record = make_record(kind="error", raw_available=False)
        assert record.is_raw_readable() is False

    def test_其它形态默认可取原文(self) -> None:
        assert make_record(kind="tool.result").is_raw_readable() is True


# ── 纪律二：截断是三值枚举 ──────────────────────────────────────────
class TestTruncationDiscipline:
    def test_三值不是布尔(self) -> None:
        assert {"none", "clipped", "offloaded"} == TRUNCATION_STATES
        assert len(TRUNCATION_STATES) == 3

    def test_溢出转存与完整是两回事(self) -> None:
        """Claude Code 溢出转存时正文毫无提示，opencode 溢出时截断标记写 false。
        布尔表达不了这两种，所以枚举里 offloaded 必须独立于 none。"""
        assert "offloaded" in TRUNCATION_STATES
        assert "offloaded" != "none"


# ── 纪律三：工具按大类分支 ──────────────────────────────────────────
class TestToolFamilyDiscipline:
    def test_十一个大类(self) -> None:
        assert {
            "shell",
            "file-read",
            "file-write",
            "search",
            "web",
            "agent",
            "todo",
            "ask",
            "schedule",
            "mcp",
            "other",
        } == TOOL_FAMILIES

    def test_留了兜底类(self) -> None:
        """工具名不是封闭集合，随用户配置变化。没有 other 就必然出现漏归的工具。"""
        assert "other" in TOOL_FAMILIES


# ── 记录本身的约束 ──────────────────────────────────────────────────
class TestUnifiedRecord:
    def test_序号从零起不许为负(self) -> None:
        assert make_record(seq=0).seq == 0
        with pytest.raises(ValueError, match="seq"):
            make_record(seq=-1)

    def test_主会话的归属轨迹是空的(self) -> None:
        assert make_record().agent_path == []

    def test_子agent带一段轨迹(self) -> None:
        record = make_record(kind="subagent.dispatch", agent_path=["explore"])
        assert record.agent_path == ["explore"]

    def test_默认值不共享(self) -> None:
        """agent_path 与 payload 用 default_factory，两条记录改一条不能串到另一条。"""
        first, second = make_record(), make_record()
        first.agent_path.append("explore")
        first.payload["text"] = "写点东西"
        assert second.agent_path == []
        assert second.payload == {}

    def test_用户输入类的分组键为空(self) -> None:
        assert make_record(kind="user.say").group_id is None

    def test_同一次回复共用分组键(self) -> None:
        say = make_record(id="a", seq=1, kind="agent.say", group_id="msg-7")
        call = make_record(id="b", seq=2, kind="tool.call", group_id="msg-7")
        assert say.group_id == call.group_id == "msg-7"

    def test_时间戳是毫秒整数不带时区(self) -> None:
        """项目统一 naive local time，统一记录内部一律毫秒整数，
        NEVER 出现 datetime.now(timezone.utc)，NEVER 手拼 Z 后缀。"""
        record = make_record(ts=1_753_000_000_000)
        assert isinstance(record.ts, int)


# ── 两家的判定 ──────────────────────────────────────────────────────
class TestDetectFamily:
    def test_两家一共两家(self) -> None:
        assert {"claude-code", "opencode"} == RECORD_FAMILIES

    @pytest.mark.parametrize(
        "session_id",
        [
            "00a02979-7eb4-5c70-94ae-867c8281e3f6",
            "0127f1ff-c5fd-597f-9fa9-f19c9b9a811f",
            "01322AD7-0DC8-5E38-BD01-8CEFAEAAE90E",
        ],
    )
    def test_uuid形状归claude_code(self, session_id: str) -> None:
        assert detect_family(session_id) == "claude-code"

    @pytest.mark.parametrize(
        "session_id",
        [
            "ses_058288655ffeYMxYC1AZKCcv56",
            "ses_0583125dfffeF2EQZPeCHREhsD",
            "ses_0583fe602ffe8b40TLZqIGy3de",
        ],
    )
    def test_ses前缀归opencode(self, session_id: str) -> None:
        assert detect_family(session_id) == "opencode"

    def test_两家编号形状互不相容(self) -> None:
        """全量核对过：1121 个 Claude Code 会话编号全是 UUID、33 个 opencode 编号
        全带 ses_ 前缀，交集 0 条。UUID 的字符集不含下划线，形状上撞不上。"""
        cc = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
        oc = "ses_058288655ffeYMxYC1AZKCcv56"
        assert detect_family(cc) != detect_family(oc)
        assert "_" not in cc

    def test_首尾空白不影响判定(self) -> None:
        assert detect_family("  ses_058288655ffeYMxYC1AZKCcv56 \n") == "opencode"

    @pytest.mark.parametrize(
        "session_id",
        ["", "not-a-session", "msg_e52e3571c001N4tI5qYKSAwIG8", "prt_e52e3571d001bHMLE8H8GvtTzh"],
    )
    def test_形状都不像的一律抛不默认一家(self, session_id: str) -> None:
        """默认当 Claude Code 会让 opencode 的编号去翻 JSONL，翻出空的，
        界面上看起来像这场会话没记录。"""
        with pytest.raises(UnknownSessionFamily):
            detect_family(session_id)


# ── 分页与骨架 ──────────────────────────────────────────────────────
class TestReaderSkeleton:
    def test_分页上限是硬的(self) -> None:
        assert DEFAULT_LIMIT == 200
        assert MAX_LIMIT == 500

    def test_两家的翻译层都已登记(self) -> None:
        """入口不写 if/else，家族到翻译层的对应关系全在注册表里。"""
        assert set(list_adapters()) == {"claude-code", "opencode"}

    def test_取不到不等于没接上(self) -> None:
        """接上翻译层之后，本机没有的那场会话取回空结果，NEVER 再抛未实现。

        骨架期这三个入口一律抛，为的是不让"没做完"伪装成"这场会话本来就没记录"。现在
        两者要能分开：真的没有，就是空。
        """
        import frago.session.record_reader as reader

        absent = "00000000-0000-4000-8000-000000000000"
        assert reader.read_records(absent) == []
        assert reader.read_raw(absent, "rec-1") is None

    def test_两家的会话合并后按最后活动时刻倒序(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """左栏只有一份清单。两家谁新谁在上，与它属于哪一家无关。"""
        import frago.session.record_reader as reader
        from frago.session.opencode_store import OpencodeSessionRow
        from frago.session.session_index import SessionSummary

        monkeypatch.setattr(
            reader.session_index,
            "list_session_summaries",
            lambda **_: [
                SessionSummary(
                    sid="00a02979-7eb4-5c70-94ae-867c8281e3f6",
                    slug=None,
                    custom_title=None,
                    ai_title="改翻译层",
                    first_user=None,
                    cwd="/Users/frago/Repos/frago",
                    first_ts=1_753_000_000.0,
                    last_active_ts=1_753_000_300.0,
                )
            ],
        )
        monkeypatch.setattr(
            reader.opencode_store,
            "list_sessions",
            lambda: [
                OpencodeSessionRow(
                    session_id="ses_abc",
                    title="opencode 那场",
                    directory="/tmp/x",
                    time_created=1_753_000_100_000,
                    time_updated=1_753_000_900_000,
                )
            ],
        )

        cards = reader.list_sessions()
        assert [card.family for card in cards] == ["opencode", "claude-code"]
        assert cards[1].title == "改翻译层"
        # 秒 → 毫秒的换算不能漏，否则 Claude Code 那侧永远排在 1970 年。
        assert cards[1].created_at == 1_753_000_000_000
        assert cards[1].last_active_at == 1_753_000_300_000


class TestSessionCardStatus:
    """会话卡上的状态与摘要。判据在 ``session_index``，这里盯的是装配这一步。"""

    def _summary(self, tail, last_active_ts):  # type: ignore[no-untyped-def]
        from frago.session.session_index import SessionSummary

        return SessionSummary(
            sid="00a02979-7eb4-5c70-94ae-867c8281e3f6",
            slug=None,
            custom_title="某场会话",
            ai_title=None,
            first_user=None,
            cwd="/Users/frago/Repos/frago",
            first_ts=last_active_ts - 600,
            last_active_ts=last_active_ts,
            tail=tail,
        )

    def _one_card(self, monkeypatch, tail, last_active_ts):  # type: ignore[no-untyped-def]
        import frago.session.record_reader as reader

        monkeypatch.setattr(
            reader.session_index,
            "list_session_summaries",
            lambda **_: [self._summary(tail, last_active_ts)],
        )
        monkeypatch.setattr(reader.opencode_store, "list_sessions", list)
        (card,) = reader.list_sessions()
        return card

    def test_报错时卡在那一格给出那条报错的原话(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import time

        from frago.session.session_index import TailSignals

        card = self._one_card(
            monkeypatch,
            TailSignals(
                last_kind="error",
                error_message="API Error: 连接中断",
                digest_done="把镜头判断追加进了 verdict.jsonl",
            ),
            time.time() - 86_400,
        )

        assert card.status == "error"
        assert card.digest_stuck == "API Error: 连接中断"
        assert card.digest_done == "把镜头判断追加进了 verdict.jsonl"

    def test_不是报错时卡在那一格恒为空(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """状态不是报错却挂一句"卡在某处"，等于凭空断言一件没有出处的事。"""
        import time

        from frago.session.session_index import TailSignals

        card = self._one_card(
            monkeypatch,
            TailSignals(last_kind="agent.say", error_message="上一轮的旧报错", digest_done="答完了"),
            time.time() - 86_400,
        )

        assert card.status == "done"
        assert card.digest_stuck is None

    def test_刚刚还有动静判在跑(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import time

        from frago.session.session_index import TailSignals

        card = self._one_card(
            monkeypatch, TailSignals(last_kind="tool.result"), time.time() - 5
        )

        assert card.status == "running"

    def test_没有要你做那一格(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """三段式摘要本次只做两段。判不出来的那一格连字段都不给，NEVER 留个空壳让人以为在算。"""
        import time
        from dataclasses import fields

        from frago.session.session_index import TailSignals

        card = self._one_card(
            monkeypatch, TailSignals(last_kind="agent.say"), time.time() - 86_400
        )
        names = {f.name for f in fields(card)}

        assert "digest_done" in names
        assert "digest_stuck" in names
        assert not [n for n in names if "todo" in n or "ask" in n]

    def test_opencode那侧的毫秒时刻要换回秒再判(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """两家的"距今多久"必须同一把尺子。拿毫秒去比 90 秒，opencode 会永远判成在跑。"""
        import time

        import frago.session.record_reader as reader
        from frago.session.opencode_store import OpencodeSessionRow
        from frago.session.session_index import TailSignals

        long_ago_ms = int((time.time() - 86_400) * 1000)
        monkeypatch.setattr(reader.session_index, "list_session_summaries", lambda **_: [])
        monkeypatch.setattr(
            reader.opencode_store,
            "list_sessions",
            lambda: [
                OpencodeSessionRow(
                    session_id="ses_abc",
                    title="opencode 那场",
                    directory="/tmp/x",
                    time_created=long_ago_ms - 1000,
                    time_updated=long_ago_ms,
                )
            ],
        )
        monkeypatch.setattr(
            reader.session_index,
            "opencode_tail_signals",
            lambda _rows: {"ses_abc": TailSignals(last_kind="agent.say", digest_done="答完了")},
        )

        (card,) = reader.list_sessions()

        assert card.status == "done"
        assert card.digest_done == "答完了"


# ── 适配器注册表 ────────────────────────────────────────────────────
class _StubAdapter:
    def to_unified(self, session_id: str, after: int, limit: int) -> list[UnifiedRecord]:
        return [make_record(session_id=session_id, seq=after)][:limit]

    def read_raw(self, session_id: str, record_id: str) -> dict[str, object] | None:
        return {"session_id": session_id, "id": record_id}


class TestAdapterRegistry:
    def test_没登记时抛不给None(self) -> None:
        """给 None 会让调用方拿着 None 往下走，错在别处才炸。"""
        with pytest.raises(AdapterNotRegistered):
            get_adapter("codex")  # type: ignore[arg-type]

    def test_登记后取得回来(self) -> None:
        stub = _StubAdapter()
        original = get_adapter("opencode")
        register_adapter("opencode", stub)
        try:
            assert get_adapter("opencode") is stub
            assert list_adapters()["opencode"] is stub
        finally:
            # 真身放回去，NEVER 让这条用例把注册表留在打了桩的状态上。
            register_adapter("opencode", original)

    def test_清单是副本改不动注册表(self) -> None:
        stub = _StubAdapter()
        snapshot = list_adapters()
        snapshot["claude-code"] = stub  # type: ignore[assignment]
        assert get_adapter("claude-code") is not stub

    def test_桩件满足适配器形状(self) -> None:
        assert isinstance(_StubAdapter(), RecordAdapter)
