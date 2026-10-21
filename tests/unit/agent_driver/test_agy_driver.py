"""agy driver 与 agy_store 的单测。

重点守四件事：

1. **忙碌中不许判就绪**。agy 的输入框在忙碌时本来就是空的 ``>``，提问行也以 ``>``
   开头。只认"有一行是裸 ``>``"会在模型还在干活时判就绪，提示词被投进去，本轮
   要么串轮要么空等超时。三态的分界在状态栏那一句。
2. **就绪信号绝不命中启动命令的回显**。敲进 shell 的那行 ``agy
   --dangerously-skip-permissions`` 在 TUI 起来之前就在屏上；命中它等于在 TUI 还没
   起来时投喂，这是 codex driver 历史上最贵的一个 bug。
3. **写信任 NEVER 动用户的其余配置**。``settings.json`` 里还存着 ``colorScheme`` 与
   ``model``，只许增 ``trustedWorkspaces`` 的一个元素。
4. **完成判定认记录不认屏**。用户输入之后出现带 ``content`` 的 ``PLANNER_RESPONSE``
   才算答完；只有 ``tool_calls`` 的那一拍不算。

屏面样本原样抄自 2026-10-13 的取证抓屏（去掉了颜色转义），一个字都没改。
"""

import json
import sqlite3

import pytest

from frago.agent_driver.drivers import agy as agy_driver
from frago.session import agy_store

# ── 屏面样本 ────────────────────────────────────────────────────────
READY_PANE = (
    " Verbosity is now medium by default, so tool calls and thoughts roll up into summaries.\n"
    "\n"
    ">\n"
    "\n"
    "? for shortcuts                                                                 Gemini 3.8 Flash · medium\n"
)

# 忙碌：提问行还在，输入框（第二处 ``>``）也是空的，状态栏换成了取消提示。
BUSY_PANE = (
    ">\n"
    "\n"
    ">\n"
    "\n"
    "⣻  Generating...\n"
    "\n"
    "esc to cancel                                                                  Gemini 3.8 Flash · medium\n"
)

# 新目录首启那道菜单。原样抄自 2026-10-13 实测抓屏。
TRUST_PANE = (
    "Accessing workspace:\n"
    "\n"
    "/tmp/agy-spike-fresh-a\n"
    "\n"
    "Do you trust the contents of this project?\n"
    "\n"
    "Antigravity CLI requires permission to read, edit, and execute files here.\n"
    "\n"
    "> Yes, I trust this folder\n"
    "  No, exit\n"
    "\n"
    "  ↑/↓ Navigate · enter Confirm\n"
    "                                                                 Gemini 3.8 Flash · medium\n"
)

# tmux 往 shell 里敲启动命令之后、TUI 起来之前那一屏。
SHELL_ECHO_PANE = (
    " ~/Repos/frago  main ····················· 20:11:07 ─╮\n"
    "❯ agy --dangerously-skip-permissions\n"
    "                                                      ─╯\n"
)


# ── 就绪 / 完成 / 阻断 ──────────────────────────────────────────────
def test_ready_matches_a_live_tui():
    assert agy_driver._READY.matches(READY_PANE) is True


def test_ready_never_matches_the_launch_command_echo():
    """回归：命中这一屏就等于在 TUI 起来之前投喂，本轮必定静默挂死。"""
    assert agy_driver._READY.matches(SHELL_ECHO_PANE) is False


def test_ready_never_matches_the_trust_menu():
    """信任菜单挡在就绪前面。把它当就绪会把提示词打进一道选择题。"""
    assert agy_driver._READY.matches(TRUST_PANE) is False


def test_ready_never_matches_while_generating():
    """回归：忙碌时输入框本来就空着，只看输入框会判成就绪。"""
    assert agy_driver._READY.matches(BUSY_PANE) is False


