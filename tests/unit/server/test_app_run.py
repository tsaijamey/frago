"""The one thing a signed-in visitor may make this server do.

Everything else the identity zone reaches only reads files. This route starts a
process, so the tests are mostly about the four ways it refuses to — and about
the response saying as little as possible when it does.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security
from frago.server.routes import app_run

PAGE = "ledger"
PASSWORD = "correct-horse-battery"
VISITOR = ("93.184.216.34", 41234)


DECLARED = {
    "note": {"type": "string", "required": False, "max_length": 20},
    "amount": {"type": "number", "required": False, "min": 0, "max": 100},
}


class _Meta:
    ui_from = None

    def __init__(self, inputs):
        self.name = PAGE
        self.inputs = inputs


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    monkeypatch.setenv("FRAGO_TRUST_LAN", "0")
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    for leak in ("FRAGO_USERS_FILE", "FRAGO_SESSIONS_DIR", "FRAGO_SIGNUP_GATE"):
        monkeypatch.delenv(leak, raising=False)
    security.ensure_token()
    ident.reset_rate_limits()
    app_run._running.clear()

    assets = tmp_path / "recipes" / PAGE / "assets"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("<h1>ledger</h1>", encoding="utf-8")

    # What the recipe declares on disk, and the singleton registry that only
    # learns about it when something scans. The real one behaves exactly this
    # way — scanned once per process, refreshed only where a caller asks
    # whether it is still current — and the difference matters here because a
    # visitor's parameters are checked strictly against whichever it is.
    disk = {"inputs": dict(DECLARED)}
    singleton = []

    class _Recipe:
        base_dir = tmp_path / "recipes" / PAGE
        script_path = tmp_path / "recipes" / PAGE / "recipe.py"

        def __init__(self, inputs):
            self.metadata = _Meta(inputs)

    class _Registry:
        def __init__(self):
            self.scanned = dict(disk["inputs"])

        def needs_rescan(self):
            return self.scanned != disk["inputs"]

        def find(self, name, source=None):
            if name != PAGE:
                raise RecipeNotFoundError(name, [])
            return _Recipe(self.scanned)

    def _get_registry():
        if not singleton:
            singleton.append(_Registry())
        return singleton[0]

    monkeypatch.setattr("frago.recipes.registry.get_registry", _get_registry)
    monkeypatch.setattr("frago.recipes.registry.invalidate_registry", singleton.clear)

    people = {}
    for who, email in (("zhang", "zhang@example.com"), ("li", "li@example.com")):
        user = ident.create_user(email, PASSWORD)
        people[who] = {"id": user.id, "cookie": ident.create_session(user.id)}

    pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[people["zhang"]["id"]], runnable=True)

    yield {"people": people, "root": tmp_path, "disk": disk, "registry": _get_registry}
    ident.reset_rate_limits()
    app_run._running.clear()


@pytest.fixture
def ran(monkeypatch):
    """Capture what the runner would have been asked to do, without doing it."""
    seen = {}

    class _Runner:
        def run(self, name, params=None, **kwargs):
            seen["name"] = name
            seen["params"] = params
            seen["ctx"] = kwargs.get("ctx")
            return {"success": True}

    monkeypatch.setattr("frago.recipes.runner.RecipeRunner", _Runner)
    return seen


def _client(cookie=None):
    from frago.server.app import create_app

    client = TestClient(create_app(), follow_redirects=False, client=VISITOR)
    if cookie:
        client.cookies.set(ident.COOKIE_NAME, cookie)
    return client


def _post(cookie, params=None):
    return _client(cookie).post(f"/app/{PAGE}/run", json={"params": params or {}})


class TestWhoMayStartOne:
    def test_anonymous_may_not(self, world):
        r = _client().post(f"/app/{PAGE}/run", json={"params": {}})
        assert r.status_code == 401

    def test_signed_in_but_off_the_list_may_not(self, world, ran):
        r = _post(world["people"]["li"]["cookie"])
        assert r.status_code == 401
        assert ran == {}

    def test_someone_on_the_list_may(self, world, ran):
        r = _post(world["people"]["zhang"]["cookie"])
        assert r.status_code == 202
        assert r.json() == {"accepted": True}

    def test_a_page_that_is_not_runnable_refuses(self, world, ran):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["people"]["zhang"]["id"]])
        r = _post(world["people"]["zhang"]["cookie"])
        assert r.status_code == 404
        assert ran == {}

    def test_an_unpublished_page_refuses_the_same_way(self, world, ran):
        pub.unpublish(PAGE)
        r = _post(world["people"]["zhang"]["cookie"])
        assert r.status_code in (401, 404)
        assert ran == {}


class TestTheParametersAreNotTakenOnTrust:
    def test_an_undeclared_parameter_is_refused(self, world, ran):
        """Eleven installed recipes read `params["data_dir"]` and use it as a
        path. An undeclared key from a stranger is not a harmless extra."""
        r = _post(world["people"]["zhang"]["cookie"], {"data_dir": "/etc"})
        assert r.status_code == 400
        assert ran == {}

    def test_a_value_past_its_declared_limit_is_refused(self, world, ran):
        r = _post(world["people"]["zhang"]["cookie"], {"note": "x" * 100})
        assert r.status_code == 400
        assert ran == {}

    def test_a_number_out_of_range_is_refused(self, world, ran):
        assert _post(world["people"]["zhang"]["cookie"], {"amount": 999}).status_code == 400
        assert _post(world["people"]["zhang"]["cookie"], {"amount": -1}).status_code == 400
        assert ran == {}

    def test_a_declared_parameter_within_its_limits_goes_through(self, world, ran):
        r = _post(world["people"]["zhang"]["cookie"], {"note": "rent", "amount": 12})
        assert r.status_code == 202
        assert ran["params"] == {"note": "rent", "amount": 12}

    def test_a_body_that_is_not_json_is_refused(self, world, ran):
        r = _client(world["people"]["zhang"]["cookie"]).post(
            f"/app/{PAGE}/run", content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400
        assert ran == {}


class TestAParameterAddedAfterTheServerStarted:
    """A recipe edited while the server runs, and the page shipped with it.

    Strict validation reads the registry's snapshot, and the registry is
    scanned once per process. Left alone, the owner never sees this — loose
    validation lets an undeclared key through — while every visitor is told
    their new parameter "is not declared by this recipe" although the recipe
    on disk declares it, until some unrelated route happens to rescan.
    """

    def test_it_is_accepted(self, world, ran):
        world["disk"]["inputs"]["force"] = {"type": "boolean", "required": False}
        r = _post(world["people"]["zhang"]["cookie"], {"note": "rent", "force": True})
        assert r.status_code == 202
        assert ran["params"] == {"note": "rent", "force": True}

    def test_a_parameter_removed_after_the_scan_is_refused(self, world, ran):
        """The same freshness in the other direction: what the recipe no longer
        declares must stop being accepted, not linger until a restart."""
        world["disk"]["inputs"].pop("note")
        assert _post(world["people"]["zhang"]["cookie"], {"note": "rent"}).status_code == 400
        assert ran == {}

    def test_an_unchanged_recipe_is_not_rescanned(self, world, ran):
        before = world["registry"]()
        assert _post(world["people"]["zhang"]["cookie"], {"note": "rent"}).status_code == 202
        assert world["registry"]() is before

    def test_a_freshness_check_that_fails_does_not_fail_the_run(self, world, ran):
        """The snapshot in hand is still a usable answer; refusing over a failed
        stat would turn a transient filesystem error into a broken page."""
        def _boom():
            raise OSError("no")

        world["registry"]().needs_rescan = _boom
        assert _post(world["people"]["zhang"]["cookie"], {"note": "rent"}).status_code == 202


class TestTheRunIsForThatPersonOnly:
    def test_the_context_names_the_caller(self, world, ran):
        _post(world["people"]["zhang"]["cookie"])
        ctx = ran["ctx"]
        assert ctx.is_visitor
        assert ctx.slot == world["people"]["zhang"]["id"]

    def test_the_directory_is_inside_that_account_s_tree(self, world, ran):
        _post(world["people"]["zhang"]["cookie"])
        account = world["root"] / "users" / world["people"]["zhang"]["id"]
        assert Path(ran["ctx"].data_dir).is_relative_to(account)

    def test_the_slot_is_written_before_the_recipe_starts(self, world, ran):
        """Otherwise the page polls a directory that does not exist yet: the
        slot declares no dataDir, and `/app/<n>/data/…` answers 404."""
        _post(world["people"]["zhang"]["cookie"])
        account = world["root"] / "users" / world["people"]["zhang"]["id"]
        assert (account / "state" / f"{PAGE}.json").is_file()


class TestTheRunDoesNotEmptyThePageOnItsWayIn:
    """Starting a run must not cost the visitor what they were already reading.

    The write that happens before the recipe starts exists only to guarantee a
    data directory. Publishing just that directory replaced the slot wholesale,
    so the page went blank the moment a run began — and a run that fails never
    writes anything back, leaving the visitor with nothing and no explanation.
    Seen on the live server 2026-08-23: a visitor's run failed at 21:23 and the
    page stayed empty until the state was restored by hand a minute later.
    """

    def _already_showing(self, world):
        app_state.publish(
            PAGE,
            {
                "dataDir": "/somewhere/stale",
                "public": {"tradeCount": 45, "generatedAt": "2026-08-23T21:24:43"},
            },
            slot=world["people"]["zhang"]["id"],
            identity=True,
        )

    def _slot_now(self, world):
        return app_state.read(
            PAGE, world["people"]["zhang"]["id"], identity=True
        )

    def test_what_the_page_was_showing_survives_the_start(self, world, ran):
        self._already_showing(world)
        _post(world["people"]["zhang"]["cookie"])
        assert self._slot_now(world)["public"] == {
            "tradeCount": 45,
            "generatedAt": "2026-08-23T21:24:43",
        }

    def test_the_data_directory_is_still_forced_to_this_account(self, world, ran):
        """Carrying the old values forward must not carry the old directory:
        that is the one key the platform decides and the recipe may not."""
        self._already_showing(world)
        _post(world["people"]["zhang"]["cookie"])
        account = world["root"] / "users" / world["people"]["zhang"]["id"]
        assert Path(self._slot_now(world)["dataDir"]).is_relative_to(account)

    def test_a_first_ever_run_still_gets_a_directory(self, world, ran):
        """Nothing to carry forward is the ordinary case on someone's first run,
        and it must still leave a usable slot behind."""
        _post(world["people"]["zhang"]["cookie"])
        assert self._slot_now(world)["dataDir"]


class TestTheResponseSaysAlmostNothing:
    def test_it_carries_no_recipe_return_value(self, world, ran):
        assert _post(world["people"]["zhang"]["cookie"]).json() == {"accepted": True}

    def test_no_refusal_quotes_a_server_path(self, world, ran):
        """Everything that is not the owner goes through the scrubber now, so a
        signed-in stranger cannot read this machine's layout off an error."""
        for body in ({"data_dir": "/etc"}, {"note": "x" * 100}):
            text = _post(world["people"]["zhang"]["cookie"], body).text
            assert str(world["root"]) not in text
            assert "/Users/" not in text


