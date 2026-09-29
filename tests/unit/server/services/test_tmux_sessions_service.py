"""会话清点这一层的判据。

锁住的是三件「错了人就白清一场」的事：闲置时长按哪个时刻算、每行那段正文能不能
认出会话、批量关会不会连累没被选中的会话。
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from frago.server.services import tmux_sessions_service as svc


class TestExcerpt:
    """浮窗每行那句话——它是人认出「这是哪一场会话」的唯一线索。"""

    def test_skips_a_leading_heading_that_says_nothing(self):
        # 回答常以「**结论**」单独起一行开头。把它截进来等于一个字没说。
        text = "**结论**\n\n大盘状态改由引擎每轮算好写进当天结果。"
        assert svc._excerpt(text, 80) == "大盘状态改由引擎每轮算好写进当天结果。"

    def test_drops_rule_lines_and_flattens_the_rest(self):
        text = "已经删掉了。\n---\n没有别的配方依赖它。"
        assert svc._excerpt(text, 80) == "已经删掉了。 没有别的配方依赖它。"

    def test_truncates_at_the_caller_s_limit(self):
        # 截多长由调用方定——不同行宽要的长度不一样，服务端不写死。
        assert svc._excerpt("一" * 50, 10) == "一" * 10 + "…"

    def test_strips_inline_markdown_that_only_eats_the_budget(self):
        # 截取是一段纯文本，星号和反引号在这里既不加粗也不高亮，只占字数。
        text = "**已重建**并核对：`index-BH4jhbsn.js`"
        assert svc._excerpt(text, 80) == "已重建并核对：index-BH4jhbsn.js"

    def test_drops_a_table_separator_row(self):
        text = "下好了也转完了。\n| 视频 | 时长 |\n|---|---|\nBV1g1bg6WEtX | 15.3 分钟"
        assert "---" not in svc._excerpt(text, 120)

    def test_empty_text_stays_empty(self):
        assert svc._excerpt("", 80) == ""


class TestIdleAnchor:
    """闲置时长的锚点。

    **NEVER 取 tmux 的活动时间。** claude 的状态栏一直在刷 token 计数，pane 上有字
    变化 tmux 就把活动时间往前推；实测同一批会话，「上次真正说完话」与「tmux 活动
    时间」能差出四个多小时。照后者清理等于什么都清不掉。
    """

    def _fake_verdict(self, *, done: bool, ts: datetime | None, text: str = "说完了"):
        class V:
            pass

        v = V()
        v.done = done
        v.stop_reason = "end_turn" if done else "tool_use"
        v.last_terminal_ts = ts
        v.final_text = text
        return v

    def _run(self, verdict):
        with (
            patch.object(svc, "_session_names", return_value=["frago-agent-s1"]),
            patch.object(svc, "_tmux", return_value="pane text"),
            patch.object(svc, "_pane_pids", return_value={"frago-agent-s1": [1]}),
            patch.object(svc, "_memory_mb", return_value={1: 200}),
            patch.object(svc, "_managed_ids", return_value=set()),
            patch.object(svc, "_is_busy", return_value=False),
            patch.object(svc, "_resolve_session_id", return_value="sid-1"),
            patch.object(svc, "_transcript_path", return_value=__import__("pathlib").Path("/x")),
            patch("frago.session.transcript_completion.evaluate_file", return_value=verdict),
        ):
            return svc.list_sessions()

    def test_idle_is_measured_from_the_last_finished_turn(self):
        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        rows = self._run(self._fake_verdict(done=True, ts=two_hours_ago))

        assert rows[0].idle_secs == pytest.approx(7200, abs=60)
        assert rows[0].last_stop_at is not None
        assert rows[0].memory_mb == 200

    def test_an_unfinished_turn_reports_no_idle_time_at_all(self):
        # 还没说完就没有「说完之后过了多久」这回事。编一个 0 出来，界面会把一场
        # 正在干活的会话显示成刚刚才闲下来。
        rows = self._run(self._fake_verdict(done=False, ts=None))

        assert rows[0].idle_secs is None
        assert rows[0].last_stop_at is None

    def test_falls_back_to_an_older_reply_when_the_current_turn_has_no_text(self):
        # 正在跑工具的那一轮往往一个字都没有。那一行要是空的，人就认不出这是哪一场。
        verdict = self._fake_verdict(done=False, ts=None, text="")
        with patch.object(svc, "_last_assistant_text", return_value="上一轮说过的话"):
            rows = self._run(verdict)

        assert rows[0].excerpt == "上一轮说过的话"


class TestClose:
    """关闭。**NEVER kill-server**——那会把没被选中的、正在干活的会话一起带走。"""

    def test_names_each_session_one_by_one(self):
        with (
            patch.object(svc, "subprocess") as sub,
            patch("frago.server.services.ui_session_runner.get_runner") as runner,
        ):
            runner.return_value.evict.return_value = False
            sub.run.return_value.returncode = 0
            svc.close_sessions(["frago-agent-a", "frago-agent-b"])

        calls = [c.args[0] for c in sub.run.call_args_list]
        assert calls == [
            ["tmux", "kill-session", "-t", "frago-agent-a"],
            ["tmux", "kill-session", "-t", "frago-agent-b"],
        ]
        # 整条命令行里不许出现 kill-server / pkill，一个都不许。
        assert not any("kill-server" in " ".join(c) or "pkill" in " ".join(c) for c in calls)

    def test_a_failure_does_not_stop_the_rest(self):
        # 批量里一条报错就整批中止，人不知道哪些已经关了、哪些还在。
        with (
            patch.object(svc, "subprocess") as sub,
            patch("frago.server.services.ui_session_runner.get_runner") as runner,
        ):
            runner.return_value.evict.return_value = False
            first = type("P", (), {"returncode": 1, "stderr": "can't find session"})()
            second = type("P", (), {"returncode": 0, "stderr": ""})()
            sub.run.side_effect = [first, second]
            results = svc.close_sessions(["frago-agent-gone", "frago-agent-ok"])

        assert [r["ok"] for r in results] == [False, True]
        assert results[0]["error"] == "can't find session"

    def test_a_pooled_session_is_evicted_through_the_pool(self):
        # 池里那些会话的把手在内存里，绕过池直接 kill 会让页面下次投喂拿着一个
        # 已经死掉的把手去 send。
        with (
            patch.object(svc, "subprocess") as sub,
            patch("frago.server.services.ui_session_runner.get_runner") as runner,
        ):
            runner.return_value.evict.return_value = True
            results = svc.close_sessions(["frago-agent-pooled"])

        assert results[0] == {"name": "frago-agent-pooled", "ok": True, "via": "pool", "error": None}
        sub.run.assert_not_called()


class TestFindForSession:
    """按会话编号反着找它那具 tmux——「结束运行」那个按钮按下去走的第一步。

    这一步错了有两种后果：找错人（关掉别人的会话）或者找不到人（人按了没反应，
    而那具壳还占着几百兆）。
    """

    SID = "9f1c2b3a-1111-2222-3333-444455556666"

    def _find(self, names, *, resolve=None):
        with (
            patch.object(svc, "_session_names", return_value=names),
            patch.object(svc, "_tmux", return_value="pane text"),
            patch.object(svc, "_pane_pids", return_value={f"frago-agent-{self.SID}": [1]}),
            patch.object(svc, "_memory_mb", return_value={1: 320}),
            patch.object(svc, "_managed_ids", return_value=set()),
            patch.object(svc, "_is_busy", return_value=False),
            patch.object(svc, "_resolve_session_id", side_effect=resolve or (lambda label, pane: None)),
        ):
            return svc.find_for_session(self.SID)

    def test_a_workbench_session_is_matched_by_name_without_reading_any_pane(self):
        # 工作台自己开的会话，tmux 名字里那截就是编号，一次字符串比较就够——不必为了
        # 认它去逐个读屏。
        called = []

        def resolve(label, pane):
            called.append(label)
            return None

        link = self._find(
            [f"frago-agent-{self.SID}", "frago-agent-feishu_oc_abc"], resolve=resolve
        )

        assert link is not None
        assert link.name == f"frago-agent-{self.SID}"
        assert link.memory_mb == 320
        assert called == []

    def test_a_session_whose_name_is_a_business_handle_is_matched_by_reading_the_pane(self):
        # 飞书群、语音、命令行起的那些，名字是业务把手，编号只在屏上自报的那行里。
        link = self._find(
            ["frago-agent-feishu_oc_abc"],
            resolve=lambda label, pane: self.SID if label == "feishu_oc_abc" else None,
        )

        assert link is not None
        assert link.name == "frago-agent-feishu_oc_abc"
        assert link.label == "feishu_oc_abc"

    def test_no_live_session_returns_nothing_at_all(self):
        # 找不到就是找不到。编一个名字回去，下一步会照着它去关，关掉的是别人。
        assert self._find(["frago-agent-someone-else"]) is None

    def test_no_tmux_at_all_returns_nothing(self):
        assert self._find([]) is None


class TestForYouSignals:
    """会话页「For you」要的三项：客户端活不活、停没停在待输入态、收尾原话。

    判不出一律给 None，前端一律不挂——宁可漏挂，也不误挂。
    """

    def test_shell_in_the_foreground_means_the_client_is_gone(self):
        assert svc._client_alive("zsh") is False
        assert svc._client_alive("-bash") is False

    def test_a_version_number_in_the_foreground_is_a_live_claude(self):
        # claude 把进程名改成自己的版本号，按「叫不叫 claude」判会失灵
        assert svc._client_alive("2.1.281") is True

    def test_unknown_foreground_is_unknown(self):
        assert svc._client_alive("") is None
        assert svc._client_alive(None) is None

    def test_dead_client_is_never_waiting(self):
        assert svc._awaiting_input("❯ \n", False) is False

    def test_unknown_client_cannot_be_judged(self):
        assert svc._awaiting_input("❯ \n", None) is None

    def test_closing_text_keeps_the_end(self):
        text = "前情" * 400 + "\n\n要我把这条记成待办吗？"
        out = svc._closing_text(text, 50)
        assert out.startswith("…")
        assert out.endswith("要我把这条记成待办吗？")

    def test_closing_text_keeps_paragraphs_and_drops_headings(self):
        text = "**结论**\n\n做完了。\n\n---\n\n你来定：A or B."
        assert svc._closing_text(text) == "做完了。\n\n你来定：A or B."

    def test_non_claude_rows_are_not_judged(self):
        # 认不出记录（opencode / codex / 非 frago 起的）不套 claude 的判据
        with (
            patch.object(svc, "_session_names", return_value=["frago-agent-oc", "misc"]),
            patch.object(svc, "_pane_commands", return_value={"frago-agent-oc": "opencode", "misc": "vim"}),
            patch.object(svc, "_tmux", return_value="┃ Build · Ask anything\n"),
            patch.object(svc, "_resolve_session_id", return_value="sid-oc"),
            patch.object(svc, "_transcript_path", return_value=None),
        ):
            rows = svc.list_waiting()
        assert [r.awaiting_input for r in rows] == [None, None]
        assert rows[0].client_alive is True

    def test_claude_row_waiting_in_an_empty_box(self):
        pane = "⏺ 做完了。\n\n────\n❯\xa0\x1b[2mA, go ahead\x1b[0m\n────\n"
        with (
            patch.object(svc, "_session_names", return_value=["frago-agent-s1"]),
            patch.object(svc, "_pane_commands", return_value={"frago-agent-s1": "2.1.281"}),
            patch.object(svc, "_tmux", return_value=pane),
            patch.object(svc, "_resolve_session_id", return_value="sid-1"),
            patch.object(svc, "_transcript_path", return_value=__import__("pathlib").Path("/x")),
            patch.object(svc, "_transcript_tail", return_value=("end_turn", "2026-09-24T13:11:00+00:00", "A or B?")),
        ):
            (row,) = svc.list_waiting()
        assert row.awaiting_input is True
        assert row.last_stop_at == "2026-09-24T13:11:00+00:00"
        assert row.closing_text == "A or B?"
