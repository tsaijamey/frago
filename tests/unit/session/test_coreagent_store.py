"""CoreAgent 会话记录这一家的单测。

固定装置是 **frago-core 真跑一趟写出来的行**（``kernel/transcript_log.rs``，2026-09-21
实测），字段名、嵌套、公共字段的取值都照抄，NEVER 按文档想象一份。

这一家的全部要点是：记录的形状就是 Claude Code 的形状，所以翻译层一个字不改，只换根
目录。测试因此盯两件事——**来源分得开**（编号前缀判到 ``coreagent``、清单里独立成一家），
以及 **过程读得全**（工具调用、结果、被拦下的调用，一样不少）。
"""

import json

from frago.session import coreagent_store, record_reader, session_index

_CWD = "/private/tmp/work"
_SID = "core_e2edemo0001"


def _row(uuid, parent, kind, extra, ts="2026-09-21T13:20:00.000Z"):
    """一行记录的公共字段。frago-core 每行都写这几样。"""
    return {
        "parentUuid": parent,
        "isSidechain": False,
        "userType": "external",
        "cwd": _CWD,
        "sessionId": _SID,
        "version": "0.1.0",
        "gitBranch": "",
        "type": kind,
        "uuid": uuid,
        "timestamp": ts,
        **extra,
    }


def _transcript():
    """一趟完整的运行：人交代 → 规则补话 → 模型说话 → 调工具 → 被拦下 → 收场。"""
    return [
        _row("u1", None, "user", {
            "promptSource": "typed",
            "message": {"role": "user", "content": [{"type": "text", "text": "清一下临时目录"}]},
        }),
        _row("u2", "u1", "attachment", {
            "attachment": {
                "type": "hook_additional_context",
                "hookName": "UserPromptSubmit",
                "content": ["动手前先说清要清哪个路径"],
            },
        }),
        _row("u3", "u2", "assistant", {
            "message": {
                "id": "msg_3", "type": "message", "role": "assistant", "model": "replay",
                "content": [{"type": "text", "text": "我来清理一下临时目录。"}],
            },
        }),
        _row("u4", "u3", "assistant", {
            "message": {
                "id": "msg_4", "type": "message", "role": "assistant", "model": "replay",
                "content": [{
                    "type": "tool_use", "id": "t1", "name": "Bash",
                    "input": {"command": "rm -rf /tmp/nothing-here"},
                }],
            },
        }),
        _row("u5", "u4", "user", {
            "toolDenialKind": "〔not allowed〕调用不在允许范围：命中 --disallowed-tools 里的 `Bash(rm:*)`",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "t1", "is_error": True,
                "content": "〔not allowed〕调用不在允许范围：命中 --disallowed-tools 里的 `Bash(rm:*)`",
            }]},
        }),
        _row("u6", "u5", "assistant", {
            "message": {
                "id": "msg_6", "type": "message", "role": "assistant", "model": "replay",
                "content": [{"type": "text", "text": "这一步被拦下了，我没有动手。"}],
            },
        }),
    ]


def _write(root, session_id=_SID, rows=None):
    """照 frago-core 的落点摆一份：``<根>/<工作目录编码>/<会话编号>.jsonl``。"""
    directory = root / "-private-tmp-work"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in (rows or _transcript())) + "\n",
        encoding="utf-8",
    )
    return path


def test_编号前缀就能判出这一家(monkeypatch, tmp_path):
    """判这场属于谁只看前缀，不落盘——编号是 frago 自己发的。

    与 codex 那一家的区别正在这里：codex 的编号是 UUID 形状，与 Claude Code 撞车，只能
    去它的目录里看一眼；CoreAgent 不用。
    """
    assert record_reader.detect_family("core_e2edemo0001") == "coreagent"
    assert record_reader.detect_family("ses_058288655ffe") == "opencode"
    # 形状不像任何一家时照旧抛，NEVER 默认归给谁。
    try:
        record_reader.detect_family("not-a-session")
    except record_reader.UnknownSessionFamily:
        pass
    else:  # pragma: no cover - 判定放宽了才会走到
        raise AssertionError("认不出的编号必须抛，不能猜一家试试")