def test_done_signal_is_the_ready_screen():
    assert agy_driver._DONE.matches(READY_PANE) is True
    assert agy_driver._DONE.matches(BUSY_PANE) is False


def test_needs_input_matches_the_trust_menu():
    assert agy_driver._NEEDS_INPUT.matches(TRUST_PANE) is True


def test_needs_input_never_matches_a_normal_answer():
    """裸 login / sign in 会出现在正常答案正文里，判据只认带失败语义的组合。"""
    body = "You can sign in later if you want. The login flow lives in auth.py."
    assert agy_driver._NEEDS_INPUT.matches(body) is False


# ── 目录信任 ────────────────────────────────────────────────────────
@pytest.fixture()
def app_dir(tmp_path, monkeypatch):
    """把 agy 的应用数据目录指到临时目录，别碰用户真实配置。"""
    root = tmp_path / "antigravity-cli"
    root.mkdir()
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(root))
    return root


def _settings(app_dir):
    return json.loads((app_dir / "settings.json").read_text(encoding="utf-8"))


def test_trust_preserves_other_keys(app_dir):
    """只增 trustedWorkspaces，colorScheme 与 model 一个字节不动。"""
    (app_dir / "settings.json").write_text(
        json.dumps({"colorScheme": "dark", "model": "Gemini 3.8 Flash (Medium)"}),
        encoding="utf-8",
    )
    agy_driver._ensure_workspace_trusted("/tmp/some-project")

    data = _settings(app_dir)
    assert data["colorScheme"] == "dark"
    assert data["model"] == "Gemini 3.8 Flash (Medium)"
    assert data["trustedWorkspaces"] == ["/tmp/some-project"]


def test_trust_is_idempotent(app_dir):
    """已经信过就不再写：值没变就一个字节都不动，不与正在跑的 agy 抢盘。"""
    path = app_dir / "settings.json"
    path.write_text(json.dumps({"trustedWorkspaces": ["/tmp/some-project"]}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    agy_driver._ensure_workspace_trusted("/tmp/some-project")

    assert path.read_text(encoding="utf-8") == before


def test_trust_appends_without_dropping_existing_entries(app_dir):
    (app_dir / "settings.json").write_text(
        json.dumps({"trustedWorkspaces": ["/a", "/b"]}), encoding="utf-8"
    )
    agy_driver._ensure_workspace_trusted("/c")

    assert _settings(app_dir)["trustedWorkspaces"] == ["/a", "/b", "/c"]


def test_trust_gives_up_on_unparsable_settings(app_dir):
    """读不动就一个字节都不写——那份文件里有用户的主题与模型，宁可菜单照弹。"""
    path = app_dir / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")

    agy_driver._ensure_workspace_trusted("/tmp/some-project")

    assert path.read_text(encoding="utf-8") == "{ this is not json"


def test_trust_creates_the_file_when_absent(app_dir):
    agy_driver._ensure_workspace_trusted("/tmp/fresh")

    assert _settings(app_dir)["trustedWorkspaces"] == ["/tmp/fresh"]


# ── 完成探针读记录 ──────────────────────────────────────────────────
CONVERSATION_ID = "481b5141-cdf9-4a3a-aeea-535dfa1c0df0"


def _write_transcript(app_dir, records, conversation_id=CONVERSATION_ID):
    path = agy_store.transcript_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def _summary_db(app_dir, rows):
    """造一份摘要库。只造代码真正读的那几列（见 ``agy_store.list_conversations``）。

    **按列名写，不按位置。** 真实那张表有二十来列（``status`` / ``agent_name`` /
    ``parent_conversation_id`` 等），按位置摆的话哪天上游插进一列，这里会**静默**错位——
    用例照样通过，读出来的却是别的东西。
    """
    conn = sqlite3.connect(app_dir / "conversation_summaries.db")
    conn.execute(
        "CREATE TABLE conversation_summaries ("
        "conversation_id text PRIMARY KEY, title text, preview text, step_count integer,"
        " last_modified_time datetime, workspace_uris text, last_user_input_time datetime)"
    )
    conn.executemany(
        "INSERT INTO conversation_summaries"
        " (conversation_id, title, preview, step_count, last_modified_time, workspace_uris,"
        "  last_user_input_time)"
        " VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_turn_is_not_done_while_the_model_only_wants_a_tool(app_dir):
    _write_transcript(
        app_dir,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>hi</USER_REQUEST>"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "search_web"}]},
        ],
    )
    turn = agy_store.latest_turn(CONVERSATION_ID)
    assert turn is not None and turn.done is False


def test_turn_is_done_once_the_model_answers(app_dir):
    _write_transcript(
        app_dir,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>hi</USER_REQUEST>"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "search_web"}]},
            {"step_index": 2, "type": "SEARCH_WEB", "content": "tool output, not an answer"},
            {"step_index": 3, "type": "PLANNER_RESPONSE", "content": "OK"},
        ],
    )
    turn = agy_store.latest_turn(CONVERSATION_ID)
    assert turn is not None and turn.done is True
    assert turn.text == "OK"


def test_tool_output_is_never_taken_as_the_answer(app_dir):
    """工具步也带 content，但它不是给用户的话。最后一拍只在调工具时不许判答完。"""
    _write_transcript(
        app_dir,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>hi</USER_REQUEST>"},
            {"step_index": 1, "type": "SEARCH_WEB", "content": "tool output"},
            {"step_index": 2, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "view_file"}]},
        ],
    )
    turn = agy_store.latest_turn(CONVERSATION_ID)
    assert turn is not None and turn.done is False


