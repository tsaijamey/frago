"""codex (OpenAI Codex CLI) TUI driver。

屏幕信号与启动行为全部来自 codex-cli 0.147.0 上的真实 pane 实测。

这一版换掉了首版占位实现。占位版的就绪信号是 ``(?i)codex|>\\s``，而 tmux 起会话
的第一步就是往 shell 里敲 ``codex`` 这行启动命令——命令回显自己就命中了就绪信号。
于是提示词在 TUI 还没起来时被投进 shell，永远到不了 codex；本轮既没有答案也没有
报错，一路空等到超时。现场证据：pane 上提示词躺在 zsh 提示符那一行，codex 的输入
框干干净净，``frago agent`` 挂满两分钟。这类静默挂起是本 driver 首要要防的东西。

## 启动路上的三道门

交互式 codex 在真正可用之前会依次弹三个模态，任何一个没处理都会让就绪信号永不
出现、会话干等到超时：

1. **有新版本**——``✨ Update available!`` 三选一菜单。用 ``-c
   check_for_update_on_startup=false`` 从源头关掉，而不是起来之后抢着敲 Esc：
   ``open()`` 的异常处理器是**等到就绪之后**才跑的，而这个模态恰恰挡在就绪前面，
   靠它救不了场。
2. **目录未信任**——``Do you trust the contents of this directory?``。信任记录在
   ``config.toml`` 的 ``[projects."<路径>"] trust_level``，且**只认落盘的配置**：
   实测 ``-c 'projects."<路径>".trust_level="trusted"'` 这样的命令行覆盖不起作用，
   所以起会话前得把它幂等地写进配置（``_ensure_workspace_trusted``），与 claude
   那边预写 ``~/.claude.json`` 是同一手法。
3. **钩子待复核**——``Hooks need review``。frago 自己装的钩子自己认，
   ``--dangerously-bypass-hook-trust`` 正是给"已在外部核过钩子来源的自动化"准备的
   开关。真人自己开 codex 时这道门照常在，frago 一个字都不改。

## 判完成靠记录不靠读屏

codex 把整个会话写成一个 append-only 的 rollout JSONL，一轮的收尾是一条
``task_complete``（带 ``turn_id`` 与 ``last_agent_message``）。这是权威判据，
``_completion_probe`` 走它；读屏只在会话 id 还没认领时兜底。会话 id 是认领来的
（codex 只接受 ``codex resume <id>`` 续接，不接受"用我给的 id 新建"），但比
opencode 好办：codex 的会话文件在 TUI 起来那一刻就建好，不必等首轮提交。
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from frago.agent_driver.driver import (
    AgentDriver,
    CompletionVerdict,
    LaunchCtx,
    PaneMatcher,
    register_driver,
)
from frago.agent_driver.tmux_session import TmuxAgentSession
from frago.agent_driver.transcript_source import JsonlTranscriptSource
from frago.session import codex_store

if TYPE_CHECKING:
    from collections.abc import MutableMapping

logger = logging.getLogger(__name__)

# 起会话时恒定携带的开关。三个各有出处，见模块头。
#
# ``--dangerously-bypass-approvals-and-sandbox`` 与 claude driver 的
# ``--dangerously-skip-permissions`` 是同一个决定：frago 驱动的是无人值守会话，
# 留着审批门就等于让第一次写文件卡住整轮。真人自己敲 codex 时这些开关一个都不在。
_BASE_FLAGS = (
    "-c check_for_update_on_startup=false "
    "--dangerously-bypass-hook-trust "
    "--dangerously-bypass-approvals-and-sandbox"
)

# 就绪：两个结构信号任一命中。
#   ① 启动横幅框里的 ``>_ OpenAI Codex (v…)``——全新会话与 ``resume`` 回放后都在；
#   ② 输入框下方的状态页脚 ``<模型> <档位> · <工作目录>``——横幅被长历史顶出可见区
#      时由它接手。
# 两者 MUST 都不命中 shell 里那行启动命令的回显，否则又会退回到"TUI 还没起来就投喂"
# 的静默挂起。页脚要求 ``·`` 两侧是空白且其后紧跟路径起始字符，这样不会误命中
# 用户 shell 提示符里成串的 ``···`` 分隔线（那种 ``·`` 之间没有空格）。
# 两条式子都不带内联 ``(?m)``：``PaneMatcher`` 编译时已经给了 ``re.MULTILINE``，
# 而把两条各自带 ``(?m)`` 的式子用 ``|`` 拼起来会让第二个全局标志落在表达式中间，
# Python 3.11+ 直接抛 PatternError——整个 driver 连装载都装载不了。
_BANNER_PAT = r"^\s*│\s*>_\s*OpenAI\s+Codex\b"
_FOOTER_PAT = r"^[^\n│╭╰]*\S\s·\s+[~/][^\n]*$"
_READY = PaneMatcher(name="codex-ready", pattern=rf"{_BANNER_PAT}|{_FOOTER_PAT}")

# 忙碌：codex 干活时在页脚给中断提示。判完成走 rollout 权威探针，这里只服务于
# 探针不可用时的读屏退路。
_BUSY = re.compile(r"(?i)esc\s+to\s+interrupt|Esc\s+again\s+to\s+interrupt")

# 完成（读屏退路）：状态页脚在 AND 屏上没有中断提示。
# 这条判据 MUST 偏严——探针失灵时宁可让本轮以超时收场（超时带着末屏、看得出发生了
# 什么），也不要因为判早了而把一屏 TUI 装饰当成答案返回。
_DONE_FOOTER = PaneMatcher(name="codex-done-footer", pattern=_FOOTER_PAT)


class _CodexDone:
    """读屏退路的完成判定：页脚在 AND 无中断提示。鸭子兼容 ``PaneMatcher``。"""

    name = "codex-done"

    def matches(self, text: str) -> bool:
        return _DONE_FOOTER.matches(text) and _BUSY.search(text) is None


_DONE = _CodexDone()

# 阻断门 needs_input：撞上即判本轮 needs_input，把"需要真人介入"投递回调用方，
# 不静默挂到超时。只认带明确失败语义的组合——裸 ``login`` / ``sign in`` 会出现在
# 启动横幅与普通答案正文里，放进来会让本轮刚提交就误判返回（claude/opencode 两侧
# 都实证过这个坑）。三道启动模态已由启动开关与预写信任消解，不在这里兜。
_NEEDS_INPUT = PaneMatcher(
    name="codex-needs-input",
    pattern=(
        r"(?i:invalid api key|api key.*(?:invalid|expired)"
        r"|not\s+logged\s+in|unauthorized|authentication\s+failed"
        r"|insufficient\s+(?:credit|balance|quota)|quota\s+exceeded"
        r"|please\s+(?:run\s*/?login|log\s*in|sign\s+in\s+to\s+continue))"
    ),
)

# 视觉装饰行：边框、状态页脚、提示行。只在探针不可用、退回读屏取答案时用到。
_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|›|⚠|▌|■|Tip:|>_\s*OpenAI)",
)

# 认领起算点：按会话记住"起会话前一刻"的毫秒时间戳。codex 的 rollout 文件在 TUI
# 起来那一刻就建，所以锚在启动之前即可罩住它；MUST 保留最早那个而不是每轮刷新。
_CLAIM_ANCHORS: MutableMapping[TmuxAgentSession, int] = WeakKeyDictionary()

# launch 那一刻记下的锚点，键是 frago 会话标识。launch 拿不到 session 对象（会话
# 对象还在构造中），故先落在这里，首次需要认领时再挪进 ``_CLAIM_ANCHORS``。
_LAUNCH_ANCHORS: dict[str, int] = {}

# Enter 之后确认"确已提交"的轮询次数与重发上限。判据是 rollout 文件变长——那是
# 提交落地的结构化证据。读屏判"输入框空了"在真实 TUI 上有竞态（重绘中途抓屏会
# 看见一瞬间的空框），claude 侧已经为此死锁过一次。
_SUBMIT_VERIFY_POLLS = 20
_ENTER_RETRIES = 2


# ── 目录信任 ────────────────────────────────────────────────────────
def _config_path() -> Path:
    return codex_store.get_codex_home() / "config.toml"


def _toml_escape(value: str) -> str:
    """把一个路径转义成 TOML 基本字符串里的安全形式。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _already_trusted(text: str, abspath: str) -> bool:
    """配置里这个目录是否已经是 trusted。解析不了就当"没有"，交给写入路径。"""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        return False
    try:
        data = tomllib.loads(text)
    except Exception:
        return False
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return False
    entry = projects.get(abspath)
    return isinstance(entry, dict) and entry.get("trust_level") == "trusted"


