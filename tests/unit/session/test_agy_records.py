"""agy 记录翻译层的单测（``frago.session.adapters.agy_records``）。

重点守五件事：

1. **人那句话要从 ``<USER_REQUEST>`` 里取出来**，外面那几段元数据另立一条「注入内容」。
   整段照收的话，界面上一句提问会被顶上一大段 agy 自己的环境说明。
2. **一行翻出多条时编号必须分开**。模型一拍可以同时带 ``thinking``、``tool_calls`` 与
   ``content``，编号撞了就会被去重吃掉两条。
3. **工具结果靠来源认、不靠工具名白名单**。认白名单的话，agy 每加一个工具，它那一步就
   退化成一条空的「未识别注入」。
4. **工具结果要配回它那次调用**。配不上宁可按行号另编一个，也不能挂到别的调用上去。
5. **只有明写 ``DONE`` 才算跑成**，其余一律按没跑成算。

记录的形状原样抄自 2026-10-13 打在真实 ``transcript.jsonl`` 上的字段（键名、类型、
``created_at`` 的写法都没改），只有正文换成了占位内容。
"""

import json

import pytest

from frago.session import agy_store, record_reader
from frago.session.adapters import agy_records

CONVERSATION_ID = "481b5141-cdf9-4a3a-aeea-535dfa1c0df0"


@pytest.fixture()
def app_dir(tmp_path, monkeypatch):
    """把 agy 的应用数据目录指到临时目录，别碰用户真实的那一份。"""
    root = tmp_path / "antigravity-cli"
    root.mkdir()
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(root))
    return root


def _write(app_dir, records, conversation_id=CONVERSATION_ID):
    path = agy_store.transcript_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def _user(step, content, source="USER_EXPLICIT", at="2026-10-13T11:42:52Z"):
    return {
        "step_index": step,
        "source": source,
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": at,
        "content": content,
    }


def _planner(
    step,
    *,
    thinking=None,
    tool_calls=None,
    content=None,
    at="2026-10-13T11:42:57Z",
    input_tokens=None,
    cache_read_tokens=None,
    output_tokens=None,
):
    record = {
        "step_index": step,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "status": "DONE",
        "created_at": at,
    }
    if thinking is not None:
        record["thinking"] = thinking
    if tool_calls is not None:
        record["tool_calls"] = tool_calls
    if content is not None:
        record["content"] = content
    # 用量三个数只在真跑过模型的那一条上有；不给就是"这一条没带用量"。
    for key, value in (
        ("input_tokens", input_tokens),
        ("cache_read_tokens", cache_read_tokens),
        ("output_tokens", output_tokens),
    ):
        if value is not None:
            record[key] = value
    return record


def _system_message(step, body, *, source="SYSTEM_SDK", truncated=False):
    """一条系统消息。hook 注入与 agy 自己的通知共用这个类型，靠正文那句话分。"""
    record = {
        "step_index": step,
        "source": source,
        "type": "SYSTEM_MESSAGE",
        "status": "DONE",
        "created_at": "2026-10-13T11:42:53Z",
        "content": (
            "The following is a <SYSTEM_MESSAGE> not actually sent by the user. "
            "It is provided by the system as important information to pay attention to."
            f"\n\n<SYSTEM_MESSAGE>\n{body}\n</SYSTEM_MESSAGE>"
        ),
    }
    if truncated:
        record["truncated_fields"] = ["content"]
    return record


def _hook_message(step, event, injected, *, truncated=False):
    """一条 hook 注入。那句 ``injected by a … hook:`` 是 agy 自己打的标签，原样照抄。"""
    return _system_message(
        step,
        f"The following system message was injected by a {event} hook:\n{injected}",
        truncated=truncated,
    )


def _tool_step(step, name, content, *, status="DONE", truncated=False):
    record = {
        "step_index": step,
        "source": "MODEL",
        "type": name,
        "status": status,
        "created_at": "2026-10-13T11:43:00Z",
        "content": content,
    }
    if truncated:
        record["truncated_fields"] = ["content"]
    return record


def _translate(app_dir, records, conversation_id=CONVERSATION_ID):
    _write(app_dir, records, conversation_id)
    return agy_records.translate_session(conversation_id)


