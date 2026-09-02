"""codebuddy (CodeBuddy Code / WorkBuddy) TUI driver。

codebuddy 是 Claude Code 的 fork：TUI 形态、jsonl transcript、``--session-id`` 派生、
``--dangerously-skip-permissions``、settings/hooks 九个事件名全部同形。故本 driver 的
骨架照 ``claude.py``，而不是 ``opencode.py``（那套 SQLite + 环境变量声明权限的形状与
codebuddy 一点不沾边）。

但**同形不等于同构**，三处实测确认的差异决定了这里不能照抄（每一条都有对应的坑）：

1. **transcript 记录 schema 不同。** claude 是 ``type:"assistant"`` +
   ``message.stop_reason:"end_turn"``；codebuddy 是 ``type:"message"`` +
   ``role:"assistant"`` + ``status:"completed"``，文本块是 ``output_text`` 不是
   ``text``，去重锚点是 ``id`` 不是 ``uuid``。照抄
   ``session.transcript_completion`` 会得到一个恒为 not-done 的死探针，每轮挂到超时。
2. **projects 目录的路径编码不同。** claude 只把 ``/`` 换成 ``-``（保留开头那个）；
   codebuddy 还要掐掉首尾横线、把连续横线压成一个（见 ``_compress_path``）。
3. **一轮答完后输入框会被自动填上一句「下一步建议」**（ghost 占位文本，右侧带
   ``↵ send``）。claude 没有这个行为。就绪式若只认空输入框，第二轮 send 会被
   ``drive_send`` 的 ready 检查当场拒发。

另有一处形状差异：codebuddy 的输入框提示符是裸 ``>`` + 普通空格（claude 是 ``❯`` +
nbsp），选择菜单的光标也是 ``>``；输入框不带 ``│`` 边框，菜单才在边框盒子里。
这个区别下面被用来把「输入框」和「选择菜单」结构性地分开。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import uuid
from pathlib import Path

from frago.agent_driver.driver import (
    AgentDriver,
    CompletionVerdict,
    LaunchCtx,
    PaneMatcher,
    register_driver,
)
from frago.agent_driver.tmux_session import TmuxAgentSession

logger = logging.getLogger(__name__)

# 与 claude 各用各的命名空间：同一个 frago session_id 在两个 agent 下派生出不同的会话
# id，否则换 agent 续会话会去读对方的 transcript。
_CODEBUDDY_SID_NS = uuid.UUID("b21f7e5c-3a48-4d16-9f02-7c8e5a1d4b93")

# CLI 不在 PATH 上（随 WorkBuddy.app 分发），故给一份兜底绝对路径。
_APP_BUNDLE_CLI = (
    "/Applications/WorkBuddy.app/Contents/Resources/"
    "app.asar.unpacked/cli/bin/codebuddy"
)

# transcript 根。与 claude 的 ``~/.claude/projects`` 平行。
_CODEBUDDY_HOME = Path.home() / ".codebuddy"
_CODEBUDDY_PROJECTS = _CODEBUDDY_HOME / "projects"


def _codebuddy_session_uuid(frago_session_id: str) -> str:
    return str(uuid.uuid5(_CODEBUDDY_SID_NS, frago_session_id))


def _locate_codebuddy() -> str | None:
    """本机装没装 codebuddy：PATH 优先，退回 WorkBuddy.app 里那份内嵌 CLI。

    找不到返回 None——这是给"列出本机能用哪几家"用的诚实答案。启动路径要的是另一种
    答案（见 :func:`_codebuddy_bin`），两者 MUST 分开：把"没装"翻成一个裸名字交给
    清单，界面上就会多出一个点了会静默失败的选项。
    """
    found = shutil.which("codebuddy")
    if found:
        return found
    if os.path.isfile(_APP_BUNDLE_CLI):
        return _APP_BUNDLE_CLI
    return None


def _codebuddy_bin() -> str:
    """启动用的 codebuddy 可执行文件；两处都不在时仍返回裸名字 ``codebuddy``。

    没装也照样把命令发进 tmux——让 shell 自己报 "command not found"，pane 上看得见，
    比 driver 在这里抛一个没有末屏的异常好排查。
    """
    return _locate_codebuddy() or "codebuddy"


# ── transcript 定位 ────────────────────────────────────────────────────────
def _compress_path(path: str) -> str:
    """把工作目录压成 ``~/.codebuddy/projects/`` 下的目录名。

    从 CodeBuddy 自己的 bundle 里挖出的原实现（``PathUtils.compressPath``）：

        eA.replace(/[/\\\\:]/g,"-").replace(/^-+/,"").replace(/-+$/,"").replace(/-+/g,"-")

    与 claude 的编码**不是同一个函数**：claude 只做第一步（``/`` → ``-``），开头那个
    横线原样留着（``-Users-frago``）；codebuddy 还要掐掉首尾横线、把连续横线压成一个
    （``Users-frago``）。差一个字符就定位不到 jsonl，探针整条失效，故这里逐步照搬。
    """
    out = re.sub(r"[/\\:]", "-", path)
    out = out.strip("-")
    return re.sub(r"-+", "-", out)


def _locate_transcript(session_id: str, cwd: str | None) -> Path | None:
    """定位 ``<sid>.jsonl``。先按编码规则直取，取不到再扫全部 project 目录。

    两层是因为编码规则是从 bundle 里逆出来的，**会随 CodeBuddy 版本改**。规则一旦失效，
    直取那条静默落空、探针永远返回 None、每轮退回读屏——这种降级没有任何声响，最难查。
    扫描兜底让规则失效时只是慢一点，而不是坏掉。
    """
    if not _CODEBUDDY_PROJECTS.is_dir():
        return None
    if cwd:
        candidate = _CODEBUDDY_PROJECTS / _compress_path(os.path.abspath(cwd)) / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    try:
        for project_dir in _CODEBUDDY_PROJECTS.iterdir():
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
    except OSError:
        return None
    return None


def transcript_path_for(session: TmuxAgentSession) -> Path | None:
    """本会话的 transcript（探针 / 提交验证共用同一套定位，NEVER 各自派生一份）。"""
    sid = (
        session.session_id
        if session.native_session_id
        else _codebuddy_session_uuid(session.session_id)
    )
    return _locate_transcript(sid, cwd=session.cwd)


# ── frago settings 注入（hook 通路 + 目录信任）────────────────────────────
def _settings_dir() -> Path:
    return Path.home() / ".frago" / "agent_driver" / "codebuddy"


def _settings_path(session_id: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in session_id)
    return _settings_dir() / f"{safe}.settings.json"


def _hook_engine() -> str | None:
    """frago 的 hook 引擎二进制；不存在返回 None。

    找不到就**不写 hooks 段**：一份指向不存在路径的 hook 会让 codebuddy 每次工具调用
    都报一次执行失败，比没有 hook 更糟。
    """
    engine = Path.home() / ".frago" / "bin" / "frago-core"
    return str(engine) if engine.is_file() else None


# 挂哪几个事件：与 frago 在 ``~/.claude/settings.json`` 里已经挂着的那四个一致。
# 同一个引擎二进制、同一套 payload 契约（codebuddy 的 hook payload 已实测与 Claude
# Code 同形），故 NEVER 为 codebuddy 另造一套事件表。
_HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop")
_HOOK_TIMEOUT_S = 20


def _disabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "off", "no", "false"}


def _build_settings(cwd: str) -> dict:
    """生成这一场会话要递给 codebuddy 的 settings。

    两件事装在同一份文件里：

    ① **目录信任。** 交互式 TUI 下 codebuddy 对没信任过的目录必弹一道
       "Do you trust the files in this folder?" 菜单，``--dangerously-skip-permissions``
       不含它。这道菜单挡在就绪信号**前面**，而 ``TmuxAgentSession.open()`` 是先等
       ready、再跑 exception_handlers——所以 ``ExceptionHandler`` 对它无效，根本轮不到
       执行，会话只会干等到超时抛 ``TmuxStartupError``。
       claude 的解法是往 ``~/.claude.json`` 幂等写信任；codebuddy 没有对应的明文配置
       （信任落在 ``~/.codebuddy/local_storage/`` 的 gzip+base64 块里，改它既脆又是在
       动用户的客户端状态）。它真正读的闸门是 settings 的 ``trustedDirectories`` /
       ``trustAll``（bundle 里 ``DirectoryTrustService.doInit``），所以写这一个键即可。
       取 ``trustedDirectories:[cwd]`` 而不是 ``trustAll:true``——只信任这次真的要工作
       的目录，不给这个进程一张全盘通行证。

    ② **hook 注入。** frago 的 hook 引擎挂上四个事件。

    这份文件只写进 frago 自己的目录，``~/.codebuddy/settings.json`` 一个字节都不碰——
    那是用户日常客户端在用的那份。
    """
    settings: dict = {"trustedDirectories": [os.path.abspath(cwd)]}
    if _disabled(os.environ.get("FRAGO_CODEBUDDY_HOOKS")):
        return settings
    engine = _hook_engine()
    if engine is None:
        logger.warning("frago hook engine not found; codebuddy session starts without hooks")
        return settings
    entry = {
        "matcher": "",
        "hooks": [{"type": "command", "command": f"{engine} --engine", "timeout": _HOOK_TIMEOUT_S}],
    }
    settings["hooks"] = {event: [entry] for event in _HOOK_EVENTS}
    return settings


def _write_settings(ctx: LaunchCtx) -> str | None:
    """把这一场的 settings 落盘，返回路径；不该注入或写不动时返回 None。

    ``FRAGO_CODEBUDDY_SETTINGS`` 有三档：
      - 未设置 → 生成一份（信任 + hooks），这是缺省
      - ``0`` / ``off`` / ``no`` / ``false`` → **完全不拼 ``--settings``**，命令行与人手
        敲 codebuddy 一模一样（"不带时行为与原生完全一致"这条要求就落在这里）
      - 其它值 → 当成调用方自己准备的 settings 文件路径，原样用

    写盘失败不阻断启动：最坏是 trust 菜单照弹、会话起不来并带着末屏报错，而不是让一次
    写文件失败变成一个没有 pane 证据的异常。
    """
    override = os.environ.get("FRAGO_CODEBUDDY_SETTINGS")
    if _disabled(override):
        return None
    if override:
        return override
    try:
        path = _settings_path(ctx.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_build_settings(ctx.cwd), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)
    except OSError:
        logger.warning("could not write codebuddy settings for %r", ctx.cwd, exc_info=True)
        return None


# ── pane 信号 ──────────────────────────────────────────────────────────────
# 输入框提示符行。codebuddy 用裸 ``>``（claude 是 ``❯``），且输入框**不在** ``│`` 边框
# 盒子里——边框盒子是模态菜单的形状。故这里 NEVER 像 claude 那样允许 ``│?`` 前缀：
# 允许了，trust 菜单里的 ``│   > 1. Trust folder only`` 就会被当成输入框。
_PROMPT_BOX = PaneMatcher(name="codebuddy-prompt", pattern=r"(?m)^\s*>(?:[\s\xa0]|$)")

# 就绪信号。两种形态都算「输入框空着、可以投喂」：
#   ① 真空框 —— 整行就一个 ``>``（首启、以及刚清空后）
#   ② ghost 建议 —— 一轮答完后 codebuddy 会自动把「下一步建议」渲染进输入框，右侧带
#      ``↵ send``（实测：敲任意字符建议整句消失、退格又回来 ⇒ 缓冲区其实是空的，
#      只是渲染层多了一行提示，``send_text`` 不会被它污染）。
# 不认第二种的话，常驻会话第二轮 send 会被 drive_command 的 ready 检查当场拒发。
_READY_BOX = PaneMatcher(
    name="codebuddy-ready",
    pattern=r"(?m)^\s*>(?:[\s\xa0]*$|[\s\xa0].*↵\s*send[\s\xa0]*$)",
)

# 忙碌标记。实拍一帧：
#   ``✷ Charging… (3s · waiting for model · ↑ 0 tokens · esc to interrupt)``
# 四条判据与 claude 完全一致（fork 的渲染层没改），故沿用同一组式子。
_BUSY = re.compile(
    r"esc to interrupt"
    r"|\(\s*\d+(?:\.\d+)?s\b"
    r"|[↑↓]\s*[\d.,]+\s*k?\s*tokens"
    r"|^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…",
    re.MULTILINE,
)

# 视觉装饰行：边框、spinner、工具结果的 ``⎿`` 缩进标记、底部权限模式页脚。
_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|[✻✽✶✢✳✺✷✸✹✦]|⏵|⎿|\?\s|—\s*for shortcuts|esc to interrupt)",
)


class _CodebuddyDone:
    """完成判定：输入框提示符在 AND pane 不含忙碌标记。

    与 claude 同构（思考期间空输入框持续显示，只认「提示符出现」会在提交后立刻误判）。
    driver 主路径只用 ``.matches(text)``，与 PaneMatcher 鸭子兼容。
    """

    name = "codebuddy-done"

    def matches(self, text: str) -> bool:
        return _PROMPT_BOX.matches(text) and _BUSY.search(text) is None


_DONE = _CodebuddyDone()


# 认证墙：撞上即要真人去登录 / 换号 / 充值，静默挂到超时只会浪费一整轮墙钟。
_AUTH_WALL = re.compile(
    r"invalid api key|api key.*(?:invalid|expired)"
    r"|not\s+logged\s+in|unauthorized|authentication\s+failed"
    r"|credit balance is too low|insufficient\s+(?:credit|balance|quota)"
    r"|sign\s+in\s+to\s+continue|please\s+(?:re-?)?login",
    re.IGNORECASE,
)

# 选择菜单的**单行**特征：光标 ``>`` + 编号 + ``.``/``)``。
# ⚠ 这一行单独用是不够的——claude 就栽在这里。``_SELECT_MENU_PAT`` 只认单行
# 「光标 + 数字 + 点」，而编辑差异视图的光标行会渲染成 ``❯ 480 +`` 这类形态并命中它，
# 一轮正常的改代码被判成 needs_input、当场切断会话（实测 80–100 秒就切，
# todo ``20260722-frago-agent-idle-detection-false``）。
_MENU_OPTION = re.compile(r"^[^\S\n]*│?[^\S\n]*>?[^\S\n]*(?P<num>\d+)[.)][^\S\n]+\S")


class _CodebuddyNeedsInput:
    """阻断门判定：认证墙，或一个**真的选择菜单**。

    怎么绕开 claude 的那个坑——不靠「看起来像菜单的某一行」，靠**菜单才有的结构**，
    三个条件同时成立才算：

      ① pane 里有**至少两个编号连续**的选项行（``1.`` 和 ``2.``）。
         差异视图给不出这个：它的行号是文件里的真实行号（480、481…），既不从 1 开始，
         也不会有「1. 紧跟 2.」这种编号序列。这一条单独就足以让 ``❯ 480 +`` 出局。
      ② 其中有一行带着选择光标 ``>``。
      ③ pane **不在忙**。菜单是「停下来等人」的状态，而差异视图恰恰是干活干到一半才
         会出现的东西，那一刻 pane 上必有 ``esc to interrupt`` / 计时 / token 计数。

    ③ 还顺带兜住另一类误伤：答案正文里若恰好写了一个「1. …／2. …」的编号清单，
    模型正在把它逐字吐出来的那些帧 pane 是忙的，不会被判成菜单；等它吐完、pane 转空闲
    时 ``completion_probe`` 已先一步判定本轮完成（``_wait_for_any`` 按插入顺序取值，
    ``ok`` 排在 ``needs_input`` 前面），也轮不到这里。
    """

    name = "codebuddy-needs-input"

    def matches(self, text: str) -> bool:
        if _AUTH_WALL.search(text):
            return True
        if _BUSY.search(text) is not None:
            return False
        numbers: list[int] = []
        cursor_on_option = False
        for line in text.splitlines():
            match = _MENU_OPTION.match(line)
            if match is None:
                continue
            numbers.append(int(match.group("num")))
            if ">" in line[: match.start("num")]:
                cursor_on_option = True
        if not cursor_on_option:
            return False
        # 编号连续（存在 n 与 n+1）才算一组真的选项，孤立的一行不算。
        seen = set(numbers)
        return any(n + 1 in seen for n in seen)


_NEEDS_INPUT = _CodebuddyNeedsInput()


# ── transcript 完成探针 ────────────────────────────────────────────────────
# 承载一轮对话的记录类型。``ai-title`` / ``summary`` / ``file-history-snapshot`` 是
# 元数据，会在一轮答完之后继续追加，拿它们判「最后一条是什么」会把刚答完的轮次误判成
# 未完成，故先滤掉。
_TURN_RECORD_TYPES = frozenset({"message", "function_call", "function_call_result"})
# 文本块。codebuddy 的助手文本是 ``output_text``（claude 是 ``text``）；两个都认，
# 免得 fork 哪天跟上游对齐时这里静默取不到文本。
_TEXT_BLOCK_TYPES = frozenset({"output_text", "text"})


def _read_records(path: Path) -> list[dict]:
    """读 jsonl，坏行跳过。NEVER 截断——一行读不动只丢那一行。"""
    records: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(data, dict):
                    records.append(data)
    except OSError:
        return []
    return records


def _block_text(record: dict) -> str:
    content = record.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") in _TEXT_BLOCK_TYPES
    ]
    return "".join(p for p in parts if isinstance(p, str))


def _completion_probe(session: TmuxAgentSession) -> CompletionVerdict | None:
    """权威完成探针：读 codebuddy 的 session jsonl 判本轮是否真答完 + 取最终文本。

    判据是 codebuddy 自己的记录，不是读屏——多工具轮里 pane 会在「上一个工具结束、下一个
    还没起」的空窗帧短暂呈现空闲态，只读屏必然误判。

    完成 = 文件里最后一条**承载对话的**记录是 ``type=message`` + ``role=assistant``
    + ``status=completed``。中途最后一条会是 ``function_call`` / ``function_call_result``。

    ⚠ 光看 jsonl 还差一层。模型先说一句「我来跑一下」再发工具调用时，那句旁白同样是
    ``message/assistant/completed``，它落盘到 ``function_call`` 落盘之间有个几十毫秒的
    窗口；轮询间隔 0.3 秒，踩进去就会把一轮刚开头的对话判成答完。故**再叠一层「pane
    不含忙碌标记」**——工具在跑时 pane 上必有 ``esc to interrupt``，这个窗口被彻底关掉。
    读屏在这里是给权威信号做去抖，不是判据本身。

    定位不到 transcript（jsonl 尚未生成）时返回 None，由主路径当帧退回 pane
    ``done_signal``，行为与没有探针时一致。
    """
    path = transcript_path_for(session)
    if path is None:
        return None
    records = [r for r in _read_records(path) if r.get("type") in _TURN_RECORD_TYPES]
    if not records:
        return None
    terminal = records[-1]
    marker = terminal.get("id")
    done = (
        terminal.get("type") == "message"
        and terminal.get("role") == "assistant"
        and terminal.get("status") == "completed"
    )
    if not done:
        return CompletionVerdict(done=False, marker=marker)
    try:
        if _BUSY.search(session.capture_pane()) is not None:
            return CompletionVerdict(done=False, marker=marker)
    except Exception:
        # 抓屏这一拍失败不该把已经拿到的权威信号作废：主路径自有会话消失的收口。
        logger.debug("codebuddy probe: capture_pane failed, trusting transcript", exc_info=True)
    text = _block_text(terminal)
    # 答完却一个字都没产出通常是鉴权失败 / provider 拒绝。轮次确实终结了（该停止轮询），
    # 但它 NEVER 是成功——静默返回空答案会让调用方以为一切正常。
    status = "ok" if text.strip() else "error"
    return CompletionVerdict(done=True, text=text, marker=marker, status=status)


# ── 提交 ───────────────────────────────────────────────────────────────────
# 粘贴突发结束到发 Enter 的静置秒数。Ink 系 TUI 把紧随粘贴到达的 Enter 当成粘贴内容里
# 的换行而非提交，长消息会整段滞留输入框。与 claude 同源同因，取同一个值。
_PASTE_SETTLE_S = 2.0
_SUBMIT_VERIFY_POLLS = 12
_ENTER_RETRIES = 2
_BUSY_CONFIRM_POLLS = 24


def _transcript_size(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _submitted(pane: str) -> bool:
    """Enter 确已生效的结构信号：输入框回空 或 忙碌标记出现，任一即真。"""
    return _READY_BOX.matches(pane) or _BUSY.search(pane) is not None


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    """投喂一轮：落字 → 静置 → Enter → 验证确已提交 → 确认进入忙碌态。

    验证优先采信 transcript 增长（Enter 真落地 = 本轮用户消息被追加、文件立刻变长），
    定位不到 transcript 才退回读屏启发式：Enter 被粘贴检测吞掉的同时 TUI 整框重绘，
    输入框会短暂呈空，读屏恰落在那一帧就会误判「已提交」，而文本其实还滞留在框里。
    """
    session.send_text(prompt)
    session._sleep(_PASTE_SETTLE_S)
    path = transcript_path_for(session)
    baseline_size = _transcript_size(path)
    for _ in range(1 + _ENTER_RETRIES):
        session.send_keys("Enter")
        confirmed = False
        for _ in range(_SUBMIT_VERIFY_POLLS):
            if baseline_size is not None:
                size = _transcript_size(path)
                confirmed = size is not None and size > baseline_size
            else:
                confirmed = _submitted(session.capture_pane())
            if confirmed:
                break
            session._sleep(session._poll_interval_s)
        if confirmed:
            break
    # 确认已进入忙碌态再交还主路径轮询完成，否则首帧落在提交后的空窗里会误判完成。
    for _ in range(_BUSY_CONFIRM_POLLS):
        if _BUSY.search(session.capture_pane()) is not None:
            return
        session._sleep(session._poll_interval_s)


# ── 清残留 ─────────────────────────────────────────────────────────────────
_CLEAR_PROBE_CHAR = "x"
_CLEAR_PROBE_ONLY = re.compile(rf"(?m)^\s*>[\s\xa0]+{_CLEAR_PROBE_CHAR}[\s\xa0]*$")
_CLEAR_RETRIES = 3
_CLEAR_PROBE_POLLS = 10


def _clear_input(session: TmuxAgentSession) -> bool:
    """清空输入框残留并结构化确认。返回 True = 缓冲区确已清空。

    C-u 清行后 Ink TUI 懒重绘（pane 仍显示旧文本），"发键后读屏等空输入框"验证不了。
    故敲一个探针字符强制重绘：输入框只剩 ``> x`` 即证明缓冲区里只有探针，再退格删掉它。

    注意与 claude 版本的一处实拍差异：claude 的输入框是 ``❯`` + nbsp，探针式要求那个
    nbsp（恰好把 shell 阶段排除掉）；codebuddy 是裸 ``>`` + **普通空格**，照抄 nbsp
    必然永远匹配不上。这里两种空白都认，shell 阶段的排除交给 ``drive_send`` 上游的
    done_signal 判定。
    """
    for _ in range(_CLEAR_RETRIES):
        session.send_keys("C-u")
        session.send_text(_CLEAR_PROBE_CHAR)
        for _ in range(_CLEAR_PROBE_POLLS):
            if _CLEAR_PROBE_ONLY.search(session.capture_pane()):
                session.send_keys("BSpace")
                return True
            session._sleep(session._poll_interval_s)
        session.send_keys("BSpace")
    return False


# ── 答案抽取 ───────────────────────────────────────────────────────────────
# 提示回显行 ``> <原句>``。
_ECHO = re.compile(r"^\s*>[\s\xa0]+(?P<text>\S.*)$")
# 一轮答案与下一轮之间的边界：分隔横线（输入框上下那两条 200 字符的 ``─``）或下一条提示符。
_BLOCK_END = re.compile(r"^\s*(?:─{5,}|>)")
# codebuddy 的答案 bullet 是 ``●``（claude 是 ``⏺``）。
_ANSWER_BULLET = re.compile(r"^\s*●\s?")
# 首启时 shell 回显的启动命令行不是答案，提取时整行剔除。
_LAUNCH_ECHO = re.compile(r"codebuddy\s+--dangerously-skip-permissions")


def _extract(delta: str) -> str:
    lines = [
        ln
        for ln in delta.splitlines()
        if not _CHROME_LINE.match(ln) and not _LAUNCH_ECHO.search(ln)
    ]
    return "\n".join(ln.strip() for ln in lines).strip()


def _read_answer(pane: str, prompt: str) -> str:
    """从完成时可见 pane 抽取「本轮 prompt」对应的答案。

    codebuddy 与 claude 同为 alt-screen TUI：底部固定输入框、答案渲染在其上方、没有
    scrollback，通用的 pre/post delta 锚点模型对它失效。多轮常驻会话里上轮内容仍可见，
    故按 prompt 回显定位本轮区块，取其后、下一边界前的文本。
    """
    norm = prompt.replace("\xa0", " ").strip()
    lines = pane.splitlines()
    start = -1
    for i in range(len(lines) - 1, -1, -1):
        match = _ECHO.match(lines[i])
        if match and match.group("text").replace("\xa0", " ").strip() == norm:
            start = i
            break
    block = lines[start + 1 :] if start >= 0 else lines
    out: list[str] = []
    for ln in block:
        if _BLOCK_END.match(ln):
            break
        if _CHROME_LINE.match(ln):
            continue
        stripped = _ANSWER_BULLET.sub("", ln).strip()
        if stripped:
            out.append(stripped)
    return "\n".join(out).strip()


# ── 启动 ───────────────────────────────────────────────────────────────────
def _launch(ctx: LaunchCtx) -> str:
    """拼启动命令。

    ``--session-id`` 与 ``--resume`` 的二分与 claude 同一套规则：``--session-id`` 是
    「用此 id **新建**会话」，撞上已存在的 transcript 会直接报错退出；同 id 换
    ``--resume`` 才是续接。故按该 sid 的 jsonl 是否已存在二分——重启 / 空闲回收后同一个
    frago session_id 重新拉起，走的正是后者。
    """
    sid = ctx.session_id if ctx.native_session_id else _codebuddy_session_uuid(ctx.session_id)
    parts = [_codebuddy_bin(), "--dangerously-skip-permissions"]
    settings = _write_settings(ctx)
    if settings:
        parts += ["--settings", settings]
    if _locate_transcript(sid, cwd=ctx.cwd) is not None:
        parts += ["--resume", sid]
    else:
        parts += ["--session-id", sid]
    return " ".join(shlex.quote(p) for p in parts)


register_driver(
    AgentDriver(
        agent_type="codebuddy",
        launch_command=_launch,
        display_name="CodeBuddy Code",
        locate=_locate_codebuddy,
        accepts_session_id=True,
        ready_signal=_READY_BOX,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        read_answer=_read_answer,
        completion_probe=_completion_probe,
        needs_input_signal=_NEEDS_INPUT,
        # trust 模态挡在 ready 之前，而 exception_handlers 是 ready 之后才跑的，对它无效。
        # 它由注入的 settings 里的 trustedDirectories 关掉（见 _build_settings）。
        exception_handlers=[],
        clear_input=_clear_input,
        # transcript_source 故意不设：JsonlTranscriptSource 要按 ``AgentType(agent_type)``
        # 取解析器，而 AgentType 枚举里还没有 codebuddy，设了也只会 warn 后返回空表。
        # 补枚举要动会话子系统，属另一个阶段的活。
        #
        # profile 同样不设：frago 的 profile 是 Anthropic 协议端点，codebuddy 走自己的
        # WorkBuddy 账号体系，``ANTHROPIC_*`` 对它无意义——没有诚实的翻译，故宁可明说。
        profile_unsupported_reason=(
            "codebuddy 走 WorkBuddy 自己的账号与模型体系，frago profile 的 Anthropic "
            "端点/密钥对它无意义；换模型请用 codebuddy 自己的 --model。"
        ),
    )
)
