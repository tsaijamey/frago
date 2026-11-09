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

import contextlib
import glob
import json
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.ontology.projectors import (
    CAPABILITY_ADAPTED,
    CAPABILITY_FALLBACK,
    CAPABILITY_NATIVE,
    CAPABILITY_UNSUPPORTED,
    get_agent_capability_level,
)

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
    if label.startswith("core_"):
        return label
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


_PATH_CACHE: dict[tuple[str, str], Path] = {}


def _transcript_path(session_id: str) -> Path | None:
    """按编号在 claude 的记录目录里找那份 jsonl。

    跨全部工程目录扫，不假设会话的工作目录——飞书、语音那些会话的 cwd 与页面
    会话不在一处，钉死一个目录会把它们全判成「找不到记录」。
    """
    projects_root = os.path.expanduser("~/.claude/projects")
    cache_key = (projects_root, session_id)
    cached = _PATH_CACHE.get(cache_key)
    if cached is not None and cached.is_file():
        return cached
    hits = glob.glob(f"{projects_root}/*/{session_id}.jsonl")
    if not hits:
        return None
    resolved = Path(hits[0])
    _PATH_CACHE[cache_key] = resolved
    return resolved


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


def _awaiting_input(pane_ansi: str, alive: bool | None, kernel: str = "claude") -> bool | None:
    """客户端退了就不可能在等人（False）；前台问不出就判不出（None）。

    优先通过驱动契约（driver.awaiting_input）多态调用，解耦服务层对单一具体驱动文件的依赖。
    """
    if alive is not True:
        return None if alive is None else False
    try:
        from frago.agent_driver.driver import registered_drivers

        driver = registered_drivers().get(kernel)
        if driver is not None and driver.awaiting_input is not None:
            return driver.awaiting_input(pane_ansi)

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


def _detect_session_kernel(session_id: str) -> str:
    """根据会话编号与记录存储判断所属内核 ('claude' | 'agy' | 'codex' | 'opencode' | 'coreagent')."""
    if not session_id:
        return "unknown"
    if session_id.startswith("core_"):
        return "coreagent"
    if session_id.startswith("ses_"):
        return "opencode"

    # 优先查找统一存储 ~/.frago/sessions/<agent>/<sid>
    try:
        frago_root = Path.home() / ".frago" / "sessions"
        for agent in ("agy", "codex", "opencode", "claude", "coreagent"):
            if (frago_root / agent / session_id).is_dir():
                return agent
    except Exception:
        pass

    try:
        from frago.session import record_reader

        family = record_reader.detect_family(session_id)
        if family == "claude-code":
            return "claude"
        return str(family)
    except Exception:
        if _transcript_path(session_id) is not None:
            return "claude"
        return "unknown"


_FALLBACK_VERDICT_CACHE: dict[str, tuple[int, bool]] = {}


def _resolve_record_file(session_id: str) -> Path | None:
    """定位多内核会话记录文件（~/.frago/sessions/、agy brain、codex rollout、claude projects）。"""
    try:
        frago_root = Path.home() / ".frago" / "sessions"
        for agent in ("agy", "codex", "opencode", "claude", "coreagent"):
            candidate = frago_root / agent / session_id / "raw.jsonl"
            if candidate.is_file():
                return candidate

        gemini_brain = (
            Path.home()
            / ".gemini"
            / "antigravity-cli"
            / "brain"
            / session_id
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )
        if gemini_brain.is_file():
            return gemini_brain

        from frago.session import codex_store

        rollout = codex_store.find_rollout(session_id)
        if rollout is not None and rollout.is_file():
            return rollout

        claude_path = _transcript_path(session_id)
        if claude_path is not None and claude_path.is_file():
            return claude_path
    except Exception:
        pass
    return None


