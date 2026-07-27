"""opencode TUI driver。

屏幕信号全部来自 opencode 1.17.10 与 1.18.0 上的真实 pane 实测，两版一致：
- 就绪：输入框自身的页脚行 ``┃  Build · <模型> <厂商>``（行首框线、不带耗时），全新
  会话与 ``-s`` 续接回放后都在；并列保留占位提示 ``Ask anything``，它只在输入框从未
  被用过时出现。
- 提交：**单次 Enter**。旧版本要连发两次，当前版本单次即提交，多敲的一次会落进
  下一轮输入框留下脏字符。send-keys 文本上屏有渲染时序，提交前重抓 pane 确认
  文本进框；Enter 之后再按会话库确认本轮确已落地（理由见
  ``_SUBMIT_VERIFY_WINDOW_S``）。确认不了 NEVER 直接补发——先看输入框里还有没有
  提示词的尾段（``_still_in_input_box``），有残留才补发，框已空就是提交早已成功。
- 忙碌：页脚 ``esc interrupt``。
- 完成（屏幕）：页脚 ``▣ Build · <模型> · 3.1s``。它只作为**无会话库时的退路**：
  实测两轮跑完后屏上同时留着两条完成标记、连耗时数字都一样，读屏连"这条属于
  哪一轮"都分辨不了。权威判定一律走 ``_completion_probe``。
- 更新模态：首启可能弹、已是最新版时不弹，故必须"看到才处理"。

会话身份是认领来的：opencode 不接受"用我给的 id 建会话"，只接受 ``-s`` 续接，
而会话行在首轮提交那一刻才建。所以认领的**起算点**锚在提交之前，而认领这个动作
本身贯穿整轮：提交后试一次，之后每次完成探针再试一次，会话行什么时候出现就什么
时候认到。认不到 NEVER 让本轮失败、NEVER 影响补发 Enter 的决定。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from frago.agent_driver.driver import (
    AgentDriver,
    CompletionVerdict,
    ExceptionHandler,
    LaunchCtx,
    PaneMatcher,
    register_driver,
)
from frago.agent_driver.tmux_session import TmuxAgentSession
from frago.session import opencode_store

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

    from frago.init.profile_manager import APIProfile
    from frago.session.parser import ParsedRecord

logger = logging.getLogger(__name__)

# 就绪：输入框自身的页脚行 "┃  Build · <model> <provider>"（行首框线、不带耗时），
# 全新会话与 ``opencode -s`` 续接回放后都在；并列保留占位提示 "Ask anything"，它只在
# 输入框从未被用过时出现。MUST 不匹配完成行 "▣ Build · <model> · 1.7s"。
_READY = PaneMatcher(
    name="opencode-ready",
    pattern=r"(?m)^\s*┃\s*Build\s*·|Ask anything",
)
# 完成（屏幕退路）：底部 "▣ Build · <model> · 3.7s" 页脚带耗时。
_DONE = PaneMatcher(name="opencode-done", pattern=r"▣\s*Build\b.*·\s*[\d.]+s")
# 忙碌：页脚的中断提示 ``esc interrupt``（伴随进度块）。当前 driver 契约没有忙碌
# 槽位——完成判定走会话库探针，不需要靠"忙碌消失"反推——故只记录不接线。
# 启动期 Update 模态。
_UPDATE_MODAL = PaneMatcher(name="opencode-update", pattern=r"(?i)\bUpdate\b.*available")

# 授权框的两个结构特征。opencode 的权限询问是个模态三选一菜单，标题文案随权限
# 类型变（实测四种措辞互不相同：``Access external directory ~/...`` /
# ``Allow opencode to access this directory`` / ``external directory access
# required`` / ``Grant permission to edit files outside``），只有框本身的骨架稳定，
# 故只认骨架、NEVER 认某一句自然语言措辞：
#   ① 标题行 ``△ Permission required``——图标与其后的说明都会变，``Permission
#      required`` 这个词组是稳定的；
#   ② 选项行三个动作同屏出现：``Allow once`` / ``Allow always`` / ``Reject``——
#      三选一菜单的结构特征，散文里不会三个一起冒出来。
# 任一命中即判 needs_input。20260726 现场：一个跨目录授权框没被认出来，本轮空等
# 满 600 秒超时才返回，且超时文本读不出发生了什么——十分钟静默黑洞。
#
# ``session_env`` 已预放行编辑 / 命令执行 / 网络抓取 / 跨目录访问四类，覆盖范围内
# 不会再弹这个框；覆盖不到的类型（opencode 将来新增的权限档、用户配置显式 deny
# 的路径）仍会弹，届时 MUST 秒级返回而不是空等。
_PERMISSION_TITLE = r"Permission\s+required"
_PERMISSION_MENU = r"(?=[\s\S]*Allow\s+once)(?=[\s\S]*Allow\s+always)(?=[\s\S]*Reject)"

# 阻断门 needs_input：撞上即判本轮为 needs_input，把"需要你介入"投递回调用方，
# 不静默挂到超时。只认带明确失败语义的组合——NEVER 放裸 ``login`` / ``sign in``
# 这类良性提示词，它们会出现在启动横幅与普通答案正文里，当帧误判会让本轮在刚
# 提交时就以 needs_input 提前返回（claude 侧 20260717 已实证过这个坑）。
_NEEDS_INPUT = PaneMatcher(
    name="opencode-needs-input",
    pattern=(
        r"(?i:invalid api key|api key.*(?:invalid|expired)"
        r"|not\s+logged\s+in|unauthorized|authentication\s+failed"
        r"|credit balance is too low|insufficient\s+(?:credit|balance|quota)"
        r"|please\s+(?:run\s*/?login|log\s*in|sign\s+in\s+to\s+continue)"
        rf"|{_PERMISSION_TITLE}|{_PERMISSION_MENU})"
    ),
)

_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|▣\s*Build|>\s*$|Ask anything)",
)

# 认领 NEVER 用固定窗口——这条是用真实 opencode 1.18.0 量出来的，不是推测。
#
# 实测「按下回车 → 会话行出现在会话库」的延迟：31 字 0.4 秒，2176 字 4.8 秒，
# 3519 字 **33 秒**。延迟主要花在首轮的两次 frago-hook 注入上（每次外调二进制），
# 随提示词长度与钩子耗时浮动，没有哪个固定秒数是安全的：曾用 20 拍 × 0.3 秒 = 6 秒，
# 3519 字那一例差 27 秒；改成 30 秒，同一例仍差 3 秒。继续调大只是接着赌。
#
# 超窗一次的完整后果（有现场日志为证）：认不到 → 没有绑定 → 完成探针全程弃权 →
# 本轮答案退回读屏 → 返回的是 TUI 的页脚与状态栏而不是模型的回答。
#
# 所以认领不再是"提交那一下的一锤子买卖"，改挂在整轮生命周期上：起算点锚在提交
# 之前（会话行必然晚于它）并按会话存下来，之后提交路径试一次、每次完成探针再试
# 一次——探针本来就在整轮里被反复调用，认领因此自然获得"整轮"这么长的机会窗口，
# 不需要任何固定时长。会话行 33 秒才出现也无妨：本轮跑到那之后的任何一拍都能认到。
#
# 认领的起算点：按会话记住"首次提交前一刻"的毫秒时间戳，供本轮后续各处复用。
# MUST 保留最早那个而不是每轮刷新——会话行是首轮提交那一刻建的，锚点往后挪就
# 再也罩不住它。认到之后立刻清掉；表随会话对象一起消亡（弱引用键），不留残留。
_CLAIM_ANCHORS: MutableMapping[TmuxAgentSession, int] = WeakKeyDictionary()

# Enter 发出后给 TUI 重绘留的结算时间（秒）与重发上限。
#
# opencode 的 TUI 有粘贴检测：紧随粘贴突发到达的 Enter 会被当成粘贴内容里的换行
# 而不是提交，整段文本滞留输入框。frago-hook 的注入让提示词很长，撞上的概率只会
# 更高——20260726 现场即是如此：``frago agent send`` 报"会话还没就绪"，而屏幕上
# 整段提示词还留在输入框里没提交。所以确实需要"确认不了就补发"这条退路。
#
# 但落地判定只认一个判据：**提示词的尾段还在不在输入框里**（``_still_in_input_box``）。
# 会话库那边等的东西（认领 / 本轮用户消息）延迟随提示词长度浮动到几十秒，拿它当
# 落地判据就是把上面那个赌局原样搬进提交路径；而输入框是本地渲染，一按回车就清空。
#
# 这里唯一等的是"按键处理 + 输入框重绘"——与提示词长度、钩子耗时都无关的一小段，
# 是真正有界的。留 2 秒是因为立刻抓屏可能撞上尚未重绘的那一帧，误判成"还卡着"而
# 补发一个空回车（它会落进下一轮，把下一次 send 变成什么都不返回）。框一空立刻返回，
# NEVER 死等满窗。全部重试之后仍看得见残留也不抛不卡，留一条 debug 日志、照常进入
# 完成轮询（那边有超时兜底）。
_INPUT_SETTLE_WINDOW_S = 2.0
_ENTER_RETRIES = 2

# 输入框区域的行首框线。opencode 的输入框每一行都以 ``┃`` 起头，消息区不带它——
# 而提交成功之后提示词会原样回显进消息区，所以判"文本还在不在框里"只准看这些行，
# 看整屏会把回显当成"还卡着"，一路补发空回车。
_INPUT_BOX_LINE = re.compile(r"^\s*┃(.*)$")

# 提示词尾段取多少字符（去空白后）。取尾不取头：长提示词在输入框里只露出末尾几行，
# 光标也停在那头；32 字够长到不会撞上界面文案，又短到不会跨出可见区。
_TAIL_CHARS = 32


def _bound_session_id(session: TmuxAgentSession) -> str | None:
    """该会话对应的 opencode 原生会话 id；未认领时 None。

    ``native_session_id`` 为真表示调用方给的就是 opencode 原生 id，直接用，
    不查映射。
    """
    if session.native_session_id:
        return session.session_id
    return opencode_store.get_binding(session.session_id)


def _launch(ctx: LaunchCtx) -> str:
    """启动命令。发 ``-s`` 之前先确认那个会话在库里还在。

    用户在 opencode 里删掉会话后，``opencode -s <已删除 id>`` 会立刻打印
    ``Error: Session not found`` 并退出：就绪信号永不出现，本轮等满超时才失败，
    而绑定还在文件里——下次启动再走一遍同一条死路，该 frago 会话就此永久不可用。
    所以这里自愈：会话没了就清掉绑定、改为裸起（spec 的 Edge Cases 要求）。
    ``session_exists`` 在库不可读时返回 True，故读失败 NEVER 误清好绑定。
    """
    # native：调用方给的就是 opencode 原生会话 id，直接续接、跳过映射查询。
    # 原生 id 同样可能已被删除，故一并检查；但 native 情况 NEVER 写映射文件。
    if ctx.native_session_id:
        if opencode_store.session_exists(ctx.session_id):
            return f"opencode -s {ctx.session_id}"
        return "opencode"
    bound = opencode_store.get_binding(ctx.session_id)
    if bound:
        if opencode_store.session_exists(bound):
            return f"opencode -s {bound}"
        opencode_store.drop_binding(ctx.session_id)
    # 尚未认领过 / 绑定已失效：裸起。会话行会在首轮提交那一刻由 opencode 自己建。
    return "opencode"


def _dismiss_update_modal(session: TmuxAgentSession) -> None:
    session.send_keys("Escape")


def _poll_until(
    session: TmuxAgentSession, probe: Callable[[], bool], window_s: float
) -> bool:
    """在时间窗内反复问 ``probe``，成立即刻返回 True；窗满仍不成立返回 False。

    按截止时间轮询而不是数拍数：拍数隐含"每拍耗时固定"的假设，抓一次屏的耗时并不
    固定。至少问一次，NEVER 因为窗口是 0 就一次都不问。
    """
    deadline = session._clock() + window_s
    while True:
        if probe():
            return True
        if session._clock() >= deadline:
            return False
        session._sleep(session._poll_interval_s)


def _remember_claim_anchor(session: TmuxAgentSession, since_ms: int) -> None:
    """记下认领的起算点（首次提交前一刻）。已经记过就不动它。

    只保留最早那个：会话行是**首轮**提交那一刻建的，锚点往后挪就再也罩不住它。
    首轮认领失败时，第二轮沿用同一个锚点仍认得到——这正是"认领贯穿整轮乃至后续
    各轮"要的效果。
    """
    _CLAIM_ANCHORS.setdefault(session, since_ms)


def _claim_once(session: TmuxAgentSession) -> str | None:
    """认领动作本身：一次廉价尝试（单次只读查询，不轮询、不阻塞）。

    这是**副作用**，不是判定。返回值只是把刚落盘的那个 id 顺手递出来省一次读文件，
    NEVER 拿它当"本轮是否落地"的判据——认不到只说明会话行还没写进库，与那一次
    Enter 有没有落地毫不相干（历史教训见 ``_submit``）。

    已有身份（native / 已落盘绑定）时直接返回 None、一次库都不查：映射一旦建立就
    不再重认，重认会让两个会话的记录互串。整条路径全程吞异常——映射文件不可写、
    库被独占都只是"这次没认到"，NEVER 逸出去影响本轮。
    """
    try:
        if session.native_session_id:
            return None
        if opencode_store.get_binding(session.session_id) is not None:
            return None
        since_ms = _CLAIM_ANCHORS.get(session)
        if since_ms is None:
            # 还没提交过：会话行尚不存在，此刻去认只会认到别人的会话。
            return None
        claimed = opencode_store.claim_session(session.cwd, since_ms)
        if not claimed:
            return None
        opencode_store.put_binding(session.session_id, claimed, session.cwd)
    except Exception:
        logger.debug("opencode claim attempt raised", exc_info=True)
        return None
    _CLAIM_ANCHORS.pop(session, None)
    logger.debug(
        "opencode claimed session %s for %s", claimed, session.session_id
    )
    return claimed


def _tail_marker(prompt: str) -> str:
    """提示词末尾的可判别尾段（去掉全部空白）。空提示词得到空串。

    去空白是因为输入框会按框宽折行，同一段文字在屏幕上被框线和换行切开，原样比对
    永远对不上。
    """
    return "".join(prompt.split())[-_TAIL_CHARS:]


def _input_box_text(pane: str) -> str:
    """把 pane 里输入框那几行拼成一条去空白的字符串（消息区的回显不算）。"""
    parts = [
        m.group(1) for line in pane.splitlines() if (m := _INPUT_BOX_LINE.match(line))
    ]
    return "".join("".join(part.split()) for part in parts)


def _still_in_input_box(session: TmuxAgentSession, tail: str) -> bool:
    """提示词是否**确实**还卡在输入框里——补发 Enter 的唯一许可。

    补发的前提 MUST 是正面证据：只有在输入框区域里重新看见提示词的尾段才补发。
    看不见（框已空 / 抓屏失败 / 屏上根本找不到输入框）一律判为不该补发——那一刻
    最可能的真相是提交早就成功了，此时补发的 Enter 打在空输入框上，会变成一个空
    提交落进下一轮，把下一次 ``send`` 变成什么都不返回。20260726 现场即是如此：
    认领超窗被当成"回车没落地"，补发两次，下一轮空转。
    """
    if not tail:
        return False
    try:
        pane = session.capture_pane()
    except Exception:
        logger.debug("opencode input-box check could not capture pane", exc_info=True)
        return False
    return tail in _input_box_text(pane)


def _prompt_stuck_in_box(session: TmuxAgentSession, tail: str) -> bool:
    """给 TUI 重绘留出结算时间之后，提示词是否**确实**还卡在输入框里。

    这是补发 Enter 的唯一判据，也是本轮"提交是否落地"的唯一判据。框一空立刻返回
    False（已落地），NEVER 死等满窗；窗满仍看得见尾段才判 True。
    """
    return not _poll_until(
        session,
        lambda: not _still_in_input_box(session, tail),
        _INPUT_SETTLE_WINDOW_S,
    )


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    # 认领的起算点 MUST 锚在提交动作之前：会话行是提交那一刻才建的，锚晚了会错过它。
    # 存进 _CLAIM_ANCHORS 供本轮后续各处（完成探针）复用，认领因此不必在这里等。
    _remember_claim_anchor(session, int(time.time() * 1000))
    session.send_text(prompt)
    # 重抓确认文本进框（渲染时序），未进框再补发一次文本。
    if prompt.strip() and prompt.strip() not in session.capture_pane():
        session.send_text(prompt)
    # 单次 Enter 即提交；多敲一次会落进下一轮输入框，所以只在**确认文本还卡在输入框
    # 里**时才重发。判据只有这一个，与认领彻底解耦：认领等的是会话库，那边的延迟随
    # 提示词长度浮动到几十秒，掺进来就会把"库还没写完"误判成"回车没落地"，补发的空
    # 回车落进下一轮，下一次 send 什么都不返回（20260726 现场）。
    tail = _tail_marker(prompt)
    landed = False
    for attempt in range(1 + _ENTER_RETRIES):
        session.send_keys("Enter")
        if not _prompt_stuck_in_box(session, tail):
            landed = True
            break
        logger.debug(
            "opencode prompt still in input box after enter #%d; resending "
            "(session=%s)",
            attempt + 1,
            session.session_id,
        )
    # 顺手认一次领：短提示词的会话行这时往往已经写进库了，认到就省得等到探针那一拍。
    # 认不到什么也不做——整轮里每次完成探针都会再试，会话行几十秒后才出现也罩得住。
    _claim_once(session)
    if not landed:
        # 全部重试之后提示词仍卡在框里：不抛不卡，交给完成轮询的超时兜底。这条日志是
        # 事后排查"整段提示词滞留输入框"的唯一线索，NEVER 静默走掉。
        logger.debug(
            "opencode submit unconfirmed after %d enters; falling through to "
            "completion polling (session=%s)",
            1 + _ENTER_RETRIES,
            session.session_id,
        )


# 本轮已终结、但聚合出来的正文是空的。真实现场：OpenRouter 因认证头配错被拒，模型
# 零产出，那条助手消息带完成时刻、结束标记是 ``unknown``、文本为空。
#
# 这一轮判 ``needs_input`` 而不是 ``error``：``error`` 在本层的既有语义是"driver /
# tmux 这条链路自己坏了"（会话中途消失、投喂退非零），而这里链路全程正常，坏的是
# 凭据或 provider 的接纳，得由真人去改 profile 才走得下去——与本 driver 已有的
# ``_NEEDS_INPUT`` 屏幕门（invalid api key / unauthorized / 余额不足）是同一类失败，
# 只是这一次它没往屏幕上打字。同一个根因 NEVER 因为可见与否落到两个状态上。
_EMPTY_ANSWER_NOTE = (
    "本轮结束但没有任何输出，通常是鉴权失败或 provider 拒绝。\n"
    "请检查这条 profile 的密钥与认证方式（自定义端点里 OpenRouter 这类要求 "
    "Authorization: Bearer，密钥头不被接受），以及账户余额与模型可用性。"
)


def _completion_probe(session: TmuxAgentSession) -> CompletionVerdict | None:
    """权威完成探针：读 opencode 会话库判本轮是否答完 + 取终答；顺手认领。

    尚无绑定时先做**一次**廉价认领尝试再判。探针在整轮里被反复调用，认领因此获得
    "整轮"这么长的机会窗口——会话行 33 秒才出现也不要紧，出现之后的下一拍就认到、
    落盘、继续走权威判定，不必赌任何固定窗口。认不到就返回 None，由 driver 当帧
    退回屏幕信号，本轮照常跑完。

    完成判据在 ``opencode_store.latest_turn`` 里：本轮存在带完成时刻、且结束标记不是
    ``tool-calls`` 的助手消息。中途的 ``tool-calls`` 段一律不算答完，否则只是把屏幕
    误判换成数据库误判。

    答完但一个字都没产出时，本轮判为 ``needs_input``（理由见 ``_EMPTY_ANSWER_NOTE``），
    NEVER 以成功姿态返回一个空字符串。
    """
    sid = _bound_session_id(session)
    if sid is None:
        sid = _claim_once(session)
    if sid is None:
        return None
    turn = opencode_store.latest_turn(sid)
    if turn is None:
        return None
    if not turn.done:
        return CompletionVerdict(done=False, text=None, marker=turn.final_message_id)
    if not turn.text.strip():
        logger.warning(
            "opencode turn finished with no output (session=%s, message=%s)",
            sid,
            turn.final_message_id,
        )
        return CompletionVerdict(
            done=True,
            text=_EMPTY_ANSWER_NOTE,
            marker=turn.final_message_id,
            status="needs_input",
        )
    return CompletionVerdict(done=True, text=turn.text, marker=turn.final_message_id)


class OpencodeTranscriptSource:
    """opencode 的记录来源：会话库里的片段流（spec 20260725 Phase 2）。

    claude 那套"文件 + 字节偏移"在这里不成立，取增量靠片段游标
    ``(time_updated, part_id)``——opencode 先插空壳片段再把内容 UPDATE 进去，游标
    建在创建时间上只能看见空壳。代价是同一个片段会被反复取回，故本类自带一本
    ``_ledger``（随实例生命周期，不落盘）记"这个片段已经发过什么"：文本记已发长度、
    只发新追加的那一段，工具记调用与结果两条各自发没发过。

    片段翻成 ``ParsedRecord`` 的规则：

    - assistant 的 ``text`` 片段 → 一条文本记录（内容是相对上次的增量）；
    - ``synthetic`` 为真的 ``text`` 片段 → **丢弃**。那是 opencode 自己注入的编辑器
      上下文（实测只挂在 user 消息上，这里防御性地一并过滤），不是答案，混进流里
      等于把注入回显重新捡回来；
    - ``tool`` 片段 → 一条带 ``tool_calls`` 的记录；该片段已进完成态时再追一条带
      ``tool_results`` 的记录，前端因此能先亮出"在调什么"再补上结果；
    - ``reasoning`` / ``step-start`` / ``step-finish`` / 其他 → 丢弃。

    未认领会话 id 时 ``poll_once`` 返回空列表——上层轮询循环据
    ``native_session_id is None`` 退避，认领成功后自然接上。
    """

    def __init__(self, session: TmuxAgentSession) -> None:
        self._session = session
        self._cursor: opencode_store.PartCursor | None = None
        self._ledger = _PartLedger()
        self._adapter: Any | None = None
        self._adapter_resolved = False

    @property
    def native_session_id(self) -> str | None:
        return _bound_session_id(self._session)

    def _get_adapter(self) -> Any | None:
        """解析交给 ``session.monitor`` 的 opencode adapter，本类只做形状归一化。"""
        if self._adapter_resolved:
            return self._adapter
        self._adapter_resolved = True
        from frago.session.models import AgentType
        from frago.session.monitor import get_adapter

        self._adapter = get_adapter(AgentType.OPENCODE)
        return self._adapter

    def seek_to_end(self) -> None:
        """锚基线：把游标推到该会话当前最末一个片段。

        尚未认领会话 id 时什么也不做——此时会话行还不存在（首轮提交那一刻才建），
        没有历史可跳过。NEVER 在这里"等认领成功再锚"：那会把首轮的答案一起跳掉。

        基线锚的是**更新时间**：历史片段只要不再被改写就不会回流。万一 opencode
        回头更新了一条老片段（例如补写 usage），簿记里没有它的记账，会把它当新内容
        发一次——这个取舍可以接受，比漏掉正在流式写入的正文安全。
        """
        sid = self.native_session_id
        if sid is None:
            return
        self._cursor = opencode_store.latest_cursor(sid)
        # 基线那一刻的片段会被 ``>=`` 再取回一次，先空转一拍把它们记进账本，
        # 否则续接既有会话时最末那条历史会当新内容重播一遍。
        items, self._cursor = opencode_store.parts_since(sid, self._cursor)
        for item in items:
            _normalize_part(item, sid, self._ledger)

    def poll_once(self) -> list[ParsedRecord]:
        """取自上次以来的新增片段并翻成记录。未认领 / 读失败时空列表，NEVER 抛。"""
        sid = self.native_session_id
        if sid is None:
            return []
        adapter = self._get_adapter()
        if adapter is None:
            return []
        items, self._cursor = opencode_store.parts_since(sid, self._cursor)
        records: list[ParsedRecord] = []
        for item in items:
            for payload in _normalize_part(item, sid, self._ledger):
                try:
                    record = adapter.parse_record(payload)
                except Exception:
                    logger.debug("opencode adapter.parse_record raised", exc_info=True)
                    continue
                if record is not None:
                    records.append(record)
        return records


class _PartLedger:
    """"这个片段已经发过什么"的账本。游标改按更新时间取增量后的重复抑制器。

    只活在来源实例的生命周期里，不落盘——重启后重新锚基线，本来就不该续用旧账。
    """

    def __init__(self) -> None:
        self._text: dict[str, str] = {}
        self._text_seq: dict[str, int] = {}
        self._tool_call: set[str] = set()
        self._tool_result: set[str] = set()

    def text_delta(self, part_id: str, text: str) -> tuple[str, int]:
        """这次该发的那一段文本，以及它是这个片段的第几次投递；没有新内容时文本为空。

        opencode 流式写入是往后追加，故常态下只发"当前文本减去已发部分"。若当前文本
        比记录的短、或前缀对不上（那是重写而不是追加），整段重发并刷新记录——宁可
        前端看见一次重复，也不能把改写后的正文吞掉。

        次序号用来给每段增量配一个互不相同的 uuid：同一片段发多条记录时 uuid 撞了，
        前端按 uuid 去重会把后面的段吃掉。
        """
        sent = self._text.get(part_id, "")
        if text == sent:
            return "", 0
        delta = text[len(sent) :] if text.startswith(sent) else text
        self._text[part_id] = text
        seq = self._text_seq.get(part_id, 0)
        self._text_seq[part_id] = seq + 1
        return delta, seq

    def claim_tool_call(self, part_id: str) -> bool:
        """调用事件是否轮到这次发（第一次看见时为真）。"""
        if part_id in self._tool_call:
            return False
        self._tool_call.add(part_id)
        return True

    def claim_tool_result(self, part_id: str) -> bool:
        """结果事件是否轮到这次发（首次进完成态时为真）。"""
        if part_id in self._tool_result:
            return False
        self._tool_result.add(part_id)
        return True


def _normalize_part(
    item: dict[str, Any], session_id: str, ledger: _PartLedger
) -> list[dict[str, Any]]:
    """把一个片段翻成 0~2 份归一化记录字典（adapter 的入参形状）。

    翻译规则本身住在 ``session.opencode_store``——归档同步要按同一套规则读同一个库，
    而 ``session/`` 不许依赖 ``agent_driver/``，所以规则只能落在下层。这里加的是
    **流式特有的那一层**：同一个片段会被游标反复取回，账本决定这次该发什么。
    """
    part_id = item["part_id"]
    records: list[dict[str, Any]] = []
    for kind, payload in opencode_store.part_payloads(item, session_id):
        if kind == opencode_store.PART_TEXT:
            # 流式常态是往后追加，只发相对上次的增量；uuid 带上次序号，否则同一片段
            # 的多段增量 uuid 撞车，前端按 uuid 去重会把后面的段吃掉。
            delta, seq = ledger.text_delta(part_id, payload["content"])
            if not delta:
                continue
            uuid = part_id if seq == 0 else f"{part_id}:{seq}"
            records.append({**payload, "uuid": uuid, "content": delta})
        elif kind == opencode_store.PART_TOOL_CALL:
            if ledger.claim_tool_call(part_id):
                records.append(payload)
        elif kind == opencode_store.PART_TOOL_RESULT:
            if ledger.claim_tool_result(part_id):
                records.append(payload)
    return records


def _transcript_source(session: TmuxAgentSession) -> OpencodeTranscriptSource:
    return OpencodeTranscriptSource(session)


# frago 注入的 provider 键。取一个不会与用户自己配置撞名的名字：注入配置与用户全局
# 配置是**合并**关系（实测确认），撞名会静默改写用户的 provider 定义。
_FRAGO_PROVIDER = "frago-profile"

# 权限放行：claude 的 ``--dangerously-skip-permissions`` 在 opencode 没有等价启动
# 开关，只能经会话级配置声明。不放行的话，无人值守时第一次写文件 / 跑命令就会弹
# 权限询问，本轮永不返回。放行只作用于这一个 tmux 会话（环境变量作用域），用户的
# ``~/.config/opencode/opencode.json`` 一个字不改。
#
# ``external_directory`` 是第四类，容易漏：工作目录之外的读写单独走这一档。agent
# 的 cwd 是被驱动的那个仓库，而产出常落在 ``~/.frago`` 下（recipe、data、viewer），
# 不放行就在第一次碰配方目录时弹框卡死。它的值是 glob → 决策的映射，不是裸字符串。
_PERMISSION_ALLOW = {
    "edit": "allow",
    "bash": "allow",
    "webfetch": "allow",
    "external_directory": {"*": "allow"},
}


def _base_config() -> dict[str, Any]:
    """注入配置的基线：只有权限放行。"""
    return {"permission": dict(_PERMISSION_ALLOW)}


def _session_env(_ctx: LaunchCtx) -> dict[str, str]:
    """opencode 起会话的基线环境变量：权限放行（与 profile 无关）。

    ``profile_env`` 产出同一个变量，由调用方注入后天然覆盖这份基线，故那边 MUST
    自己也带上权限放行，NEVER 依赖合并。
    """
    return {"OPENCODE_CONFIG_CONTENT": json.dumps(_base_config())}


def _profile_env(profile: APIProfile) -> dict[str, str]:
    """把一条 profile 翻成 opencode 的注入配置。

    provider 用 Anthropic 兼容的 SDK（profile 的端点本就是 Anthropic 协议端点），
    ``baseURL`` / ``apiKey`` 进 ``options``；认证头的选择走 ``resolve_auth_style``
    这个公共出口——判定为授权头时额外在 ``options.headers`` 里放
    ``Authorization: Bearer <key>``，密钥头端点则不放（SDK 自己发 ``x-api-key``）。

    模型只映射两档：主模型 → 顶层 ``model``，快模型 → ``small_model``。profile 的
    中档（sonnet）模型 **不映射**——那是 claude 的三档分层策略，opencode 没有这个
    概念（spec 已定）。profile 没有主模型时不设 ``model``，只提供 provider，模型仍
    听 opencode 自己的配置。

    权限放行必须自带：本函数的产出会覆盖 ``session_env`` 的同名变量。
    """
    from frago.init.configurator import (
        AUTH_STYLE_AUTH_TOKEN,
        PRESET_ENDPOINTS,
        resolve_auth_style,
    )

    base_url = profile.url
    if not base_url:
        preset = PRESET_ENDPOINTS.get(profile.endpoint_type, {})
        base_url = preset.get("ANTHROPIC_BASE_URL")

    options: dict[str, Any] = {"apiKey": profile.api_key}
    if base_url:
        options["baseURL"] = base_url
    # 密钥与端点 URL 一并交给公共出口：自定义端点没有预设声明可查，认证方式靠
    # 密钥前缀 / 主机名这两类结构化依据推断（OpenRouter 只认授权头，漏判就是零产出）。
    auth_style = resolve_auth_style(
        profile.endpoint_type, api_key=profile.api_key, url=base_url
    )
    if auth_style == AUTH_STYLE_AUTH_TOKEN:
        options["headers"] = {"Authorization": f"Bearer {profile.api_key}"}

    # provider 里必须逐个声明会被引用的模型：只给 npm/options 而不给 models，
    # opencode 解析不出 `frago-profile/<模型名>`，会**静默回退**到用户自己配的
    # provider（模型名相同时页脚都看不出异常）。引用与声明 MUST 配套。
    models: dict[str, dict[str, Any]] = {}
    if profile.default_model:
        models[profile.default_model] = {}
    if profile.haiku_model:
        models[profile.haiku_model] = {}

    provider: dict[str, Any] = {
        "npm": "@ai-sdk/anthropic",
        "options": options,
    }
    if models:
        provider["models"] = models

    config = _base_config()
    config["provider"] = {_FRAGO_PROVIDER: provider}
    if profile.default_model:
        config["model"] = f"{_FRAGO_PROVIDER}/{profile.default_model}"
    if profile.haiku_model:
        config["small_model"] = f"{_FRAGO_PROVIDER}/{profile.haiku_model}"
    return {"OPENCODE_CONFIG_CONTENT": json.dumps(config)}


def _extract(delta: str) -> str:
    lines = [ln for ln in delta.splitlines() if not _CHROME_LINE.match(ln)]
    return "\n".join(ln.strip() for ln in lines).strip()


register_driver(
    AgentDriver(
        agent_type="opencode",
        launch_command=_launch,
        ready_signal=_READY,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        needs_input_signal=_NEEDS_INPUT,
        completion_probe=_completion_probe,
        # attached 流式据此读会话库的片段增量（spec 20260725 Phase 2）。
        transcript_source=_transcript_source,
        # 起会话的基线：权限放行（spec 20260725 Phase 4）。
        session_env=_session_env,
        # profile → provider 定义 + 模型选择（同上）。
        profile_env=_profile_env,
        exception_handlers=[
            ExceptionHandler(
                name="dismiss-update-modal",
                trigger=_UPDATE_MODAL,
                action=_dismiss_update_modal,
            ),
        ],
    )
)
