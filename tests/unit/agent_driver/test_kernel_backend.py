"""内核一轮的归类：把 frago-core 的 (returncode, stdout JSON) 翻成 frago 的四态。

夹具是从真机实测样本上抄下来的（2026-10-09，``frago-core --mode agent -p ... --output-format
json``）：成功、模型调用失败、连接没解析出来三种。内核自己的退出码只有 0/1/2，与 frago 的
0/1/2/3 **同名不同义**，所以每一条映射都得有对照——不然"连接没配好"会被读成"需要真人介入"。
"""

from __future__ import annotations

from frago.agent_driver.kernel_backend import (
    _classify,
    _classify_chat,
    _parse_payload,
    build_chat_command,
    build_command,
)

# 真机样本：成功（--as-profile 指向一条能用的连接），exit 0。
_OK = (
    '{"duration_ms":4025,"error_kind":null,"is_error":false,"model":"deepseek-flash",'
    '"profile":"9e770df9","result":"OK","session_id":"core_probe_ok","stop_reason":"end_turn",'
    '"subtype":"success","type":"result"}'
)

# 真机样本：模型那一轮失败——上游报订阅过期（error_kind=llm），exit 1。
_LLM_SUBSCRIPTION = (
    '{"duration_ms":2098,"error_kind":"llm","is_error":true,"model":"glm-5.3-flash",'
    '"profile":"0ef6d728","result":"LLM call 1 failed and the run stopped: ... HTTP 400 '
    '{\\"error\\":{\\"code\\":\\"InvalidSubscription\\",\\"message\\":\\"Your account does '
    'not have a valid AgentPlan subscription...\\"}}","subtype":"error_during_execution",'
    '"type":"result"}'
)

# 真机样本：连接没解析出来（error_kind=credential），exit 2。
_CREDENTIAL = (
    '{"error_kind":"credential","is_error":true,"result":"profiles.json 里没有 id 为'
    '「deadbeef」的连接","subtype":"error_during_execution","type":"result"}'
)

# 一次普通的传输失败：该重试的那一类，不该被当成认证墙。
_LLM_TRANSIENT = (
    '{"error_kind":"llm","is_error":true,"result":"LLM call 1 failed: connection reset by peer",'
    '"subtype":"error_during_execution","type":"result"}'
)


def test_success_is_ok():
    got = _classify(_OK, "", 0, 4025)
    assert got.status == "ok"
    assert got.text == "OK"


def test_subscription_wall_is_needs_input_not_error():
    """订阅过期要人去续，不是"再试一次"——归 needs_input（退出码 2）。"""
    got = _classify(_LLM_SUBSCRIPTION, "", 1, 2098)
    assert got.status == "needs_input"


def test_credential_error_is_needs_input():
    got = _classify(_CREDENTIAL, "", 2, 0)
    assert got.status == "needs_input"


def test_plain_transport_failure_stays_error():
    got = _classify(_LLM_TRANSIENT, "", 1, 10)
    assert got.status == "error"


def test_unparsable_output_is_error_with_the_stderr_note():
    got = _classify("", "frago-core: boom", 2, 3)
    assert got.status == "error"
    assert "boom" in got.text


def test_nonzero_exit_with_a_success_shaped_payload_is_error():
    """result 说自己没出错、进程却非零退出：以退出码为准，NEVER 报成成功。"""
    got = _classify(_OK, "", 1, 5)
    assert got.status == "error"


def test_parse_payload_skips_leading_noise():
    assert _parse_payload("progress line\n" + _OK)["result"] == "OK"
    assert _parse_payload("not json at all") is None


def test_parse_payload_rejects_non_result_objects():
    assert _parse_payload('{"type":"assistant","text":"hi"}') is None


# ── chat 那一轮（问一句答一句，不留会话记录） ────────────────────────────────
#
# 样本同样抄自真机（2026-10-11，``frago-core --mode chat -p -``）：成功那句来自
# ``--as-role observer``，失败那句来自 ``--as-profile deadbeef``（id 不在 profiles.json
# 里 ⇒ 连接没解析出来）。两种形状与 agent 那条不同，认错了就会把成功读成失败。

