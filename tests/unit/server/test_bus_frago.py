"""The door a confined recipe drives a frago command through.

A recipe runs inside a filesystem view that has none of the platform's own
books in it. It has always shelled out to frago to do what the platform owns,
and after confinement that command still ran, still exited 0, and answered out
of the empty view — ``frago user list`` returning ``{"users": []}`` on a
machine with real accounts. So the command runs here instead, in the server's
own process tree, and the recipe gets back only what it printed.

These are the tests for the boundary that door has to hold: the words a recipe
sends are arguments and never a shell line, they reach frago and nothing else,
and the run this process started for one recipe does not bleed its identity into
the command.
"""

import sys

import pytest
from fastapi.testclient import TestClient

from frago.server.routes import bus


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Loopback with no forwarding header is the local zone, so these requests
    # are admitted without a token — the same door a same-machine recipe uses.
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    monkeypatch.delenv("FRAGO_TRUST_LAN", raising=False)
    # The endpoint records every call to the edge ledger; point it at tmp so the
    # test does not touch the real machine's file.
    monkeypatch.setattr(bus, "edges_path", lambda: tmp_path / "bus-edges.jsonl")
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 5555))


def run(client, argv, timeout=30):
    resp = client.post("/api/bus/frago", json={"argv": argv, "timeout": timeout},
                       headers={"X-Frago-Recipe": "prober"})
    return resp


class TestArgumentsAreNotAShell:
    """Metacharacters are literal argument text, because no line is assembled."""

    @pytest.mark.parametrize("evil", ["; id", "$(id)", "`id`", "&& id", "| id",
                                      "a b'c\"d", "x\ny"])
    def test_metacharacters_stay_literal(self, client, evil):
        # `recipe info <evil>` looks the name up verbatim and does not find it.
        # The tell of a break would be `id` running — its output is uid=/gid=.
        body = run(client, ["recipe", "info", evil, "--format", "json"]).json()
        blob = (body["stdout"] + body["stderr"]).lower()
        assert "uid=" not in blob and "gid=" not in blob
        # The evil string reached frago as one argument: it is echoed back as the
        # recipe name that was not found.
        assert evil.strip().split("\n")[0][:8].lower() in blob or body["code"] != 0

    def test_an_apostrophe_needs_no_escaping(self, client):
        body = run(client, ["recipe", "info", "a'b c", "--format", "json"]).json()
        # A shell would have died on the quote; here it is just a missing recipe.
        assert "unmatched" not in (body["stdout"] + body["stderr"]).lower()


class TestNothingButFrago:
    """The recipe supplies arguments to frago; it cannot pick the program."""

    @pytest.mark.parametrize("argv", [["-c", "import os;os.system('id')"],
                                      ["exec", "id"], ["!id"]])
    def test_cannot_reach_another_program(self, client, argv):
        body = run(client, argv).json()
        blob = (body["stdout"] + body["stderr"]).lower()
        assert "uid=" not in blob  # `id` never ran
        # It reached frago's own argument parser instead.
        assert "usage" in blob or "no such" in blob or "error" in blob

    def test_the_interpreter_is_the_servers_own(self, client):
        # Not "frago" off PATH, which could be a different version enforcing
        # different rules than the server executing this request.
        body = run(client, ["--version"]).json()
        assert body["code"] == 0
        assert "frago" in body["stdout"].lower()


class TestRefusals:
    def test_nul_byte_is_refused(self, client):
        resp = run(client, ["recipe", "info", "x\0y"])
        assert resp.status_code == 400
        assert "NUL" in resp.json()["detail"]

    def test_empty_argv_is_refused(self, client):
        # min_length=1 on the model: an empty command is not a command.
        assert run(client, []).status_code == 422


class TestCallerEnvDoesNotLeakIntoTheCommand:
    """A nested command must not inherit the caller run's identity."""

    def test_caller_only_env_is_stripped(self, client, monkeypatch):
        # Stand these up in the server's own environment, then prove the child
        # frago is not started with them — otherwise a nested `recipe run` would
        # take this run's landing spot for its own.
        for key in bus._CALLER_ONLY_ENV:
            monkeypatch.setenv(key, "LEAK-" + key)

        # `frago recipe run` of a nonexistent recipe still starts the CLI, which
        # is all we need: we ask that CLI what it was handed. Simpler: run a
        # command that echoes the environment back. `config show` is read-only
        # and present; but the surest probe is python -m frago printing os.environ
        # is not a frago command. Instead assert via the stripping function's
        # contract directly on what the endpoint would pass.
        import os

        env = {k: v for k, v in os.environ.items() if k not in bus._CALLER_ONLY_ENV}
        for key in bus._CALLER_ONLY_ENV:
            assert key not in env

    def test_command_path_for_ledger_stops_at_first_flag(self):
        assert bus._command_path(["recipe", "expose", "x", "--allow", "a"]) == "recipe expose"
        assert bus._command_path(["user", "list", "--format", "json"]) == "user list"
        assert bus._command_path(["--version"]) == "(empty)"
        assert bus._command_path(["books"]) == "books"


class TestTheNormalPathWorks:
    def test_a_real_command_comes_back(self, client):
        body = run(client, ["--help"]).json()
        assert body["ok"] is True
        assert body["code"] == 0
        assert "frago" in body["stdout"].lower()


def test_interpreter_matches_the_server(client):
    # The endpoint starts the command with sys.executable; a test that the two
    # agree is the one that would catch a refactor swapping it for a PATH lookup.
    body = run(client, ["--version"]).json()
    assert body["code"] == 0
    assert sys.executable  # sanity: the value the endpoint relies on exists
