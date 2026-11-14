"""frago ask CLI 交互组件生成工具的单元测试。

覆盖：
1. 4 类交互组件（single-choice、multi-choice、text-answer、choice-and-text）的正常输出结构；
2. 选项的 JSON 格式与管道分隔简写格式（KEY|LABEL|EFFECT[|FLAGS]）解析；
3. 参数错误（缺必填项、选项格式写错、把 effect 写成 description、跨组件混用参数、传未知参数、传未知子命令）时立即报错退出（exit_code != 0），且仅返回对应组件类型的正确示例；
4. schedule_pending.card_in 对 frago ask 输出 JSON 的识别。
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from frago.cli.ask_commands import ask_group
from frago.server.services import schedule_pending as sp


class TestAskSingleChoice:
    def test_single_choice_json_options(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "本次需要执行到哪一步？",
                "--why",
                "SIT 环境拥有 98 家真实样本数据",
                "-o",
                '{"key":"A","label":"全量改造 + SIT 验证","effect":"改代码、跑单测并更新 SIT","recommended":true}',
                "-o",
                '{"key":"B","label":"仅本地改造","effect":"只修改本地仓库代码与单测","reversible":false}',
            ],
        )
        assert res.exit_code == 0, res.output
        assert "\n" not in res.output.strip(), "output must be single-line JSON so | tail / | head never truncates it"
        payload = json.loads(res.output)
        assert payload["frago_ui_component"] == "decision-card"
        assert payload["component_type"] == "single-choice"
        data = payload["data"]
        assert data["type"] == "single-choice"
        assert data["question"] == "本次需要执行到哪一步？"
        assert data["why"] == "SIT 环境拥有 98 家真实样本数据"
        assert "multi" not in data
        assert "suggestions" not in data
        assert len(data["options"]) == 2
        assert data["options"][0] == {
            "key": "A",
            "label": "全量改造 + SIT 验证",
            "effect": "改代码、跑单测并更新 SIT",
            "recommended": True,
            "reversible": True,
        }
        assert data["options"][1] == {
            "key": "B",
            "label": "仅本地改造",
            "effect": "只修改本地仓库代码与单测",
            "recommended": False,
            "reversible": False,
        }

    def test_single_choice_pipe_shorthand_and_teammate_fields(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "队友请求修改 hook 规则，是否批准？",
                "--from-teammate",
                "--request",
                "修改收尾提醒触发条件",
                "--changes",
                "~/.frago/hook/builtin-rules.json",
                "-o",
                "A|批准|按请求修改规则|recommended",
                "-o",
                "B|拒绝|保持原样不动|irreversible",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "\n" not in res.output.strip(), "output must be single-line JSON so | tail / | head never truncates it"
        payload = json.loads(res.output)
        data = payload["data"]
        assert data["from"] == "teammate"
        assert data["request"] == "修改收尾提醒触发条件"
        assert data["changes"] == "~/.frago/hook/builtin-rules.json"
        assert data["options"][0]["recommended"] is True
        assert data["options"][1]["reversible"] is False


class TestAskMultiChoice:
    def test_multi_choice_valid(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "multi-choice",
                "-q",
                "本次需要同步更新哪些环境？",
                "-o",
                "A|SIT 环境|写入 SIT Admin DB|recommended",
                "-o",
                "B|本地单测|跑通全量 pytest",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "\n" not in res.output.strip(), "output must be single-line JSON so | tail / | head never truncates it"
        payload = json.loads(res.output)
        assert payload["component_type"] == "multi-choice"
        assert payload["data"]["type"] == "multi-choice"
        assert len(payload["data"]["options"]) == 2


class TestAskTextAnswer:
    def test_text_answer_with_draft_and_suggestions(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "text-answer",
                "-q",
                "请确认物理表名：",
                "--draft",
                "rtm_data",
                "-s",
                "rtm_data",
                "-s",
                "cust_engage_rtm_summary",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "\n" not in res.output.strip(), "output must be single-line JSON so | tail / | head never truncates it"
        payload = json.loads(res.output)
        assert payload["component_type"] == "text-answer"
        data = payload["data"]
        assert data["type"] == "text-answer"
        assert data["draft"] == "rtm_data"
        assert data["suggestions"] == ["rtm_data", "cust_engage_rtm_summary"]
        assert "options" not in data


class TestAskChoiceAndText:
    def test_choice_and_text_with_multi_and_draft(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "choice-and-text",
                "-q",
                "请选择处理范围（可补充说明）：",
                "--multi",
                "--draft",
                "默认按全 BG 汇总计算",
                "-o",
                "A|支持可选 bg 参数|按对应 BG 计算",
                "-o",
                "B|暂不增加 bg 参数|仅保留 l2_mdm_id",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "\n" not in res.output.strip(), "output must be single-line JSON so | tail / | head never truncates it"
        payload = json.loads(res.output)
        assert payload["component_type"] == "choice-and-text"
        data = payload["data"]
        assert data["type"] == "choice-and-text"
        assert data["multi"] is True
        assert data["draft"] == "默认按全 BG 汇总计算"
        assert len(data["options"]) == 2


class TestAskFriendlyErrorFeedback:
    def test_missing_options_returns_only_single_choice_example(self):
        runner = CliRunner()
        res = runner.invoke(ask_group, ["single-choice", "-q", "选哪个？"])
        assert res.exit_code != 0
        assert "single-choice 组件必须提供 --option" in res.output
        assert "frago app ask single-choice" in res.output
        assert "frago app ask text-answer" not in res.output
        assert "frago app ask multi-choice" not in res.output

    def test_description_instead_of_effect_gives_targeted_hint(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "选哪个？",
                "-o",
                '{"key":"A","label":"选项A","description":"误写成 description"}',
            ],
        )
        assert res.exit_code != 0
        assert "缺少必填字段 'effect'（检测到传了 'description'" in res.output
        assert "frago app ask single-choice" in res.output
        assert "frago app ask text-answer" not in res.output

    def test_unknown_flag_on_subcommand_returns_component_example(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["multi-choice", "--title", "错误标题", "-q", "选哪些？"],
        )
        assert res.exit_code != 0
        assert "--title" in res.output
        assert "frago app ask multi-choice" in res.output
        assert "frago app ask single-choice" not in res.output

    def test_cross_component_misplaced_flag_rejected(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "选哪个？",
                "--draft",
                "草稿不能用在 single-choice",
                "-o",
                "A|选项A|后果A",
            ],
        )
        assert res.exit_code != 0
        assert "--draft 仅支持 text-answer 与 choice-and-text 组件" in res.output
        assert "frago app ask single-choice" in res.output
        assert "frago app ask choice-and-text" not in res.output

    def test_duplicate_recommended_rejected(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "选哪个？",
                "-o",
                "A|选项A|后果A|recommended",
                "-o",
                "B|选项B|后果B|recommended",
            ],
        )
        assert res.exit_code != 0
        assert "至多只能标记 1 个推荐项" in res.output
        assert "frago app ask single-choice" in res.output

    def test_unknown_component_type_returns_four_types_overview(self):
        runner = CliRunner()
        res = runner.invoke(ask_group, ["approve-irreversible", "-q", "旧类型名"])
        assert res.exit_code != 0
        assert "未知的交互组件类型 'approve-irreversible'" in res.output
        assert "single-choice" in res.output
        assert "multi-choice" in res.output
        assert "text-answer" in res.output
        assert "choice-and-text" in res.output


class TestAskKeyShape:
    """选项 KEY 是短标识：卡片上只占一个 18 像素小方块，答复也靠 `·` 切回来。

    2026-11-13 修：此前只查非空与唯一，`IMPL_DYNAMIC` 这类整句被当 KEY 写进卡片，
    前端方块装不下就溢出去压住标题。这里把「KEY 必须短」钉成命令侧的硬校验。
    """

    # ── 放行：短标识 ──────────────────────────────────────────────────
    @pytest.mark.parametrize("key", ["A", "B", "C", "HOLD", "RETRY", "OPT-1", "OPT_1", "APPROVE"])
    def test_short_keys_accepted(self, key):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", f"{key}|选项|后果"],
        )
        assert res.exit_code == 0, res.output
        assert json.loads(res.output)["data"]["options"][0]["key"] == key

    def test_eight_char_boundary_accepted(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", "ABCDEFGH|选项|后果"],
        )
        assert res.exit_code == 0, res.output
        assert json.loads(res.output)["data"]["options"][0]["key"] == "ABCDEFGH"

    # ── 拒绝：截图上那两张真实卡片用的长 KEY ────────────────────────────
    @pytest.mark.parametrize("key", ["IMPL_DYNAMIC", "REPLY_JIRA"])
    def test_long_keys_rejected_with_rule_hint(self, key):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", f"{key}|选项|后果"],
        )
        assert res.exit_code != 0
        assert f"KEY '{key}'" in res.output
        assert "超过 8 个字符的上限" in res.output
        assert "推荐直接用 A、B、C" in res.output
        # 只回当前题型示例，不串到别的题型
        assert "frago app ask single-choice" in res.output
        assert "frago app ask text-answer" not in res.output

    def test_nine_chars_rejected(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", "ABCDEFGHI|选项|后果"],
        )
        assert res.exit_code != 0
        assert "超过 8 个字符的上限" in res.output

    # ── 拒绝：分隔符与空白 ─────────────────────────────────────────────
    @pytest.mark.parametrize("key", ["A B", "AB\tC", "AB·C", "AB|C"])
    def test_separators_and_whitespace_rejected(self, key):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", f"{key}|选项|后果"],
        )
        assert res.exit_code != 0, f"KEY {key!r} 应当被拒"

    def test_pipe_in_key_cannot_smuggle_extra_field(self):
        """KEY 里塞竖线会把 KEY|LABEL|EFFECT 切错位——必须在解析后仍被形状校验拦住。"""
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", "A|B|选项|后果"],
        )
        assert res.exit_code != 0
        assert "KEY" in res.output

    @pytest.mark.parametrize("key", ["选项", "选项A"])
    def test_cjk_key_rejected(self, key):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", f"{key}|选项|后果"],
        )
        assert res.exit_code != 0

    @pytest.mark.parametrize("key", ["A.B", "A/B", "A+B", "A:B", "A·B"])
    def test_symbol_keys_rejected(self, key):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            ["single-choice", "-q", "选哪个？", "-o", f"{key}|选项|后果"],
        )
        assert res.exit_code != 0

    # ── 四条带选项的入口共用同一道闸 ────────────────────────────────────
    @pytest.mark.parametrize(
        "argv",
        [
            ["multi-choice", "-q", "选哪些？", "-o", "IMPL_DYNAMIC|选项|后果"],
            ["choice-and-text", "-q", "选哪个？", "-o", "IMPL_DYNAMIC|选项|后果"],
            ["choice-and-text", "-q", "选哪些？", "--multi", "-o", "IMPL_DYNAMIC|选项|后果"],
        ],
    )
    def test_all_option_types_share_the_key_gate(self, argv):
        runner = CliRunner()
        res = runner.invoke(ask_group, argv)
        assert res.exit_code != 0
        assert "超过 8 个字符的上限" in res.output

    # ── JSON 写法与简写写法都过同一道闸 ─────────────────────────────────
    def test_json_option_key_also_checked(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "选哪个？",
                "-o",
                '{"key":"IMPL_DYNAMIC","label":"按动态字号改造","effect":"启动新任务"}',
            ],
        )
        assert res.exit_code != 0
        assert "超过 8 个字符的上限" in res.output

    def test_json_short_key_still_accepted(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "选哪个？",
                "-o",
                '{"key":"HOLD","label":"暂不处理","effect":"仅记录结果"}',
            ],
        )
        assert res.exit_code == 0, res.output
        assert json.loads(res.output)["data"]["options"][0]["key"] == "HOLD"

    # ── 报错文案要能让人当场改对 ────────────────────────────────────────
    def test_help_documents_key_shape(self):
        runner = CliRunner()
        res = runner.invoke(ask_group, ["single-choice", "--help"])
        assert res.exit_code == 0
        assert "KEY 是短标识" in res.output
        assert "1–8 个字符" in res.output


class TestSchedulePendingIntegration:
    def test_card_in_recognizes_frago_ask_json_output(self):
        runner = CliRunner()
        res = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "是否绑定 SIT 现有物理表 rtm_data？",
                "-o",
                "A|绑定 rtm_data|直接查询 commercial_sit.public.rtm_data|recommended",
                "-o",
                "B|预留切换能力|在配置中预留表名切换",
            ],
        )
        assert res.exit_code == 0
        card = sp.card_in(res.output)
        assert card is not None
        assert card["question"] == "是否绑定 SIT 现有物理表 rtm_data？"
        assert card["options"] == ["绑定 rtm_data", "预留切换能力"]
        assert card["recommended"] == "绑定 rtm_data"
