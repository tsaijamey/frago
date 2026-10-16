"""agy (Antigravity CLI) TUI driver。

屏幕信号与启动行为全部来自 2026-10-13 在本机的真实 pane 实测（agy 1.0.6 起抓、
期间自升到 1.3.4）。取证样本与结论记在
``.claude/docs/spec-driven-plan/20261013-agy-agent-support/spec.md`` 的 Phase 0。

## 就绪、忙碌、答完三态长什么样

agy 的输入框**单独占一行**，那一行只有一个 ``>``；它的底下是一条暗色横线，再底下
是状态栏。三态靠状态栏与输入框的组合区分：

- **就绪** —— 状态栏是 ``? for shortcuts``，输入框那一行只有 ``>``。
- **忙碌** —— 状态栏换成 ``esc to cancel``，正文区出现 ``Generating`` 与转轮。
- **答完** —— 回到就绪那一屏，答案渲染在提问行下方。

判就绪 MUST 带上状态栏那半句。只认「有一行是裸 ``>``」是不够的：提交之后输入框
本来就是空的 ``>``，提问行也以 ``>`` 开头，这一条在忙碌中同样命中。

**没有灰色占位提示这道坑。** claude 在 2.1.282 之后空输入框里会显示一句暗色提示
（见 ``frago-dev/claude-ready-dim-placeholder``），读屏会把提示当成用户打的字。agy
的空输入框就是空的，故本 driver 不需要 ``ready_signal_ansi``。

## 判完成靠记录不靠读屏

agy 把每一轮写进 ``brain/<会话编号>/.system_generated/logs/transcript.jsonl``，那是
它的原生账本：用户那一轮是 ``USER_INPUT``，模型每一拍是 ``PLANNER_RESPONSE``（带
``tool_calls`` = 还要动手，带 ``content`` = 说完了）。这是权威判据，
``_completion_probe`` 走它；读屏只在还没认领会话编号时兜底。

这条路的来由是 opencode 那次的教训（``frago-dev/opencode-core-support-spec``）：
答完标记若在屏上常驻，纯读屏判完成会在第二轮刚提交时误判、把上一轮答案取回来；而
hook 注入的文本会在 TUI 屏上原样回显，屏幕增量抠答案必然混入注入内容。agy 有与
claude JSONL 同级的记录，故不把完成判定压在读屏上。

## 新目录有一道信任菜单

agy 对没进过的目录先弹 ``Do you trust the contents of this project?``（``> Yes, I
trust this folder`` 与 ``No, exit``）。这道菜单会挡在就绪信号前面—— ``open()`` 的
异常处理器要等就绪之后才跑，靠它救不了场。确认后的记录落在 agy 自己的日常配置
``~/.gemini/antigravity-cli/settings.json`` 的 ``trustedWorkspaces`` 数组里，没有
"只写 frago 自己目录"的落点可选。

故起会话前把它幂等写进去（``_ensure_workspace_trusted``）——用户主动在某目录跑
``frago agent`` 本就等于信任它。**只增 ``trustedWorkspaces`` 的一个元素，
``colorScheme`` 与 ``model`` 等其余键一个字节不动。**

driver **不代替用户按键**：菜单若还是弹出来（预写没生效），说明这一轮该由人接手，
``needs_input_signal`` 认下它，本次以 needs_input 收场并把末屏带给调用方。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
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
from frago.session import agy_store

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from frago.init.profile_manager import APIProfile

logger = logging.getLogger(__name__)

# 起会话时恒定携带的开关。与 claude 的 ``--dangerously-skip-permissions`` 是同一个
# 决定：frago 驱动的是无人值守会话，留着权限确认就等于让第一次写文件卡住整轮。
# 真人自己敲 agy 时这个开关不在。
_BASE_FLAGS = "--dangerously-skip-permissions"

# 状态栏。就绪态那条尾巴是 agy 自己的按键提示；忙碌态换成取消提示。
_FOOTER_READY = PaneMatcher(name="agy-footer-ready", pattern=r"(?m)^.*\?\s+for\s+shortcuts")
_BUSY = re.compile(r"(?i)esc\s+to\s+cancel|\bGenerating\b")

# 输入框那一行：只有 ``>``。用于确认框是空的，以及读屏退路判答案的边界。
_INPUT_BOX = re.compile(r"(?m)^\s*>\s*$")


class _AgyReady:
    """就绪 = 状态栏在就绪态 **且** 屏上没有忙碌标记。鸭子兼容 ``PaneMatcher``。

    只看输入框的话，忙碌中那一拍同样命中（输入框本来就空着），提示词会在模型还在
    干活时被投进去。状态栏那一句才是三态真正的分界。
    """

    name = "agy-ready"

    def matches(self, text: str) -> bool:
        return _FOOTER_READY.matches(text) and _BUSY.search(text) is None


_READY = _AgyReady()


class _AgyDone:
    """读屏退路的完成判定：就绪那一屏回来了即视为答完。

    与就绪同一个判据是有意的——探针失灵时宁可让本轮以超时收场（超时带着末屏、
    看得出发生了什么），也不要因为判早了把一屏 TUI 装饰当答案返回。就绪那一屏
    只在"模型没在干活"时出现，作为退路足够严。
    """

    name = "agy-done"

    def matches(self, text: str) -> bool:
        return _READY.matches(text)


_DONE = _AgyDone()

# 需要真人介入的门。只认带明确失败语义的组合——裸 ``login`` / ``sign in`` 会出现在
# 启动横幅与答案正文里，claude 与 codex 两侧都为此误判过。
#
# 信任菜单也在这一道：预写没生效时它就是"该由人接手"的那一屏，本次以 needs_input
# 收场，几百毫秒就返回，而不是空等到启动超时。
_NEEDS_INPUT = PaneMatcher(
    name="agy-needs-input",
    pattern=(
        r"(?i:do\s+you\s+trust\s+the\s+contents\s+of\s+this\s+project"
        r"|invalid\s+api\s+key|api\s+key.*(?:invalid|expired)"
        r"|not\s+logged\s+in|unauthorized|authentication\s+failed"
        r"|insufficient\s+(?:credit|balance|quota)|quota\s+exceeded"
        r"|you\s+have\s+reached\s+your\s+(?:usage\s+)?limit"
        r"|please\s+(?:run\s*/?login|log\s*in|sign\s+in\s+to\s+continue))"
    ),
)

# 视觉装饰行：边框、横线、状态栏、按键提示。只在退回读屏取答案时用到。
_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼━┃]|>|Gemini\s|\?\s+for\s+shortcuts|esc\s+to\s+cancel)"
)

# 认领起算点：按会话记住"起会话前一刻"的毫秒时间戳。agy 的摘要行在首轮提交后才有，
# 锚在启动之前即可罩住它；MUST 保留最早那个而不是每轮刷新。
_CLAIM_ANCHORS: MutableMapping[TmuxAgentSession, int] = WeakKeyDictionary()

# launch 那一刻记下的锚点，键是 frago 会话标识。launch 拿不到 session 对象（会话对象
# 还在构造中），故先落在这里，首次需要认领时再挪进 ``_CLAIM_ANCHORS``。
_LAUNCH_ANCHORS: dict[str, int] = {}

# Enter 之后确认"确已提交"的轮询次数与重发上限。判据是 transcript 文件变长——那是
# 提交落地的结构化证据。读屏判"输入框空了"在真实 TUI 上有竞态，claude 侧为此死锁过。
_SUBMIT_VERIFY_POLLS = 20
_ENTER_RETRIES = 2


# ── 探测可执行文件 ──────────────────────────────────────────────────
def _locate() -> str | None:
    """agy 装在哪。

    agy 自己的安装器把它放在 ``~/.local/bin``，那不在 ``find_agent_cli`` 兜底的
    几个系统目录里，故先看这一处，再退回通用的 PATH 查找。
    """
    local = Path.home() / ".local" / "bin" / "agy"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    found = shutil.which("agy")
    if found:
        return found
    for base in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(base) / "agy"
        if candidate.is_file():
            return str(candidate)
    return None


# ── 目录信任 ────────────────────────────────────────────────────────
def _settings_path() -> Path:
    """agy 存日常配置的文件（``colorScheme``、``model`` 与信任名单都在这一份里）。"""
    return agy_store.get_app_data_dir() / "settings.json"


def _load_settings(path: Path) -> dict[str, Any] | None:
    """读配置。文件不存在给空表；读不动给 None（调用方据此放弃写入）。"""
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _ensure_workspace_trusted(cwd: str) -> None:
    """起 TUI 前把 ``cwd`` 写进 agy 的信任名单，好让信任菜单不再出现。

    哪个环节出事、当事人看到什么：交互式 agy 对任何还没被信任过的工作目录都会先拦
    一道 ``Do you trust the contents of this project?`` 菜单。frago 用交互式 TUI
    驱动 agy，这道菜单必现，而就绪信号（状态栏 ``? for shortcuts``）永不匹配这一屏
    ——会话干等到 ``open()`` 超时、以 ``TmuxStartupError`` 收场。也就是"第一次在某个
    新目录跑 frago agent 就卡死"。

    用户主动在某目录跑 frago agent 本就等于信任它，故把这份信任幂等写进 agy 自己的
    登记，也就是他手点 "Yes, I trust this folder" 会落的同一个数组。

    三条约束，缺一不可：
    - **只增 ``trustedWorkspaces`` 的一个元素**。这份文件里还存着用户的
      ``colorScheme`` 与 ``model``，逐键原样保留，只回写这一个数组。
    - **值确实要变才写**。已在名单里就一个字节都不动，不与正在跑的 agy 抢盘。
    - **写失败绝不阻断启动**。最坏是菜单照常弹（与现状一致），而不是让一次配置写错
      把 agent 启动整个打死。走临时文件 + ``os.replace`` 原子替换收窄窗口。
    """
    try:
        abspath = os.path.abspath(cwd)
        path = _settings_path()
        data = _load_settings(path)
        if data is None:
            logger.warning(
                "agy settings at %s is not a JSON object; leaving it alone", path
            )
            return
        trusted = data.get("trustedWorkspaces")
        if not isinstance(trusted, list):
            trusted = []
        if abspath in trusted:
            return
        data["trustedWorkspaces"] = [*trusted, abspath]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.frago.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
        logger.debug("pre-trusted %s for agy", abspath)
    except Exception:  # 信任写入尽力而为，NEVER 让它把 launch 打死
        logger.warning("could not pre-trust workspace %r for agy", cwd, exc_info=True)


# ── 启动 ────────────────────────────────────────────────────────────
def _bound_session_id(session: TmuxAgentSession) -> str | None:
    """该会话对应的 agy 原生会话编号；未认领时 None。"""
    if session.native_session_id:
        return session.session_id
    return agy_store.get_binding(session.session_id)


def _launch(ctx: LaunchCtx) -> str:
    """启动命令。续接时先确认那场会话的记录还在。

    记录被删掉之后 ``agy --conversation <编号>`` 起不来，就绪信号永不出现、本轮等满
    超时，而绑定还留在文件里——下次再走一遍同一条死路。故这里自愈：记录没了就清掉
    绑定、改为裸起。``conversation_exists`` 在整个 brain 目录都读不到时返回 True，
    故读失败 NEVER 误清一条好绑定。
    """
    _ensure_workspace_trusted(ctx.cwd)
    # 认领的起算点锚在启动之前：摘要行是会话建出来之后才写的，锚晚了会错过它。
    _LAUNCH_ANCHORS.setdefault(ctx.session_id, int(time.time() * 1000))

    if ctx.native_session_id:
        if agy_store.conversation_exists(ctx.session_id):
            return f"agy {_BASE_FLAGS} --conversation {ctx.session_id}"
        return f"agy {_BASE_FLAGS}"

    bound = agy_store.get_binding(ctx.session_id)
    if bound:
        if agy_store.conversation_exists(bound):
            return f"agy {_BASE_FLAGS} --conversation {bound}"
        agy_store.drop_binding(ctx.session_id)
    return f"agy {_BASE_FLAGS}"


# ── 认领 ────────────────────────────────────────────────────────────
def _claim_anchor(session: TmuxAgentSession) -> int | None:
    """认领的起算点（毫秒）。三处依次退让，都取不到时 None。

    **不能只信进程内那两处。** ``frago agent start`` 与之后的每一次
    ``frago agent send`` 是各自独立的进程，``_LAUNCH_ANCHORS`` / ``_CLAIM_ANCHORS``
    活不过第一条命令。codex 那边不显这个问题，是因为它的 rollout 文件在会话建出来
    的那一刻就存在，认领在**启动那一趟**就做完了；agy 的会话编号要等第一轮提交之后
    才进摘要库，认领因此正好发生在启动进程早已退出的那一刻——只信进程内的话，它会
    永远认不到，完成探针永远 None，然后静默退回读屏（2026-10-14 实机就是这么错的：
    五轮全答对了，回文本却全空）。

    所以补了第三处：问 tmux 这场会话什么时候建的。那个时刻跨进程都在，且一定早于
    会话编号出现的那一刻。
    """
    memo = _CLAIM_ANCHORS.get(session)
    if memo is not None:
        return memo
    launched = _LAUNCH_ANCHORS.get(session.session_id)
    if launched is not None:
        _CLAIM_ANCHORS[session] = launched
        return launched
    created = session.created_at()
    if created is None:
        return None
    anchor = int(created * 1000)
    _CLAIM_ANCHORS[session] = anchor
    return anchor


def _claim_once(session: TmuxAgentSession) -> str | None:
    """认领动作：一次廉价尝试（单次读库，不轮询、不阻塞）。

    这是**副作用**，不是判定——认不到只说明 agy 还没把会话写进摘要库，与本轮提交
    有没有落地毫不相干。已有身份时直接返回 None，映射一旦建立就不再重认，重认会让
    两场会话的记录互串。全程吞异常：库被占、映射文件不可写都只是"这次没认到"。
    """
    claimed: str | None = None
    try:
        if session.native_session_id:
            return None
        if agy_store.get_binding(session.session_id) is not None:
            return None
        since_ms = _claim_anchor(session)
        if since_ms is None:
            return None
        claimed = agy_store.claim_conversation(session.cwd, since_ms)
        if not claimed:
            return None
        agy_store.put_binding(session.session_id, claimed, session.cwd)
        # 认到真编号，顺手把「这场是 frago 派出去的」记进会话关系账——父会话编号从派活
        # 那一刻的环境里认（见 ``record_dispatch``）。记账 MUST 在这里做：绑定表在会话
        # 收场时就清了，跑完之后再想拿这个编号已经拿不到。
        from frago.session.session_origin import record_dispatch

        record_dispatch(claimed, agent_type="agy", cwd=session.cwd)
        # 认到真编号就把这个窗口改认它。名字与真编号一致之后，常驻池重启时按名字就能
        # 找到这个还活着的窗口并接管，不必另起一个去续接同一场对话。改不动只是名字
        # 留在原处，不阻断认领本身。
        if not session.rename_tmux(claimed):
            logger.debug(
                "agy claimed %s for %s but could not rename %s",
                claimed,
                session.session_id,
                session.tmux_name,
            )
    except Exception:
        logger.debug("agy claim attempt raised", exc_info=True)
        return None
    _LAUNCH_ANCHORS.pop(session.session_id, None)
    logger.debug("agy claimed session %s for %s", claimed, session.session_id)
    return claimed


def transcript_path_for(session: TmuxAgentSession) -> Path | None:
    """该会话的原文文件路径（探针与投喂验证共用）。未认领时 None。"""
    sid = _bound_session_id(session) or _claim_once(session)
    if sid is None:
        return None
    path = agy_store.transcript_path(sid)
    return path if path.exists() else None


# ── 提交 ────────────────────────────────────────────────────────────
def _transcript_size(session: TmuxAgentSession) -> int | None:
    path = transcript_path_for(session)
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    """投喂一轮：文本进框 → Enter → 确认落地（确认不了才补发）。

    落地判据是 **transcript 文件变长**。agy 一收到提交就把用户那一轮追加进记录，
    这是本地、即时、与提示词长度无关的证据。读屏判"输入框空了"在重绘中途会看见假象，
    补发的空 Enter 会落进下一轮——opencode 与 claude 两侧都为此付过代价。

    实测：agy 一次 Enter 即提交，不需要连发两次（与 opencode 1.17.10 相同，与
    claude 早期那版的差异无关）。

    确认不了也不抛不卡：留一条 debug 日志，交给完成轮询的超时兜底。那条日志是事后
    排查"整段提示词滞留输入框"的唯一线索，NEVER 静默走掉。
    """
    _claim_once(session)
    baseline = _transcript_size(session)
    session.send_text(prompt)

    landed = False
    for attempt in range(1 + _ENTER_RETRIES):
        session.send_keys("Enter")
        for _ in range(_SUBMIT_VERIFY_POLLS):
            if baseline is None:
                # 还没认领到会话编号：这一拍再试一次，认到之后就有基线可比。
                baseline = _transcript_size(session)
                if baseline is not None:
                    break
            else:
                size = _transcript_size(session)
                if size is not None and size > baseline:
                    landed = True
                    break
            session._sleep(session._poll_interval_s)
        if landed:
            break
        logger.debug(
            "agy submit unconfirmed after enter #%d; resending (session=%s)",
            attempt + 1,
            session.session_id,
        )
    if not landed:
        logger.debug(
            "agy submit unconfirmed after %d enters; falling through to "
            "completion polling (session=%s)",
            1 + _ENTER_RETRIES,
            session.session_id,
        )


# ── 完成探针 ────────────────────────────────────────────────────────
def _completion_probe(session: TmuxAgentSession) -> CompletionVerdict | None:
    """权威完成探针：读 transcript 判本轮是否答完 + 取终答；顺手认领。

    尚无绑定时先做一次廉价认领再判。探针在整轮里被反复调用，认领因此获得"整轮"
    这么长的机会窗口，不必赌任何固定时长。认不到就返回 None，由主路径当帧退回读屏
    信号，本轮照常跑完。
    """
    sid = _bound_session_id(session) or _claim_once(session)
    if sid is None:
        return None
    turn = agy_store.latest_turn(sid)
    if turn is None:
        return None
    if not turn.done:
        return CompletionVerdict(done=False, text=None, marker=turn.turn_id)
    return CompletionVerdict(done=True, text=turn.text, marker=turn.turn_id)


# ── 流式来源 ────────────────────────────────────────────────────────
class AgyTranscriptSource(JsonlTranscriptSource):
    """agy 的记录来源：brain 下 transcript.jsonl 的字节偏移增量读取。

    转录是 append-only 的 JSONL，claude 那套"文件 + 字节偏移"原样成立，故直接复用
    ``JsonlTranscriptSource``。只有两处要改：

    - **会话编号不在文件名里**。文件名恒为 ``transcript.jsonl``，编号在它上面两级
      那个目录名上（``brain/<编号>/.system_generated/logs/``），基类按 stem 取的
      那个值永远是 "transcript"——照它盖上去，这一场就被记到一个叫 transcript 的
      会话名下。所以由知道自己在读哪一场的本类补上；
    - 每行转录里也没有编号（agy 只把它记在目录名与摘要库上），交给 adapter 之前先
      盖上去。
    """

    def __init__(self, session: TmuxAgentSession) -> None:
        super().__init__("agy", lambda: transcript_path_for(session))
        self._session = session

    @property
    def native_session_id(self) -> str | None:
        return _bound_session_id(self._session)

    def _prepare(self, data: dict[str, Any]) -> dict[str, Any]:
        sid = self.native_session_id
        if sid is None or "session_id" in data:
            return data
        return {**data, "session_id": sid}


def _transcript_source(session: TmuxAgentSession) -> AgyTranscriptSource:
    return AgyTranscriptSource(session)


# ── 读屏退路 ────────────────────────────────────────────────────────
_LAUNCH_ECHO = re.compile(r"agy\s+--dangerously-skip-permissions")


def _extract(delta: str) -> str:
    """从屏幕增量里抠答案。

    只在探针不可用时走这条路。剔掉边框、状态栏、按键提示与启动命令的回显——启动
    命令本身以 ``agy`` 开头，不剔的话它会被当成答案的第一行。
    """
    lines = [
        ln
        for ln in delta.splitlines()
        if not _CHROME_LINE.match(ln) and not _LAUNCH_ECHO.search(ln)
    ]
    return "\n".join(ln.strip() for ln in lines).strip()


# ── profile ─────────────────────────────────────────────────────────
#: agy 的端点覆盖开关，官方文档「将 CLI 指向自定义端点」一节给出的环境变量。
#: 它改的是**模型请求发往哪里**，协议仍是 Gemini 兼容。
_ENV_BASE_URL = "GOOGLE_GEMINI_BASE_URL"
#: 用 API 密钥跑（而非订阅登录态）时，密钥从这个环境变量读。
#: 官方原话：单独设它没有效果，必须同时把 settings.json 的 ``modelProvider`` 设成
#: ``gemini``；且它只读环境变量，NEVER 读 ``.env`` 文件（``GOOGLE_API_KEY`` 无效）。
_ENV_API_KEY = "GEMINI_API_KEY"
#: 配套的 provider 选择，落在 agy 自己的 settings.json 上。``gemini`` 是唯一接受的值。
_PROVIDER_GEMINI = "gemini"


def _profile_env(profile: APIProfile) -> dict[str, str]:
    """把一条 profile 翻成 agy 的**会话级**注入环境变量。

    只影响 frago 起的这一个 tmux 会话，用户的 ``~/.gemini/antigravity-cli/settings.json``
    一个字不改；要改那份常驻配置是"激活"，走 ``_profile_apply``。

    ## 为什么是这两个变量、而不是照抄别家

    agy 的 profile 落地**横跨两处**，这与三家既有 driver 都不同：

    - 端点覆盖走**环境变量** ``GOOGLE_GEMINI_BASE_URL``（官方文档「将 CLI 指向自定义端点」）；
    - 密钥走**环境变量** ``GEMINI_API_KEY``，但它**必须**与 settings.json 里的
      ``modelProvider: "gemini"`` 配对才生效——官方明确写着「单独设置 GEMINI_API_KEY
      环境变量没有任何效果」。

    第二条是 agy 独有的坑：注入密钥而不设 provider，agy 会**照旧走订阅登录态**，端点
    也就没被真正用上。故本函数把 provider 一并处理（见 ``_profile_apply`` 与会话注入
    说明），并在密钥缺席时按订阅态实情处理，NEVER 产出一个"设了密钥却不用"的假象。

    没有密钥（例如只想换端点、仍走订阅登录态）时只注端点：那时 agy 用登录态去请求
    这个端点，这是官方支持的组合，不是残缺。
    """
    env: dict[str, str] = {}
    if profile.url:
        env[_ENV_BASE_URL] = profile.url
    if profile.api_key:
        env[_ENV_API_KEY] = profile.api_key
    return env


def _profile_model(profile: APIProfile) -> dict[str, Any]:
    """profile 里要写进 agy settings.json 的模型/provider 那几格。

    与 ``_profile_env`` 同源同字段，区别只是落点。只有走 API 密钥时才需要写
    ``modelProvider``——它是"用密钥而非订阅"的总开关，缺了它密钥不生效。
    """
    patch: dict[str, Any] = {}
    if profile.api_key:
        patch["modelProvider"] = _PROVIDER_GEMINI
    if profile.default_model:
        patch["model"] = profile.default_model
    return patch


def _profile_apply(profile: APIProfile) -> None:
    """激活到 agy：把这条 profile 写进它的 ``~/.gemini/antigravity-cli/settings.json``。

    **只增/改 frago 自己那几个键**（``modelProvider`` / ``model``），用户的
    ``colorScheme``、``trustedWorkspaces`` 与其余键逐键原样保留——这与
    ``_ensure_workspace_trusted`` 改写同一份文件时的纪律一致，两处 MUST 用同一种
    合并方式，否则激活 profile 会把用户的信任名单抹掉。

    接管前把被动过的键的原值备份，撤销时还原（与 codex 同一套 ``profile_target_backup``）。
    取不到密钥时不写 ``modelProvider``：那会让 agy 变成"设了 provider 却没密钥"，
    官方文档说这种组合**CLI 直接起不来**——比不激活坏得多。
    """
    from frago.init import profile_target_backup

    path = _settings_path()
    data = _load_settings(path)
    if data is None:
        logger.warning("agy settings at %s is not a JSON object; leaving it alone", path)
        return

    patch = _profile_model(profile)
    if not profile_target_backup.has("agy"):
        profile_target_backup.remember("agy", {k: data.get(k) for k in patch})

    data.update(patch)
    _write_settings(path, data)


def _profile_revert() -> None:
    """取消激活：把 frago 写进去的那几格还原成接管前的样子。

    有备份就抄回去；被改的键原本不存在（``None``）则删掉——留一个
    ``modelProvider: "gemini"`` 而环境里没有密钥，agy 下次启动直接起不来。
    """
    from frago.init import profile_target_backup

    previous = profile_target_backup.take("agy")
    if previous is None:
        return
    path = _settings_path()
    data = _load_settings(path)
    if data is None:
        return
    for key, value in previous.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    _write_settings(path, data)


def _write_settings(path: Path, data: dict[str, Any]) -> None:
    """原子写回 agy 的 settings.json（与 ``_ensure_workspace_trusted`` 同一套手法）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.frago.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


