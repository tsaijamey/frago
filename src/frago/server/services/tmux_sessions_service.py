"""本机 tmux agent 会话的清点与手动清理。

**为什么另起一份，而不是复用空闲回收那条巡检。** 服务端本来就有一条自动回收
（``ui_session_lifecycle`` + ``UiSessionRunner.evict_idle``），但它只认自己池子里
那些会话——池上限缺省 10 个，装的全是工作台亲手开的。飞书群会话、语音会话、
命令行 ``frago agent`` 起的那些，池子里没有它们的把手，巡检一个都碰不到。实测本机
15 个 tmux 会话共占 3.9 GB，其中大半属于后者，没有任何人回收。这份服务就是补这个
缺口：不问池子，直接问 tmux 本人有哪些会话，再逐个去它自己的记录里取状态。

**闲置时间一律取「最后一条终结记录的时间戳」，NEVER 取 tmux 的活动时间。**
这是实测换来的判据。tmux 的 ``session_activity`` 只在 attach/detach 一类事件上动，
detached 会话里 claude 刷了一整天屏它也不变；``window_activity`` 走另一个极端——
pane 上任何一个字变了它就往前跳，而 claude 的状态栏一直在刷 token 计数和五小时窗口
倒计时，那不是「有人在用」。同一批会话两个口径能差出四个多小时：某场最后一次真正
回答停在早上 7:10，窗口活动却报 23 分钟前。人要清的是「说完话之后就没人管了」的
会话，那个时刻只有会话自己的记录知道。

解析记录用的是既有探针 ``transcript_completion``：它返回的 ``last_terminal_ts``
字段旁边一直写着「idle clock anchor」，但在此之前全仓没有一个消费者。本模块是第一个。

**关闭逐条点名，NEVER kill-server。** 池内的会话交给池自己驱逐（池的内存状态得跟着
变，否则页面下次投喂会拿着一个已经死掉的把手去 send）；池外的才落到
``tmux kill-session -t <name>``。一条失败不影响其余，结果逐条回报。
"""

from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# tmux 会话名的前缀，与 ``agent_driver.tmux_session.tmux_name_for`` 同一套。
_PREFIX = "frago-agent-"

# 屏面底部 claude 自报的真实会话编号。**名字推不出编号时唯一的来源。**
# 工作台开的会话，tmux 名字里那截本身就是编号；而飞书群会话、语音会话的名字是
# ``feishu_oc_<聊天室 id>`` 这类业务把手，driver 起会话时按它派生一个 uuid5——实测
# 那个派生值在记录目录里根本不存在，claude 自己用的是另一个编号，只在屏上报出来。
_PANE_SID = re.compile(r"\bsid=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# 正文截取的缺省长度。**不写死在取数逻辑里**：够不够判断「这是哪一场会话」因人而异，
# 调用方（浮窗）可以按自己的行宽要一个不同的长度。
DEFAULT_EXCERPT_CHARS = 160

# 纯标题行（``**结论**``、``## 要点``、``---``）单独占一行时对认会话没有任何帮助，
# 截取要跳过它们，从第一句有内容的话开始。
#
# **认标题只认两种形状：``#`` 开头，或者整行被 ``*`` 包住。** 早先这里还按「短于
# 十几个字就算标题」判过，那条判据会把「已经删掉了。」这种六个字的正文一起吃掉——
# 短句恰恰是回答里最能说明问题的那一句，丢了它整行就空着。
_HEADING_ONLY = re.compile(r"^\s*(?:#{1,6}\s+\S.*|\*{1,2}[^*\n]+\*{1,2})\s*$")
_RULE_ONLY = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|─+)\s*$")

# 表格的分隔行（``|---|---|``）在一段纯文本里什么都不是，只占字数。
_TABLE_RULE = re.compile(r"^\s*\|?[\s|:-]+\|[\s|:-]*$")

# 行内的 markdown 标记。截取是一段纯文本，``**`` 和反引号在这里不加粗也不高亮，
# 只是把本来能多放几个字的位置占掉。
_INLINE_MARKS = re.compile(r"\*{1,2}|`+")


