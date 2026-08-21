"""schedule_executor 的通知回路与原生执行。

这里验的几乎全是「看输出看不出来」的事：任务照样在跑、日志照样有记录，
但该说话时没说、或者不该说时天天说。后者比前者更隐蔽——它不会被报障，
只会让人在两周内学会无视这个通知源。
"""

from datetime import datetime, timedelta

import pytest

from frago.server.services import schedule_executor as ex


def sched(**kw):
    base = {
        "id": "sch_test",
        "name": "测试任务",
        "kind": "recipe",
        "notify": {"on": "change", "to": "desktop", "context": {}},
        "created_at": datetime(2026, 8, 1, 9, 0, 0).isoformat(),
    }
    base.update(kw)
    return base


def ok(**kw):
    d = {"ok": True, "kind": "recipe", "exit_code": 0, "digest": "d1"}
    d.update(kw)
    return ex.RunOutcome(**d)


def bad(**kw):
    d = {"ok": False, "kind": "recipe", "exit_code": 1, "error": "炸了"}
    d.update(kw)
    return ex.RunOutcome(**d)


# --- 沉默必须有意义 ---------------------------------------------------------

class TestChangeIsTheDefault:
    def test_配方没报_notify_就不说话(self):
        d = ex.decide_notification(sched(), ok(notify_text=None), {})
        assert d.should is False

    def test_配方报了_notify_就说话且原话带上(self):
        d = ex.decide_notification(sched(), ok(notify_text="新增 3 位 star"), {})
        assert d.should is True
        assert "新增 3 位 star" in d.text

    def test_always_即使无事也说话(self):
        s = sched(notify={"on": "always", "to": "desktop"})
        assert ex.decide_notification(s, ok(notify_text=None), {}).should is True

    def test_never_连失败都不说(self):
        s = sched(notify={"on": "never", "to": "desktop"})
        assert ex.decide_notification(s, bad(), {}).should is False


class TestCommandChangeDetection:
    def test_首轮只记基线不打扰(self):
        s = sched(kind="command")
        d = ex.decide_notification(s, ok(kind="command", digest="a"), {})
        assert d.should is False
        assert "基线" in d.reason

    def test_输出没变就不说话(self):
        s = sched(kind="command")
        d = ex.decide_notification(s, ok(kind="command", digest="a"), {"last_digest": "a"})
        assert d.should is False

    def test_输出变了才说话(self):
        s = sched(kind="command")
        d = ex.decide_notification(s, ok(kind="command", digest="b", stdout="新内容"),
                                   {"last_digest": "a"})
        assert d.should is True


# --- 失败必须说话，但不能刷屏 -----------------------------------------------

class TestFailureEscalation:
    def test_首次失败一定说(self):
        d = ex.decide_notification(sched(), bad(), {"consecutive_failures": 0})
        assert d.should is True
        assert "失败" in d.text

    def test_第三次失败收敛掉(self):
        d = ex.decide_notification(sched(), bad(), {"consecutive_failures": 2})
        assert d.should is False

    def test_第五次失败再喊一声(self):
        d = ex.decide_notification(sched(), bad(), {"consecutive_failures": 4})
        assert d.should is True
        assert "连续失败 5 次" in d.text

    def test_失败时_on_change_也照样说话(self):
        """任务自己没机会报 notify——它根本没跑完。这时沉默等于把故障藏起来。"""
        s = sched(notify={"on": "change", "to": "desktop"})
        assert ex.decide_notification(s, bad(), {}).should is True

    def test_恢复正常要说一声(self):
        d = ex.decide_notification(sched(), ok(notify_text=None), {"consecutive_failures": 3})
        assert d.should is True
        assert "恢复" in d.text

    def test_没失败过就不会报恢复(self):
        d = ex.decide_notification(sched(), ok(notify_text=None), {"consecutive_failures": 0})
        assert d.should is False


# --- 指纹不能被时间戳污染 ---------------------------------------------------