def _write_trust(text: str, abspath: str) -> str:
    """把 ``trust_level = "trusted"`` 放进这个目录的表里，返回新的配置全文。

    三种情形分开处理，NEVER 无脑追加：表已存在时再追加一个同名表头会让整个
    ``config.toml`` 变成非法 TOML（重复键），codex 会直接拒绝加载配置并退出——
    那等于用一次"帮你省事"把用户的 codex 彻底弄坏。

    保留原文逐行改写而不是解析后回写，是因为这个文件是用户手写手维护的：注释、
    键序、空行都得原样留着。
    """
    header = f'[projects."{_toml_escape(abspath)}"]'
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        prefix = text if text.endswith("\n") or not text else text + "\n"
        return f'{prefix}\n{header}\ntrust_level = "trusted"\n'
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    for i in range(start + 1, end):
        if lines[i].split("=", 1)[0].strip() == "trust_level":
            lines[i] = 'trust_level = "trusted"'
            return "\n".join(lines) + "\n"
    lines.insert(start + 1, 'trust_level = "trusted"')
    return "\n".join(lines) + "\n"


def _ensure_workspace_trusted(cwd: str) -> None:
    """起 TUI 前把 ``cwd`` 标成已信任，好让 codex 不弹一次性的目录信任菜单。

    哪个环节出事、当事人看到什么：交互式 codex 对任何还没被信任过的工作目录都会
    先拦一道 ``Do you trust the contents of this directory?`` 菜单。frago 用交互式
    TUI 驱动 codex，这道菜单必现，而就绪信号永不匹配这一屏——会话干等到 ``open()``
    超时、以 ``TmuxStartupError`` 收场。也就是"第一次在某个新目录跑 frago agent
    就卡死"，谁都会中招。

    用户主动在某目录跑 frago agent 本就等于信任它，故把这份信任幂等写进 codex 自己
    的登记，也就是他手点 "Yes, continue" 会落的同一个字段。

    写失败绝不阻断启动：最坏是菜单照常弹（与现状一致），而不是让一次配置写错把
    agent 启动整个打死。走临时文件 + 原子替换，把与 codex 自身写盘撞车的窗口收到最小。
    """
    try:
        abspath = os.path.abspath(cwd)
        path = _config_path()
        text = ""
        if path.exists():
            text = path.read_text(encoding="utf-8")
        if _already_trusted(text, abspath):
            return
        updated = _write_trust(text, abspath)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.frago.{os.getpid()}.tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:  # 信任写入尽力而为，NEVER 让它把 launch 打死
        logger.warning("could not pre-trust workspace %r for codex", cwd, exc_info=True)