@dataclass
class TmuxSessionInfo:
    """浮窗里的一行。

    ``idle_secs`` 是「自最后一条终结记录起过了多久」；判不出来（找不到记录、
    那一轮还没终结）为 None，前端据此显示「—」而不是一个编出来的 0。
    """

    name: str  # tmux 会话名（关闭时点的就是它）
    label: str  # 去掉前缀后的那截，浮窗上显示的名字
    session_id: str | None  # 解出来的真实会话编号
    stop_reason: str | None
    last_stop_at: str | None  # ISO8601，最后一条终结记录的时刻
    idle_secs: float | None
    excerpt: str  # 最后一段回答的正文截取
    memory_mb: int
    busy: bool  # 屏上仍在干活（转轮 / 后台 shell 在跑）——批量关时必须排除
    managed: bool  # 是不是工作台那个池子管着的会话
    # 窗格前台跑的不是登录 shell（agent 还在）；问不出为 None
    client_alive: bool | None = None
    # 停在待输入态等人说下一句；判不出（不是 Claude Code、认不出是哪一场）为 None
    awaiting_input: bool | None = None
    # 收尾原话：保留句末，超长截开头。要的东西（问句、选项）多在句末
    closing_text: str = ""


@dataclass
class TmuxWaitingInfo:
    """「For you」要的那几项，给会话页每 15 秒问一次。

    与 ``TmuxSessionInfo`` 同源同判据，少了内存和截取——那两样只有人点开浮窗才要。
    """

    name: str
    session_id: str | None
    client_alive: bool | None
    awaiting_input: bool | None
    stop_reason: str | None
    last_stop_at: str | None
    closing_text: str


# 收尾原话留多长。前端还要从里面挑出问句那一句，给短了就挑不着。
CLOSING_CHARS = 600