class TestOneAtATimePerPerson:
    def test_a_second_run_while_one_is_going_is_refused(self, world, ran):
        key = (PAGE, world["people"]["zhang"]["id"])
        assert app_run._claim(key, None) is True
        r = _post(world["people"]["zhang"]["cookie"])
        assert r.status_code == 409

    def test_two_different_people_do_not_block_each_other(self, world, ran):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, runnable=True)
        assert app_run._claim((PAGE, world["people"]["zhang"]["id"]), None) is True
        assert _post(world["people"]["li"]["cookie"]).status_code == 202

    def test_a_claim_nobody_released_expires(self, world, ran, monkeypatch):
        """A `finally` runs almost always, and "almost" here would mean an
        account that can never run this page again."""
        key = (PAGE, world["people"]["zhang"]["id"])
        app_run._claim(key, None)
        app_run._running[key] = 0.0  # a deadline already in the past
        assert _post(world["people"]["zhang"]["cookie"]).status_code == 202

    def test_the_claim_is_released_when_the_run_finishes(self, world, ran):
        assert _post(world["people"]["zhang"]["cookie"]).status_code == 202
        _wait_for_state(world, "zhang", "done")
        assert _post(world["people"]["zhang"]["cookie"]).status_code == 202


class TestOneRunPerAccountAcrossPages:
    """The pool has a fixed number of slots shared by every visitor. If one
    account could hold a slot on each distinct page it reaches, it would fill
    the pool by itself and every other visitor's run would come back 503. So the
    cap is per account, not per page."""

    def test_one_account_cannot_hold_two_pages_at_once(self, world):
        who = world["people"]["zhang"]["id"]
        assert app_run._claim(("page_a", who), None) is True
        # A different page, same account — refused, because the account is
        # already using its one slot.
        assert app_run._claim(("page_b", who), None) is False

    def test_a_second_page_over_http_is_refused_409(self, world, ran):
        # Their one slot is spent on some other page; the run they POST here is
        # turned away rather than taking a second slot.
        app_run._claim(("other_page", world["people"]["zhang"]["id"]), None)
        assert _post(world["people"]["zhang"]["cookie"]).status_code == 409
        assert ran == {}

    def test_two_accounts_each_hold_one(self, world):
        zhang, li = world["people"]["zhang"]["id"], world["people"]["li"]["id"]
        assert app_run._claim(("page_a", zhang), None) is True
        # A different account is exactly what the pool's slots are for.
        assert app_run._claim(("page_a", li), None) is True

    def test_releasing_one_page_frees_the_account_for_another(self, world):
        who = world["people"]["zhang"]["id"]
        assert app_run._claim(("page_a", who), None) is True
        app_run._release(("page_a", who))
        assert app_run._claim(("page_b", who), None) is True

    def test_an_abandoned_claim_does_not_lock_the_account_out(self, world):
        """An expired claim on one page must not bar the account from every
        other page forever — the deadline is what makes a lost release recover."""
        who = world["people"]["zhang"]["id"]
        app_run._claim(("page_a", who), None)
        app_run._running[("page_a", who)] = 0.0  # a deadline already in the past
        assert app_run._claim(("page_b", who), None) is True