# ── 启动 ────────────────────────────────────────────────────────────
def _bound_session_id(session: TmuxAgentSession) -> str | None:
    """该会话对应的 codex 原生会话 id；未认领时 None。"""
    if session.native_session_id:
        return session.session_id
    return codex_store.get_binding(session.session_id)


def _launch(ctx: LaunchCtx) -> str:
    """启动命令。发 ``resume`` 之前先确认那个会话的记录还在。

    记录被用户删掉之后 ``codex resume <id>`` 起不来，就绪信号永不出现、本轮等满
    超时，而绑定还留在文件里——下次再走一遍同一条死路，该 frago 会话就此永久不可用。
    所以这里自愈：记录没了就清掉绑定、改为裸起。``session_exists`` 在整个 sessions
    目录都读不到时返回 True，故读失败 NEVER 误清一条好绑定。
    """
    _ensure_workspace_trusted(ctx.cwd)
    # 认领的起算点锚在启动之前：rollout 文件是 TUI 起来那一刻建的，锚晚了会错过它。
    _LAUNCH_ANCHORS.setdefault(ctx.session_id, int(time.time() * 1000))

    if ctx.native_session_id:
        if codex_store.session_exists(ctx.session_id):
            return f"codex {_BASE_FLAGS} resume {ctx.session_id}"
        return f"codex {_BASE_FLAGS}"
    bound = codex_store.get_binding(ctx.session_id)
    if bound:
        if codex_store.session_exists(bound):
            return f"codex {_BASE_FLAGS} resume {bound}"
        codex_store.drop_binding(ctx.session_id)
    return f"codex {_BASE_FLAGS}"