def test_second_turn_ignores_the_first_turns_answer(app_dir):
    """多轮的要点：上一轮的收尾回复 MUST NOT 被当成这一轮已答完。"""
    _write_transcript(
        app_dir,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>one</USER_REQUEST>"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "first answer"},
            {"step_index": 2, "type": "USER_INPUT", "content": "<USER_REQUEST>two</USER_REQUEST>"},
            {"step_index": 3, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "view_file"}]},
        ],
    )
    turn = agy_store.latest_turn(CONVERSATION_ID)
    assert turn is not None and turn.done is False
    assert turn.turn_id == "2"


def test_missing_transcript_reads_as_unknown(app_dir):
    assert agy_store.latest_turn(CONVERSATION_ID) is None


def test_turn_is_not_done_while_background_task_is_running(app_dir):
    """回归（26c4680e）：run_command 超 5s 转后台后，agy 写的进度播报不带 tool_calls，
    但后台任务仍在 RUNNING，此时绝不可判本轮已完成。
    """
    _write_transcript(
        app_dir,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>check disk</USER_REQUEST>"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command"}]},
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "status": "RUNNING",
                "content": (
                    "Created At: 2026-10-18T11:19:12+08:00\n"
                    f"Tool is running as a background task with task id: {CONVERSATION_ID}/task-4\n"
                    "YOU MUST TAKE ONE OF THE FOLLOWING TWO ACTIONS..."
                ),
            },
            {
                "step_index": 3,
                "type": "PLANNER_RESPONSE",
                "content": "正在统计本机磁盘占用，等待命令返回结果。",
            },
        ],
    )
    turn = agy_store.latest_turn(CONVERSATION_ID)
    assert turn is not None and turn.done is False
    assert turn.turn_id == "0"


