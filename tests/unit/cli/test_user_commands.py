"""`frago user` —— 主人对来访者能做的四件事，加上会话那两件。

这些用例守的不是「命令跑得通」，是几条真出过事、或出了事就没法补救的性质：

* 运维视图里绝不能出现密码材料——一次 `frago user list` 会进终端回滚、进
  screen 日志、进对话记录；
* 改密与停用必须**立刻**让旧凭条作废，否则「我怀疑 cookie 被偷了」这件事在
  这套没有找回流程的设计里就无解；
* 密码只能走隐藏输入。命令行参数对同机其他账号可见（`ps -ww`），还会落进
  shell history；
* 登录会话挂在 `frago user session` 之下，顶层 `frago session` 一个子命令都不许少——
  click 的同名 `add_command` 是静默覆盖，20260817 已经因此把 `frago recipe publish`
  顶掉过一次，所有带界面的配方从 WebUI 点运行都打不开页面。
"""

from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from frago.cli import user_commands
from frago.cli.main import cli
from frago.server import identity as ident

GOOD_PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "another-entirely-different-one"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """两张表加身份 slot 根都指到临时目录。少一处用例就会写真人的账号表。"""
    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setattr(ident, "USER_STATE_DIR", tmp_path / "app-state-users")
    for name in ("FRAGO_USERS_FILE", "FRAGO_SESSIONS_DIR", "FRAGO_USER_STATE_DIR",
                 "FRAGO_SIGNUP_GATE", "FRAGO_BEHIND_PROXY", "FRAGO_TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    ident.reset_rate_limits()
    yield
    ident.reset_rate_limits()


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def visitor():
    """一个来过的人，手里有两张凭条（两台设备）。"""
    user, _ = ident.authenticate("zhang@example.com", GOOD_PASSWORD)
    return user, ident.create_session(user.id), ident.create_session(user.id)


def _run(runner, args, **kwargs):
    return runner.invoke(user_commands.user_group, args, **kwargs)


class TestList:
    def test_it_shows_the_id_email_pairing(self, runner, visitor):
        user, _, _ = visitor
        result = _run(runner, ["list"])
        assert result.exit_code == 0, result.output
        assert user.id in result.output
        assert "zhang@example.com" in result.output

    def test_every_line_says_the_address_is_unverified(self, runner, visitor):
        """没有验证环节，所以这张表记的是「谁先用了这个地址」，
        不是「这个地址属于谁」。运维看到的每一行都要带着这句话。"""
        ident.authenticate("li@example.com", GOOD_PASSWORD)
        lines = [ln for ln in _run(runner, ["list"]).output.splitlines() if "@example.com" in ln]
        assert len(lines) == 2
        assert all("unverified" in line for line in lines)

    def test_no_password_material_comes_out(self, runner, visitor):
        """哈希串本身也不行：它进终端就进了回滚缓冲和会话记录。"""
        stored = json.loads(ident.users_path().read_text(encoding="utf-8"))
        hashes = [rec["pwd"] for rec in stored.values()]
        assert hashes and hashes[0].startswith("scrypt$")

        for args in (["list"], ["list", "--format", "json"], ["list", "--recent"]):
            output = _run(runner, args).output
            for field in ("pwd", "scrypt$", "password", GOOD_PASSWORD):
                assert field not in output, f"{args} 漏出了 {field}"
            for encoded in hashes:
                assert encoded not in output

    def test_the_json_shape_says_the_address_is_unverified_too(self, runner, visitor):
        payload = json.loads(_run(runner, ["list", "--format", "json"]).output)
        assert payload["users"][0]["email_verified"] is False
        assert "pwd" not in payload["users"][0]

    def test_an_empty_table_is_not_an_error(self, runner):
        result = _run(runner, ["list"])
        assert result.exit_code == 0
        assert "No accounts" in result.output

    def test_recent_puts_the_last_seen_first(self, runner):
        quiet, _ = ident.authenticate("quiet@example.com", GOOD_PASSWORD)
        busy, _ = ident.authenticate("busy@example.com", GOOD_PASSWORD)
        ident.create_session(busy.id)

        lines = [ln for ln in _run(runner, ["list", "--recent"]).output.splitlines()
                 if "@example.com" in ln]
        assert lines[0].startswith(busy.id)
        assert lines[1].startswith(quiet.id)


class TestPasswd:
    def test_the_password_is_never_a_command_line_argument(self):
        """`ps -ww` 对同机其他账号是敞开的，shell history 还会留几个月。
        所以这个命令连一个能接收密码的形参都不该有。"""
        params = user_commands.user_passwd.params
        assert [p.name for p in params] == ["who"]
        assert all(not isinstance(p, click.Option) for p in params)
        assert "--password" not in (user_commands.user_passwd.get_help(
            click.Context(user_commands.user_passwd)))

    def test_the_prompt_hides_what_is_typed(self, runner, visitor, monkeypatch):
        seen = {}

        def fake_prompt(text, **kwargs):
            seen.update(kwargs)
            return NEW_PASSWORD

        monkeypatch.setattr(user_commands.click, "prompt", fake_prompt)
        result = _run(runner, ["passwd", "zhang@example.com"])
        assert result.exit_code == 0, result.output
        assert seen.get("hide_input") is True
        assert seen.get("confirmation_prompt") is True

    def test_what_was_typed_is_not_echoed_back(self, runner, visitor):
        result = _run(runner, ["passwd", "zhang@example.com"],
                      input=f"{NEW_PASSWORD}\n{NEW_PASSWORD}\n")
        assert result.exit_code == 0, result.output
        assert NEW_PASSWORD not in result.output

    def test_the_old_sessions_stop_working(self, runner, visitor):
        """改密的全部意义就在这里：旧口令连同用它做出来的凭条一起失效。"""
        user, one, two = visitor
        assert ident.resolve_session(one) is not None

        result = _run(runner, ["passwd", user.id], input=f"{NEW_PASSWORD}\n{NEW_PASSWORD}\n")
        assert result.exit_code == 0, result.output

        assert ident.resolve_session(one) is None
        assert ident.resolve_session(two) is None
        assert ident.list_sessions() == []

    def test_the_new_password_is_the_one_that_works(self, runner, visitor):
        user, _, _ = visitor
        _run(runner, ["passwd", user.id], input=f"{NEW_PASSWORD}\n{NEW_PASSWORD}\n")

        assert ident.verify_user_password(user.id, NEW_PASSWORD)
        with pytest.raises(ident.IdentityError):
            ident.authenticate("zhang@example.com", GOOD_PASSWORD)

    def test_a_weak_new_password_is_refused_without_touching_anything(self, runner, visitor):
        user, one, _ = visitor
        result = _run(runner, ["passwd", user.id], input="123456\n123456\n")
        assert result.exit_code != 0
        assert ident.verify_user_password(user.id, GOOD_PASSWORD)
        assert ident.resolve_session(one) is not None

    def test_an_unknown_account_fails_loudly(self, runner):
        result = _run(runner, ["passwd", "nobody@example.com"])
        assert result.exit_code != 0
        assert "No account" in result.output


class TestDisableAndEnable:
    def test_disabling_stops_the_next_login(self, runner, visitor):
        user, _, _ = visitor
        assert _run(runner, ["disable", user.id]).exit_code == 0

        with pytest.raises(ident.IdentityError) as caught:
            ident.authenticate("zhang@example.com", GOOD_PASSWORD)
        assert caught.value.reason == "bad_credentials"

    def test_disabling_does_not_quietly_create_a_second_account(self, runner, visitor):
        user, _, _ = visitor
        _run(runner, ["disable", user.id])
        with pytest.raises(ident.IdentityError):
            ident.authenticate("zhang@example.com", GOOD_PASSWORD)
        assert len(ident.load_users()) == 1

    def test_the_live_cookies_go_too(self, runner, visitor):
        """不等过期——停用的承诺是「下一次请求就不认」。"""
        user, one, two = visitor
        _run(runner, ["disable", user.id])
        assert ident.resolve_session(one) is None
        assert ident.resolve_session(two) is None

    def test_the_row_stays_and_says_disabled(self, runner, visitor):
        """删账号会让它名下的数据变成孤儿，所以是停用不是删除。"""
        user, _, _ = visitor
        _run(runner, ["disable", user.id])
        assert ident.find_user_by_id(user.id) is not None
        assert "disabled" in _run(runner, ["list"]).output

    def test_enabling_lets_them_back_in(self, runner, visitor):
        user, _, _ = visitor
        _run(runner, ["disable", user.id])
        assert _run(runner, ["enable", user.id]).exit_code == 0
        _, outcome = ident.authenticate("zhang@example.com", GOOD_PASSWORD)
        assert outcome == "ok"

    def test_disabling_twice_is_not_an_error(self, runner, visitor):
        user, _, _ = visitor
        _run(runner, ["disable", user.id])
        result = _run(runner, ["disable", user.id])
        assert result.exit_code == 0
        assert "already disabled" in result.output


class TestReferences:
    """id 是 32 位十六进制，没人记得住。邮箱与 id 前缀都要能用，但歧义要报错。"""

    def test_an_email_finds_the_account(self, runner, visitor):
        assert _run(runner, ["disable", "ZHANG@Example.com"]).exit_code == 0
        assert ident.find_user_by_id(visitor[0].id).disabled is True

    def test_a_unique_id_prefix_works(self, runner, visitor):
        user, _, _ = visitor
        assert _run(runner, ["disable", user.id[:6]]).exit_code == 0

    def test_an_ambiguous_prefix_refuses_to_guess(self, runner):
        """停错人这件事不能靠再跑一次来补救。空前缀是所有账号的前缀。"""
        ident.authenticate("a@example.com", GOOD_PASSWORD)
        ident.authenticate("b@example.com", GOOD_PASSWORD)
        result = _run(runner, ["disable", ""])
        assert result.exit_code != 0
        assert "matches 2 accounts" in result.output
        assert all(not u.disabled for u in ident.list_users())

    def test_a_typo_is_an_error_not_a_no_op(self, runner, visitor):
        result = _run(runner, ["disable", "deadbeef"])
        assert result.exit_code != 0
        assert "No account matching" in result.output


class TestSessions:
    def test_it_lists_who_is_signed_in(self, runner, visitor):
        result = _run(runner, ["session", "list"])
        assert result.exit_code == 0, result.output
        assert result.output.count("zhang@example.com") == 2

    def test_what_is_printed_is_not_a_usable_cookie(self, runner, visitor):
        """列表里出现的是服务端存的哈希，不是凭条本身。"""
        _, one, two = visitor
        output = _run(runner, ["session", "list"]).output
        assert one not in output
        assert two not in output

    def test_revoking_kills_exactly_one_cookie(self, runner, visitor):
        """运维手上只有列表里的 id，没有凭条；踢一张不能连坐另一张。"""
        _, one, two = visitor
        target = ident.list_sessions()[0].sid

        result = _run(runner, ["session", "revoke", target])
        assert result.exit_code == 0, result.output

        alive = [token for token in (one, two) if ident.resolve_session(token) is not None]
        assert len(alive) == 1
        assert len(ident.list_sessions()) == 1

    def test_a_prefix_of_the_id_is_enough(self, runner, visitor):
        target = ident.list_sessions()[0].sid
        assert _run(runner, ["session", "revoke", target[:10]]).exit_code == 0
        assert [s.sid for s in ident.list_sessions()] != [target]

    def test_revoking_something_that_is_not_there_fails_loudly(self, runner, visitor):
        result = _run(runner, ["session", "revoke", "ffffffffffff"])
        assert result.exit_code != 0
        assert "No live session" in result.output

    def test_an_empty_list_is_not_an_error(self, runner):
        result = _run(runner, ["session", "list"])
        assert result.exit_code == 0
        assert "Nobody is signed in" in result.output

    def test_the_json_shape_carries_no_cookie(self, runner, visitor):
        _, one, _ = visitor
        payload = json.loads(_run(runner, ["session", "list", "--format", "json"]).output)
        assert len(payload["sessions"]) == 2
        assert payload["sessions"][0]["email"] == "zhang@example.com"
        assert one not in json.dumps(payload)


class TestTheNamespaceItLandedIn:
    """登录会话挂在 `frago user session`。顶层 `frago session` 是 agent 会话记录，
    click 的同名注册是静默覆盖——往那里加一条，就少一条。"""

    def test_login_sessions_hang_under_user(self):
        user = cli.get_command(click.Context(cli), "user")
        session = user.get_command(click.Context(user), "session")
        assert isinstance(session, click.Group)
        assert set(session.list_commands(click.Context(session))) == {"list", "revoke"}

    def test_the_agent_session_group_still_has_all_seven(self):
        group = cli.get_command(click.Context(cli), "session")
        available = set(group.list_commands(click.Context(group)))
        missing = [c for c in
                   ("list", "search", "show", "watch", "clean", "delete", "sync")
                   if c not in available]
        assert not missing, f"frago session 少了子命令：{missing}"

    def test_frago_session_list_is_still_the_agent_transcript_one(self):
        """名字对了不够，得是原来那个东西。"""
        group = cli.get_command(click.Context(cli), "session")
        listing = group.get_command(click.Context(group), "list")
        assert "user session list" not in (listing.help or "")

    def test_the_user_group_has_exactly_the_documented_commands(self):
        user = cli.get_command(click.Context(cli), "user")
        assert set(user.list_commands(click.Context(user))) == {
            "list", "passwd", "disable", "enable", "session",
        }