def _check_last_record_is_assistant(record_file: Path, session_id: str) -> bool:
    """确认会话最后一条实质记录是智能体输出完毕，且无未完成的工具调用。"""
    try:
        from frago.session import record_reader

        recs = record_reader.read_records(session_id, limit=10)
        if recs:
            for r in reversed(recs):
                if r.kind == "agent.say":
                    return True
                if r.kind in ("user.say", "tool.call", "error", "interrupt", "agent.think"):
                    return False
    except Exception:
        pass

    try:
        size = record_file.stat().st_size
        if size <= 0:
            return False
        read_size = min(size, 64 * 1024)
        with record_file.open("rb") as f:
            f.seek(size - read_size)
            chunk = f.read(read_size).decode("utf-8", errors="ignore")
        lines = chunk.splitlines()
        for raw in reversed(lines):
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            role = item.get("role") or item.get("type") or item.get("kind")
            if role in ("assistant", "agent.say", "PLANNER_RESPONSE"):
                content = item.get("content") or (item.get("message") or {}).get("content")
                if isinstance(content, list) and content:
                    last_block = content[-1]
                    if isinstance(last_block, dict) and last_block.get("type") in ("tool_use", "tool_call"):
                        return False
                return True
            if role in ("user", "user.say", "tool", "tool.result", "tool_call", "error"):
                return False
    except Exception:
        pass
    return False


def _fallback_awaiting_input(
    session_id: str,
    pane_ansi: str,
    client_alive: bool | None,
    commands_entry: Any = None,
) -> bool | None:
    """通用启发式待输入兜底探针（第 2 级回退链）。

    门禁 1：窗格非忙碌且终端/记录静默满 3.0 秒；
    门禁 2：末条实质记录为智能体输出完毕（无未完工具调用）；
    门禁 3：(session_id, file_mtime_ns) O(1) 内存缓存与全异常隔离防护。
    """
    _ = commands_entry
    if client_alive is not True:
        return None if client_alive is None else False

    try:
        kernel = _detect_session_kernel(session_id)
        if _is_busy(_plain(pane_ansi), kernel=kernel):
            return False

        record_file = _resolve_record_file(session_id)
        if record_file is None:
            return None

        st = record_file.stat()
        file_mtime = st.st_mtime
        file_mtime_ns = st.st_mtime_ns
        now = time.time()

        if (now - file_mtime) < 3.0:
            return False

        cached = _FALLBACK_VERDICT_CACHE.get(session_id)
        if cached is not None and cached[0] == file_mtime_ns:
            return cached[1]

        verdict = _check_last_record_is_assistant(record_file, session_id)
        _FALLBACK_VERDICT_CACHE[session_id] = (file_mtime_ns, verdict)
        return verdict
    except Exception:
        return False


def _fallback_tail(record_file: Path, session_id: str) -> tuple[str | None, str | None, str]:
    """为 fallback 内核提取 (stop_reason, last_stop_at, text)，带缓存。"""
    try:
        st = record_file.stat()
        key = (st.st_size, st.st_mtime)
        hit = _VERDICT_CACHE.get(str(record_file))
        if hit is not None and hit[0] == key:
            return hit[1]

        last_stop_at: str | None = None
        text = ""
        try:
            from frago.session import record_reader

            recs = record_reader.read_records(session_id, limit=5)
            for r in reversed(recs):
                if r.kind == "agent.say" and r.payload:
                    text = str(r.payload.get("text") or "")
                    if text:
                        if r.ts:
                            last_stop_at = datetime.fromtimestamp(r.ts / 1000.0).isoformat()
                        break
        except Exception:
            pass

        if not text:
            text = _last_assistant_text(record_file)
        if last_stop_at is None:
            last_stop_at = datetime.fromtimestamp(st.st_mtime).isoformat()

        val = ("end_turn", last_stop_at, text)
        _VERDICT_CACHE[str(record_file)] = (key, val)
        return val
    except Exception:
        return None, None, ""


