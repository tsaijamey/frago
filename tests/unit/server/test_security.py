"""The access zones a deployed frago depends on.

These tests are the contract for "what may an untrusted caller reach". Each one
corresponds to a way the box gets owned if the middleware regresses, so they are
written from the attacker's side: not "the API works" but "this request must not
be served".
"""

import pytest
from fastapi import FastAPI, Request, WebSocket
from starlette.testclient import TestClient

from frago.recipes import publish as publish_mod
from frago.server import security
from frago.server.security import AccessZoneMiddleware, is_public_request

REMOTE = ("93.184.216.34", 41234)
LOCAL = ("127.0.0.1", 41234)


@pytest.fixture
def token(tmp_path, monkeypatch):
    from frago.server import security

    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    return security.ensure_token()


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_mod, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(publish_mod, "_cache", None, raising=False)
    return publish_mod


@pytest.fixture
def app():
    application = FastAPI()

    @application.get("/api/file")
    async def read_any_file():
        return {"content": "secrets"}

    @application.post("/api/agent")
    async def start_agent():
        return {"started": True}

    @application.get("/app/{name}/config.json")
    async def config(name: str, request: Request):
        return {"name": name, "public": is_public_request(request)}

    @application.get("/app/{name}/{path:path}")
    async def asset(name: str, path: str):
        return {"name": name, "path": path}

    @application.post("/app/{name}/run")
    async def run_from_page(name: str):
        return {"ran": name}

    @application.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"hello": True})
        await websocket.close()

    application.add_middleware(AccessZoneMiddleware)
    return application


def client(app, peer):
    return TestClient(app, client=peer)


# --- trusted local -------------------------------------------------------


def test_local_caller_needs_no_token(app, token, published):
    """The personal-frago case: installing the gate changes nothing on loopback."""
    resp = client(app, LOCAL).get("/api/file")
    assert resp.status_code == 200


def test_local_caller_behind_a_proxy_is_not_trusted(app, token, published):
    """A reverse proxy on the same box also dials from 127.0.0.1.

    Without this, every request the proxy forwards from the internet would
    inherit the owner's unconditional trust — the whole API, wide open.
    """
    resp = client(app, LOCAL).get("/api/file", headers={"X-Forwarded-For": "93.184.216.34"})
    assert resp.status_code == 401


def test_forged_forwarding_header_cannot_gain_privilege(app, token, published):
    """The header check only ever downgrades: a remote caller stays out."""
    resp = client(app, REMOTE).get("/api/file", headers={"X-Forwarded-For": "127.0.0.1"})
    assert resp.status_code == 401


# --- private zone --------------------------------------------------------


def test_remote_caller_is_refused_without_token(app, token, published):
    assert client(app, REMOTE).get("/api/file").status_code == 401
    assert client(app, REMOTE).post("/api/agent").status_code == 401


def test_remote_caller_with_token_is_admitted(app, token, published):
    resp = client(app, REMOTE).get("/api/file", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_wrong_token_is_refused(app, token, published):
    resp = client(app, REMOTE).get("/api/file", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_server_with_no_token_admits_no_one(app, tmp_path, monkeypatch, published):
    """Fail closed: a box that never minted a token has no remote users."""
    from frago.server import security

    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "absent-token")
    resp = client(app, REMOTE).get("/api/file", headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 401


def test_websocket_without_token_is_closed(app, token, published):
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        client(app, REMOTE).websocket_connect("/ws") as ws,
    ):
        ws.receive_json()


def test_websocket_with_query_token_is_admitted(app, token, published):
    with client(app, REMOTE).websocket_connect(f"/ws?token={token}") as ws:
        assert ws.receive_json() == {"hello": True}


# --- public zone ---------------------------------------------------------


def test_unpublished_recipe_page_is_not_public(app, token, published):
    resp = client(app, REMOTE).get("/app/secret_dashboard/config.json")
    assert resp.status_code == 401


def test_published_recipe_page_is_public(app, token, published):
    published.publish("weekly_report")
    resp = client(app, REMOTE).get("/app/weekly_report/config.json")
    assert resp.status_code == 200
    assert resp.json()["public"] is True


def test_published_page_is_read_only(app, token, published):
    """A page's own front end may POST; an anonymous visitor's copy may not.

    `/api/recipes/<name>/run` is the call these front ends make, and it executes
    a script on the server.
    """
    published.publish("weekly_report")
    assert client(app, REMOTE).post("/app/weekly_report/run").status_code == 401


def test_publishing_one_slot_does_not_publish_another(app, token, published):
    published.publish("weekly_report", slot="public_view")
    ok = client(app, REMOTE).get("/app/weekly_report/config.json?key=public_view")
    leak = client(app, REMOTE).get("/app/weekly_report/config.json?key=acme_client")
    assert ok.status_code == 200
    assert leak.status_code == 401


def test_unpublishing_takes_effect_without_restart(app, token, published):
    published.publish("weekly_report")
    assert client(app, REMOTE).get("/app/weekly_report/config.json").status_code == 200
    published.unpublish("weekly_report")
    assert client(app, REMOTE).get("/app/weekly_report/config.json").status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/app/..%2f..%2fetc/passwd",
        "/app/./config.json",
        "/app/../api/file",
    ],
)
def test_odd_app_paths_are_not_public(app, token, published, path):
    published.publish("weekly_report")
    assert client(app, REMOTE).get(path).status_code in (401, 404, 307)


