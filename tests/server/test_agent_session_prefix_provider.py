"""Regression tests for AgentSession.prefix_provider.

Background: AgentSession.send_message restarts the underlying subprocess
each time. Prior to the fix, the PA session's identity prompt (PA_SYSTEM_PROMPT
+ bootstrap) was lost on the first send_message because it was only embedded
in the initial start() prompt. New subprocesses ran as vanilla frago agents
with no PA identity or 4-action output protocol.

Fix: AgentSession now holds a prefix_provider callable invoked on every
(re)start to re-attach session-bound prefix.
"""
from frago.server.services.agent_service import AgentSession


def test_assemble_prompt_no_prefix_provider_returns_message_unchanged():
    sess = AgentSession("test-id", "/tmp")
    assert sess._assemble_prompt("hello") == "hello"


def test_assemble_prompt_with_prefix_provider_prepends_prefix():
    sess = AgentSession("test-id", "/tmp", prefix_provider=lambda: "PREFIX")
    assert sess._assemble_prompt("hello") == "PREFIX\n\nhello"


def test_assemble_prompt_empty_message_returns_prefix_only():
    sess = AgentSession("test-id", "/tmp", prefix_provider=lambda: "PREFIX")
    assert sess._assemble_prompt("") == "PREFIX"


def test_prefix_provider_re_evaluated_each_call():
    counter = {"n": 0}

    def provider() -> str:
        counter["n"] += 1
        return f"prefix-v{counter['n']}"

    sess = AgentSession("test-id", "/tmp", prefix_provider=provider)
    assert sess._assemble_prompt("a") == "prefix-v1\n\na"
    assert sess._assemble_prompt("b") == "prefix-v2\n\nb"
    assert counter["n"] == 2