# ── 认领 ────────────────────────────────────────────────────────────
def _claim_once(session: TmuxAgentSession) -> str | None:
    """认领动作：一次廉价尝试（单次目录扫描，不轮询、不阻塞）。

    这是**副作用**，不是判定——认不到只说明 rollout 文件还没落盘，与本轮提交有没有
    落地毫不相干。已有身份（native / 已落盘绑定）时直接返回 None，映射一旦建立就
    不再重认，重认会让两个会话的记录互串。全程吞异常：目录不可读、映射文件不可写
    都只是"这次没认到"，NEVER 逸出去影响本轮。
    """
    try:
        if session.native_session_id:
            return None
        if codex_store.get_binding(session.session_id) is not None:
            return None
        since_ms = _CLAIM_ANCHORS.get(session)
        if since_ms is None:
            since_ms = _LAUNCH_ANCHORS.get(session.session_id)
            if since_ms is None:
                return None
            _CLAIM_ANCHORS[session] = since_ms
        claimed = codex_store.claim_session(session.cwd, since_ms)
        if not claimed:
            return None
        codex_store.put_binding(session.session_id, claimed, session.cwd)
    except Exception:
        logger.debug("codex claim attempt raised", exc_info=True)
        return None
    _LAUNCH_ANCHORS.pop(session.session_id, None)
    logger.debug("codex claimed session %s for %s", claimed, session.session_id)
    return claimed


def rollout_path_for(session: TmuxAgentSession) -> Path | None:
    """该会话的 rollout 文件路径（探针 / 流式来源共用）。未认领时 None。"""
    sid = _bound_session_id(session) or _claim_once(session)
    if sid is None:
        return None
    return codex_store.find_rollout(sid)


# ── 提交 ────────────────────────────────────────────────────────────
def _rollout_size(session: TmuxAgentSession) -> int | None:
    path = rollout_path_for(session)
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    """投喂一轮：文本进框 → Enter → 确认落地（确认不了才补发）。

    落地判据是 **rollout 文件变长**。codex 一收到提交就把用户消息追加进记录，
    这是本地、即时、与提示词长度无关的证据。读屏判"输入框空了"在重绘中途会看见
    假象，补发的空 Enter 会落进下一轮，把下一次 send 变成什么都不返回——opencode
    与 claude 两侧都为此付过代价，这里不再重蹈。

    确认不了也不抛不卡：留一条 debug 日志，交给完成轮询的超时兜底。那条日志是事后
    排查"整段提示词滞留输入框"的唯一线索，NEVER 静默走掉。
    """
    _claim_once(session)
    baseline = _rollout_size(session)
    session.send_text(prompt)
    # 文本上屏有渲染时序；没进框就再投一次，再发 Enter。
    if prompt.strip() and prompt.strip() not in session.capture_pane():
        session.send_text(prompt)

    landed = False
    for attempt in range(1 + _ENTER_RETRIES):
        session.send_keys("Enter")
        for _ in range(_SUBMIT_VERIFY_POLLS):
            if baseline is None:
                # 还没认领到 rollout：这一拍再试一次，认到之后就有基线可比。
                baseline = _rollout_size(session)
                if baseline is not None:
                    break
            else:
                size = _rollout_size(session)
                if size is not None and size > baseline:
                    landed = True
                    break
            session._sleep(session._poll_interval_s)
        if landed:
            break
        logger.debug(
            "codex submit unconfirmed after enter #%d; resending (session=%s)",
            attempt + 1,
            session.session_id,
        )
    if not landed:
        logger.debug(
            "codex submit unconfirmed after %d enters; falling through to "
            "completion polling (session=%s)",
            1 + _ENTER_RETRIES,
            session.session_id,
        )


# ── 完成探针 ────────────────────────────────────────────────────────
# 本轮已终结、但 codex 给它标了错误（provider 拒绝、鉴权失败、模型不可用等）。
# 判 ``needs_input`` 而不是 ``error``：``error`` 在本层的既有语义是"driver / tmux
# 这条链路自己坏了"，而这里链路全程正常，坏的是凭据或 provider 的接纳，得由真人去
# 改配置才走得下去——与屏幕上的认证墙是同一类失败，只是这一次它没往屏幕上打字。
_TURN_ERROR_NOTE = (
    "本轮结束但 codex 标了错误，通常是鉴权失败、provider 拒绝或模型不可用。\n"
    "用 `codex doctor` 查 provider、鉴权来源与端点可达性；配置在 ~/.codex/config.toml。\n"
    "codex 报的原文：\n"
)