def test_local_page_request_is_not_marked_public(app, token, published):
    """The owner's own browser gets the full config, not the visitor's view."""
    published.publish("weekly_report")
    resp = client(app, LOCAL).get("/app/weekly_report/config.json")
    assert resp.json()["public"] is False


# --- the home network ----------------------------------------------------
#
# frago binds 0.0.0.0 by default and prints its LAN URLs on `frago server
# status`: reading the workbench from your phone is an advertised feature. A
# gate that silently 401s it would be a regression for every personal install,
# so LAN peers stay trusted unless a deployment turns them off.

LAN = ("192.168.1.50", 41234)


def test_the_home_network_is_trusted_by_default(app, token, published):
    assert client(app, LAN).get("/api/file").status_code == 200


@pytest.mark.parametrize("peer", [("10.0.0.5", 1), ("172.16.3.9", 1), ("169.254.4.4", 1)])
def test_every_private_range_counts_as_home(app, token, published, peer):
    assert client(app, peer).get("/api/file").status_code == 200


@pytest.mark.parametrize("value", ["0", "false", "no", "FALSE"])
def test_a_deployment_can_shut_the_home_network_out(app, token, published, monkeypatch, value):
    monkeypatch.setenv("FRAGO_TRUST_LAN", value)
    assert client(app, LAN).get("/api/file").status_code == 401


def test_shutting_out_the_lan_does_not_shut_out_this_machine(app, token, published, monkeypatch):
    monkeypatch.setenv("FRAGO_TRUST_LAN", "0")
    assert client(app, LOCAL).get("/api/file").status_code == 200


def test_a_lan_caller_behind_a_proxy_is_still_not_trusted(app, token, published):
    resp = client(app, LAN).get("/api/file", headers={"X-Real-IP": "93.184.216.34"})
    assert resp.status_code == 401


# --- peer parsing --------------------------------------------------------


def test_ipv6_mapped_loopback_is_loopback(app, token, published):
    """A prefix match on the string form would miss this and lock the owner out."""
    assert client(app, ("::ffff:127.0.0.1", 1)).get("/api/file").status_code == 200


@pytest.mark.parametrize(
    "peer",
    [
        ("127.0.0.1.evil.example", 1),  # merely starts with the right characters
        ("", 1),
        ("0.0.0.0", 1),
        ("not-an-ip", 1),
    ],
)
def test_a_peer_we_cannot_parse_is_not_trusted(app, token, published, peer):
    assert client(app, peer).get("/api/file").status_code == 401


# --- slot smuggling ------------------------------------------------------


def test_duplicate_slot_parameters_are_refused_outright(app, token, published):
    """Two values for `key` is not a question to answer, it is a request to drop.

    Found by audit 20260817: the gate and the route used different query
    parsers, so the pair authorised one slot and served another.
    """
    published.publish("weekly_report")
    resp = client(app, REMOTE).get("/app/weekly_report/config.json?key=default&key=acme")
    assert resp.status_code == 401


def test_the_gate_hands_the_route_the_slot_it_authorised(app, token, published):
    from frago.server.security import classify_public

    published.publish("weekly_report", slot="public_view")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/app/weekly_report/config.json",
        "query_string": b"key=public_view",
    }
    assert classify_public(scope) == "public_view"
    scope["query_string"] = b"key=public_view&key=acme"
    assert classify_public(scope) is None


# --- minting the token ---------------------------------------------------


