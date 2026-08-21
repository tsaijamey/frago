"""数据仓库那一页背后的判断。

这页要扛的是真实规模：一台天天在用的机器，~/.frago 里两万多个文件待提交是常态。
所以这里锁三件事——清点不能把整份索引塞进响应、按目录的归并要算对（那是唯一能让
五位数变得能看的视图）、以及交给 agent 的那份任务书里，AGENTS.md 中仍然有效的
硬规则一条都不能漏，已经失效的契约一条都不能混进去。
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services import data_repo_service as svc
from frago.server.services.data_repo_service import (
    DataRepoSync,
    build_sync_prompt,
    get_policy,
    get_status,
)


def _porcelain(*entries: str) -> str:
    """git status --porcelain -z 的输出形状：NUL 分隔、结尾也有一个 NUL。"""
    return "".join(entry + "\0" for entry in entries)


def _fake_git(status_out: str = "", **overrides):
    """按子命令派发的假 git。"""
    defaults = {
        "remote": "https://github.com/someone/frago-working-dir\n",
        "rev-parse": "main\n",
        "rev-list": "0 4\n",
        "log": "abc123def456\x1fchore: 上一次备份\x1f2026-08-20T23:49:52+08:00\n",
        "status": status_out,
    }
    defaults.update(overrides)

    def run(*args, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = defaults.get(args[0], "")
        return result

    return run


class TestGetStatus:
    def test_not_a_repo_is_a_setup_state_not_an_error(self, tmp_path: Path):
        """没初始化过的目录要能渲染成一句人话，而不是抛异常。"""
        with patch.object(svc, "repo_path", return_value=tmp_path):
            result = get_status()

        assert result["configured"] is False
        assert result["error"] is None
        assert result["pending_total"] == 0

    def test_counts_every_file_and_groups_by_area(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        entries = _porcelain(
            " M books/registry.json",
            " M books/etf/notes.md",
            " D sessions/claude-misc/a/x.jsonl",
            " D sessions/claude-misc/b/y.jsonl",
            "?? data/新任务/report.md",
            " M hook-rules.json",
        )
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=_fake_git(entries)
        ):
            result = get_status()

        assert result["pending_total"] == 6
        assert result["counts"] == {"modified": 3, "deleted": 2, "untracked": 1}
        # 归并按第一层目录，带斜杠；根文件保持原样。
        rollup = {row["area"]: row["count"] for row in result["rollup"]}
        assert rollup == {"books/": 2, "sessions/": 2, "data/": 1, "hook-rules.json": 1}

    def test_rollup_is_ordered_by_size(self, tmp_path: Path):
        """最大的那一堆要排在最前面——它才是决定用户下一步做什么的那个数字。"""
        (tmp_path / ".git").mkdir()
        entries = _porcelain(
            " M a/one",
            " D b/one",
            " D b/two",
            " D b/three",
            " M c/one",
            " M c/two",
        )
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=_fake_git(entries)
        ):
            result = get_status()

        assert [row["area"] for row in result["rollup"]] == ["b/", "c/", "a/"]

    def test_file_list_is_capped_but_totals_are_not(self, tmp_path: Path):
        """两万条路径塞进 JSON 只是把墙搬到浏览器里；总数照实说，清单给样本。"""
        (tmp_path / ".git").mkdir()
        entries = _porcelain(*[f" M data/f{i}.json" for i in range(300)])
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=_fake_git(entries)
        ):
            result = get_status(limit=50)

        assert result["pending_total"] == 300
        assert len(result["files"]) == 50
        assert result["truncated"] is True

    def test_untruncated_when_everything_fits(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=_fake_git(_porcelain(" M a.json", " M b.json"))
        ):
            result = get_status(limit=50)

        assert result["truncated"] is False
        assert len(result["files"]) == 2

    def test_rename_does_not_get_counted_twice(self, tmp_path: Path):
        """-z 下改名会多带一条旧路径，跟着算就会虚报待备份数量。"""
        (tmp_path / ".git").mkdir()
        entries = "R  recipes/new.py\0recipes/old.py\0 M books/x.md\0"
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=_fake_git(entries)
        ):
            result = get_status()

        assert result["pending_total"] == 2
        assert result["counts"]["renamed"] == 1

    def test_reports_ahead_and_behind(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=_fake_git("", **{"rev-list": "2 7\n"})
        ):
            result = get_status()

        # git 的顺序是 左=落后 右=领先。
        assert result["behind"] == 2
        assert result["ahead"] == 7

    def test_a_wedged_git_says_so_instead_of_hanging_the_page(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        with patch.object(svc, "repo_path", return_value=tmp_path), patch.object(
            svc, "_git", side_effect=subprocess.TimeoutExpired("git", 30)
        ):
            result = get_status()

        assert result["error"]
        assert "超时" in result["error"]


class TestPolicy:
    def test_names_both_halves(self):
        """只说不备份什么会让这个按钮显得没意义；两边都要给。"""
        policy = get_policy()
        assert policy["excluded"] and policy["included"]

    def test_every_excluded_category_says_why(self):
        """「不备份」不给理由，用户就只能猜是不是坏了。"""
        for category in get_policy()["excluded"]:
            assert category["why"].strip()
            assert category["examples"]

    def test_credentials_are_called_out(self):
        keys = {c["key"] for c in get_policy()["excluded"]}
        assert "secret" in keys


class TestSyncPrompt:
    """交给 agent 的任务书。写错一条，agent 就会拿用户的仓库去执行它。"""

    def test_release_the_confirmation_gate(self):
        """/git-push 的常规流程会停下等人点头。这里没人在终端前面，停了就是挂死。"""
        prompt = build_sync_prompt("all")
        assert "用户已经在界面上确认过了" in prompt
        assert "不要再呈现方案等人点头" in prompt

    def test_carries_the_hard_rules_that_still_apply(self):
        prompt = build_sync_prompt("all")
        assert "git add -f" in prompt          # 禁止绕过 .gitignore
        assert "git ls-files -c -i --exclude-standard" in prompt  # 提交前自检
        assert "git pull --rebase" in prompt   # 推送前先 rebase

    def test_deletions_get_their_own_rule(self):
        """成规模删除按普通改动提交，会把仓库里那份一起删掉。"""
        prompt = build_sync_prompt("all")
        assert "归因" in prompt
        assert "停下来报告" in prompt

    def test_drops_the_contracts_that_expired(self):
        """AGENTS.md 里的历史部分不该进任务书——照着做只会做错事。

        `--allow-unrelated-histories` 是 2026-05 那次 filter-repo 留下的一次性
        分支，历史早已收敛；留着它等于邀请 agent 在该 rebase 的时候去 merge。
        """
        prompt = build_sync_prompt("all")
        assert "allow-unrelated-histories" not in prompt
        assert "filter-repo" not in prompt
        assert "sync_repo.py" not in prompt
        assert "reset --hard" not in prompt

    def test_never_signs_as_a_non_human(self):
        prompt = build_sync_prompt("all")
        assert "git config user.name" in prompt

    def test_selective_mode_quotes_the_user_and_fences_the_scope(self):
        prompt = build_sync_prompt("selective", "只传今天改的配方，data 别动")
        assert "只传今天改的配方，data 别动" in prompt
        assert "范围之外的改动**这次不要碰**" in prompt

    def test_selective_without_words_falls_back_to_everything(self):
        """空指令下不该出现一段引用空话的范围限定。"""
        prompt = build_sync_prompt("selective", "   ")
        assert "这次备份全部符合条件的改动" in prompt


class TestSyncLifecycle:
    """一个工作区上同时跑两个 agent 提交，会交错出谁都没打算要的 commit。"""

    def setup_method(self):
        DataRepoSync.reset()

    def teardown_method(self):
        DataRepoSync.reset()

    def test_starts_the_agent_in_the_data_repo(self, tmp_path: Path):
        started = {}

        def fake_start(prompt, project_path=None, **kwargs):
            started["prompt"] = prompt
            started["cwd"] = project_path
            return {"status": "ok", "id": "t1", "claude_session_id": "s1", "pid": 4242}

        with patch.object(svc, "repo_path", return_value=tmp_path), patch(
            "frago.server.services.agent_service.AgentService.start_task", fake_start
        ):
            result = DataRepoSync.start("all")

        assert result["status"] == "ok"
        assert started["cwd"] == str(tmp_path)
        assert "分组提交" in started["prompt"]
        assert result["task"]["session_id"] == "s1"

    def test_a_second_press_does_not_start_a_second_agent(self):
        with patch(
            "frago.server.services.agent_service.AgentService.start_task",
            return_value={"status": "ok", "id": "t1", "claude_session_id": "s1", "pid": 4242},
        ), patch.object(DataRepoSync, "_is_running_locked", return_value=True):
            DataRepoSync._current = {"task_id": "t1", "pid": 4242}
            result = DataRepoSync.start("all")

        assert result["status"] == "error"
        assert result["already_running"] is True

    def test_a_finished_agent_stops_reading_as_running(self):
        DataRepoSync._current = {"task_id": "t1", "pid": 4242}
        with patch("os.kill", side_effect=ProcessLookupError):
            assert DataRepoSync.get()["running"] is False

    def test_a_live_agent_reads_as_running(self):
        DataRepoSync._current = {"task_id": "t1", "pid": 4242}
        with patch("os.kill", return_value=None):
            assert DataRepoSync.get()["running"] is True

    def test_a_failed_launch_is_not_recorded_as_a_run(self):
        with patch(
            "frago.server.services.agent_service.AgentService.start_task",
            return_value={"status": "error", "error": "frago command not found"},
        ):
            result = DataRepoSync.start("all")

        assert result["status"] == "error"
        assert DataRepoSync.get()["running"] is False
        assert DataRepoSync.get()["task"] is None


class TestCredentialsAreNamedNotJustCategorized:
    """~/.frago 根目录下躺着几个凭据文件，而那份 .gitignore 并没有忽略它们。

    server-token 是本机 /api 的 bearer，remotes.json 里是别的机器的 token。一个写着
    「全部备份」的按钮如果只给 agent 一句「注意凭据」，它完全可能把这两个当成普通的
    根级 json 提交上去。所以任务书里点名，并且明说「没被忽略」不构成可以提交的理由。
    """

    @pytest.mark.parametrize(
        "name",
        ["server-token", "remotes.json", "config.yaml", "users.json", "login-sessions/"],
    )
    def test_each_credential_file_is_named(self, name):
        assert name in build_sync_prompt("all")

    def test_says_gitignore_silence_is_not_permission(self):
        prompt = build_sync_prompt("all")
        assert "无论 .gitignore 里有没有写" in prompt
        assert "不能拿「它没被忽略」当成可以提交的理由" in prompt

    def test_selective_mode_carries_the_same_guard(self):
        """圈定范围不该把凭据那道闸一起圈掉。"""
        assert "server-token" in build_sync_prompt("selective", "把根目录下的东西传上去")