_CHAT_OK = (
    '{"type":"final","ok":true,"text":"Hi! How\'s it going?","rounds":1,"mode":"chat",'
    '"role":"observer","profile":"9e770df9","model":"deepseek-flash","wire":"anthropic",'
    '"duration_ms":809,"error_kind":null,"error":null}'
)

_CHAT_CREDENTIAL = (
    '{"type":"final","ok":false,"text":"","rounds":0,"mode":"chat","role":null,'
    '"profile":"deadbeef","model":null,"wire":null,"duration_ms":0,'
    '"error_kind":"credential","error":"profiles.json 里没有 id 为「deadbeef」的连接"}'
)


def test_chat_success_is_ok():
    got = _classify_chat(_CHAT_OK, "", 0, 809)
    assert got.status == "ok"
    assert got.text == "Hi! How's it going?"


def test_chat_credential_is_needs_input():
    got = _classify_chat(_CHAT_CREDENTIAL, "", 2, 0)
    assert got.status == "needs_input"


def test_chat_failure_carries_the_reason_as_text():
    """``text`` 空着、原因在 ``error`` 里：往上交原因，别交一个没有理由的空串。"""
    got = _classify_chat(_CHAT_CREDENTIAL, "", 2, 0)
    assert "deadbeef" in got.text


def test_chat_self_reported_success_with_nonzero_exit_is_error():
    """与 agent 那条同一条规矩：自报成功却非零退出，以退出码为准。"""
    assert _classify_chat(_CHAT_OK, "", 1, 5).status == "error"


def test_chat_without_a_final_object_is_error():
    got = _classify_chat("", "frago-core: boom", 2, 3)
    assert got.status == "error"
    assert "boom" in got.text


def test_each_shape_reader_ignores_the_other_shape():
    """两种形状必须指名道姓地认：认错了会把字段全对不上的对象一路读成"输出不是 JSON"。"""
    assert _parse_payload(_CHAT_OK) is None
    assert _parse_payload(_OK, kind="final") is None


def test_chat_command_asks_once_and_leaves_no_session_behind():
    cmd = build_chat_command(cwd="/repos/x", profile_id=None)
    assert cmd[cmd.index("--mode") + 1] == "chat"
    assert "--session-id" not in cmd  # 落会话靠它，chat 不该有
    assert cmd[-2:] == ["-p", "-"]  # 任务从 stdin 来


def test_agent_command_still_names_its_session():
    cmd = build_command(session_id="core_abc", cwd="/repos/x", profile_id="0ef6d728")
    assert cmd[cmd.index("--mode") + 1] == "agent"
    assert cmd[cmd.index("--session-id") + 1] == "core_abc"
    assert cmd[cmd.index("--as-profile") + 1] == "0ef6d728"
    assert "--model" not in cmd


def test_model_flag_is_forwarded_in_both_modes():
    agent_cmd = build_command(
        session_id="core_abc", cwd="/repos/x", profile_id="0ef6d728", model="haiku"
    )
    assert agent_cmd[agent_cmd.index("--model") + 1] == "haiku"

    chat_cmd = build_chat_command(cwd="/repos/x", profile_id=None, model="deepseek-v4-flash")
    assert chat_cmd[chat_cmd.index("--model") + 1] == "deepseek-v4-flash"


def test_wire_flag_is_forwarded_in_both_modes():
    agent_cmd = build_command(
        session_id="core_abc", cwd="/repos/x", profile_id="fd708df2", wire="openai"
    )
    assert agent_cmd[agent_cmd.index("--wire") + 1] == "openai"

    chat_cmd = build_chat_command(cwd="/repos/x", profile_id="fd708df2", wire="OpenAI")
    assert chat_cmd[chat_cmd.index("--wire") + 1] == "openai"


def test_api_profile_preserves_wire_field():
    from frago.init.profile_manager import APIProfile

    p = APIProfile(
        id="fd708df2",
        name="Colab-Clover-35B",
        endpoint_type="custom",
        api_key="sk-test",
        url="https://absent-dozens-thinks-habits.trycloudflare.com",
        default_model="Diffuspace/Clover-35B-A3B-Preview",
        wire="openai",
    )
    dumped = p.model_dump(mode="json")
    assert dumped["wire"] == "openai"