_EMPTY_ANSWER_NOTE = (
    "本轮结束但没有任何输出，通常是鉴权失败或 provider 拒绝。\n"
    "用 `codex doctor` 查 provider、鉴权来源与端点可达性；配置在 ~/.codex/config.toml。"
)


def _completion_probe(session: TmuxAgentSession) -> CompletionVerdict | None:
    """权威完成探针：读 rollout 判本轮是否答完 + 取终答；顺手认领。

    尚无绑定时先做一次廉价认领再判。探针在整轮里被反复调用，认领因此获得"整轮"
    这么长的机会窗口，不必赌任何固定时长。认不到就返回 None，由主路径当帧退回
    读屏信号，本轮照常跑完。
    """
    sid = _bound_session_id(session) or _claim_once(session)
    if sid is None:
        return None
    turn = codex_store.latest_turn(sid)
    if turn is None:
        return None
    if not turn.done:
        return CompletionVerdict(done=False, text=None, marker=turn.turn_id)
    if turn.error:
        logger.warning(
            "codex turn finished with an error (session=%s, turn=%s): %s",
            sid,
            turn.turn_id,
            turn.error,
        )
        return CompletionVerdict(
            done=True,
            text=f"{_TURN_ERROR_NOTE}{turn.error}",
            marker=turn.turn_id,
            status="needs_input",
        )
    if not turn.text.strip():
        logger.warning(
            "codex turn finished with no output (session=%s, turn=%s)", sid, turn.turn_id
        )
        return CompletionVerdict(
            done=True,
            text=_EMPTY_ANSWER_NOTE,
            marker=turn.turn_id,
            status="needs_input",
        )
    return CompletionVerdict(done=True, text=turn.text, marker=turn.turn_id)


# ── 流式来源 ────────────────────────────────────────────────────────
class CodexTranscriptSource(JsonlTranscriptSource):
    """codex 的记录来源：rollout JSONL 的字节偏移增量读取。

    rollout 是 append-only 的 JSONL，claude 那套"文件 + 字节偏移"原样成立，故直接
    复用 ``JsonlTranscriptSource``。只有两处要改：

    - 会话 id 不在文件名的 stem 里（stem 是 ``rollout-<时间戳>-<id>``），也不在每
      一行里（只在首行的 ``session_meta`` 出现一次），所以由知道自己在读哪个会话的
      本类补上；
    - 每条原始记录交给 adapter 之前先把会话 id 盖上去。
    """

    def __init__(self, session: TmuxAgentSession) -> None:
        super().__init__("codex", lambda: rollout_path_for(session))
        self._session = session

    @property
    def native_session_id(self) -> str | None:
        return _bound_session_id(self._session)

    def _prepare(self, data: dict[str, Any]) -> dict[str, Any]:
        sid = self.native_session_id
        if sid is None or "session_id" in data:
            return data
        return {**data, "session_id": sid}


def _transcript_source(session: TmuxAgentSession) -> CodexTranscriptSource:
    return CodexTranscriptSource(session)


# ── 读屏退路 ────────────────────────────────────────────────────────
_LAUNCH_ECHO = re.compile(r"codex\s+-c\s+check_for_update_on_startup")


def _extract(delta: str) -> str:
    lines = [
        ln
        for ln in delta.splitlines()
        if not _CHROME_LINE.match(ln) and not _LAUNCH_ECHO.search(ln)
    ]
    return "\n".join(ln.strip() for ln in lines).strip()


register_driver(
    AgentDriver(
        agent_type="codex",
        launch_command=_launch,
        ready_signal=_READY,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        needs_input_signal=_NEEDS_INPUT,
        completion_probe=_completion_probe,
        transcript_source=_transcript_source,
        exception_handlers=[],
        # profile_env / profile_apply 刻意都不提供：frago 的 profile 是 Anthropic 协议
        # 端点，而 codex 0.147 的自定义 provider 走 OpenAI 的 responses 协议，两者不是
        # 同一套线协议，没有诚实的翻译。`--use-profile` 因此对 codex 不生效，会话跑在
        # codex 自己配置的模型上；激活时 codex 也不在可选目标里——这两处都由 UI/CLI
        # 明说，NEVER 假装翻译过了。
        profile_unsupported_reason=(
            "frago 的 profile 存的是 Anthropic 协议端点，codex 的自定义 provider 只认 "
            "OpenAI responses 协议，两者不是同一套线协议，没有诚实的翻译。"
            "要让 codex 用同一个模型，得直接改 ~/.codex/config.toml。"
        ),
    )
)