# ── 用户输入 ────────────────────────────────────────────────────────
def test_用户那句话从标签里取出来_元数据另立一条注入(app_dir):
    records = _translate(
        app_dir,
        [
            _user(
                0,
                "<USER_REQUEST>帮我把这件事办完</USER_REQUEST>\n"
                "<ADDITIONAL_METADATA>工作目录 /Users/frago</ADDITIONAL_METADATA>\n"
                "<USER_SETTINGS_CHANGE>model=medium</USER_SETTINGS_CHANGE>",
            )
        ],
    )
    assert [r.kind for r in records] == ["user.say", "context.inject"]
    assert records[0].payload["text"] == "帮我把这件事办完"
    assert "<ADDITIONAL_METADATA>" not in records[0].payload["text"]
    assert "工作目录" in records[1].payload["body"]
    assert records[1].payload["unrecognized"] is False


def test_标签拆不出来时整段都算人那句话(app_dir):
    """拆不出标签时按标签切会把正文整段丢掉，界面上这场会话就一句用户发言都没有。"""
    records = _translate(app_dir, [_user(0, "没有标签的一句话")])
    assert [r.kind for r in records] == ["user.say"]
    assert records[0].payload["text"] == "没有标签的一句话"


def test_历史回放那一行跳过(app_dir):
    """``CONVERSATION_HISTORY`` 是 agy 自己的记账，翻进时间线只会把真正的内容挤走。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>hi</USER_REQUEST>"),
            {
                "step_index": 1,
                "source": "SYSTEM",
                "type": "CONVERSATION_HISTORY",
                "status": "DONE",
                "created_at": "2026-10-13T11:42:53Z",
            },
        ],
    )
    assert [r.kind for r in records] == ["user.say"]


# ── 模型一拍 ────────────────────────────────────────────────────────
def test_想与动手与说话各是一条且编号互不相同(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>查一下</USER_REQUEST>"),
            _planner(
                1,
                thinking="先搜一下",
                tool_calls=[{"name": "search_web", "args": {"query": "x"}}],
                content="我这就去看",
            ),
        ],
    )
    assert [r.kind for r in records] == [
        "user.say",
        "agent.think",
        "tool.call",
        "agent.say",
    ]
    ids = [r.id for r in records]
    assert len(set(ids)) == len(ids)


def test_工具调用带上大类与原始参数(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>查一下</USER_REQUEST>"),
            _planner(1, tool_calls=[{"name": "search_web", "args": {"query": "限额"}}]),
        ],
    )
    call = records[-1]
    assert call.kind == "tool.call"
    assert call.payload["tool_name"] == "search_web"
    assert call.payload["tool_family"] == "web"
    assert call.payload["args"] == {"query": "限额"}


def test_认不出的工具名归other(app_dir):
    """工具名不是封闭集合，认不出的一律 other，NEVER 因为没见过的名字炸。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, tool_calls=[{"name": "某种新工具", "args": {}}]),
        ],
    )
    assert records[-1].payload["tool_family"] == "other"


# ── 工具跑完那一步 ──────────────────────────────────────────────────
def test_工具结果配上前面那次调用(app_dir):
    """agy 的结果那一步不带调用编号，靠工具名与先来后到配对。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>查一下</USER_REQUEST>"),
            _planner(1, tool_calls=[{"name": "search_web", "args": {}}]),
            _tool_step(2, "SEARCH_WEB", "搜到的东西"),
        ],
    )
    call, result = records[-2], records[-1]
    assert result.kind == "tool.result"
    assert result.payload["call_id"] == call.payload["call_id"]
    assert result.payload["tool_name"] == "search_web"
    assert result.payload["tool_family"] == "web"
    assert result.payload["body"] == "搜到的东西"


def test_配不上调用时按行号另编一个(app_dir):
    """配不上宁可让界面知道"这一步有结果、不知道对应哪次调用"，也不能挂到别的调用上。"""
    records = _translate(app_dir, [_tool_step(0, "SEARCH_WEB", "凭空一个结果")])
    assert records[0].kind == "tool.result"
    assert records[0].payload["call_id"] == f"ag{0}"


def test_两个同名工具按先来后到各配一次(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>查两次</USER_REQUEST>"),
            _planner(1, tool_calls=[{"name": "search_web", "args": {"query": "一"}}]),
            _tool_step(2, "SEARCH_WEB", "结果一"),
            _planner(3, tool_calls=[{"name": "search_web", "args": {"query": "二"}}]),
            _tool_step(4, "SEARCH_WEB", "结果二"),
        ],
    )
    calls = [r for r in records if r.kind == "tool.call"]
    results = [r for r in records if r.kind == "tool.result"]
    assert [r.payload["call_id"] for r in results] == [c.payload["call_id"] for c in calls]
    assert calls[0].payload["call_id"] != calls[1].payload["call_id"]


def test_截断过的正文照实说(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _tool_step(1, "SEARCH_WEB", "被截过的正文", truncated=True),
        ],
    )
    assert records[-1].payload["truncation"] == "clipped"


def test_没被截过时说完整(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _tool_step(1, "SEARCH_WEB", "完整正文"),
        ],
    )
    assert records[-1].payload["truncation"] == "none"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("DONE", "ok"),
        ("ERROR", "error"),
        ("CANCELED", "error"),
        ("INTERRUPTED", "error"),
        ("HALTED", "error"),
    ],
)
def test_只有明写DONE才算跑成(app_dir, status, expected):
    """把一次没跑成摆成成功，比把成功摆成失败坏得多——前者会让人以为那个动作真的发生了。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _tool_step(1, "SEARCH_WEB", "正文", status=status),
        ],
    )
    assert records[-1].payload["status"] == expected