def _tmux(*args: str) -> str:
    """跑一条 tmux 命令拿标准输出；失败返回空串（tmux 没起来也算「零个会话」）。"""
    try:
        proc = subprocess.run(
            ["tmux", *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("tmux %s failed: %s", args[:1], e)
        return ""
    return proc.stdout


def _session_names() -> list[str]:
    return [n for n in _tmux("list-sessions", "-F", "#{session_name}").splitlines() if n]


def _resolve_session_id(label: str, pane: str) -> str | None:
    """定出这场 tmux 会话对应哪一份记录。

    三个来源按可信度排：名字本身就是编号（工作台开的）→ 屏上自报的那行 →
    按业务把手派生的 uuid5（driver 起会话时用的那套规则）。挨个去记录目录里找，
    找到文件的那个才算数——派生值算得出来不等于那份记录存在。
    """
    candidates: list[str] = []
    if _UUID.match(label):
        candidates.append(label)
    m = _PANE_SID.search(pane)
    if m:
        candidates.append(m.group(1))
    try:
        from frago.agent_driver.drivers import claude as claude_driver

        candidates.append(claude_driver.claude_session_uuid(label))
    except Exception:  # noqa: BLE001 — 派生规则取不到只是少一个候选
        pass

    for sid in candidates:
        if _transcript_path(sid) is not None:
            return sid
    return candidates[0] if candidates else None


def _transcript_path(session_id: str) -> Path | None:
    """按编号在 claude 的记录目录里找那份 jsonl。

    跨全部工程目录扫，不假设会话的工作目录——飞书、语音那些会话的 cwd 与页面
    会话不在一处，钉死一个目录会把它们全判成「找不到记录」。
    """
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    return Path(hits[0]) if hits else None


def _excerpt(text: str, limit: int) -> str:
    """从最后一段回答里截出足以认出「这是哪一场」的那几句。

    先扔掉只有标题或分隔线的行——``**结论**`` 单独一行时，把它截进来等于什么都没说；
    再把剩下的正文压成一行，超长按字数截断并补省略号。
    """
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or _RULE_ONLY.match(line) or _TABLE_RULE.match(line):
            continue
        if not lines and _HEADING_ONLY.match(line):
            continue  # 开头的纯标题行跳过，从第一句有内容的话起算
        lines.append(line)
    body = _INLINE_MARKS.sub("", " ".join(lines)).strip()
    body = re.sub(r"\s{2,}", " ", body)
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + "…"


def _closing_text(text: str, limit: int = CLOSING_CHARS) -> str:
    """收尾原话：去掉标题行、分隔线和行内标记，**段落之间保留空行**，超长截开头。

    与 ``_excerpt`` 方向相反——那边认会话要开头，这边等人回话要结尾：「…A or B.」
    截掉了，人就不知道它在问什么。段落留着，前端才能分出「最后一段」。
    """
    paras: list[str] = []
    current: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or _RULE_ONLY.match(line) or _TABLE_RULE.match(line):
            if current:
                paras.append(" ".join(current))
                current = []
            continue
        if _HEADING_ONLY.match(line):
            continue
        current.append(line)
    if current:
        paras.append(" ".join(current))
    body = "\n\n".join(re.sub(r"\s{2,}", " ", _INLINE_MARKS.sub("", p)).strip() for p in paras)
    body = body.strip()
    if len(body) <= limit:
        return body
    return "…" + body[-limit:].lstrip()


def _pane_commands() -> dict[str, str]:
    """每场 tmux 会话窗格前台在跑什么，一条 ``list-panes`` 拿全。"""
    out: dict[str, str] = {}
    for line in _tmux(
        "list-panes", "-a", "-F", "#{session_name}\t#{pane_current_command}"
    ).splitlines():
        name, _, command = line.partition("\t")
        if name and name not in out:
            out[name] = command.strip()
    return out


def _client_alive(command: str | None) -> bool | None:
    """前台是不是登录 shell——是就说明 agent 已经退了。

    表与驱动 ``has_live_agent`` 用同一张 ``_SHELL_COMMANDS``：claude 把进程名改成自己
    的版本号（实测 ``2.1.281``），按「叫不叫 claude」判等于每升一版失灵一次。
    """
    if not command:
        return None
    from frago.agent_driver.tmux_session import _SHELL_COMMANDS

    return command not in _SHELL_COMMANDS


def _awaiting_input(pane_ansi: str, alive: bool | None) -> bool | None:
    """客户端退了就不可能在等人（False）；前台问不出就判不出（None）。"""
    if alive is not True:
        return None if alive is None else False
    try:
        from frago.agent_driver.drivers import claude as claude_driver

        return claude_driver.awaiting_input(pane_ansi)
    except Exception:  # noqa: BLE001 — 判不出就不挂，宁可漏挂也不误挂
        return None


def _plain(pane_ansi: str) -> str:
    try:
        from frago.agent_driver.drivers import claude as claude_driver

        return claude_driver.strip_ansi(pane_ansi)
    except Exception:  # noqa: BLE001
        return re.sub(r"\x1b\[[0-9;:?]*[A-Za-z]", "", pane_ansi)


# 记录判读的缓存：按（大小, 修改时刻）失效。「For you」每 15 秒问一次，十几场会话的
# 记录没变就不必每次整份重读——只有真的多写了一行，才重新判一次。
_VERDICT_CACHE: dict[str, tuple[tuple[int, float], tuple[str | None, str | None, str]]] = {}


def _transcript_tail(path: Path) -> tuple[str | None, str | None, str]:
    """(stop_reason, last_stop_at, 最后一段回答全文)，带缓存。"""
    from frago.session import transcript_completion as tc

    try:
        st = path.stat()
    except OSError:
        return None, None, ""
    key = (st.st_size, st.st_mtime)
    hit = _VERDICT_CACHE.get(str(path))
    if hit is not None and hit[0] == key:
        return hit[1]
    stop_reason: str | None = None
    last_stop_at: str | None = None
    text = ""
    try:
        verdict = tc.evaluate_file(path)
        stop_reason = verdict.stop_reason
        if verdict.done and verdict.last_terminal_ts is not None:
            last_stop_at = verdict.last_terminal_ts.isoformat()
        text = verdict.final_text or ""
        if not text.strip():
            text = _last_assistant_text(path)
    except Exception as e:  # noqa: BLE001 — 一份记录读坏不该让整张清单开天窗
        logger.debug("transcript probe failed for %s: %s", path, e)
    value = (stop_reason, last_stop_at, text)
    _VERDICT_CACHE[str(path)] = (key, value)
    return value


def list_waiting() -> list[TmuxWaitingInfo]:
    """「For you」那三条判据要的全部：开在 tmux 里、客户端活着、停在待输入态。

    **awaiting_input 只对认得出记录的 Claude Code 会话判。** opencode、codex、
    codebuddy 的会话在 ``~/.claude/projects`` 里没有记录，非 frago 起的 tmux 解不出
    编号——这些一律给 None，前端一律不挂。判不出宁可漏挂，也不拿 claude 的判据去套
    别家的界面。
    """
    names = _session_names()
    commands = _pane_commands()
    rows: list[TmuxWaitingInfo] = []
    for name in names:
        if not name.startswith(_PREFIX):
            alive = _client_alive(commands.get(name))
            rows.append(TmuxWaitingInfo(name, None, alive, None, None, None, ""))
            continue
        pane_ansi = _tmux("capture-pane", "-p", "-e", "-t", name)
        session_id = _resolve_session_id(name[len(_PREFIX) :], _plain(pane_ansi))
        path = _transcript_path(session_id) if session_id else None
        alive = _client_alive(commands.get(name))
        if path is None:
            rows.append(TmuxWaitingInfo(name, session_id, alive, None, None, None, ""))
            continue
        stop_reason, last_stop_at, text = _transcript_tail(path)
        rows.append(
            TmuxWaitingInfo(
                name=name,
                session_id=session_id,
                client_alive=alive,
                awaiting_input=_awaiting_input(pane_ansi, alive),
                stop_reason=stop_reason,
                last_stop_at=last_stop_at,
                closing_text=_closing_text(text),
            )
        )
    return rows


def _last_assistant_text(path: Path) -> str:
    """往回翻，找最近一段有正文的回答。

    只在探针给不出正文时用。**正在干活的那一轮往往没有一个字**：最后一条记录是
    一次工具调用，探针照实返回空正文。可浮窗上那一行要是空的，人就认不出这是哪一场
    会话——而认出来正是他打开这个浮窗的目的。往回找到的那段文字仍然是这场会话自己
    说过的话，够用来认人。
    """
    import json

    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if record.get("type") != "assistant":
            continue
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        text = " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if text:
            return text
    return ""


def _memory_mb() -> dict[int, int]:
    """一次 ps 建好「进程 → 自己及全部后代的常驻内存」的表。

    **按进程树算，不按进程组。** pane 里那个 shell 自己只有一两兆，claude 是它的
    子进程、单个二三百兆——照进程组统计会把每场会话报成 2 MB，看上去无事发生。
    """
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    rss: dict[int, int] = {}
    children: dict[int, list[int]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            pid, ppid, kb = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        rss[pid] = kb
        children.setdefault(ppid, []).append(pid)

    def total(root: int) -> int:
        seen: set[int] = set()
        stack = [root]
        acc = 0
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            acc += rss.get(pid, 0)
            stack.extend(children.get(pid, ()))
        return acc

    return {pid: round(total(pid) / 1024) for pid in rss}


def _pane_pids() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for line in _tmux("list-panes", "-a", "-F", "#{session_name} #{pane_pid}").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            out.setdefault(parts[0], []).append(int(parts[1]))
        except ValueError:
            continue
    return out


def _is_busy(pane: str) -> bool:
    """屏上还在干活吗——转轮在转、或者派出去的后台 shell 还没回来。

    批量关之前必须问这一句。**光看「上次回答在几小时前」会误杀刚点开的旧会话**：
    工作台 resume 一场昨天的会话时，它的记录最后一条本来就是昨天的，闲置时长天然
    超过任何阈值，而那一刻它正在重建、马上就要接着干。这个坑自动回收那条路踩过，
    注释记在 ``ui_session_runner._idle_age`` 里。
    """
    try:
        from frago.agent_driver.drivers import claude as claude_driver

        if claude_driver._SHELL_RUNNING.search(pane) is not None:
            return True
        if claude_driver._BUSY.search(pane) is not None:
            return True
        return claude_driver._WORKING.matches(pane)
    except Exception:  # noqa: BLE001 — 判不出忙就当忙，宁可少关一个也不误杀
        return True


def _managed_ids() -> set[str]:
    """工作台那个池子此刻管着哪些会话编号。"""
    try:
        from frago.server.services.ui_session_runner import get_runner

        return {str(sid) for sid in get_runner()._pool.active_ids()}
    except Exception:  # noqa: BLE001 — 问不到就当都不归池管，关闭时走 tmux 那条路
        return set()


def list_sessions(*, excerpt_chars: int = DEFAULT_EXCERPT_CHARS) -> list[TmuxSessionInfo]:
    """清点本机全部 frago tmux 会话，按闲置由久到近排。

    ``excerpt_chars`` 决定正文截多长——够不够认出会话由调用方定，这里不写死。
    """
    from frago.session import transcript_completion as tc

    names = _session_names()
    pids = _pane_pids()
    mem = _memory_mb()
    managed = _managed_ids()
    commands = _pane_commands()
    now = time.time()

    rows: list[TmuxSessionInfo] = []
    for name in names:
        # 非 frago 起的 tmux 会话照常清点（人要知道本机一共几个），只是编号解不出、
        # 记录读不到，那一行上除了名字和内存没有别的可说。
        label = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name

        # 带颜色读一次：纯文字给认编号、判忙用，颜色留给「停在待输入态」那一问
        pane_ansi = _tmux("capture-pane", "-p", "-e", "-t", name)
        pane = _plain(pane_ansi)
        session_id = _resolve_session_id(label, pane) if name.startswith(_PREFIX) else None
        alive = _client_alive(commands.get(name))

        stop_reason: str | None = None
        last_stop_at: str | None = None
        idle_secs: float | None = None
        excerpt = ""
        closing = ""
        awaiting: bool | None = None
        if session_id:
            path = _transcript_path(session_id)
            if path is not None:
                # 认得出记录才是 Claude Code 会话，才套它的就绪判据
                awaiting = _awaiting_input(pane_ansi, alive)
                try:
                    verdict = tc.evaluate_file(path)
                    stop_reason = verdict.stop_reason
                    if verdict.done and verdict.last_terminal_ts is not None:
                        last_stop_at = verdict.last_terminal_ts.isoformat()
                        idle_secs = max(0.0, now - verdict.last_terminal_ts.timestamp())
                    text = verdict.final_text or ""
                    if not text.strip():
                        text = _last_assistant_text(path)
                    excerpt = _excerpt(text, excerpt_chars)
                    closing = _closing_text(text)
                except Exception as e:  # noqa: BLE001 — 一份记录读坏不该让整张清单开天窗
                    logger.debug("transcript probe failed for %s: %s", session_id, e)

        rows.append(
            TmuxSessionInfo(
                name=name,
                label=label,
                session_id=session_id,
                stop_reason=stop_reason,
                last_stop_at=last_stop_at,
                idle_secs=idle_secs,
                excerpt=excerpt,
                memory_mb=sum(mem.get(p, 0) for p in pids.get(name, ())),
                busy=_is_busy(pane),
                managed=bool(session_id and session_id in managed),
                client_alive=alive,
                awaiting_input=awaiting,
                closing_text=closing,
            )
        )

    # 闲得最久的排最前——那是人来这个浮窗要找的东西。判不出闲置的排在最后。
    rows.sort(key=lambda r: (r.idle_secs is None, -(r.idle_secs or 0.0)))
    return rows


def count_sessions() -> dict:
    """只数个数和内存，不碰任何一份记录。

    左下角那个数字每分钟要刷一次。走完整清点的话，每次都得把十几份 jsonl 整个读一遍
    ——那些文件动辄几兆，一分钟一轮纯属白烧。人点开浮窗时才需要知道每一场说了什么。
    """
    names = _session_names()
    pids = _pane_pids()
    mem = _memory_mb()
    return {
        "total": len(names),
        "total_memory_mb": sum(
            sum(mem.get(p, 0) for p in pids.get(name, ())) for name in names
        ),
    }


def close_sessions(names: list[str]) -> list[dict]:
    """逐条点名关闭，返回每一条的结果。

    **NEVER kill-server / pkill tmux。** 那会把这台机器上所有会话一起带走，包括
    没被选中的、正在干活的，以及别人（虚拟桌面的终端）赖以存活的那些。

    池内的会话交给池驱逐，池外的才走 ``kill-session``。一条失败继续下一条——
    批量操作里一条报错就整批中止，等于让人不知道哪些已经关了。
    """
    from frago.server.services.ui_session_runner import get_runner

    results: list[dict] = []
    runner = get_runner()
    for name in names:
        label = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
        ok = False
        via = "tmux"
        error: str | None = None
        try:
            if runner.evict(label):
                ok, via = True, "pool"
            else:
                proc = subprocess.run(
                    ["tmux", "kill-session", "-t", name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                ok = proc.returncode == 0
                if not ok:
                    error = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        except Exception as e:  # noqa: BLE001 — 关不掉一条不该拖垮整批
            error = str(e)
        results.append({"name": name, "ok": ok, "via": via, "error": error})
    return results


@dataclass
class TmuxSessionLink:
    """一个会话编号与它此刻那具 tmux 之间的对应。"""

    name: str  # tmux 会话名（关闭时点的就是它）
    label: str  # 去掉前缀后的那截
    busy: bool  # 屏上还在干活——关之前必须先问一句
    managed: bool  # 工作台那个池子管着它，关闭要走池的驱逐
    memory_mb: int


def find_for_session(session_id: str) -> TmuxSessionLink | None:
    """这个会话编号此刻有没有一具活着的 tmux；没有返回 None。

    ``list_sessions`` 是从 tmux 往回认会话（本机有哪几场、各是谁）。会话页要问的是
    反方向的那一句：我手上这个编号，此刻有没有一具活着的 tmux。方向反过来，判据不变
    ——认编号仍走 ``_resolve_session_id``，忙不忙仍走 ``_is_busy``。

    **NEVER 拿会话卡片上那个「在跑」当判据。** 那一档是从记录文件推的：一场昨天的
    会话，记录停在昨天而 tmux 早就没了；反过来也有 tmux 活着、记录看着已终结的。
    界面上要不要给人「结束运行」这个按钮，只有 tmux 本人说了算。

    **一份记录都不读。** 这条问路挂在「打开一场会话」上，人每点一行就要走一次；
    浮窗那条路每行都要把一份 jsonl 整个读完，那是人点开浮窗才做的重活。

    先按名字直接对：工作台自己开的会话，tmux 名字里那截就是编号，一次比较就够。
    对不上才逐个读屏——飞书群、语音、命令行起的那些，名字是业务把手，编号只在屏上。
    """
    sid = (session_id or "").strip()
    if not sid:
        return None

    names = _session_names()
    if not names:
        return None

    from frago.agent_driver.tmux_session import tmux_name_for

    hit: str | None = None
    pane = ""

    expected = tmux_name_for(sid)
    if expected in names:
        hit = expected
        pane = _tmux("capture-pane", "-p", "-t", expected)
    else:
        for name in names:
            if not name.startswith(_PREFIX):
                continue
            candidate = _tmux("capture-pane", "-p", "-t", name)
            if _resolve_session_id(name[len(_PREFIX) :], candidate) == sid:
                hit, pane = name, candidate
                break

    if hit is None:
        return None

    pids = _pane_pids().get(hit, ())
    mem = _memory_mb() if pids else {}
    return TmuxSessionLink(
        name=hit,
        label=hit[len(_PREFIX) :] if hit.startswith(_PREFIX) else hit,
        busy=_is_busy(pane),
        managed=sid in _managed_ids(),
        memory_mb=sum(mem.get(p, 0) for p in pids),
    )


def open_session_names() -> set[str]:
    """此刻本机活着的 tmux 会话名，一条 ``list-sessions``，不读屏、不读记录。

    左栏的会话清单每 15 秒拉一次，每张卡要答「这一场此刻开在 tmux 里吗」。调用方拿
    ``tmux_name_for(编号)`` 来这里查即可——**只认名字**：飞书群、语音这类名字是业务
    把手的会话在这里对不上，要认它们得逐个读屏，每轮几十毫秒乘以会话数，清单扛不住。
    """
    return set(_session_names())


def as_dicts(rows: list[TmuxSessionInfo] | list[TmuxWaitingInfo]) -> list[dict]:
    return [asdict(r) for r in rows]


__all__ = [
    "CLOSING_CHARS",
    "DEFAULT_EXCERPT_CHARS",
    "TmuxSessionInfo",
    "TmuxSessionLink",
    "TmuxWaitingInfo",
    "as_dicts",
    "close_sessions",
    "find_for_session",
    "list_sessions",
    "list_waiting",
    "open_session_names",
]