def test_turn_is_done_only_after_background_task_finishes_and_model_replies(app_dir):
    """后台任务回调到达后，旧的等待播报必须作废，等模型基于回调结果给出真正终答才算完。"""
    records = [
        {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>check disk</USER_REQUEST>"},
        {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command"}]},
        {
            "step_index": 2,
            "source": "MODEL",
            "type": "GENERIC",
            "status": "RUNNING",
            "content": f"Tool is running as a background task with task id: {CONVERSATION_ID}/task-4\n",
        },
        {"step_index": 3, "type": "PLANNER_RESPONSE", "content": "正在等待后台命令完成…"},
        {
            "step_index": 4,
            "source": "SYSTEM",
            "type": "SYSTEM_MESSAGE",
            "status": "DONE",
            "content": (
                "<SYSTEM_MESSAGE>\n"
                f'[Message] sender={CONVERSATION_ID}/task-4 content=Task id "{CONVERSATION_ID}/task-4" '
                "finished with result:\nThe command exited with code 0.\n</SYSTEM_MESSAGE>"
            ),
        },
    ]
    _write_transcript(app_dir, records)
    # 回调刚写入、模型还没回答时，不应把 step 3 的过渡播报当成终答
    mid_turn = agy_store.latest_turn(CONVERSATION_ID)
    assert mid_turn is not None and mid_turn.done is False

    # 模型拿到后台结果给出正式答复后，才算本轮完成
    records.append({"step_index": 5, "type": "PLANNER_RESPONSE", "content": "磁盘检查完毕，剩余 9.6G。"})
    _write_transcript(app_dir, records)
    done_turn = agy_store.latest_turn(CONVERSATION_ID)
    assert done_turn is not None and done_turn.done is True
    assert done_turn.text == "磁盘检查完毕，剩余 9.6G。"


def test_turn_is_not_done_when_planner_response_is_interrupted_by_stream_error(app_dir):
    """回归（36f51a51）：流式连接中途断开时，agy 先把半截 PLANNER_RESPONSE（无 tool_calls）
    落盘，紧接着写一条 ERROR_MESSAGE 并准备自动续写。若把半截残片判成 done=True，调用方
    会当场把还在自动续写的会话当已完成收尾。
    """
    records = [
        {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>检查未合并分支</USER_REQUEST>"},
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "content": "**我将先查阅配置并检索历史，随后检查所有分支的合并状态。** `gitlab_mr",
        },
        {
            "step_index": 2,
            "source": "SYSTEM",
            "type": "ERROR_MESSAGE",
            "status": "DONE",
            "error": "The stream was interrupted. Please continue the task you were working on.",
        },
    ]
    _write_transcript(app_dir, records)
    interrupted = agy_store.latest_turn(CONVERSATION_ID)
    assert interrupted is not None and interrupted.done is False

    # agy 自动续写启动新一拍（PreInvocation 注入 EPHEMERAL_MESSAGE）期间仍未完成
    records.append(
        {
            "step_index": 3,
            "source": "SYSTEM_SDK",
            "type": "EPHEMERAL_MESSAGE",
            "status": "DONE",
            "content": "[主控提醒] ...",
        }
    )
    _write_transcript(app_dir, records)
    resuming = agy_store.latest_turn(CONVERSATION_ID)
    assert resuming is not None and resuming.done is False

    # 自动续写最终给出完整收尾回复后，才算本轮完成
    records.append(
        {
            "step_index": 4,
            "type": "PLANNER_RESPONSE",
            "content": "所有远端分支均已合并。",
        }
    )
    _write_transcript(app_dir, records)
    completed = agy_store.latest_turn(CONVERSATION_ID)
    assert completed is not None and completed.done is True
    assert completed.text == "所有远端分支均已合并。"


# ── 会话编号认领 ────────────────────────────────────────────────────
def test_claim_falls_back_to_the_summaries_table(app_dir):
    """没有 last_conversations 线索时，按工作目录与时刻从摘要库里挑。"""
    other = "11111111-1111-1111-1111-111111111111"
    _write_transcript(app_dir, [{"step_index": 0, "type": "USER_INPUT"}], other)
    _summary_db(
        app_dir,
        [
            (
                other,
                "t",
                "",
                1,
                "2026-10-13 11:40:00.000000+00:00",
                json.dumps(["file:///tmp/proj"]),
                "",
            )
        ],
    )

    # 锚点在会话建立之前，故能认到。
    claimed = agy_store.claim_conversation("/tmp/proj", since_ms=0)
    assert claimed == other


def test_claim_ignores_conversations_started_before_the_anchor(app_dir):
    _summary_db(
        app_dir,
        [
            (
                CONVERSATION_ID,
                "t",
                "",
                1,
                "2026-10-13 11:40:00.000000+00:00",
                json.dumps(["file:///tmp/proj"]),
                "",
            )
        ],
    )
    # 锚点在它之后（2026-10-13 11:41 UTC = 1791...），这一场是别人起的，不许认。
    since_ms = 1_900_000_000_000
    assert agy_store.claim_conversation("/tmp/proj", since_ms=since_ms) is None


def test_claim_trusts_the_directory_hint_when_it_is_new_enough(app_dir):
    (app_dir / "cache").mkdir()
    (app_dir / "cache" / "last_conversations.json").write_text(
        json.dumps({"/tmp/proj": CONVERSATION_ID}), encoding="utf-8"
    )
    _summary_db(
        app_dir,
        [
            (
                CONVERSATION_ID,
                "t",
                "",
                1,
                "2026-10-13 11:40:00.000000+00:00",
                json.dumps(["file:///tmp/proj"]),
                "",
            )
        ],
    )

    assert agy_store.claim_conversation("/tmp/proj", since_ms=0) == CONVERSATION_ID


def test_claim_returns_none_when_agy_never_ran(app_dir):
    """agy 没跑过任何会话是完全正常的状态，认不到就是认不到，不许抛。"""
    assert agy_store.claim_conversation("/tmp/proj", since_ms=0) is None


# ── 认领的起算点 ────────────────────────────────────────────────────
class _FakeSession:
    """只够 driver 问出"这场会话什么时候起的"。"""

    def __init__(self, created):
        self.session_id = "e2e"
        self.cwd = "/tmp/proj"
        self._created = created

    def created_at(self):
        return self._created


def test_anchor_falls_back_to_the_tmux_session(monkeypatch):
    """**进程内记的锚点活不过第一条命令。**

    ``frago agent start`` 与之后的每一次 ``frago agent send`` 是各自独立的进程；agy 的
    会话编号要等第一轮提交之后才进摘要库，认领因此正好发生在启动进程早已退出的那一刻。
    只信进程内的话永远认不到——完成探针永远 None，静默退回读屏，回文本全空
    （2026-10-14 实机就是这么错的）。
    """
    monkeypatch.setattr(agy_driver, "_LAUNCH_ANCHORS", {})
    session = _FakeSession(created=1791941895.0)

    assert agy_driver._claim_anchor(session) == 1791941895000


def test_anchor_prefers_the_launch_moment_when_it_is_still_around(monkeypatch):
    """同一进程里（启动那一趟）那个时刻更早也更准，仍优先用它。"""
    monkeypatch.setattr(agy_driver, "_LAUNCH_ANCHORS", {"e2e": 1791941000000})
    monkeypatch.setattr(agy_driver, "_CLAIM_ANCHORS", {})
    session = _FakeSession(created=1791941895.0)

    assert agy_driver._claim_anchor(session) == 1791941000000


def test_anchor_is_unknown_when_nothing_can_say(monkeypatch):
    """三处都问不出来时不硬编一个——编一个会把同一目录里别人的会话认成自己的。"""
    monkeypatch.setattr(agy_driver, "_LAUNCH_ANCHORS", {})
    monkeypatch.setattr(agy_driver, "_CLAIM_ANCHORS", {})

    assert agy_driver._claim_anchor(_FakeSession(created=None)) is None


# ── 注册 ────────────────────────────────────────────────────────────
def test_driver_is_registered():
    from frago.agent_driver.driver import load_driver

    driver = load_driver("agy")
    assert driver.display_name == "Antigravity CLI"
    assert driver.accepts_session_id is False