def test_two_callers_racing_to_mint_get_the_same_token(tmp_path, monkeypatch):
    """Found by audit 20260817.

    The server mints its token at startup; a person runs `frago server token` to
    read it. Before O_EXCL the loser of that race walked away with a string that
    was never written to disk, and the failure looked like "the remote rejects a
    token I just copied".
    """
    import threading

    from frago.server import security

    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")

    handed_out: list[str] = []
    barrier = threading.Barrier(8)

    def mint():
        barrier.wait()
        handed_out.append(security.ensure_token())

    threads = [threading.Thread(target=mint) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    on_disk = security.read_token()
    assert len(set(handed_out)) == 1
    assert handed_out[0] == on_disk


def test_the_token_file_is_owner_only(tmp_path, monkeypatch):
    import os

    from frago.server import security

    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    security.ensure_token()
    if os.name != "nt":
        assert (tmp_path / "server-token").stat().st_mode & 0o077 == 0


def test_a_refusal_is_logged(app, token, published, caplog):
    """A 256-bit token will not be guessed; the point is that trying leaves a mark."""
    import logging

    with caplog.at_level(logging.WARNING, logger="frago.server.security"):
        client(app, REMOTE).get("/api/file?path=/etc/shadow")
    assert any("access denied" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("query", ["", "?key=", "?key=default"])
def test_the_gate_and_the_route_agree_on_what_names_the_default_slot(
    app, token, published, query
):
    """`?key=` is the default slot to the route, so it must be here too.

    Every reading the two do not share is the B-1 bug in a new costume.
    """
    published.publish("weekly_report")
    resp = client(app, REMOTE).get(f"/app/weekly_report/config.json{query}")
    assert resp.status_code == 200


# --- behind a proxy ------------------------------------------------------
#
# Every rule above reasons backwards from the socket, and a proxy that sets no
# forwarding header defeats that reasoning silently. A deployment says so
# instead of being guessed at.


def test_behind_a_proxy_the_peer_address_grants_nothing(app, token, published, monkeypatch):
    """The header list is a heuristic over other people's software.

    With FRAGO_BEHIND_PROXY set, a proxy that forwards without a single
    recognised header still cannot hand a visitor the owner's seat.
    """
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    assert client(app, LOCAL).get("/api/file").status_code == 401
    assert client(app, LAN).get("/api/file").status_code == 401


def test_behind_a_proxy_the_token_still_works(app, token, published, monkeypatch):
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    resp = client(app, LOCAL).get("/api/file", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_behind_a_proxy_published_pages_are_still_public(app, token, published, monkeypatch):
    """The switch closes the inferred zone, not the declared one."""
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    published.publish("weekly_report")
    assert client(app, LOCAL).get("/app/weekly_report/config.json").status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        "X-Forwarded-For",
        "X-Real-IP",
        "Forwarded",
        "CF-Connecting-IP",
        "True-Client-IP",
        "X-Client-IP",
        "X-Envoy-External-Address",
        "X-Original-Forwarded-For",
    ],
)
def test_each_known_forwarding_header_drops_local_trust(app, token, published, header):
    resp = client(app, LOCAL).get("/api/file", headers={header: "93.184.216.34"})
    assert resp.status_code == 401


# --- deployment posture --------------------------------------------------


def test_a_loopback_bind_without_the_proxy_switch_is_warned_about(monkeypatch):
    """Binding to loopback is the deliberate act that says "proxy in front".

    Found by audit 20260817: a layer-4 forwarder leaves no header to detect, so
    the switch is the only defence and its absence must not be silent.
    """
    from frago.server import security

    monkeypatch.setenv("FRAGO_SERVER_HOST", "127.0.0.1")
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    warning = security.deployment_warning()
    assert warning is not None
    assert "FRAGO_BEHIND_PROXY" in warning


def test_no_warning_once_the_switch_is_set(monkeypatch):
    from frago.server import security

    monkeypatch.setenv("FRAGO_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    monkeypatch.setenv("FRAGO_TRUSTED_PROXIES", "127.0.0.1")
    assert security.deployment_warning() is None


def test_saying_there_is_a_proxy_without_saying_which_is_warned_about(monkeypatch):
    """Declaring a proxy but not naming it switches per-IP rate limiting off.

    uvicorn rewrites the peer from a header this server has not agreed to
    believe, so the login limiter has no address it can count against. Silence
    here would leave the owner thinking they are rate limited when they are not.
    """
    from frago.server import security

    monkeypatch.setenv("FRAGO_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    monkeypatch.delenv("FRAGO_TRUSTED_PROXIES", raising=False)
    warning = security.deployment_warning()
    assert warning is not None
    assert "FRAGO_TRUSTED_PROXIES" in warning


def test_no_warning_on_a_personal_machine(monkeypatch):
    """The default bind is 0.0.0.0; nagging every personal install teaches people
    to ignore the warning that matters."""
    from frago.server import security

    monkeypatch.setenv("FRAGO_SERVER_HOST", "0.0.0.0")
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    assert security.deployment_warning() is None


def test_hardening_tightens_what_earlier_versions_left_open(tmp_path, monkeypatch):
    """Write-time permissions do nothing for what is already on disk."""
    import os

    if os.name == "nt":
        pytest.skip("POSIX permission bits")

    from frago.server import security

    home = tmp_path / ".frago"
    (home / "app-state" / "some_recipe").mkdir(parents=True)
    log = home / "server.log"
    log.write_text("old", encoding="utf-8")
    log.chmod(0o644)
    slot = home / "app-state" / "some_recipe" / "default.json"
    slot.write_text("{}", encoding="utf-8")
    slot.chmod(0o644)
    home.chmod(0o755)

    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    security.harden_home()

    assert home.stat().st_mode & 0o077 == 0
    assert log.stat().st_mode & 0o077 == 0
    assert slot.stat().st_mode & 0o077 == 0


def test_hardening_is_quiet_when_there_is_nothing_to_harden(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    security.harden_home()  # must not raise on a machine with no ~/.frago


def test_hardening_does_not_reach_through_a_symlink(tmp_path, monkeypatch):
    """chmod follows links; a recipe that linked a shared directory into
    app-state must not have that directory's permissions rewritten."""
    import os

    if os.name == "nt":
        pytest.skip("POSIX permission bits")

    home = tmp_path / ".frago"
    (home / "app-state").mkdir(parents=True)
    outside = tmp_path / "shared"
    outside.mkdir()
    outside.chmod(0o755)
    (home / "app-state" / "linked").symlink_to(outside)

    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    security.harden_home()

    assert outside.stat().st_mode & 0o777 == 0o755


# --- switches that must not fail open ------------------------------------
#
# Found by audit 20260817, reviewing the fixes above: the safety switch used a
# whitelist of spellings, so FRAGO_BEHIND_PROXY=on silently meant off.


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "Y", "enabled", "2", "TRUE"])
def test_any_affirmative_spelling_arms_the_safety_switch(monkeypatch, value):
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", value)
    assert security.peer_trust_disabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_only_an_explicit_negative_disarms_it(monkeypatch, value):
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", value)
    assert security.peer_trust_disabled() is False


def test_unset_means_off(monkeypatch):
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    assert security.peer_trust_disabled() is False


# --- containers ----------------------------------------------------------
#
# The audit's critical finding on the fixes: a container publishes on 0.0.0.0
# and every forwarded request arrives from the bridge gateway, which is
# RFC1918. With LAN trust on, that made every internet visitor the owner — and
# the warning, which only looked at loopback binds, said nothing.


def test_a_container_does_not_trust_its_bridge_network(monkeypatch):
    monkeypatch.delenv("FRAGO_TRUST_LAN", raising=False)
    monkeypatch.setattr(security, "in_container", lambda: True)
    assert security.lan_is_trusted() is False


def test_the_docker_gateway_is_not_the_owner(app, token, published, monkeypatch):
    monkeypatch.delenv("FRAGO_TRUST_LAN", raising=False)
    monkeypatch.setattr(security, "in_container", lambda: True)
    assert client(app, ("172.17.0.1", 4444)).get("/api/file").status_code == 401


def test_a_container_can_still_opt_back_in(monkeypatch):
    monkeypatch.setenv("FRAGO_TRUST_LAN", "1")
    monkeypatch.setattr(security, "in_container", lambda: True)
    assert security.lan_is_trusted() is True


def test_a_container_is_warned_even_though_it_binds_all_interfaces(monkeypatch):
    """The first version of this check only looked at loopback binds, which is
    precisely the shape a container is not."""
    monkeypatch.setenv("FRAGO_SERVER_HOST", "0.0.0.0")
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    monkeypatch.setattr(security, "in_container", lambda: True)
    warning = security.deployment_warning()
    assert warning is not None
    assert "container" in warning


def test_a_container_that_armed_the_switch_is_not_nagged(monkeypatch):
    monkeypatch.setenv("FRAGO_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    monkeypatch.setenv("FRAGO_TRUSTED_PROXIES", "172.17.0.1")
    monkeypatch.setattr(security, "in_container", lambda: True)
    assert security.deployment_warning() is None


def test_hardening_covers_the_cloud_token_file(tmp_path, monkeypatch):
    """`config.yaml` reads like settings but holds the cloud OAuth tokens."""
    import os

    if os.name == "nt":
        pytest.skip("POSIX permission bits")

    home = tmp_path / ".frago"
    home.mkdir(parents=True)
    cloud = home / "config.yaml"
    cloud.write_text("access_token: secret\nrefresh_token: secret\n", encoding="utf-8")
    cloud.chmod(0o644)

    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    security.harden_home()

    assert cloud.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("peer", [("100.64.0.1", 1), ("100.101.5.7", 1)])
def test_a_tailnet_peer_is_not_the_home_network(app, token, published, peer):
    """CGNAT space stopped counting as private in Python 3.13.

    Pinned because the docstring next to `_peer_zone` makes a claim about it,
    and a claim in a comment that nothing checks is a claim that rots.
    """
    assert client(app, peer).get("/api/file").status_code == 401