# ── 编号、轮次、原文 ────────────────────────────────────────────────
def test_序号按物理行序(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>一</USER_REQUEST>"),
            _planner(1, content="答一"),
            _user(2, "<USER_REQUEST>二</USER_REQUEST>"),
            _planner(3, content="答二"),
        ],
    )
    assert [r.seq for r in records] == list(range(len(records)))


def test_轮次分组键取用户输入的步号(app_dir):
    """用户输入类不设分组键；它之后的那些都归到它这一轮。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>一</USER_REQUEST>"),
            _planner(1, content="答一"),
            _user(2, "<USER_REQUEST>二</USER_REQUEST>"),
            _planner(3, content="答二"),
        ],
    )
    by_kind = {r.kind: r for r in records}
    assert by_kind["user.say"].group_id is None
    assert [r.group_id for r in records if r.kind != "user.say"] == ["0", "2"]


def test_时刻按转录行上那个(app_dir):
    records = _translate(app_dir, [_user(0, "<USER_REQUEST>x</USER_REQUEST>")])
    assert records[0].ts > 0


def test_取原文按编号回查(app_dir):
    _write(app_dir, [_user(0, "<USER_REQUEST>回查这句</USER_REQUEST>")])
    raw = agy_records.AgyRecordAdapter().read_raw(CONVERSATION_ID, "ag0")
    assert raw is not None
    assert "回查这句" in raw["content"]


def test_取不存在的编号返回None(app_dir):
    _write(app_dir, [_user(0, "<USER_REQUEST>x</USER_REQUEST>")])
    assert agy_records.AgyRecordAdapter().read_raw(CONVERSATION_ID, "ag999") is None


def test_认不出的记录归未识别的注入(app_dir):
    """NEVER 静默丢弃：丢掉的记录在界面上等于没发生过。"""
    records = _translate(
        app_dir,
        [{"step_index": 0, "source": "SYSTEM", "type": "某种新记账", "status": "DONE"}],
    )
    assert [r.kind for r in records] == ["context.inject"]
    assert records[0].payload["unrecognized"] is True
    assert records[0].payload["record_type"] == "某种新记账"


def test_会话文件不在时翻出空表(app_dir):
    assert agy_records.translate_session("00000000-0000-0000-0000-000000000000") == []


# ── 分页 ────────────────────────────────────────────────────────────
def test_分页按闭区间起点取(app_dir):
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>一</USER_REQUEST>"),
            _planner(1, content="答一"),
            _user(2, "<USER_REQUEST>二</USER_REQUEST>"),
            _planner(3, content="答二"),
        ],
    )
    adapter = agy_records.AgyRecordAdapter()
    assert [r.seq for r in adapter.to_unified(CONVERSATION_ID, 0, 2)] == [0, 1]
    assert [r.seq for r in adapter.to_unified(CONVERSATION_ID, 2, 2)] == [2, 3]


def test_尾部取法落在最后几条上(app_dir):
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>一</USER_REQUEST>"),
            _planner(1, content="答一"),
            _user(2, "<USER_REQUEST>二</USER_REQUEST>"),
            _planner(3, content="答二"),
        ],
    )
    adapter = agy_records.AgyRecordAdapter()
    records = adapter.to_unified(CONVERSATION_ID, 0, 2, tail=True)
    assert [r.kind for r in records] == ["user.say", "agent.say"]
    assert records[-1].payload["text"] == "答二"


# ── hook 注入：认得出、也认得对 ─────────────────────────────────────
def test_hook注入单独立一档(app_dir):
    """界面把 Hooks 那一档数出来，唯一的判据就是 ``payload.source == "hook"``。

    2026-10-14 之前这里认不出这条记录，它落进「未识别注入」，于是开场明明注进了宪法，
    工作台上 Hooks 那一档却写着 0——注入是生效的，是记账记错了地方。
    """
    records = _translate(app_dir, [_hook_message(0, "SessionStart", "【必须遵守】…")])
    assert [r.kind for r in records] == ["context.inject"]
    payload = records[0].payload
    assert payload["source"] == "hook"
    assert payload["channel"] == "hook"
    assert payload["hook_event"] == "SessionStart"
    assert payload["unrecognized"] is False
    assert payload["blocks"] == ["【必须遵守】…"]
    assert payload["body"] == "【必须遵守】…"


def test_注入正文不带包裹它的闭合标签(app_dir):
    """``</SYSTEM_MESSAGE>`` 是 agy 包注入内容用的，不是注入的内容。"""
    records = _translate(app_dir, [_hook_message(0, "PreInvocation", "先查手册")])
    assert records[0].payload["body"] == "先查手册"
    assert "</SYSTEM_MESSAGE>" not in records[0].payload["body"]


def test_事件名从标签里读(app_dir):
    """标签里写的是哪个事件就是哪个，不靠类型猜。"""
    records = _translate(app_dir, [_hook_message(0, "SessionStart", "开场那份")])
    assert records[0].payload["hook_event"] == "SessionStart"


def test_事件名翻成界面认得的那一套(app_dir):
    """agy 的 ``PreInvocation`` 摆出去就是一句机器名——它对应的引擎事件叫 UserPromptSubmit。"""
    records = _translate(app_dir, [_hook_message(0, "PreInvocation", "每轮那份")])
    assert records[0].payload["hook_event"] == "UserPromptSubmit"


def test_agy自己的系统通知不算hook(app_dir):
    """同一个记录类型下也躺着 agy 自己的通知（"所有子代理因服务重启已停止"）。

    把它算成 hook 注入，Hooks 那一档就掺进了不是 hook 的东西；照旧摆出来标未识别，
    好过挂错档。
    """
    records = _translate(
        app_dir,
        [
            _system_message(
                0,
                "[Message] timestamp=2026-10-14T05:54:37Z sender=system "
                "priority=MESSAGE_PRIORITY_LOW content=[Notice] All your subagents and "
                "background tasks have been stopped due to server restart.",
                source="SYSTEM",
            )
        ],
    )
    assert [r.kind for r in records] == ["context.inject"]
    assert records[0].payload["unrecognized"] is True
    assert records[0].payload["source"] != "hook"


def test_即弃注入也算hook(app_dir):
    """``ephemeralMessage`` 的落盘形态：正文就是注入原文，外面没有任何包裹。

    2026-10-14 实测确认过这个形状（一条 ``{"ephemeralMessage": "PROBE-EPHEMERAL-99887"}``
    原样落成这个类型）。轻量 ai 每轮那份走的就是它，认不出的话工作台 Hooks 那一档仍然
    数不到每轮的注入。
    """
    records = _translate(
        app_dir,
        [
            {
                "step_index": 3,
                "source": "SYSTEM_SDK",
                "type": "EPHEMERAL_MESSAGE",
                "status": "DONE",
                "created_at": "2026-10-13T11:42:54Z",
                "content": "这一轮先查手册",
            }
        ],
    )
    assert [r.kind for r in records] == ["context.inject"]
    payload = records[0].payload
    assert payload["source"] == "hook"
    assert payload["body"] == "这一轮先查手册"
    assert payload["unrecognized"] is False


def test_即弃注入标的是界面认得的那个事件名(app_dir):
    """agy 叫 PreInvocation，界面上那张对照表按引擎的词表写，只认 UserPromptSubmit。

    原样摆 ``PreInvocation`` 出去，卡片上就是一句机器名。
    """
    records = _translate(
        app_dir,
        [
            {
                "step_index": 3,
                "source": "SYSTEM_SDK",
                "type": "EPHEMERAL_MESSAGE",
                "status": "DONE",
                "created_at": "2026-10-13T11:42:54Z",
                "content": "x",
            }
        ],
    )
    assert records[0].payload["hook_event"] == "UserPromptSubmit"
    assert records[0].payload["label"] == "UserPromptSubmit"


def test_不是sdk来的即弃消息不算hook(app_dir):
    """注入都从 SDK 那一侧进来；别的来源照旧走未识别，别挂错档。"""
    records = _translate(
        app_dir,
        [
            {
                "step_index": 3,
                "source": "SYSTEM",
                "type": "EPHEMERAL_MESSAGE",
                "status": "DONE",
                "created_at": "2026-10-13T11:42:54Z",
                "content": "x",
            }
        ],
    )
    assert records[0].payload["unrecognized"] is True
    assert records[0].payload["source"] != "hook"


# ── 读给人看的是未截的那一份 ────────────────────────────────────────
def _write_both(app_dir, clipped, full, conversation_id=CONVERSATION_ID):
    """主账与未截那份各写一份，行数一样、只有正文长度不同——真实的样子。"""
    plain = agy_store.transcript_path(conversation_id)
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in clipped) + "\n", encoding="utf-8"
    )
    agy_store.full_transcript_path(conversation_id).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in full) + "\n", encoding="utf-8"
    )


def test_展示读未截的那一份(app_dir):
    """主账把长正文剪短过，照它摆出去，人看到的是"当时注进来的只有这么点"。"""
    clipped = _hook_message(0, "SessionStart", "短的")
    clipped["truncated_fields"] = ["content"]
    full = _hook_message(0, "SessionStart", "完整的那一长段")
    _write_both(app_dir, [clipped], [full])

    records = agy_records.translate_session(CONVERSATION_ID)

    assert records[0].payload["body"] == "完整的那一长段"
    assert "truncation" not in records[0].payload


def test_未截那份不在时退回主账(app_dir):
    """多一份文件不在，不该让整场会话读不出来。"""
    _write(app_dir, [_user(0, "<USER_REQUEST>退回主账也能读</USER_REQUEST>")])

    records = agy_records.translate_session(CONVERSATION_ID)

    assert [r.kind for r in records] == ["user.say"]
    assert records[0].payload["text"] == "退回主账也能读"


def test_完成探针仍读主账(app_dir):
    """探针只回读末尾一段固定字节数；未截那份大出四成，同样一段窗口盖住的记录就少一截。

    两份条数与次序一致（本机 9 场逐个核过），所以探针读哪份判出来的结果一样——挑小的
    那份是为了让那一段窗口盖得住长会话。
    """
    _write_both(
        app_dir,
        [_user(0, "<USER_REQUEST>主账这句</USER_REQUEST>")],
        [_user(0, "<USER_REQUEST>未截那句</USER_REQUEST>")],
    )

    assert agy_store.display_transcript_path(CONVERSATION_ID).name == "transcript_full.jsonl"
    assert agy_store.transcript_path(CONVERSATION_ID).name == "transcript.jsonl"
    assert agy_store.latest_turn(CONVERSATION_ID) is not None


def test_被截过的注入照实说(app_dir):
    """agy 那条 SessionStart 注入在本机就是被截过的，摆成完整的等于骗人。"""
    records = _translate(app_dir, [_hook_message(0, "SessionStart", "半截", truncated=True)])
    assert records[0].payload["truncation"] == "clipped"


def test_没被截过时不提这回事(app_dir):
    records = _translate(app_dir, [_hook_message(0, "SessionStart", "完整")])
    assert "truncation" not in records[0].payload


# ── 用量刻度 ────────────────────────────────────────────────────────
def test_一条模型回复产一道刻度(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, content="答", input_tokens=100, cache_read_tokens=900, output_tokens=50),
        ],
    )
    ticks = [r for r in records if r.kind == "usage.tick"]
    assert len(ticks) == 1
    assert ticks[0].payload["context_tokens"] == 1000
    assert ticks[0].payload["total_tokens"] == 1050
    assert ticks[0].payload["breakdown"] == {
        "input": 100,
        "output": 50,
        "cache_creation": 0,
        "cache_read": 900,
    }


def test_上下文水位把缓存读的也算进去(app_dir):
    """那些 token 确实被模型读了一遍，也确实计费——扣掉得到的是另一个数，不是这个数。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, content="答", input_tokens=10, cache_read_tokens=990, output_tokens=0),
        ],
    )
    tick = next(r for r in records if r.kind == "usage.tick")
    assert tick.payload["context_tokens"] == 1000


