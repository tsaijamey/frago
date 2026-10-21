"""agy hook 垫片的入参/出参转换。

盯三件人真会撞上的事：

1. **工具名与参数键要翻。** 引擎的规则写在 Claude Code 词表里（``Bash`` + ``tool_input.command``），
   agy 报的是 ``run_command`` + ``args.CommandLine``。名字不翻，规则一条都命中不了——2026-10-14
   实测，``tool_name=run_command`` 喂进引擎，rm 那条规则纹丝不动。用例直接盯翻译后的形状，
   因为那才是引擎看到的输入。
2. **出参按事件分三种形状。** SessionStart 要 ``injectSteps``、PreToolUse 要 ``decision``、
   其余一律 ``{}``。翻错形状 agy 直接不认——PreToolUse 尤其：``decision`` 是必填，缺了它
   agy 按**拒绝**处理（2026-10-14 实测，一条无害的 echo 被空理由挡下），所以引擎没意见时
   垫片回 ``ask``。
3. **坏输入降级成 ``ask``，绝不回 ``allow``。** 垫片夹在中间，它出错时若回一个"放行"，
   等于把引擎的拦截能力静默关掉；回 ``ask``（按 agy 自己的权限流程走）才是安全的降级。

全程不碰真引擎——那些转换是纯函数，钉它们即可；真跑一遍留给 spec 的手动验收。
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from frago.cli import agy_hook


# ── 入参：信封字段 ──────────────────────────────────────────────────
def test_信封字段翻成引擎认的名字():
    out = agy_hook.translate_input(
        {
            "conversationId": "c-1",
            "transcriptPath": "/tmp/x.jsonl",
            "workspacePaths": ["/tmp/proj"],
            "modelName": "auto",
        },
        "SessionStart",
    )
    assert out["hook_event_name"] == "SessionStart"
    assert out["session_id"] == "c-1"
    assert out["transcript_path"] == "/tmp/x.jsonl"
    assert out["cwd"] == "/tmp/proj"


def test_事件名只从参数来():
    """agy 的 payload 里没有事件名字段，事件名由 hooks.json 的 command 带进来。"""
    out = agy_hook.translate_input({"conversationId": "c-1"}, "Stop")
    assert out["hook_event_name"] == "Stop"


def test_缺的字段不硬造():
    """认不出的字段宁可不填：编一个假的 cwd 会让规则按错误的目录判事。"""
    out = agy_hook.translate_input({"conversationId": "c-1"}, "SessionStart")
    assert "cwd" not in out
    assert "transcript_path" not in out


# ── 入参：工具名与参数键 ────────────────────────────────────────────
def test_shell工具名与参数键都翻过去():
    """**这条是垫片存在的理由。** 引擎只认 Bash + tool_input.command。"""
    out = agy_hook.translate_input(
        {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm -rf /tmp/x", "Cwd": "/tmp"},
            },
            "conversationId": "c-1",
        },
        "PreToolUse",
    )
    assert out["tool_name"] == "Bash"
    assert out["tool_input"] == {"command": "rm -rf /tmp/x"}


def test_读文件工具名与参数键翻过去():
    out = agy_hook.translate_input(
        {"toolCall": {"name": "view_file", "args": {"AbsolutePath": "/etc/hosts"}}},
        "PreToolUse",
    )
    assert out["tool_name"] == "Read"
    assert out["tool_input"] == {"file_path": "/etc/hosts"}


def test_原生子代理工具名翻成Agent命中内置拦截规则():
    """agy 的 invoke_subagent 翻成 Agent，直接复用 builtin-tool-agent-deny 拦下。"""
    out = agy_hook.translate_input(
        {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "research", "Role": "Evaluator", "Prompt": "x"},
            }
        },
        "PreToolUse",
    )
    assert out["tool_name"] == "Agent"


def test_agy自己的记账键不进引擎():
    """toolAction / toolSummary 是给人看的，不是工具参数，留着只会污染引擎的输入。"""
    out = agy_hook.translate_input(
        {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "ls", "toolAction": "列出文件", "toolSummary": "ls"},
            }
        },
        "PreToolUse",
    )
    assert out["tool_input"] == {"command": "ls"}


def test_不认识的工具名原样透传():
    """凭空编一个 Claude Code 名字，只会让规则认错工具。透传至少让按名字匹配的规则有机会中。"""
    out = agy_hook.translate_input(
        {"toolCall": {"name": "moma_search", "args": {"query": "x"}}}, "PreToolUse"
    )
    assert out["tool_name"] == "moma_search"
    assert out["tool_input"] == {"query": "x"}


def test_post_tool_use带上错误():
    out = agy_hook.translate_input(
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "false"}}, "error": "exit 1"},
        "PostToolUse",
    )
    assert out["tool_response"] == {"error": "exit 1"}


# ── 出参：三种形状 ──────────────────────────────────────────────────
def test_session_start把上下文包成注入步():
    out = agy_hook.translate_output(
        "SessionStart",
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "宪法在此"}},
    )
    assert out == {"injectSteps": [{"systemMessage": {"systemMessage": "宪法在此"}}]}


def test_session_start没话说就回空对象():
    assert agy_hook.translate_output("SessionStart", {"hookSpecificOutput": {}}) == {}
    assert agy_hook.translate_output("SessionStart", {}) == {}


def test_pre_tool_use的拦截翻成decision():
    out = agy_hook.translate_output(
        "PreToolUse",
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "rm 被拦下",
            }
        },
    )
    assert out == {"decision": "deny", "reason": "rm 被拦下"}


def test_pre_tool_use把规则全文并进reason():
    """引擎把"为什么"和"规则全文"分两栏放，agy 只有一个 reason 栏，两者都要留住。"""
    out = agy_hook.translate_output(
        "PreToolUse",
        {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "拦下",
                "additionalContext": "正路：改用 frago def save",
            }
        },
    )
    assert out["decision"] == "deny"
    assert "拦下" in out["reason"]
    assert "frago def save" in out["reason"]


def test_pre_tool_use没有意见时回ask而不是allow():
    """**安全要点，也是实测撞出来的。** agy 的 PreToolUse 契约里 ``decision`` 是必填，缺了
    它 agy 按拒绝处理——2026-10-14 实测：垫片回 ``{}``，一条无害的 echo 也被挡下。所以没
    意见时回 ``ask``（交回 agy 自己的权限流程），NEVER 回 ``allow``（那等于静默放行）。"""
    assert agy_hook.translate_output("PreToolUse", {"hookSpecificOutput": {}}) == {
        "decision": "ask"
    }
    assert agy_hook.translate_output("PreToolUse", {}) == {"decision": "ask"}


def test_defer翻成ask():
    """agy 没有 defer 这一档，翻成 ask——最坏多问一次，比放行安全。"""
    out = agy_hook.translate_output(
        "PreToolUse", {"hookSpecificOutput": {"permissionDecision": "defer"}}
    )
    assert out["decision"] == "ask"


@pytest.mark.parametrize("event", ["PostToolUse", "Stop", "PostInvocation", "Nope"])
def test_其余事件一律回空对象(event):
    """引擎没有对端的那几路一律 {}。

    ``PostInvocation`` 在这张名单里是**真的没有对端**（它唯一的作用是强制续跑）；它旁边
    那个 ``PreInvocation`` 曾经也被摆在这里，那是错的——它就是 ``UserPromptSubmit``。
    """
    assert (
        agy_hook.translate_output(event, {"hookSpecificOutput": {"additionalContext": "x"}}) == {}
    )


def test_pre_invocation的注入是每轮一次性的():
    """用 ``ephemeralMessage`` 不用 ``systemMessage``。

    agy 的 ``systemMessage`` 会常驻在对话轨迹里跨轮累积，每轮一份；轻量 ai 每轮的话都在
    一千字上下，十几轮就是上万字的污染，而人一句都读不到。``ephemeralMessage`` 说完即弃，
    与 claude 那边每轮注入的性质一致。
    """
    out = agy_hook.translate_output(
        "PreInvocation", {"hookSpecificOutput": {"additionalContext": "这一轮先查手册"}}
    )
    assert out == {"injectSteps": [{"ephemeralMessage": "这一轮先查手册"}]}
    assert agy_hook.translate_output("PreInvocation", {"hookSpecificOutput": {}}) == {}


# ── 端到端：stdin → stdout ──────────────────────────────────────────
@pytest.fixture
def runner():
    return CliRunner()


def _feed(runner, event, payload, monkeypatch, engine_response):
    seen: dict = {}

    def fake_engine(engine_payload):
        seen["payload"] = engine_payload
        return engine_response

    monkeypatch.setattr(agy_hook, "_call_engine", fake_engine)
    result = runner.invoke(agy_hook.agy_hook, ["--event", event], input=json.dumps(payload))
    return result, seen


def test_session_start一路走通(runner, monkeypatch):
    result, seen = _feed(
        runner,
        "SessionStart",
        {"conversationId": "c-1", "workspacePaths": ["/tmp"]},
        monkeypatch,
        {"hookSpecificOutput": {"additionalContext": "你好"}},
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "injectSteps": [{"systemMessage": {"systemMessage": "你好"}}]
    }
    assert seen["payload"]["hook_event_name"] == "SessionStart"


def test_pre_tool_use一路走通(runner, monkeypatch):
    result, seen = _feed(
        runner,
        "PreToolUse",
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "rm -rf /tmp/x"}}},
        monkeypatch,
        {"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "不许"}},
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["decision"] == "deny"
    # 引擎看到的是翻过的形状，不是 agy 的。
    assert seen["payload"]["tool_name"] == "Bash"
    assert seen["payload"]["tool_input"] == {"command": "rm -rf /tmp/x"}


def test_坏输入降级成ask不炸(runner, monkeypatch):
    """垫片出错 MUST 静默降级成"我不管，按 agy 自己的规矩来"，而不是把会话打断，也不是放行。"""
    monkeypatch.setattr(agy_hook, "_call_engine", lambda p: pytest.fail("坏输入不该问引擎"))
    for bad in ("", "not json", "[1,2,3]"):
        result = runner.invoke(agy_hook.agy_hook, ["--event", "PreToolUse"], input=bad)
        assert result.exit_code == 0
        assert json.loads(result.output) == {"decision": "ask"}


def test_引擎不可用时降级成ask(monkeypatch):
    """引擎不在 / 超时 / 吐的不是 JSON，PreToolUse 回 ask——规则失效好过会话挂死。"""
    monkeypatch.setattr(agy_hook, "_call_engine", lambda p: {})
    assert agy_hook.translate_output("PreToolUse", {}) == {"decision": "ask"}


# ── PreInvocation：引擎那一侧的 UserPromptSubmit ─────────────────────
def test_pre_invocation翻成user_prompt_submit():
    """名字不同、位置相同：两边都在"用户提交了、模型还没跑"这一刻触发。"""
    assert agy_hook.EVENT_MAP["PreInvocation"] == "UserPromptSubmit"


def test_pre_invocation把那句话与前面几轮一并递给引擎(monkeypatch):
    """agy 的载荷里没有用户那句话，引擎判"用户到底要什么"正需要它——回读转录补上。

    只在**本轮第一次模型调用**时补：agy 的 PreInvocation 每次调模型都触发，若每次都补，
    轻量 ai 的每轮复核就跟着每一步跑一遍。
    """
    from frago.session.adapters import agy_records

    monkeypatch.setattr(
        agy_records,
        "review_context",
        lambda path, cid, **kw: ("本轮这句", "[用户] 上一句\n[助手] 上一答", True),
    )

    out = agy_hook.translate_input(
        {"conversationId": "c-1", "transcriptPath": "/tmp/t.jsonl", "workspacePaths": ["/tmp"]},
        "PreInvocation",
    )

    assert out["hook_event_name"] == "UserPromptSubmit"
    assert out["prompt"] == "本轮这句"
    assert out["recent_turns"] == "[用户] 上一句\n[助手] 上一答"


def test_同一轮后续步骤不再递prompt(monkeypatch):
    """一轮之内第二次及以后的模型调用、上一拍也没被拒：什么都不递。

    引擎的 ``situation`` 因此为空，复核那一趟不跑（省一次模型调用），确定性规则照旧由
    dispatch 跑完返回。这就是「轻量 ai 不再每个步骤触发一次」的落点。
    """
    from frago.session.adapters import agy_records

    monkeypatch.setattr(
        agy_records,
        "review_context",
        lambda path, cid, **kw: ("本轮这句", "[用户] 上一句", False),
    )

    out = agy_hook.translate_input(
        {"conversationId": "c-1", "transcriptPath": "/tmp/t.jsonl", "workspacePaths": ["/tmp"]},
        "PreInvocation",
    )

    assert out["hook_event_name"] == "UserPromptSubmit"
    assert "prompt" not in out
    assert "recent_turns" not in out


def test_上一拍被拒时照样递prompt(monkeypatch):
    """上一拍工具刚被 hook 拒掉：复核照跑。

    补的是「首拍那趟复核没成、整轮就再没人提醒」的窟窿——被拒之后正是最该提醒的时刻。
    """
    from frago.session.adapters import agy_records

    monkeypatch.setattr(
        agy_records,
        "review_context",
        lambda path, cid, **kw: ("本轮这句", "[用户] 上一句", True),
    )

    out = agy_hook.translate_input(
        {"conversationId": "c-1", "transcriptPath": "/tmp/t.jsonl", "workspacePaths": ["/tmp"]},
        "PreInvocation",
    )

    assert out["prompt"] == "本轮这句"
    assert out["recent_turns"] == "[用户] 上一句"


def test_读不出转录就什么都不补(monkeypatch):
    """瞎猜一句喂过去比不喂坏得多——复核会照着错的那句话给建议，人还看不出它判错了对象。"""
    from frago.session.adapters import agy_records

    monkeypatch.setattr(agy_records, "review_context", lambda path, cid, **kw: (None, None, True))

    out = agy_hook.translate_input({"conversationId": "c-1"}, "PreInvocation")

    assert "prompt" not in out
    assert "recent_turns" not in out


def test_pre_invocation一路走通(runner, monkeypatch):
    result, seen = _feed(
        runner,
        "PreInvocation",
        {"conversationId": "c-1", "workspacePaths": ["/tmp"]},
        monkeypatch,
        {"hookSpecificOutput": {"additionalContext": "这一轮先查手册"}},
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == {"injectSteps": [{"ephemeralMessage": "这一轮先查手册"}]}
    assert seen["payload"]["hook_event_name"] == "UserPromptSubmit"


def test_轻量ai没话说时回空对象(runner, monkeypatch):
    """复核没有意见时引擎只回规则那部分；两边都空就什么都不注。"""
    result, _seen = _feed(
        runner, "PreInvocation", {"conversationId": "c-1"}, monkeypatch, {"hookSpecificOutput": {}}
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == {}


# ── hooks.json 的写法 ───────────────────────────────────────────────
class _FakeShutil:
    """只替掉 which，别把全局 shutil 一起换了。"""

    @staticmethod
    def which(_name: str) -> str:
        return "/usr/local/bin/frago"


@pytest.fixture
def agy_home(tmp_path, monkeypatch):
    """一个装好 agy 的假家目录：~/.gemini 在，hooks.json 路径指向它。"""
    from frago.init import hook_binary

    gemini = tmp_path / ".gemini"
    (gemini / "config").mkdir(parents=True)
    path = gemini / "config" / "hooks.json"
    monkeypatch.setattr(hook_binary, "get_agy_hooks_path", lambda: path)
    monkeypatch.setattr(hook_binary, "shutil", _FakeShutil)
    return path


def test_hooks_json形状按agy的规矩(agy_home):
    """平铺事件直接是列表，工具事件要拿 matcher 包一层——照 agy 手册。"""
    from frago.init import hook_binary

    hook_binary.sync_agy_hook_events()

    frago = json.loads(agy_home.read_text(encoding="utf-8"))["frago"]
    assert (
        frago["SessionStart"][0]["command"] == "/usr/local/bin/frago agy-hook --event SessionStart"
    )
    assert frago["SessionStart"][0]["type"] == "command"
    assert frago["PreToolUse"][0]["matcher"] == "*"
    assert frago["PreToolUse"][0]["hooks"][0]["command"].endswith("--event PreToolUse")
    assert frago["Stop"][0]["type"] == "command"
    # PreInvocation 也是平铺那一档。少了它，轻量 ai 的每轮复核一次都不会跑。
    assert frago["PreInvocation"][0]["command"].endswith("--event PreInvocation")
    assert frago["PreInvocation"][0]["type"] == "command"


def test_老版本登记的缺的那一路会被补上(agy_home):
    """已经在跑的那份 hooks.json 里没有 PreInvocation，下一次启动要把它补进去。

    这一条盯的是升级这条路：2026-10-14 之前登记的就是少了它，光改代码不重写文件，
    老机器上永远补不上。
    """
    from frago.init import hook_binary

    agy_home.write_text(
        json.dumps(
            {
                "frago": {
                    "SessionStart": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/frago agy-hook --event SessionStart",
                            "timeout": 20,
                        }
                    ],
                    "Stop": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/frago agy-hook --event Stop",
                            "timeout": 20,
                        }
                    ],
                },
                "someone-else": {"Stop": [{"command": "x"}]},
            }
        ),
        encoding="utf-8",
    )

    hook_binary.sync_agy_hook_events()

    data = json.loads(agy_home.read_text(encoding="utf-8"))
    assert data["frago"]["PreInvocation"][0]["command"].endswith("--event PreInvocation")
    assert data["someone-else"] == {"Stop": [{"command": "x"}]}


def test_用户既有的hook一个字节不动(agy_home):
    """agy 的顶层键是 hook 名；frago 只占自己那一个键，别家的一律留着。"""
    from frago.init import hook_binary

    agy_home.write_text(
        json.dumps({"someone-else": {"Stop": [{"command": "x"}]}}), encoding="utf-8"
    )

    hook_binary.sync_agy_hook_events()

    data = json.loads(agy_home.read_text(encoding="utf-8"))
    assert data["someone-else"] == {"Stop": [{"command": "x"}]}
    assert "frago" in data


def test_重复登记不重写(agy_home, monkeypatch):
    """已经是目标形状就一个字节不写——别每启动一次就动一遍用户的文件。"""
    from frago.init import hook_binary

    hook_binary.sync_agy_hook_events()
    before = agy_home.read_text(encoding="utf-8")

    written: list = []
    real_replace = hook_binary.os.replace
    monkeypatch.setattr(hook_binary.os, "replace", lambda *a: written.append(a) or real_replace(*a))
    hook_binary.sync_agy_hook_events()

    assert written == []
    assert agy_home.read_text(encoding="utf-8") == before


def test_格式坏就跳过不动用户内容(agy_home):
    """读不动时 NEVER 拿一份空表顶掉——那会把用户自己的 hook 抹掉。"""
    from frago.init import hook_binary

    agy_home.write_text("{ this is not json", encoding="utf-8")

    hook_binary.sync_agy_hook_events()

    assert agy_home.read_text(encoding="utf-8") == "{ this is not json"


def test_agy没装就不写(tmp_path, monkeypatch):
    """~/.gemini 不在 = 这台机器没跑过 agy，别凭空造一个目录出来。"""
    from frago.init import hook_binary

    path = tmp_path / ".gemini" / "config" / "hooks.json"
    monkeypatch.setattr(hook_binary, "get_agy_hooks_path", lambda: path)

    hook_binary.sync_agy_hook_events()

    assert not path.exists()
    assert not (tmp_path / ".gemini").exists()


# ── SessionStart：把这场会话是从谁那儿起来的记进账 ────────────────────
@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """账本与扫描缓存挪到临时目录，用例之间互不干扰（CoreAgent 的会话根一并掐掉）。"""
    from frago.session import session_origin

    monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
    monkeypatch.setattr(session_origin, "PARENT_SCAN_CACHE", tmp_path / "agent-parent-scan.json")
    monkeypatch.setattr(session_origin, "_coreagent_scan_root", lambda: None)
    root = tmp_path / "projects"
    root.mkdir()
    return root


def _origin_index(projects_root):
    from frago.session import session_origin

    return session_origin.load_origin_index(projects_root=projects_root, use_memo=False)


def test_会话里起的agy会话折到发起它那一场下面(ledger, monkeypatch):
    """``agy -p`` 那种自建会话：父亲只能从它起来那一瞬的环境里认。"""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-sid")
    agy_hook._record_launch_relation({"conversationId": "child-conv", "workspacePaths": ["/tmp"]})
    index = _origin_index(ledger)
    assert index.parent_of("child-conv") == "parent-sid"
    assert index.origin_of("child-conv") == "worker"


def test_终端里直接起的agy会话不记(ledger, monkeypatch):
    """认不出派活者就是人在终端里敲的 ``agy -p``，没有派人——按人开的算。"""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("FRAGO_SESSION_ID", raising=False)
    # 兜底那条「按当前目录最近写入的记录推断」不算数：它 certain=False，认父亲时一律不用。
    monkeypatch.setattr("frago.session.self_id.resolve_self", lambda **_: None)
    agy_hook._record_launch_relation({"conversationId": "human-conv", "workspacePaths": ["/tmp"]})
    index = _origin_index(ledger)
    assert index.origin_of("human-conv") == "human"
    assert index.parent_of("human-conv") is None


def test_环境里那个编号就是本场自己时不记(ledger, monkeypatch):
    """frago 起的会话，环境里声明的是它自己的编号——那不是父亲，父子另由派活那一刻记。"""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("FRAGO_SESSION_ID", "same-conv")
    agy_hook._record_launch_relation({"conversationId": "same-conv"})
    index = _origin_index(ledger)
    assert index.origin_of("same-conv") == "human"


def test_载荷里没有编号就不动账本(ledger):
    agy_hook._record_launch_relation({"workspacePaths": ["/tmp"]})
    from frago.session import session_origin

    assert not session_origin.LAUNCH_LEDGER.exists()
