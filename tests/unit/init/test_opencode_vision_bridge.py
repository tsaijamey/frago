"""Behaviour tests for the opencode bridge's image-reading path.

The assertions in test_opencode_plugin.py can only read the plugin's source.
These drive the real file through node with the payload shape opencode
actually delivers (captured from opencode 1.18.10), so the gate that decides
whether to spend money on a vision call is verified rather than assumed.

No network is involved: FRAGO_LAUNCHER points the bridge at a stub that
answers in the recipe's output shape and records that it was called.
"""

import json
import os
import shutil
import subprocess

import pytest

from frago.init.opencode_plugin import get_bundled_plugin_path

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

STUB_DESCRIPTION = "STUB-DESCRIPTION-一张截图"

DRIVER = """
import { pathToFileURL } from "node:url"

const [pluginPath, payloadPath] = process.argv.slice(2)
const { readFileSync } = await import("node:fs")
const { FragoHookPlugin } = await import(pathToFileURL(pluginPath).href)
const { input, output, toolCalls } = JSON.parse(readFileSync(payloadPath, "utf8"))

const hooks = await FragoHookPlugin({ directory: process.cwd() })
await hooks["chat.message"](input, output)

// The message hook always runs first in a real session; tool hooks depend on
// it having recorded which model the session is driving.
const toolResults = []
for (const call of toolCalls || []) {
  await hooks["tool.execute.before"]({ ...call.input }, { args: call.input.args })
  await hooks["tool.execute.after"]({ ...call.input }, call.output)
  toolResults.push(call.output.output)
}

const texts = (output.parts || []).filter((p) => p.type === "text")
process.stdout.write(
  JSON.stringify({
    texts: texts.map((p) => ({ synthetic: p.synthetic === true, text: p.text })),
    toolResults,
  }),
)
"""

# The stub stands in for `frago recipe run`: it answers in the recipe's output
# shape and leaves a trace so a test can assert the call never happened.
STUB = (
    "#!/bin/sh\n"
    'echo "$@" >> "$FRAGO_STUB_CALLS"\n'
    "cat \"$FRAGO_STUB_REPLY\"\n"
)


def _image_part():
    # A 1x1 png is enough: the bridge only ever passes the data URL through.
    return {
        "type": "file",
        "mime": "image/png",
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        "filename": "shot.png",
        "synthetic": True,
    }


def _image_read_call(call_id="call_1", path="/tmp/shot.png"):
    """One `read` of an image file, in the shape opencode 1.18.10 delivers."""
    return {
        "input": {"tool": "read", "sessionID": "ses_test_vision", "callID": call_id, "args": {"filePath": path}},
        "output": {
            "title": path,
            "output": "Image read successfully",
            "metadata": {"preview": "Image read successfully"},
            "attachments": [_image_part()],
        },
    }


def _payload(model_id, *, provider="opencode", with_image=True, tool_calls=()):
    parts = []
    if with_image:
        parts.append({"type": "text", "synthetic": True, "text": "Called the Read tool with the following input: {}"})
        parts.append(_image_part())
    parts.append({"type": "text", "text": "这张图里有什么？"})
    return {
        "input": {"sessionID": "ses_test_vision", "model": {"providerID": provider, "modelID": model_id}},
        "output": {"message": {"role": "user"}, "parts": parts},
        "toolCalls": list(tool_calls),
    }


@pytest.fixture
def bridge(tmp_path):
    """Run the packaged plugin under node with a stubbed frago launcher."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    for src in get_bundled_plugin_path().parent.iterdir():
        if src.is_file():
            shutil.copy2(src, plugin_dir / src.name)

    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")

    stub = tmp_path / "frago-stub"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    calls = tmp_path / "calls.txt"
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({"success": True, "raw_text": STUB_DESCRIPTION}), encoding="utf-8")

    def run(payload):
        payload_path = tmp_path / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        env = {
            **os.environ,
            "FRAGO_LAUNCHER": str(stub),
            "FRAGO_STUB_CALLS": str(calls),
            "FRAGO_STUB_REPLY": str(reply),
        }
        proc = subprocess.run(
            ["node", str(driver), str(plugin_dir / "frago-hook.js"), str(payload_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        return result, calls.read_text(encoding="utf-8") if calls.exists() else ""

    return run


def test_blind_model_gets_the_image_described(bridge):
    """deepseek cannot see an attachment; the description stands in for it."""
    result, calls = bridge(_payload("deepseek-v4-flash-free"))
    texts = result["texts"]

    user_text = next(t["text"] for t in texts if not t["synthetic"])
    assert STUB_DESCRIPTION in user_text
    assert "代读" in user_text
    assert "recipe run openrouter_vision_classify" in calls


def test_description_lands_on_the_users_own_words(bridge):
    """Attachments prepend opencode's narration; injecting there buries it."""
    result, _ = bridge(_payload("deepseek-v4-flash-free"))
    texts = result["texts"]

    narration = next(t["text"] for t in texts if t["synthetic"])
    assert STUB_DESCRIPTION not in narration
    user_text = next(t["text"] for t in texts if not t["synthetic"])
    assert user_text.endswith("这张图里有什么？")


def test_seeing_model_pays_nothing(bridge):
    """A model with vision of its own must not trigger a second model."""
    result, calls = bridge(_payload("gpt-5", provider="openai"))

    assert STUB_DESCRIPTION not in "".join(t["text"] for t in result["texts"])
    assert calls == ""


def test_no_image_no_call(bridge):
    """The gate is images-and-blind-model, not blind-model alone."""
    result, calls = bridge(_payload("deepseek-v4-flash-free", with_image=False))

    assert STUB_DESCRIPTION not in "".join(t["text"] for t in result["texts"])
    assert calls == ""


def test_image_the_model_reads_itself_is_described(bridge):
    """The agent opening an image file hits the same wall as an attachment.

    opencode returns the picture as an attachment on the tool result and the
    text "Image read successfully" — which tells a blind model nothing.
    """
    result, calls = bridge(
        _payload("deepseek-v4-flash-free", with_image=False, tool_calls=[_image_read_call()])
    )

    assert STUB_DESCRIPTION in result["toolResults"][0]
    assert "你刚读取的" in result["toolResults"][0]
    assert "Image read successfully" in result["toolResults"][0]
    assert calls.count("recipe run") == 1


def test_reading_the_same_image_twice_pays_once(bridge):
    """A re-read must not stall the agent on the vision model all over again."""
    result, calls = bridge(
        _payload(
            "deepseek-v4-flash-free",
            with_image=False,
            tool_calls=[_image_read_call("call_1"), _image_read_call("call_2")],
        )
    )

    assert all(STUB_DESCRIPTION in r for r in result["toolResults"])
    assert calls.count("recipe run") == 1


def test_seeing_model_reads_images_untouched(bridge):
    """The gate covers the tool path too, not just the message path."""
    result, calls = bridge(
        _payload("gpt-5", provider="openai", with_image=False, tool_calls=[_image_read_call()])
    )

    assert result["toolResults"][0] == "Image read successfully"
    assert calls == ""
