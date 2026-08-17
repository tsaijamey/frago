"""`frago remote` — the local frago's side of a two-frago setup.

The interesting behaviour is not the HTTP call (that is `frago chat`'s, already
tested by use) but the handling around it: tokens must be stored privately and
never printed back, an unknown remote must fail loudly rather than silently
target localhost, and `send` must return the remote PA's answer as a value the
calling agent can read.
"""

from __future__ import annotations

import json
import os
import threading

import pytest
from click.testing import CliRunner

from frago.cli import remote_commands


@pytest.fixture(autouse=True)
def remotes_file(tmp_path, monkeypatch):
    path = tmp_path / "remotes.json"
    monkeypatch.setattr(remote_commands, "REMOTES_PATH", path)
    return path


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def configured(runner):
    result = runner.invoke(
        remote_commands.remote_group,
        ["add", "box", "--url", "http://127.0.0.1:18093/", "--token", "s3cret"],
    )
    assert result.exit_code == 0, result.output
    return "box"


class TestRegistry:
    def test_add_then_list(self, runner, configured):
        result = runner.invoke(remote_commands.remote_group, ["list"])
        assert "box" in result.output
        assert "http://127.0.0.1:18093" in result.output

    def test_the_token_is_never_printed(self, runner, configured):
        for args in (["list"], ["list", "--format", "json"]):
            result = runner.invoke(remote_commands.remote_group, args)
            assert "s3cret" not in result.output

    def test_the_token_file_is_not_world_readable(self, runner, configured, remotes_file):
        if os.name == "nt":
            pytest.skip("POSIX permission bits")
        assert remotes_file.stat().st_mode & 0o077 == 0

    def test_a_trailing_slash_does_not_double_up(self, runner, configured):
        result = runner.invoke(remote_commands.remote_group, ["list", "--format", "json"])
        assert json.loads(result.output)["remotes"][0]["url"] == "http://127.0.0.1:18093"

    def test_unknown_remote_fails_instead_of_defaulting_to_localhost(self, runner):
        """Silently falling back to this machine would run the work on the wrong box."""
        result = runner.invoke(remote_commands.remote_group, ["send", "typo", "do a thing"])
        assert result.exit_code != 0
        assert "Unknown remote" in result.output

    def test_remove(self, runner, configured):
        assert runner.invoke(remote_commands.remote_group, ["remove", "box"]).exit_code == 0
        assert "No remotes" in runner.invoke(remote_commands.remote_group, ["list"]).output


class TestSend:
    """`send` posts one brief and waits on the remote PA's event stream."""

    @pytest.fixture
    def wired(self, monkeypatch):
        """Stand in for the two chat functions, recording what they were given."""
        seen: dict = {}

        def fake_send(base_url, prompt, session_id, headers=None):
            seen["base_url"] = base_url
            seen["prompt"] = prompt
            seen["headers"] = headers
            return "cli_abc123"

        def fake_stream(base_url, sent_msg_ids, stop_event, on_event, headers=None):
            seen["stream_headers"] = headers
            on_event("pa_decision", {"action": "run", "details": {"description": "跑 recipe"}}, {})
            on_event("pa_reply", {"reply_text": "done: 3 rows"}, {})
            stop_event.wait(timeout=5)

        monkeypatch.setattr("frago.cli.chat.send_message", fake_send)
        monkeypatch.setattr("frago.cli.chat.stream_session_events", fake_stream)
        return seen

    def test_reply_is_printed(self, runner, configured, wired):
        result = runner.invoke(remote_commands.remote_group, ["send", "box", "跑一下"])
        assert result.exit_code == 0
        assert "done: 3 rows" in result.output

    def test_json_form_carries_reply_and_trace(self, runner, configured, wired):
        result = runner.invoke(
            remote_commands.remote_group, ["send", "box", "跑一下", "--format", "json"]
        )
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert payload["reply"] == "done: 3 rows"
        assert payload["msg_id"] == "cli_abc123"
        assert [e["event"] for e in payload["trace"]] == ["pa_decision", "pa_reply"]

    def test_the_token_reaches_both_channels(self, runner, configured, wired):
        runner.invoke(remote_commands.remote_group, ["send", "box", "跑一下"])
        assert wired["headers"] == {"Authorization": "Bearer s3cret"}
        assert wired["stream_headers"] == {"Authorization": "Bearer s3cret"}

    def test_prompt_file_is_read(self, runner, configured, wired, tmp_path):
        brief = tmp_path / "brief.md"
        brief.write_text("# 任务书\n跑 weekly_report", encoding="utf-8")
        runner.invoke(
            remote_commands.remote_group, ["send", "box", "--prompt-file", str(brief)]
        )
        assert "weekly_report" in wired["prompt"]

    def test_nothing_to_send_is_an_error(self, runner, configured, wired):
        result = runner.invoke(remote_commands.remote_group, ["send", "box"])
        assert result.exit_code != 0
        assert "Nothing to send" in result.output

    def test_no_wait_returns_immediately(self, runner, configured, monkeypatch):
        monkeypatch.setattr(
            "frago.cli.chat.send_message", lambda *a, **k: "cli_queued1"
        )

        def explode(*a, **k):
            raise AssertionError("--no-wait must not open the event stream")

        monkeypatch.setattr("frago.cli.chat.stream_session_events", explode)
        result = runner.invoke(
            remote_commands.remote_group, ["send", "box", "长任务", "--no-wait"]
        )
        assert result.exit_code == 0
        assert "cli_queued1" in result.output

    def test_a_refused_message_is_not_reported_as_success(self, runner, configured, monkeypatch):
        monkeypatch.setattr("frago.cli.chat.send_message", lambda *a, **k: None)
        result = runner.invoke(remote_commands.remote_group, ["send", "box", "x"])
        assert result.exit_code != 0

    def test_timeout_exits_nonzero_and_says_where_to_look(self, runner, configured, monkeypatch):
        monkeypatch.setattr("frago.cli.chat.send_message", lambda *a, **k: "cli_slow")

        def never_replies(base_url, sent, stop_event: threading.Event, on_event, headers=None):
            stop_event.wait(timeout=5)

        monkeypatch.setattr("frago.cli.chat.stream_session_events", never_replies)
        result = runner.invoke(
            remote_commands.remote_group, ["send", "box", "x", "--timeout", "1"]
        )
        assert result.exit_code == 1
        assert "frago remote chat box" in result.output