def list_waiting() -> list[TmuxWaitingInfo]:
    """「For you」待输入判定清单，接入 Agent Ontology 三级降级回退链：

    1. native/adapted（Claude）：100% 保持原有专用探针与转录判定逻辑不变；
    2. fallback（agy / codex / opencode）：通用启发式兜底探针（3 秒静默 + 末条回复完工 + O(1) 缓存）；
    3. unsupported / 未知：返回 None，不挂标签。
    """
    names = _session_names()
    commands = _pane_commands()
    frago_names = [n for n in names if n.startswith(_PREFIX)]
    pane_by_name: dict[str, str] = {}
    if len(frago_names) == 1:
        n = frago_names[0]
        pane_by_name[n] = _tmux("capture-pane", "-p", "-e", "-t", n)
    elif len(frago_names) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(frago_names))) as pool:
            captured = list(
                pool.map(
                    lambda n: _tmux("capture-pane", "-p", "-e", "-t", n),
                    frago_names,
                )
            )
        pane_by_name = dict(zip(frago_names, captured, strict=False))

    rows: list[TmuxWaitingInfo] = []
    for name in names:
        if not name.startswith(_PREFIX):
            alive = _client_alive(commands.get(name))
            rows.append(TmuxWaitingInfo(name, None, alive, None, None, None, ""))
            continue
        pane_ansi = pane_by_name.get(name, "")
        session_id = _resolve_session_id(name[len(_PREFIX) :], _plain(pane_ansi))
        alive = _client_alive(commands.get(name))

        if not session_id:
            rows.append(TmuxWaitingInfo(name, None, alive, None, None, None, ""))
            continue

        kernel = _detect_session_kernel(session_id)
        cap_level = get_agent_capability_level(kernel, "awaiting_input_probe")

        if cap_level in (CAPABILITY_NATIVE, CAPABILITY_ADAPTED):
            # 第一级：Claude 专属探针（100% 保持存量行为）
            path = _transcript_path(session_id)
            if path is None:
                rows.append(TmuxWaitingInfo(name, session_id, alive, None, None, None, ""))
                continue
            stop_reason, last_stop_at, text = _transcript_tail(path)
            rows.append(
                TmuxWaitingInfo(
                    name=name,
                    session_id=session_id,
                    client_alive=alive,
                    awaiting_input=_awaiting_input(pane_ansi, alive, kernel=kernel),
                    stop_reason=stop_reason,
                    last_stop_at=last_stop_at,
                    closing_text=_closing_text(text),
                )
            )
        elif cap_level == CAPABILITY_FALLBACK:
            # 第二级：通用启发式兜底探针（agy / codex / opencode）
            awaiting = _fallback_awaiting_input(session_id, pane_ansi, alive, commands.get(name))
            rec_file = _resolve_record_file(session_id)
            if rec_file is not None:
                stop_reason, last_stop_at, text = _fallback_tail(rec_file, session_id)
                closing = _closing_text(text)
            else:
                stop_reason, last_stop_at, closing = None, None, ""
            rows.append(
                TmuxWaitingInfo(
                    name=name,
                    session_id=session_id,
                    client_alive=alive,
                    awaiting_input=awaiting,
                    stop_reason=stop_reason,
                    last_stop_at=last_stop_at,
                    closing_text=closing,
                )
            )
        else:
            # 第三级：CAPABILITY_UNSUPPORTED 或未知内核
            _ = CAPABILITY_UNSUPPORTED
            rows.append(
                TmuxWaitingInfo(
                    name=name,
                    session_id=session_id,
                    client_alive=alive,
                    awaiting_input=None,
                    stop_reason=None,
                    last_stop_at=None,
                    closing_text="",
                )
            )
    return rows


def _extract_last_assistant_from_lines(lines: list[str]) -> str:
    import json

    for raw in reversed(lines):
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            continue
        role = record.get("type") or record.get("role") or record.get("kind")
        if role not in ("assistant", "agent.say", "PLANNER_RESPONSE"):
            continue
        msg = record.get("message")
        content = (msg.get("content") if isinstance(msg, dict) else None) or record.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = " ".join(
                block.get("text", "")
                if isinstance(block, dict)
                else str(block)
                for block in content
                if (isinstance(block, dict) and block.get("type") == "text") or isinstance(block, str)
            ).strip()
            if text:
                return text
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("text"):
            return str(payload["text"]).strip()
        if isinstance(record.get("text"), str) and record["text"].strip():
            return record["text"].strip()
    return ""


