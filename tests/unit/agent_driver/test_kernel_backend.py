"""内核一轮的归类：把 frago-core 的 (returncode, stdout JSON) 翻成 frago 的四态。

夹具是从真机实测样本上抄下来的（2026-10-09，``frago-core --mode agent -p ... --output-format
json``）：成功、模型调用失败、连接没解析出来三种。内核自己的退出码只有 0/1/2，与 frago 的
0/1/2/3 **同名不同义**，所以每一条映射都得有对照——不然"连接没配好"会被读成"需要真人介入"。
"""

from __future__ import annotations

from frago.agent_driver.kernel_backend import _classify, _parse_payload

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
