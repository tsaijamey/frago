"""``frago app propose`` CLI 非阻塞提案命令单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from frago.cli.apps_commands import apps_group
from frago.cli.ask_commands import ask_group
from frago.cli.propose_commands import propose_group
from frago.decision_inbox import get_decision_inbox_service


@pytest.fixture(autouse=True)
def _isolated_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    inbox_dir = tmp_path / "decision-inbox"
    monkeypatch.setenv("FRAGO_DECISION_INBOX_DIR", str(inbox_dir))
    for key in (
        "FRAGO_SESSION_ORIGIN",
        "FRAGO_UNATTENDED",
        "FRAGO_AGENT_ROLE",
        "FRAGO_ALLOW_INTERACTIVE_ASK",
        "FRAGO_SESSION_ID",
        "FRAGO_SCHEDULE_ID",
        "FRAGO_SCHEDULE_NAME",
        "FRAGO_EMPLOYEE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    return inbox_dir


class TestProposeSubcommands:
    def test_single_choice_and_all_fields(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            propose_group,
            [
                "single-choice",
                "-q",
                "是否删除 3 个过期备份表？",
                "-w",
                "连续 30 天未被引用",
                "--dedup-key",
                "db:drop-stale",
                "--risk",
                "high",
                "--irreversible",
                "--ttl-hours",
                "48",
                "--impact-scope",
                "analytics.backup_* (3 tables)",
                "--evidence",
                "pg_stat_user_tables 0 scans",
                "--skip-reason",
                "不可逆删表动作，无人值守跳过",
                "-o",
                "A|永久删除|执行 DROP TABLE",
                "-o",
                "B|保留归档|仅记录不删除",
                "--recommended",
                "B",
                "--schedule-id",
                "sch_db_clean",
                "--schedule-name",
                "夜间巡检",
            ],
        )
        assert res.exit_code == 0, res.output
        out = json.loads(res.output)
        assert out["frago_proposal"] is True
        assert out["dedup_key"] == "db:drop-stale"
        assert out["deduped"] is False
        assert out["occurrence_count"] == 1
        assert out["status"] == "pending"
        assert out["risk"] == "high"
        assert out["irreversible"] is True
        assert out["recommended"] == "B"
        assert out["ttl_hours"] == 48.0

        svc = get_decision_inbox_service()
        saved = svc.get(out["proposal_id"])
        assert saved["impact_scope"] == "analytics.backup_* (3 tables)"
        assert saved["evidence"] == "pg_stat_user_tables 0 scans"
        assert saved["skip_reason"] == "不可逆删表动作，无人值守跳过"
        assert saved["schedule_id"] == "sch_db_clean"
        assert saved["schedule_name"] == "夜间巡检"

    def test_binary_auto_synthesizes_options(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            propose_group,
            [
                "binary",
                "-q",
                "确认对外发送本周月报邮件？",
                "--dedup-key",
                "mail:monthly",
                "--risk",
                "high",
                "--irreversible",
                "--recommended",
                "reject",
            ],
        )
        assert res.exit_code == 0, res.output
        out = json.loads(res.output)
        assert out["action_type"] == "binary"
        assert out["recommended"] == "reject"
        item = get_decision_inbox_service().get(out["proposal_id"])
        assert [o["key"] for o in item["options"]] == ["approve", "reject"]

    def test_multi_choice_and_text_answer(self) -> None:
        runner = CliRunner()
        res_multi = runner.invoke(
            propose_group,
            [
                "multi-choice",
                "-q",
                "本轮需对外推送哪些渠道？",
                "--dedup-key",
                "push:channels",
                "--risk",
                "medium",
                "-o",
                "A|飞书群|推送日报摘要",
                "-o",
                "B|邮件|发送客户简报",
                "--recommended",
                "A",
            ],
        )
        assert res_multi.exit_code == 0, res_multi.output
        assert json.loads(res_multi.output)["action_type"] == "multi-choice"

        res_text = runner.invoke(
            propose_group,
            [
                "text-answer",
                "-q",
                "请补充下月预算调整备注",
                "--dedup-key",
                "budget:note",
                "--draft",
                "保持上月预算上限不变",
                "-s",
                "维持原值",
            ],
        )
        assert res_text.exit_code == 0, res_text.output
        out_text = json.loads(res_text.output)
        assert out_text["action_type"] == "text-answer"
        item = get_decision_inbox_service().get(out_text["proposal_id"])
        assert item["draft"] == "保持上月预算上限不变"
        assert item["suggestion"] == "维持原值"


class TestProposeDedupAndUnattended:
    def test_same_dedup_key_three_times_aggregates_in_place(self) -> None:
        runner = CliRunner()
        ids: list[str] = []
        expires: list[float] = []
        for idx in range(1, 4):
            res = runner.invoke(
                propose_group,
                [
                    "binary",
                    "-q",
                    "发现过期日志目录，是否清理？",
                    "--dedup-key",
                    "logs:prune",
                    "--risk",
                    "medium",
                    "--evidence",
                    f"第 {idx} 次巡检发现",
                ],
            )
            assert res.exit_code == 0, res.output
            payload = json.loads(res.output)
            ids.append(payload["proposal_id"])
            expires.append(payload["expires_at"])
            assert payload["occurrence_count"] == idx
            assert payload["deduped"] is (idx > 1)

        assert len(set(ids)) == 1
        assert len(set(expires)) == 1
        assert len(get_decision_inbox_service().list_items()) == 1

    @pytest.mark.parametrize(
        ("env_name", "env_value"),
        [
            ("FRAGO_SESSION_ORIGIN", "schedule"),
            ("FRAGO_UNATTENDED", "1"),
            ("FRAGO_AGENT_ROLE", "worker"),
        ],
    )
    def test_unattended_allows_propose_while_blocking_ask(
        self, monkeypatch: pytest.MonkeyPatch, env_name: str, env_value: str
    ) -> None:
        monkeypatch.setenv(env_name, env_value)
        runner = CliRunner()

        res_propose = runner.invoke(
            apps_group,
            [
                "propose",
                "binary",
                "-q",
                "不可逆生产变更确认",
                "--dedup-key",
                f"unattended:{env_name}",
                "--irreversible",
            ],
        )
        assert res_propose.exit_code == 0, res_propose.output
        assert json.loads(res_propose.output)["frago_proposal"] is True

        res_ask = runner.invoke(
            ask_group,
            [
                "single-choice",
                "-q",
                "不可逆生产变更确认",
                "-o",
                "A|执行|立刻变更",
            ],
        )
        assert res_ask.exit_code != 0
        assert "frago app propose" in res_ask.output

    def test_apps_list_includes_propose(self) -> None:
        runner = CliRunner()
        res = runner.invoke(apps_group, ["list", "--format", "json"])
        assert res.exit_code == 0, res.output
        names = {item["name"] for item in json.loads(res.output)}
        assert "propose" in names
        assert "ask" in names


class TestProposeValidationErrors:
    def test_invalid_inputs_fail_with_guidance(self) -> None:
        runner = CliRunner()

        res_no_q = runner.invoke(propose_group, ["binary"])
        assert res_no_q.exit_code != 0
        assert "--question" in res_no_q.output

        res_bad_key = runner.invoke(
            propose_group,
            ["single-choice", "-q", "选哪个", "-o", "TOO_LONG_KEY_123|标签|说明"],
        )
        assert res_bad_key.exit_code != 0

        res_bad_rec = runner.invoke(
            propose_group,
            ["single-choice", "-q", "选哪个", "-o", "A|标签|说明", "--recommended", "Z"],
        )
        assert res_bad_rec.exit_code != 0

        res_opt_on_text = runner.invoke(
            propose_group,
            ["text-answer", "-q", "请填写", "-o", "A|标签|说明"],
        )
        assert res_opt_on_text.exit_code != 0

        res_unknown = runner.invoke(propose_group, ["bad-type"])
        assert res_unknown.exit_code != 0


class TestProposeJsonOptionReversible:
    def test_json_option_preserves_reversible_flag(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            propose_group,
            [
                "single-choice",
                "-q",
                "确认执行生产切流策略？",
                "--dedup-key",
                "rollout:reversible-opt",
                "-o",
                '{"key":"A","label":"灰度 10%","effect":"可随时回滚","reversible":true,"recommended":true}',
                "-o",
                '{"key":"B","label":"全量切换","effect":"覆盖生产流量，不可回退","reversible":false}',
            ],
        )
        assert res.exit_code == 0, res.output
        out = json.loads(res.output)
        saved = get_decision_inbox_service().get(out["proposal_id"])
        by_key = {opt["key"]: opt for opt in saved["options"]}
        assert by_key["A"]["reversible"] is True
        assert by_key["A"]["recommended"] is True
        assert by_key["B"]["reversible"] is False
        assert by_key["B"]["recommended"] is False