def test_累计是流水_逐条往上加(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>一</USER_REQUEST>"),
            _planner(1, content="答一", input_tokens=100, output_tokens=10),
            _user(2, "<USER_REQUEST>二</USER_REQUEST>"),
            _planner(3, content="答二", input_tokens=200, output_tokens=20),
        ],
    )
    ticks = [r for r in records if r.kind == "usage.tick"]
    assert [t.payload["total_tokens"] for t in ticks] == [110, 330]
    # 水位不累加——累加出来的数没有任何含义。
    assert [t.payload["context_tokens"] for t in ticks] == [100, 200]


def test_没带用量的那一条不出刻度(app_dir):
    """只有想、只有工具调用的那一拍没有用量，凭空出一道 0 的刻度是编数据。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, tool_calls=[{"name": "search_web", "args": {}}]),
        ],
    )
    assert [r.kind for r in records if r.kind == "usage.tick"] == []


def test_刻度按编号回查不到原文(app_dir):
    """刻度是算出来的，不是档案里的某一行。挂一个点不开的入口比不挂更糟。"""
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, content="答", input_tokens=1, output_tokens=1),
        ],
    )
    tick = next(r for r in agy_records.translate_session(CONVERSATION_ID) if r.kind == "usage.tick")
    assert tick.raw_available is False


def test_刻度独立成行_不进那一轮的归组容器(app_dir):
    """它说的不是"这次回复的一部分"，是"到这里为止烧了多少"。"""
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, content="答", input_tokens=1, output_tokens=1),
        ],
    )
    tick = next(r for r in records if r.kind == "usage.tick")
    assert tick.group_id is None


# ── 模型名：转录里没有，去另一处问 ──────────────────────────────────
def _write_conversation_db(app_dir, blob, conversation_id=CONVERSATION_ID, table="gen_metadata"):
    import sqlite3

    path = agy_store.conversation_db_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table} (idx INTEGER, data BLOB, size INTEGER)")
    conn.execute(f"INSERT INTO {table} VALUES (0, ?, ?)", (blob, len(blob)))
    conn.commit()
    conn.close()


def test_模型名从会话库的二进制块里抠出来(app_dir):
    """转录一个字都没写是谁答的，全机只有这一处记着。"""
    _write_conversation_db(
        app_dir,
        b"\x00\x12sessionID\x00\x1a\x0bclaude-sonnet-5-5-medium\x00"
        b"used_non_gemini_model\x00true\x00model_enum\x00MODEL_PLACEHOLDER_M404\x00",
    )
    assert agy_store.session_model(CONVERSATION_ID) == "claude-sonnet-5-5-medium"


def test_近邻那些像模型名的串都挡在外面(app_dir):
    """同一个块里还躺着 ``disable-teamwork-forced-flash-model`` 这类近邻。

    式子收尾必须落在档位词上，才分得开——收在别的词上的串一律不算。
    """
    _write_conversation_db(
        app_dir,
        b"disable-teamwork-forced-flash-model\x00gemini-3.8-flash-n\x00gemini-3.8-flash-medium\x00",
    )
    assert agy_store.session_model(CONVERSATION_ID) == "gemini-3.8-flash-medium"


def test_库不在或没有这个表时不给模型名(app_dir):
    """失效方式是静默降级：那一格空着，其余两个数照常，绝不编一个名字顶上。"""
    assert agy_store.session_model(CONVERSATION_ID) is None
    _write_conversation_db(app_dir, b"nothing here", table="executor_metadata")
    assert agy_store.session_model(CONVERSATION_ID) is None


def test_模型名落到刻度与回复上(app_dir):
    _write_conversation_db(app_dir, b"\x00gemini-3.8-flash-medium\x00")
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, content="答", input_tokens=1, output_tokens=1),
        ],
    )
    assert next(r for r in records if r.kind == "usage.tick").payload["model"] == (
        "gemini-3.8-flash-medium"
    )
    assert next(r for r in records if r.kind == "agent.say").payload["model"] == (
        "gemini-3.8-flash-medium"
    )


def test_没有模型名时不编一个(app_dir):
    records = _translate(
        app_dir,
        [
            _user(0, "<USER_REQUEST>x</USER_REQUEST>"),
            _planner(1, content="答", input_tokens=1, output_tokens=1),
        ],
    )
    assert next(r for r in records if r.kind == "usage.tick").payload["model"] is None


# ── 递给引擎复核那一趟的料 ──────────────────────────────────────────
def test_复核拿到本轮那句话与前面几轮的提要(app_dir):
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>第一句</USER_REQUEST>"),
            _planner(1, content="答一"),
            _user(2, "<USER_REQUEST>第二句</USER_REQUEST>"),
        ],
    )
    prompt, recent = agy_records.context_for_review(None, CONVERSATION_ID)
    assert prompt == "第二句"
    # 本轮那句不重复进提要——两边都给等于让复核把同一句读两遍。
    assert "第二句" not in recent
    assert "[用户] 第一句" in recent
    assert "[助手] 答一" in recent


def test_复核的提要带得动工具调用(app_dir):
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>查一下</USER_REQUEST>"),
            _planner(1, tool_calls=[{"name": "run_command", "args": {"CommandLine": "ls"}}]),
            _user(2, "<USER_REQUEST>再查</USER_REQUEST>"),
        ],
    )
    _prompt, recent = agy_records.context_for_review(None, CONVERSATION_ID)
    assert "[调用] run_command" in recent


def test_转录读不到时两样都给None(app_dir):
    """读不出来就什么都不给：引擎退化成"只有规则、没有复核"，比照着错的那句话判好。"""
    assert agy_records.context_for_review(None, "00000000-0000-0000-0000-000000000000") == (
        None,
        None,
    )
    assert agy_records.context_for_review(None, None) == (None, None)


# ── 一轮一次：哪一次才算是"用户刚提交" ────────────────────────────────
def test_本轮第一次模型调用认得出(app_dir):
    """最后一条 USER_INPUT 之后还没有 PLANNER_RESPONSE —— 这就是用户刚提交的那一下。"""
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>上一轮</USER_REQUEST>"),
            _planner(1, content="上一答"),
            _user(2, "<USER_REQUEST>本轮这句</USER_REQUEST>"),
        ],
    )
    prompt, _recent, is_first = agy_records.review_context(None, CONVERSATION_ID)
    assert prompt == "本轮这句"
    assert is_first is True


def test_同一轮的后续步骤认得出不是第一次(app_dir):
    """本轮已经跑过一拍模型了，眼下的 PreInvocation 是后续步骤，不该再跑复核。"""
    _write(
        app_dir,
        [
            _user(0, "<USER_REQUEST>本轮这句</USER_REQUEST>"),
            _planner(1, content="第一拍"),
        ],
    )
    _prompt, _recent, is_first = agy_records.review_context(None, CONVERSATION_ID)
    assert is_first is False


def test_后续步骤数个几拍都还是不是第一次(app_dir):
    """一轮之内第 2、3、5 拍都一样：只要本轮的 PLANNER_RESPONSE 出现过就不算第一次。"""
    for extra in (2, 3, 5):
        _write(
            app_dir,
            [
                _user(0, "<USER_REQUEST>本轮这句</USER_REQUEST>"),
                *[_planner(i, content=f"第{i}拍") for i in range(1, extra + 1)],
            ],
        )
        _prompt, _recent, is_first = agy_records.review_context(None, CONVERSATION_ID)
        assert is_first is False, f"本轮已有 {extra} 拍，不该判成第一次"


def test_转录读不到时当第一次处理(app_dir):
    """判不出来就放行：复核少跑一次的代价远小于它悄悄再也不跑。"""
    assert agy_records.review_context(None, "00000000-0000-0000-0000-000000000000")[2] is True
    assert agy_records.review_context(None, None)[2] is True


def test_优先用agy递过来的路径(app_dir, tmp_path):
    """hook 载荷里那份路径是 agy 自己给的，比按编号去猜准。"""
    elsewhere = tmp_path / "别处" / "transcript.jsonl"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text(
        json.dumps(_user(0, "<USER_REQUEST>从别处读到的</USER_REQUEST>"), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt, _recent = agy_records.context_for_review(str(elsewhere), CONVERSATION_ID)
    assert prompt == "从别处读到的"


# ── 家族判定 ────────────────────────────────────────────────────────
def test_编得出来这场会话就归agy(app_dir, monkeypatch):
    """agy 的编号是裸 UUID，与另外三家撞形状，所以判定要落盘看一眼。"""
    monkeypatch.setattr(record_reader, "_is_codex_session", lambda sid: False)
    monkeypatch.setattr(record_reader, "_is_coreagent_session", lambda sid: False)
    _write(app_dir, [_user(0, "<USER_REQUEST>x</USER_REQUEST>")])

    assert record_reader.detect_family(CONVERSATION_ID) == "agy"


def test_agy那边没有这场就退回ClaudeCode(app_dir, monkeypatch):
    monkeypatch.setattr(record_reader, "_is_codex_session", lambda sid: False)
    monkeypatch.setattr(record_reader, "_is_coreagent_session", lambda sid: False)

    assert record_reader.detect_family(CONVERSATION_ID) == "claude-code"


def test_brain目录整个不在时不当成agy(monkeypatch, tmp_path):
    """读不到不等于会话没了，但判家族不许把它归给 agy——那会让每一个裸 UUID 都成 agy。"""
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(tmp_path / "never-created"))
    assert record_reader._is_agy_session(CONVERSATION_ID) is False


# ── 归一成 monitor 认的形状 ─────────────────────────────────────────
def test_用户那半轮只取人那句话(app_dir):
    """外面那几段元数据不进实时流——进去了，前端每条提问都顶着一段环境说明。"""
    payloads = agy_records.record_payloads(
        _user(
            0,
            "<USER_REQUEST>帮我把这件事办完</USER_REQUEST><ADDITIONAL_METADATA>目录 /x</ADDITIONAL_METADATA>",
        ),
        CONVERSATION_ID,
        include_user=True,
    )
    assert [kind for kind, _ in payloads] == [agy_records.RECORD_USER_TEXT]
    kind, payload = payloads[0]
    assert payload["role"] == "user"
    assert payload["content"] == "帮我把这件事办完"
    assert payload["session_id"] == CONVERSATION_ID


def test_实时流里不重复投用户那句(app_dir):
    """实时流里用户消息由主路径自己投递，重复投会在前端出现两遍；归档那一路才要它。"""
    assert (
        agy_records.record_payloads(_user(0, "<USER_REQUEST>x</USER_REQUEST>"), CONVERSATION_ID)
        == []
    )


def test_模型说了话就出正文(app_dir):
    payloads = agy_records.record_payloads(
        _planner(2, thinking="想了点什么", content="答完了"), CONVERSATION_ID
    )
    assert [kind for kind, _ in payloads] == [agy_records.RECORD_TEXT]
    assert payloads[0][1]["content"] == "答完了"


def test_只说想不说话的模型不成一条记录(app_dir):
    """codex 那边的 ``reasoning`` 也是这么处理的：不是一轮的任一半，不进时间线。"""
    assert agy_records.record_payloads(_planner(2, thinking="只有想"), CONVERSATION_ID) == []


def test_要动手时出工具调用(app_dir):
    payloads = agy_records.record_payloads(
        _planner(2, tool_calls=[{"name": "search_web", "args": {"query": "x"}}]), CONVERSATION_ID
    )
    kind, payload = payloads[0]
    assert kind == agy_records.RECORD_TOOL_CALL
    assert payload["tool_calls"] == [
        {"id": "search_web", "name": "search_web", "input": {"query": "x"}}
    ]


def test_工具结果的编号就是工具名_两边对得上(app_dir):
    """agy 不给调用编号。两边都用工具名当编号，消费方取名字那一步才配得上。"""
    call = agy_records.record_payloads(
        _planner(2, tool_calls=[{"name": "search_web", "args": {}}]), CONVERSATION_ID
    )[0][1]
    result = agy_records.record_payloads(
        _tool_step(3, "SEARCH_WEB", "搜到的东西"), CONVERSATION_ID
    )[0][1]

    assert result["tool_results"][0]["tool_use_id"] == call["tool_calls"][0]["id"]
    assert result["tool_results"][0]["content"] == "搜到的东西"


def test_没跑成的工具结果标成错(app_dir):
    payload = agy_records.record_payloads(
        _tool_step(3, "SEARCH_WEB", "正文", status="INTERRUPTED"), CONVERSATION_ID
    )[0][1]

    assert payload["tool_results"][0]["is_error"] is True


def test_历史回放不成记录(app_dir):
    record = {"step_index": 0, "source": "SYSTEM", "type": "CONVERSATION_HISTORY"}
    assert agy_records.record_payloads(record, CONVERSATION_ID, include_user=True) == []


# ── monitor 那一侧的适配器 ──────────────────────────────────────────
def test_adapter_认原始转录行(app_dir):
    """``JsonlTranscriptSource`` 只会逐行 tail 再调 ``parse_record``，形状要在适配器里认。"""
    from frago.session.models import AgentType
    from frago.session.monitor import get_adapter

    adapter = get_adapter(AgentType.AGY)
    assert adapter is not None

    record = adapter.parse_record(
        {**_user(0, "<USER_REQUEST>问一句</USER_REQUEST>"), "session_id": CONVERSATION_ID}
    )

    assert record is not None
    assert record.record_type == "user"
    assert record.content_text == "问一句"
    assert record.session_id == CONVERSATION_ID


def test_adapter_也认driver递过来的纯文本轮次(app_dir):
    """两路输入都要能走：一路是转录行，一路是 driver 已经归一好的那半轮。"""
    from frago.session.models import AgentType
    from frago.session.monitor import get_adapter

    adapter = get_adapter(AgentType.AGY)
    record = adapter.parse_record({"role": "assistant", "content": "答一句", "session_id": "s"})

    assert record is not None
    assert record.content_text == "答一句"