def _wait_for_state(world, who, wanted, tries=100):
    import time

    account = world["root"] / "users" / world["people"][who]["id"]
    path = account / "data" / PAGE / app_run.RUN_STATE_FILE
    for _ in range(tries):
        if path.is_file():
            state = json.loads(path.read_text("utf-8"))
            if state.get("state") == wanted:
                return state
        time.sleep(0.02)
    raise AssertionError(f"run.json never reached {wanted}")


class TestTheTerminalStateIsAlwaysRecorded:
    def test_a_finished_run_says_done(self, world, ran):
        _post(world["people"]["zhang"]["cookie"])
        assert _wait_for_state(world, "zhang", "done")["error"] is None

    def test_a_crashed_run_says_failed(self, world, monkeypatch):
        class _Boom:
            def run(self, *a, **k):
                raise RuntimeError("/Users/owner/secret/path blew up")

        monkeypatch.setattr("frago.recipes.runner.RecipeRunner", _Boom)
        _post(world["people"]["zhang"]["cookie"])
        state = _wait_for_state(world, "zhang", "failed")
        assert "/Users/" not in state["error"], "a failure must not quote server paths"

    def test_the_page_can_read_its_own_run_state(self, world, ran):
        _post(world["people"]["zhang"]["cookie"])
        _wait_for_state(world, "zhang", "done")
        r = _client(world["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/data/{app_run.RUN_STATE_FILE}"
        )
        assert r.status_code == 200
        assert r.json()["state"] == "done"
