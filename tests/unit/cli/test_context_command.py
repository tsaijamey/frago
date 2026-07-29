"""``frago context`` 命令层。

这一层只做三件事，各钉各的：把无前缀的全盘搜索拦在确认闸后、选输出格式、
把业务层的报错原样转成带修复建议的命令行错误。

确认闸有三条出口：交互终端下问一句、非交互终端下拒绝而不是挂着等、``--yes``
直接放行。第二条尤其重要——agent 是从工具调用里跑这条命令的，那里没有终端，
一个等不到的回车会把整轮任务挂死。
"""

import json
import shutil

import pytest
from click.testing import CliRunner

from frago.cli import context_commands
from frago.cli.context_commands import context_command
from frago.context import data_scheme, whole_home

needs_rg = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep 不在 PATH 上")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "frago_home"
    (root / "data" / "etf-plan").mkdir(parents=True)
    (root / "data" / "etf-plan" / "spec.md").write_text("etf 的计划正文", encoding="utf-8")
    (root / "app-state" / "kline-blind").mkdir(parents=True)
    (root / "app-state" / "kline-blind" / "notes.md").write_text("盲测笔记", encoding="utf-8")
    monkeypatch.setattr(whole_home, "FRAGO_ROOT", root)
    monkeypatch.setattr(data_scheme, "DATA_ROOT", root / "data")
    return root


@pytest.fixture
def tty(monkeypatch):
    """假装有真人坐在终端前，好让确认闸走到真正问问题那一支。

    打的是命令模块里那个判定函数，而不是 ``sys.stdin`` 本身——CliRunner 在
    invoke 期间会把 ``sys.stdin`` 整个换成自己的假对象，对原对象打桩不起作用。
    """
    monkeypatch.setattr(context_commands, "_stdin_is_tty", lambda: True)


class TestSchemeFastPath:
    def test_prefixed_ref_never_prompts(self, runner, home):
        result = runner.invoke(context_command, ["data:etf"])
        assert result.exit_code == 0
        assert "要翻整个" not in result.output
        assert "etf-plan" in result.output

    def test_unknown_scheme_reports_with_a_fix(self, runner, home):
        result = runner.invoke(context_command, ["run:etf"])
        assert result.exit_code == 1
        assert "不认识的 scheme" in result.output
        assert "[Fix] frago context data:etf" in result.output


class TestConsentGate:
    def test_non_interactive_refuses_instead_of_hanging(self, runner, home):
        """没有终端时 MUST 当场拒绝，NEVER 停在那儿等一个不会来的回车。"""
        result = runner.invoke(context_command, ["kline-blind"])
        assert result.exit_code == 1
        assert "不是交互终端" in result.output
        assert "frago context data:kline-blind" in result.output
        assert "frago context kline-blind --yes" in result.output

    def test_declining_aborts_without_searching(self, runner, home, tty, monkeypatch):
        def boom(*_args, **_kwargs):
            raise AssertionError("用户拒绝了却还是动手扫了")

        monkeypatch.setattr(whole_home, "resolve_anywhere", boom)
        result = runner.invoke(context_command, ["kline-blind"], input="n\n")
        assert result.exit_code == 1
        assert "已取消" in result.output

    def test_bare_enter_declines(self, runner, home, tty):
        """默认是否，回车 MUST 不触发那趟又慢又脏的活。"""
        result = runner.invoke(context_command, ["kline-blind"], input="\n")
        assert result.exit_code == 1
        assert "已取消" in result.output

    def test_accepting_runs_the_whole_home_search(self, runner, home, tty):
        result = runner.invoke(context_command, ["kline-blind"], input="y\n")
        assert result.exit_code == 0
        assert "app-state/kline-blind" in result.output

    def test_yes_flag_skips_the_prompt(self, runner, home):
        result = runner.invoke(context_command, ["kline-blind", "--yes"])
        assert result.exit_code == 0
        assert "要翻整个" not in result.output
        assert "app-state/kline-blind" in result.output

    def test_warning_states_the_cost_before_asking(self, runner, home, tty):
        """慢和脏两笔账都要摆出来，否则这道确认就是走过场。

        时间那一笔单独钉住：文案曾经写"实测数秒"，那是只扫名字那一版量的；
        后来加了全文检索，行为变了却没回头重量，确认闸开始低估四倍。报少了
        比不报还糟——调用方是按这个数字决定要不要走的。
        """
        result = runner.invoke(context_command, ["kline-blind"], input="n\n")
        assert "秒" in result.output, "必须给出时间代价"
        assert "全文检索" in result.output, "必须说清楚慢在哪一步"
        assert "几十 GB" in result.output
        assert "浏览器 profile" in result.output
        assert "data:<关键词>" in result.output


class TestOutput:
    def test_three_sections_in_text_mode(self, runner, home):
        result = runner.invoke(context_command, ["data:etf"])
        assert "目录命中" in result.output
        assert "文件名命中" in result.output
        assert "可读内容命中" in result.output

    @needs_rg
    def test_never_prints_file_bodies(self, runner, home):
        """命令层不能把业务层刚砍掉的全文又贴回来。

        正文要远长于摘要窗口才验得出来：文件小到一整篇都装得进摘要时，
        "吐了摘要"和"吐了全文"在输出上没有区别，那样的用例什么也没证明。
        """
        far = "这一段离关键词很远，不该被打印出来"
        (home / "data" / "etf-plan" / "long.md").write_text(
            f"etf 开头\n{'填充' * 3000}\n{far}", encoding="utf-8"
        )
        result = runner.invoke(context_command, ["data:etf"])
        assert "etf-plan/long.md" in result.output
        assert far not in result.output

    def test_json_carries_all_three_tiers(self, runner, home):
        result = runner.invoke(context_command, ["data:etf", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ref"] == "data:etf"
        assert payload["dir_hits"]["listed"][0]["rel"] == "etf-plan"
        assert "total" in payload["file_hits"]
        assert "machine_format_files" in payload["content_hits"]

    def test_json_reports_scan_scope(self, runner, home):
        payload = json.loads(runner.invoke(context_command, ["data:etf", "--json"]).output)
        assert payload["scanned_dirs"] >= 1
        assert "skipped_dirs" in payload