class TestDigestStability:
    def test_只有时间变了不算变化(self):
        a = ex._stable_for_digest(
            {"total": 59, "generated_at": "2026-08-21T09:00:00Z", "elapsed_sec": 2.4}, "")
        b = ex._stable_for_digest(
            {"total": 59, "generated_at": "2026-08-22T21:00:00Z", "elapsed_sec": 9.9}, "")
        assert a == b, "时间戳进了指纹，会让每一轮都被判成有变化"

    def test_实质变了就是变了(self):
        a = ex._stable_for_digest({"total": 59, "generated_at": "x"}, "")
        b = ex._stable_for_digest({"total": 62, "generated_at": "x"}, "")
        assert a != b


# --- 逾期未跑 ---------------------------------------------------------------

class TestStaleness:
    def test_按时跑的不算逾期(self):
        now = datetime(2026, 8, 22, 10, 0, 0)
        s = sched(last_success_at=(now - timedelta(hours=2)).isoformat())
        assert ex.is_stale(s, now, 12 * 3600) is None

    def test_超过三个周期算逾期(self):
        now = datetime(2026, 8, 22, 10, 0, 0)
        s = sched(last_success_at=(now - timedelta(days=3)).isoformat())
        overdue = ex.is_stale(s, now, 12 * 3600)
        assert overdue is not None and overdue.total_seconds() > 0

    def test_从来没成功过就以创建时间起算(self):
        now = datetime(2026, 8, 22, 10, 0, 0)
        s = sched(created_at=datetime(2026, 8, 1).isoformat(), last_success_at=None)
        assert ex.is_stale(s, now, 3600) is not None

    def test_没有周期就不判逾期(self):
        assert ex.is_stale(sched(), datetime.now(), None) is None

    def test_逾期通知里说得出是哪个任务(self):
        text = ex.staleness_text(sched(name="star 名单"), timedelta(hours=30))
        assert "star 名单" in text
        assert "30 小时" in text


# --- 命令执行 ---------------------------------------------------------------

class TestCommandExecution:
    def test_成功的命令拿得到输出(self):
        r = ex.execute_command("echo 你好", timeout=30)
        assert r.ok is True
        assert r.stdout == "你好"
        assert r.exit_code == 0

    def test_失败的命令带着错误信息回来(self):
        r = ex.execute_command("echo 出事了 >&2; exit 3", timeout=30)
        assert r.ok is False
        assert r.exit_code == 3
        assert "出事了" in r.error

    def test_超时被当成失败而不是挂死(self):
        r = ex.execute_command("sleep 5", timeout=1)
        assert r.ok is False
        assert "超时" in r.error

    def test_相同输出指纹相同(self):
        a = ex.execute_command("echo same", timeout=30)
        b = ex.execute_command("echo same", timeout=30)
        assert a.digest == b.digest


# --- 投递落点 ---------------------------------------------------------------

class TestDelivery:
    def test_落点不认识时说清楚有哪些可选(self):
        s = sched(notify={"on": "change", "to": "不存在的落点", "context": {}})
        r = ex.deliver(s, "文本")
        assert r["status"] == "error"
        assert "不存在的落点" in r["error"]

    def test_pa_落点在队列不可用时明确报错(self):
        s = sched(notify={"on": "change", "to": "pa", "context": {}})
        r = ex.deliver(s, "文本", pa_enqueue=None)
        assert r["status"] == "error"

    def test_pa_落点可用时交回给调用方入队(self):
        s = sched(notify={"on": "change", "to": "pa", "context": {}})
        r = ex.deliver(s, "文本", pa_enqueue=lambda *_: None)
        assert r["status"] == "queued"


# --- 结果解析 ---------------------------------------------------------------

class TestPayloadParsing:
    @pytest.mark.parametrize("field", ["notify", "summary", "notify_text"])
    def test_三种字段名都认(self, field):
        assert ex._extract_notify_field({field: "有事"}) == "有事"

    def test_空字符串不算有事(self):
        assert ex._extract_notify_field({"notify": "   "}) is None

    def test_不是字典就没有通知文本(self):
        assert ex._extract_notify_field("一串文本") is None