def test_整趟过程读得全含被拦下的那次(tmp_path):
    """工具调用、结果、被拦下的调用一样不少——这正是这件事要解决的问题。"""
    _write(tmp_path)
    records = coreagent_store.CoreAgentRecordAdapter(tmp_path).to_unified(_SID, 0, 50)
    kinds = [r.kind for r in records]
    assert kinds == [
        "user.say",
        "context.inject",
        "agent.say",
        "tool.call",
        "permission.outcome",
        "tool.result",
        "agent.say",
    ]
    said = records[0].payload
    assert said["text"] == "清一下临时目录"
    assert said["is_tool_result"] is False
    call = records[3].payload
    assert (call["tool_name"], call["tool_family"]) == ("Bash", "shell")
    assert call["args"]["command"] == "rm -rf /tmp/nothing-here"
    # 被拦下的那次出两条：拦截标记 + 状态为 denied 的结果。少任何一条，界面上都看不出
    # 这次调用是被挡住的，只看得出它"失败了"。
    assert records[4].payload["decision"] == "denied"
    assert "Bash(rm:*)" in records[4].payload["reason"]
    assert records[5].payload["status"] == "denied"
    assert records[6].payload["text"] == "这一步被拦下了，我没有动手。"


def _card_title(monkeypatch, root, session_id=_SID):
    """左栏那一行实际摆出来的标题。清单的根目录与索引都挪到临时目录，不碰真 ``~/.frago``。"""
    from frago.session.session_origin import OriginIndex

    monkeypatch.setattr(coreagent_store, "sessions_root", lambda: root)
    monkeypatch.setattr(session_index, "COREAGENT_CACHE_FILE", root / "index.json")
    cards = record_reader._coreagent_cards(OriginIndex(parents={}, workers=frozenset()))
    return next(c.title for c in cards if c.session_id == session_id)


def test_清单里单独成一家且标题取那句任务(monkeypatch, tmp_path):
    """左栏要看得出这一场是去干什么的。

    没人给这一场起过名字时，标题取开口第一句——那句正是交给它的任务。取不到时用会话
    编号，NEVER 留空串。
    """
    _write(tmp_path)
    rows = session_index.list_session_summaries(tmp_path, tmp_path / "index.json")
    assert [r.sid for r in rows] == [_SID]
    assert rows[0].first_user == "清一下临时目录"
    assert rows[0].cwd == _CWD
    assert rows[0].ai_title is None
    assert _card_title(monkeypatch, tmp_path) == "清一下临时目录"


def test_启动时起的名字盖过开口第一句(monkeypatch, tmp_path):
    """定时任务、待办拟稿这些由程序发起的会话，开口第一句是一整段说明书。

    二十场摆在左栏长得一模一样，人分不出哪行是哪条任务。所以发起方可以在启动时命名
    （``frago-core --title``），名字写成记录里的一行，清单优先认它。
    """
    named = [
        {"type": "ai-title", "aiTitle": "定时任务：清临时目录", "sessionId": _SID},
        *_transcript(),
    ]
    _write(tmp_path, rows=named)
    rows = session_index.list_session_summaries(tmp_path, tmp_path / "index.json")
    assert rows[0].ai_title == "定时任务：清临时目录"
    assert rows[0].first_user == "清一下临时目录", "开口第一句照旧读得到，只是不再当标题"
    assert _card_title(monkeypatch, tmp_path) == "定时任务：清临时目录"


def test_删掉之后清单里就没有它了(tmp_path):
    """删的是那个 JSONL，位置稳定、格式公开，不必借别人的命令。"""
    path = _write(tmp_path)
    assert coreagent_store.session_exists(_SID, tmp_path)
    deleted = coreagent_store.delete_session_files(_SID, tmp_path)
    assert deleted is not None
    assert deleted.problems == []
    assert not path.exists()
    assert not coreagent_store.session_exists(_SID, tmp_path)
    # 本机已经没有它了 ≠ 删不动：前者回 None 由调用方各说各话，NEVER 抛。
    assert coreagent_store.delete_session_files(_SID, tmp_path) is None