register_driver(
    AgentDriver(
        agent_type="agy",
        launch_command=_launch,
        display_name="Antigravity CLI",
        locate=_locate,
        # 编号由 agy 自己分配：它没有"用调用方给的 id 新建会话"的开关（对比 claude 的
        # ``--session-id``），续接只认 ``--conversation <编号>``。页面新建一场 agy
        # 会话时，编号得等会话起来后认领。
        accepts_session_id=False,
        # 后两者是鸭子兼容 PaneMatcher 的对象：三态的分界要"状态栏在 AND 没在忙"这样
        # 的合取，单条正则表达不了。mypy 认不出这层兼容，故标 ignore（codex 那边是
        # 同一处摩擦，只是它没标）。
        ready_signal=_READY,  # type: ignore[arg-type]
        submit=_submit,
        done_signal=_DONE,  # type: ignore[arg-type]
        extract=_extract,
        needs_input_signal=_NEEDS_INPUT,
        completion_probe=_completion_probe,
        transcript_source=_transcript_source,
        # 会话级注入：只影响 frago 起的这一个 tmux 会话，用户的 agy 配置一个字不改
        # （与 opencode 的 ``OPENCODE_CONFIG_CONTENT`` 同一条纪律）。
        profile_env=_profile_env,
        # "激活"落到 agy 自己的 settings.json，人自己敲 agy 起的会话同样生效。
        # 与 ``profile_env`` 同源同字段，两处 MUST 一致，否则"激活了"和"worker 跑的"
        # 是两个端点。
        profile_apply=_profile_apply,
        profile_revert=_profile_revert,
        # agy 只讲 Gemini 协议，不接受 Anthropic 那套通道。
        profile_protocol="gemini",
        # 名单由 agy 自己的服务端下发（``agy models``），frago 无从推断。
        known_models=(
            "gemini-3.8-flash-high",
            "gemini-3.8-flash-medium",
            "gemini-3.8-flash-low",
            "claude-opus-5-5-high",
            "claude-opus-5-5-medium",
            "claude-opus-5-5-low",
            "claude-sonnet-5-5-high",
            "claude-sonnet-5-5-medium",
            "claude-sonnet-5-5-low",
            "gpt-oss-120b-medium",
        ),
    )
)