def _last_assistant_text(path: Path) -> str:
    """往回翻，找最近一段有正文的回答。

    只在探针给不出正文时用。**正在干活的那一轮往往没有一个字**：最后一条记录是
    一次工具调用，探针照实返回空正文。可浮窗上那一行要是空的，人就认不出这是哪一场
    会话——而认出来正是他打开这个浮窗的目的。往回找到的那段文字仍然是这场会话自己
    说过的话，够用来认人。

    先按尾部窗口（256 KB → 2 MB）逆向找，避免对数十 MB 的长会话整份读入内存；
    尾部窗口都没命中时再退回整份兜底。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= 0:
        return ""

    for window in (256 * 1024, 2 * 1024 * 1024):
        if size <= window:
            break
        try:
            with path.open("rb") as f:
                f.seek(size - window)
                chunk = f.read(window).decode("utf-8", errors="ignore")
        except OSError:
            return ""
        lines = chunk.splitlines()
        if len(lines) > 1:
            lines = lines[1:]
        found = _extract_last_assistant_from_lines(lines)
        if found:
            return found

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    return _extract_last_assistant_from_lines(lines)


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


def memory_by_pid() -> dict[int, int]:
    """进程号 → 它自己及全部后代的常驻内存（MB）。

    公开入口是给合并层用的：CoreAgent 不在 tmux 里，没有 pane 可以挂，只能拿着
    进程号来问。口径与 tmux 那几行完全一致，浮窗上的数字才可比。
    """
    return _memory_mb()


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


_GENERIC_FALLBACK_BUSY = re.compile(
    r"(?i:\besc\s+to\s+(?:interrupt|cancel)\b)"
    r"|\bGenerating\b"
    r"|(?i:running\s+stop\s+hook)"
    r"|^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…",
    re.MULTILINE,
)


def _is_busy(pane: str, kernel: str = "unknown") -> bool:
    """按智能体本体能力矩阵（busy_probe）派发终端忙碌探测，阻断跨内核正则污染。

    1. native (claude)：保留原生 claude_driver 专属正则链；
    2. adapted (agy)：走 agy_driver.is_terminal_busy 专属探针，剔除 (45s 括号耗时正则；
    3. fallback / unknown (codex / opencode 等)：走无副作用通用转轮与中断提示探针。
    """
    if not pane:
        return False
    try:
        normalized = (kernel or "unknown").strip().lower()
        cap_level = get_agent_capability_level(normalized, "busy_probe")

        if cap_level == CAPABILITY_NATIVE and normalized == "claude":
            from frago.agent_driver.drivers import claude as claude_driver

            if claude_driver._SHELL_RUNNING.search(pane) is not None:
                return True
            if claude_driver._BUSY.search(pane) is not None:
                return True
            return claude_driver._WORKING.matches(pane)

        if cap_level in (CAPABILITY_NATIVE, CAPABILITY_ADAPTED) and normalized == "agy":
            from frago.agent_driver.drivers import agy as agy_driver

            if hasattr(agy_driver, "is_terminal_busy"):
                return agy_driver.is_terminal_busy(pane)
            return agy_driver._BUSY.search(pane) is not None

        # CAPABILITY_FALLBACK、coreagent 终端托管窗格或未知内核：
        # 仅匹配通用转轮行与明确中断提示，绝不套用 Claude 专属的括号耗时 (45s 正则
        return _GENERIC_FALLBACK_BUSY.search(pane) is not None
    except Exception:  # noqa: BLE001 — 判不出忙就当忙，宁可少关一个也不误杀
        return True


check_session_terminal_busy = _is_busy


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
        kernel = "unknown"
        if session_id:
            kernel = _detect_session_kernel(session_id)
            cap_level = get_agent_capability_level(kernel, "awaiting_input_probe")

            if cap_level in (CAPABILITY_NATIVE, CAPABILITY_ADAPTED):
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
            elif cap_level == CAPABILITY_FALLBACK:
                awaiting = _fallback_awaiting_input(session_id, pane_ansi, alive, commands.get(name))
                rec_file = _resolve_record_file(session_id)
                if rec_file is not None:
                    try:
                        stop_reason, last_stop_at, text = _fallback_tail(rec_file, session_id)
                        if last_stop_at:
                            dt = datetime.fromisoformat(last_stop_at)
                            idle_secs = max(0.0, now - dt.timestamp())
                        excerpt = _excerpt(text, excerpt_chars)
                        closing = _closing_text(text)
                    except Exception as e:  # noqa: BLE001
                        logger.debug("fallback tail probe failed for %s: %s", session_id, e)
            else:
                awaiting = None

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
                busy=_is_busy(pane, kernel=kernel),
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
            if label.startswith("core_"):
                from frago.server.services import coreagent_runner

                stopped = coreagent_runner.stop(label, by="页面上的人")
                if stopped.get("stopped"):
                    ok, via = True, "coreagent"
                # 兜底确保同名 tmux 窗口（或 CLI 单轮 worker 的窗口）也被清掉
                proc = subprocess.run(
                    ["tmux", "kill-session", "-t", name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    ok = True
                elif not ok:
                    error = (proc.stderr or "").strip() or f"exit {proc.returncode}"
            elif runner.evict(label):
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
    kernel = _detect_session_kernel(sid)
    return TmuxSessionLink(
        name=hit,
        label=hit[len(_PREFIX) :] if hit.startswith(_PREFIX) else hit,
        busy=_is_busy(pane, kernel=kernel),
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


def capture_session_terminal(session_id: str, *, lines: int = 500) -> dict:
    """抓取指定会话此刻的 tmux 终端屏幕（含 ANSI 转义与 scrollback）。

    - 若该会话此刻有活着的 tmux 窗格，实时调 ``tmux capture-pane -p -e -S -<lines>`` 返回；
    - 若 tmux 已退出（例如 CoreAgent 单轮 worker 已跑完收场），但留有 ``panes/<sid>.log``，
      则返回留底终端日志并标 ``alive=False, source="saved_pane"``；
    - 两者皆无时返回 ``alive=False, source="none", content=""``。
    """
    sid = (session_id or "").strip()
    clamped_lines = max(50, min(int(lines or 500), 5000))
    if not sid:
        return {
            "session_id": "",
            "alive": False,
            "tmux_name": None,
            "pane_command": "",
            "client_alive": False,
            "busy": False,
            "memory_mb": 0,
            "source": "none",
            "content": "",
        }

    link = find_for_session(sid)
    if link is not None:
        raw = _tmux("capture-pane", "-p", "-e", "-S", f"-{clamped_lines}", "-t", link.name)
        pane_cmd = _pane_commands().get(link.name) or ""
        client_alive = _client_alive(pane_cmd)
        busy = link.busy
        if sid.startswith("core_"):
            with contextlib.suppress(Exception):
                from frago.server.services import coreagent_runner

                busy = busy or coreagent_runner.busy(sid)
        content = "\n".join((raw or "").splitlines()).rstrip()
        return {
            "session_id": sid,
            "alive": True,
            "tmux_name": link.name,
            "pane_command": pane_cmd,
            "client_alive": client_alive,
            "busy": busy,
            "memory_mb": link.memory_mb,
            "source": "tmux",
            "content": content,
        }

    if sid.startswith("core_"):
        from frago.agent_driver.coreagent_pane_host import read_saved_pane_log
        from frago.agent_driver.tmux_session import tmux_name_for

        saved = read_saved_pane_log(sid, max_lines=clamped_lines).rstrip()
        if saved:
            return {
                "session_id": sid,
                "alive": False,
                "tmux_name": tmux_name_for(sid),
                "pane_command": "",
                "client_alive": False,
                "busy": False,
                "memory_mb": 0,
                "source": "saved_pane",
                "content": saved,
            }

    return {
        "session_id": sid,
        "alive": False,
        "tmux_name": None,
        "pane_command": "",
        "client_alive": False,
        "busy": False,
        "memory_mb": 0,
        "source": "none",
        "content": "",
    }


def as_dicts(rows: list[TmuxSessionInfo] | list[TmuxWaitingInfo]) -> list[dict]:
    return [asdict(r) for r in rows]


__all__ = [
    "CLOSING_CHARS",
    "DEFAULT_EXCERPT_CHARS",
    "TmuxSessionInfo",
    "TmuxSessionLink",
    "TmuxWaitingInfo",
    "as_dicts",
    "capture_session_terminal",
    "close_sessions",
    "find_for_session",
    "list_sessions",
    "list_waiting",
    "open_session_names",
]
