"""账号、口令、会话——身份模块自己的契约。

这些用例大多是 20260817 那两轮审计换来的：每一条对应一种「照着做就会出事」的写法，
而不是对应一个函数。审计报告在
`~/.frago/data/frago-dev/20260817-identity-spec-audit/reports/`。
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from frago.server import identity as ident

GOOD_PASSWORD = "correct-horse-battery-staple"


def _mark_disabled(user_id: str) -> None:
    """停用账号。写入侧的命令属于 Phase 3，这里直接改表模拟它。"""
    raw = json.loads(ident.users_path().read_text(encoding="utf-8"))
    raw[user_id]["disabled"] = True
    ident.users_path().write_text(json.dumps(raw), encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """两张表都指到临时目录。少了这一步用例会写真人的账号表。"""
    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    monkeypatch.delenv("FRAGO_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("FRAGO_PUBLIC_HTTPS", raising=False)
    ident.reset_rate_limits()
    yield
    ident.reset_rate_limits()


class TestDeriveId:
    """邮箱到 slot 名。语义化 slug 会碰撞，碰撞就是两个人共用一份数据。"""

    def test_the_same_address_always_lands_on_the_same_id(self):
        assert ident.derive_id("a@x.com") == ident.derive_id("a@x.com")

    def test_case_and_whitespace_are_the_same_person(self):
        assert ident.derive_id(" A@X.com ") == ident.derive_id("a@x.com")

    def test_a_plus_alias_is_not_the_same_person_as_an_underscore(self):
        """Gmail 加号别名是主流用法。任何把非法字符折叠成下划线的规则都会让
        这两个地址撞成一个 id，而撞了就是互相读写对方的数据。"""
        assert ident.derive_id("a+b@x.com") != ident.derive_id("a_b@x.com")

    def test_the_same_local_part_at_different_domains_stays_apart(self):
        assert ident.derive_id("zhang@a.com") != ident.derive_id("zhang@b.com")

    def test_unicode_normalisation_has_exactly_one_implementation(self):
        """`str.lower()` 与 `str.casefold()` 在 İ(U+0130) 上结果不同。
        两处代码各写一个就会派生出两个 id，同一个人进不去自己的数据。"""
        assert ident.normalize_email("İ@x.com") == ident.normalize_email("İ@x.com")
        assert ident.derive_id("İ@x.com") == ident.derive_id(ident.normalize_email("İ@x.com"))

    def test_an_overlong_address_still_yields_a_usable_filename(self):
        """RFC 允许 320 字节。展开成语义化 slug 会超过文件名上限，
        事后截断更糟——截断即碰撞。"""
        monster = "x" * 64 + "@" + ("y" * 60 + ".") * 3 + "com"
        derived = ident.derive_id(monster)
        assert len(derived) == 32
        assert derived.isalnum()

    def test_the_id_is_a_legal_slot_name(self):
        from frago.recipes.app_state import _SAFE_NAME

        assert _SAFE_NAME.match(ident.derive_id("a@x.com"))


class TestPasswords:
    def test_a_password_round_trips(self):
        encoded = ident.hash_password(GOOD_PASSWORD)
        assert ident.verify_password(GOOD_PASSWORD, encoded)
        assert not ident.verify_password("wrong", encoded)

    def test_the_plaintext_never_appears_in_what_is_stored(self):
        assert GOOD_PASSWORD not in ident.hash_password(GOOD_PASSWORD)

    def test_the_stored_form_carries_its_own_parameters(self):
        """将来调参不能作废旧记录——校验要按串里写的参数走。"""
        encoded = ident.hash_password(GOOD_PASSWORD)
        assert encoded.startswith("scrypt$")
        assert len(encoded.split("$")) == 6

    def test_a_weak_password_is_refused_at_signup(self):
        with pytest.raises(ident.IdentityError):
            ident.authenticate("a@x.com", "123456")


class TestSignInAndSignUp:
    def test_a_new_address_creates_an_account(self):
        user, outcome = ident.authenticate("a@x.com", GOOD_PASSWORD)
        assert outcome == "created"
        assert user.email == "a@x.com"

    def test_the_second_visit_must_use_the_same_password(self):
        ident.authenticate("a@x.com", GOOD_PASSWORD)
        user, outcome = ident.authenticate("a@x.com", GOOD_PASSWORD)
        assert outcome == "ok"
        with pytest.raises(ident.IdentityError):
            ident.authenticate("a@x.com", "another-long-password")

    def test_a_wrong_password_does_not_quietly_create_a_second_account(self):
        ident.authenticate("a@x.com", GOOD_PASSWORD)
        with pytest.raises(ident.IdentityError):
            ident.authenticate("a@x.com", "another-long-password")
        assert len(ident.load_users()) == 1

    def test_a_disabled_account_reads_as_bad_credentials(self):
        """停用不能成为「这个邮箱注册过没有」的探针。"""
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        _mark_disabled(user.id)
        with pytest.raises(ident.IdentityError) as caught:
            ident.authenticate("a@x.com", GOOD_PASSWORD)
        assert caught.value.reason == "bad_credentials"


class TestConcurrency:
    def test_racing_signups_do_not_break_the_cap(self, monkeypatch):
        """整表读-改-写不是原子的。没有文件锁，两个新邮箱同时进来会双双
        读到「还没到上限」，把承重层直接绕过去。"""
        monkeypatch.setenv("FRAGO_MAX_USERS", "8")
        monkeypatch.setenv("FRAGO_MAX_UNUSED_USERS", "8")
        errors: list[Exception] = []
        barrier = threading.Barrier(16)

        def signup(n: int) -> None:
            barrier.wait()
            try:
                ident.authenticate(f"u{n}@x.com", GOOD_PASSWORD)
            except ident.IdentityError:
                pass
            except Exception as exc:  # noqa: BLE001 — 记下来给断言看
                errors.append(exc)

        threads = [threading.Thread(target=signup, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(ident.load_users()) <= 8

    def test_every_issued_session_survives_a_concurrent_burst(self):
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        tokens: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(12)

        def issue() -> None:
            barrier.wait()
            token = ident.create_session(user.id)
            with lock:
                tokens.append(token)

        threads = [threading.Thread(target=issue) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        resolved = [t for t in tokens if ident.resolve_session(t) is not None]
        assert len(resolved) == len(tokens), "签发过的会话不许凭空消失"


class TestSessions:
    def test_the_cookie_value_is_not_what_is_stored(self):
        """会话表被读走，也不能拿里面的东西当 cookie 用。"""
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        token = ident.create_session(user.id)
        on_disk = " ".join(p.read_text() + p.stem for p in ident.sessions_dir().glob("*.json"))
        assert token not in on_disk

    def test_a_session_pointing_at_a_vanished_account_is_signed_out(self, caplog):
        """查不到账号绝不能当成「不是停用所以放行」——那是个运维工具看不见、
        也停不掉的幽灵会话。"""
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        token = ident.create_session(user.id)
        ident.users_path().write_text("{}", encoding="utf-8")
        assert ident.resolve_session(token) is None

    def test_disabling_an_account_takes_effect_on_the_next_request(self):
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        token = ident.create_session(user.id)
        _mark_disabled(user.id)
        assert ident.resolve_session(token) is None

    def test_changing_the_password_drops_the_other_sessions(self):
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        stale = ident.create_session(user.id)
        ident.set_password(user.id, "a-different-long-password")
        assert ident.resolve_session(stale) is None

    def test_revoking_one_session_leaves_the_others_alone(self):
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        doomed = ident.create_session(user.id)
        keeper = ident.create_session(user.id)
        ident.revoke_session(doomed)
        assert ident.resolve_session(doomed) is None
        assert ident.resolve_session(keeper) is not None

    def test_an_unknown_cookie_resolves_to_nobody(self):
        assert ident.resolve_session("not-a-real-token") is None


class TestRateLimitingAndTheGate:
    """限速这一层是本模块第一次把攻击者可控的值变成安全决策的键。"""

    def test_the_address_is_worthless_behind_an_undeclared_proxy(self, monkeypatch):
        monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
        monkeypatch.delenv("FRAGO_TRUSTED_PROXIES", raising=False)
        assert ident.ip_rate_limiting_available() is False
        assert ident.client_ip({"client": ("10.0.0.1", 1)}) is None

    def test_declaring_the_proxies_brings_the_layer_back(self, monkeypatch):
        monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
        monkeypatch.setenv("FRAGO_TRUSTED_PROXIES", "127.0.0.1")
        assert ident.ip_rate_limiting_available() is True

    def test_a_missing_layer_is_covered_by_another_one(self, monkeypatch):
        """限速不可用时口令自动变成不可关——缺的那层要被顶上，不能静默消失。"""
        monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
        monkeypatch.delenv("FRAGO_TRUSTED_PROXIES", raising=False)
        monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
        assert ident.signup_gate_required() is True
        assert ident.check_signup_gate(None) is False
        with pytest.raises(ident.IdentityError) as caught:
            ident.authenticate("a@x.com", GOOD_PASSWORD)
        assert caught.value.reason == "gate_required"

    def test_the_gate_lets_the_right_passphrase_through(self, monkeypatch):
        monkeypatch.setenv("FRAGO_SIGNUP_GATE", "open-sesame")
        assert ident.check_signup_gate("open-sesame") is True
        assert ident.check_signup_gate("wrong") is False

    def test_the_gate_only_guards_signup(self, monkeypatch):
        """口令泄露后换一个，不该把已有的人锁在门外。"""
        monkeypatch.setenv("FRAGO_SIGNUP_GATE", "first")
        ident.authenticate("a@x.com", GOOD_PASSWORD, gate="first")
        monkeypatch.setenv("FRAGO_SIGNUP_GATE", "second")
        user, outcome = ident.authenticate("a@x.com", GOOD_PASSWORD)
        assert outcome == "ok"


class TestAccountCaps:
    def test_a_flood_of_empty_accounts_does_not_lock_out_the_next_person(self, monkeypatch):
        """纯拒绝的上限，挡住的是所有还没来过的真实体验者——
        500 个请求就能永久关掉这个功能。无数据的账号要被淘汰掉腾位。"""
        monkeypatch.setenv("FRAGO_MAX_USERS", "50")
        monkeypatch.setenv("FRAGO_MAX_UNUSED_USERS", "5")
        for i in range(5):
            ident.authenticate(f"junk{i}@x.com", GOOD_PASSWORD)
        newcomer, outcome = ident.authenticate("real@x.com", GOOD_PASSWORD)
        assert outcome == "created", "配额满了也要让新人进得来"
        assert ident.find_user_by_id(newcomer.id) is not None


class TestOnDisk:
    def test_neither_table_is_readable_by_other_accounts(self):
        if os.name == "nt":
            pytest.skip("POSIX permission bits")
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        ident.create_session(user.id)
        assert ident.users_path().stat().st_mode & 0o077 == 0
        assert ident.sessions_dir().stat().st_mode & 0o077 == 0
        for path in ident.sessions_dir().glob("*.json"):
            assert path.stat().st_mode & 0o077 == 0

    def test_a_corrupt_users_table_does_not_take_the_server_down(self):
        ident.users_path().parent.mkdir(parents=True, exist_ok=True)
        ident.users_path().write_text("{ not json", encoding="utf-8")
        assert ident.load_users() == {}

    def test_the_table_is_reread_when_another_process_changes_it(self):
        """`frago user disable` 是另一个进程在改文件。按时长的 TTL 缓存会把
        「下一次请求即失效」变成「最多 N 秒后失效」。"""
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        assert ident.find_user_by_id(user.id) is not None
        raw = json.loads(ident.users_path().read_text(encoding="utf-8"))
        raw[user.id]["disabled"] = True
        ident.users_path().write_text(json.dumps(raw), encoding="utf-8")
        assert ident.find_user_by_id(user.id).disabled is True


class TestCookieSecurity:
    @pytest.mark.parametrize(
        ("scheme", "public_https", "expected"),
        [("https", False, True), ("wss", False, True), ("http", False, False), ("http", True, True)],
    )
    def test_secure_follows_this_request_not_a_global_switch(
        self, monkeypatch, scheme, public_https, expected
    ):
        """依据必须是这条连接是不是 TLS。挂在别的开关上，在裸 HTTP 部署
        与 HTTPS sidecar 两种形态下都会让凭条明文上路。"""
        monkeypatch.setenv("FRAGO_PUBLIC_HTTPS", "1" if public_https else "0")
        assert ident.cookie_is_secure({"scheme": scheme}) is expected


class TestPurgeIsNotTriggerHappy:
    """清理程序跑在每一次签发上，所以它和签发是并发的。

    20260817：签发先把文件建成空的再写内容，中间那一瞬另一个线程的清理
    读不懂它、判定为坏、删掉——刚发给用户的会话就这么没了。
    """

    def test_a_file_being_written_right_now_is_left_alone(self):
        directory = ident.sessions_dir()
        directory.mkdir(parents=True, exist_ok=True)
        newborn = directory / ("a" * 64 + ".json")
        newborn.write_text("", encoding="utf-8")   # 空的，正如写到一半

        ident.purge_expired_sessions()

        assert newborn.exists(), "刚出生还没写完的会话文件不许被当成垃圾清掉"

    def test_something_that_has_been_rubbish_for_ages_does_get_swept(self, monkeypatch):
        import time as _time

        directory = ident.sessions_dir()
        directory.mkdir(parents=True, exist_ok=True)
        junk = directory / ("b" * 64 + ".json")
        junk.write_text("{ not json", encoding="utf-8")
        ancient = _time.time() - (ident.session_ttl() + 3600)
        os.utime(junk, (ancient, ancient))

        ident.purge_expired_sessions()

        assert not junk.exists(), "真正的垃圾还是要扫掉，否则目录只涨不落"

    def test_an_expired_session_still_goes(self):
        user, _ = ident.authenticate("a@x.com", GOOD_PASSWORD)
        token = ident.create_session(user.id)
        path = next(iter(ident.sessions_dir().glob("*.json")))
        record = json.loads(path.read_text(encoding="utf-8"))
        record["expires"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(record), encoding="utf-8")

        ident.purge_expired_sessions()

        assert ident.resolve_session(token) is None
