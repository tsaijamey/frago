"""会话的出身：这场是人自己开的，还是 frago 派出去干活的 worker，以及谁派的。

左栏清单里本机有两千多场会话，其中一千五百场是 frago 起的 worker。它们与人自己开的
会话混在同一列里，一眼看过去分不出哪一场是自己刚才在谈的——这个模块负责把这件事判出来，
判据有三条，从确定到推断：

1. **起 worker 那一刻记下的账**（``LAUNCH_LEDGER``）。``frago agent`` 每派一次活就写一条，
   里面既有子会话的编号，也有派活的那场会话的编号。这一条是往后新起的会话的正路，
   父子关系是当场记的，不是事后猜的。

2. **旧会话记录里派活留下的痕迹**（``PARENT_SCAN_CACHE``）。主 agent 是在自己的会话里敲的
   ``frago agent``，那几条命令与它们的回显原样躺在主会话的记录文件里。所以第 1 条上线之前
   的那些旧会话，父子关系仍能从记录里捞回来。这一趟要扫整个会话库，故按天缓存——它只服务
   历史，新起的会话走第 1 条。

   **派活有两条路，两条都要认。** 一次性那条（``frago agent <任务>``）在回显里报出新会话的
   编号；常驻那条（``frago agent start --name w1``，再 ``frago agent send w1``）只回一个名字，
   编号是从**名字**推出来的。只认前者的代价是实测出来的：某场调研会话先用一次性路径起了 7 个
   worker 全部启动失败，随后改用常驻路径起了 14 个并全部跑完——只认回显的话，那 14 场一个都
   挂不上，界面上看起来就是"这场只派过一个 worker"，与人的记忆正相反。

   常驻会话的名字是全局的（谁都可以叫 ``w1``），所以同一个名字可能被好几场主会话用过。
   这种时候认**最近活动的那一场**：那正是它当前的主人，也是人打开清单时期待看到的关系。

3. **会话编号的形状**。frago 起 worker 时不让 claude 自己分配编号，而是拿 frago 那一侧的
   编号经一个固定命名空间派生，派生出来的是第 5 版 UUID；人在终端敲 ``claude``、或在页面上
   新建会话，拿到的都是第 4 版。本机实测 1507 : 627，且第 5 版的那一批没有一场带 slug
   （slug 只发给 claude 自己分配编号的会话）。这一条认不出"谁派的活"，只认得出"这不是人开的"。

三条的关系是补充而非替代：第 3 条覆盖面最广但只答一半问题，第 1、2 条答得全但各有各的
覆盖边界。**认不出来一律当人开的**——把一场人自己谈了半天的会话折进 worker 堆里，比多显示
几场 worker 糟得多。

编号形状这一条只对 Claude Code 成立。codex 与 opencode 的会话编号是它们自己分配、frago
事后认领的，形状上与人开的会话没有区别，所以那两家只认第 1、2 条记下的账。

## 关系种类

第 1 条那本账起初只记「谁派了谁」，后来升级成一本通用的**会话关系账**：每条多记一项
``kind``，说明子会话是怎么从父会话里出来的（spec 20260928-webui-session-branch）。

- ``dispatch`` **派活**：``frago agent`` 派出去的 worker。子会话算 worker。
- ``branch`` **分支**：人在会话页圈一段原文、起一场新会话去处理旁支问题。那一场是人亲自
  在谈的，子会话**算人开的**——它等你时照样该挂进「等你」，只是在左栏折到原会话下面。
  分支另记从主线哪段原文分出去（``anchor``）、人写的那句话（``note``）与收口状态
  （``closed_at`` / ``closed_by``）。
- ``handoff`` **交接**：留位，只在读取侧认得，眼下没有写入方。

**老账照读。** 升级之前写下的记录没有 ``kind``，一律当 ``dispatch``——那时账上只有派活
这一种。读不懂的单条（种类不认得、编号不是字符串）跳过，NEVER 让整份清单取不出来。
第 2 条扫描出来的关系一律算派活，判据不变。

左栏折叠要的父会话由 ``dispatch`` 与 ``branch`` 两种一起给出；出身只有 ``dispatch``
的子会话算 worker。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR

logger = logging.getLogger(__name__)

__all__ = [
    "LAUNCH_LEDGER",
    "PARENT_SCAN_CACHE",
    "OriginIndex",
    "RelationKind",
    "SessionOrigin",
    "SessionRelation",
    "clear_cache",
    "close_relation",
    "find_relation",
    "is_worker_shape",
    "load_origin_index",
    "record_launch",
    "record_relation",
]

# 出身两档，没有第三档。"说不准"那一档看着诚实，实际上界面拿它没办法——一行卡片要么
# 折进 worker 堆里，要么留在主干上，中间态最后还是要落到这两个里的一个。判不出来就是
# ``human``，理由见模块开头。
SessionOrigin = Literal["human", "worker"]

# 子会话是怎么从父会话里出来的。见模块开头「关系种类」。
RelationKind = Literal["dispatch", "branch", "handoff"]
RELATION_KINDS: tuple[str, ...] = ("dispatch", "branch", "handoff")

# 收口的两种来路：分支会话里「带回主线」，或主线那段原文上手动标记。
CloseBy = Literal["bring-back", "manual"]
CLOSE_BY: tuple[str, ...] = ("bring-back", "manual")

# 与会话索引同一个落点：它们服务的是同一张页面，清缓存时人找一个地方就够了。
CACHE_DIR = Path.home() / ".frago" / "workbench"

# 起 worker 那一刻写的账。
LAUNCH_LEDGER = CACHE_DIR / "agent-launches.json"

# 从旧会话记录里捞回来的父子关系。
PARENT_SCAN_CACHE = CACHE_DIR / "agent-parent-scan.json"

# 账本留多少条。一条一百来字节，四千条不到半兆；再老的会话早被 claude 滚删了，
# 留着也对不上任何一个会话文件。
LEDGER_LIMIT = 4000

# 整库全扫多久重来一次。一趟是在整个会话库上跑一次 ripgrep（本机 5.2 GB、2.2 秒）。
SCAN_MAX_AGE_S = 24 * 3600

# 两次全扫之间，多久补一次增量。**关系不能落后太多**：人一直在用，会话一直在新建，
# 一天才认一次等于清单上那几行关系永远是昨天的。
#
# 增量只扫「上次扫过之后动过的那几个会话文件」——通常是个位数，耗时毫秒级，所以这个间隔
# 可以定得很短。全扫仍然留着：它管的是那些从来没被扫到过的老会话，那部分不会自己变。
SCAN_REFRESH_S = 180

# 增量那一趟最多扫多少个文件；超过就直接全扫。文件多到一定程度时，逐个传路径给 ripgrep
# 反而比让它自己遍历整个目录更慢，命令行长度也顶不住。
INCREMENTAL_FILE_CAP = 300

# 增量取「动过的文件」时往回多看一点：扫描本身要花时间，正好卡在这段时间里写入的文件
# 会两头落空。多看一分钟，宁可重扫几个也不漏。
INCREMENTAL_OVERLAP_S = 60

# 同一个进程里，索引最多这么久不重读。左栏每 15 秒取一次清单，每次都去读两个文件、
# 判一遍两千个编号是白烧；而派活是人主动做的事，晚半分钟认出来没有任何影响。
MEMO_TTL_S = 30

# claude 派生编号的版本位。UUID 的第 15 个十六进制位就是版本号。
_WORKER_UUID_VERSION = 5

# 派活在主会话记录里留下的三种痕迹。三条都只捕获**frago 那一侧的编号或名字**，
# 换算成目标 agent 那边的真实编号是同一个动作（见 ``_derive_claude_session_id``）。
#
#   ① 一次性派活的回显：``frago agent <任务>`` 起会话后往 stderr 打这一句。认回显而不是
#      认命令行——命令行只说明有人打算派活，回显才证明那一场真的起来了。
#   ② 常驻会话的起会话命令：``frago agent start claude --name w1``。
#   ③ 常驻会话的驱动命令：``frago agent send|peek|stop w1``。它们证明这场主会话在驱动
#      那个名字，与 ② 互为补充——起会话那条常写成 shell 循环（``--name $n``），名字在变量里
#      根本捕获不到，而驱动命令里的名字是字面量。
#
# 名字要求首字符是字母或数字：``--help`` / ``--json`` 这类选项因此不会被当成会话名。
_LAUNCH_ECHO = re.compile(r"tmux driver: agent=([a-zA-Z0-9_-]+) session=([0-9a-fA-F-]{36})")
_RESIDENT_START = re.compile(
    r"frago agent start\s+[a-z]+\s+--name\s+([A-Za-z0-9][A-Za-z0-9_-]{0,39})"
)
_RESIDENT_DRIVE = re.compile(r"frago agent (?:send|peek|stop)\s+([A-Za-z0-9][A-Za-z0-9_-]{0,39})")

# 一趟 ripgrep 同时找这三种痕迹，命中的整段再在 Python 侧分别解析。
_SCAN_PATTERNS = (
    _LAUNCH_ECHO.pattern,
    _RESIDENT_START.pattern,
    _RESIDENT_DRIVE.pattern,
)


def _now() -> float:
    return time.time()


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _write_json(path: Path, payload: object) -> bool:
    """原子写，返回写上没有。写不进去不抛——记账失败最多让一场会话认不出出身，NEVER
    让它把派活打死。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.debug("could not write %s", path, exc_info=True)
        return False
    return True


# ── 判据三：编号形状 ────────────────────────────────────────────────────────


def is_worker_shape(session_id: str) -> bool:
    """这个编号是不是 frago 派生出来的（第 5 版 UUID）。

    形状不合法一律返回 False：opencode 的 ``ses_`` 前缀编号、以及任何不是 UUID 的东西
    都从这里安静地走掉，NEVER 抛异常——判出身失败不该让整份清单取不出来。
    """
    try:
        return uuid.UUID(session_id).version == _WORKER_UUID_VERSION
    except (ValueError, AttributeError, TypeError):
        return False


# ── 判据一：起 worker 那一刻记下的账 ────────────────────────────────────────


# 账本是「读—改—原子替换」。派活与起分支可能在同一个服务进程里同时发生，两边各读一份、
# 各写回去，先写的那条就丢了。进程内这把锁挡住这种情况；跨进程（命令行派活与页面起分支
# 撞在同一刻）仍可能丢一条，那只影响左栏的挂靠显示，不影响会话本身已经起好。
_ledger_lock = threading.Lock()


def _ledger_entries() -> list[Any]:
    raw = _read_json(LAUNCH_LEDGER)
    return raw if isinstance(raw, list) else []


def record_relation(
    *,
    kind: RelationKind,
    child_session_id: str,
    parent_session_id: str | None,
    agent_type: str,
    cwd: str,
    prompt_head: str = "",
    anchor: dict[str, Any] | None = None,
    note: str | None = None,
) -> bool:
    """往关系账里记一条，返回记上没有。

    ``anchor`` / ``note`` 只有分支才带，收口的两项记账时一律为空（分支刚起，还开着）。
    ``parent_session_id`` 取不到就留空，**NEVER 为了让父子关系好看而编一个出来**：编错的
    父亲会把一场会话折到一场跟它毫无关系的会话下面。

    整个函数吞掉一切异常：记账是给界面用的，派活、起分支本身不该因为它失败。
    """
    global _memo
    if kind not in RELATION_KINDS:
        return False
    entry: dict[str, Any] = {
        "child": child_session_id,
        "parent": parent_session_id or None,
        "kind": kind,
        "agent_type": agent_type,
        "cwd": cwd,
        # 第一句话开头留一句，排查时能认出这条账对应的是哪一次。
        "prompt_head": (prompt_head or "").strip()[:120],
        "at": int(_now()),
    }
    if kind == "branch":
        entry.update({"anchor": anchor, "note": note or "", "closed_at": None, "closed_by": None})
    try:
        with _ledger_lock:
            entries = _ledger_entries()
            entries.append(entry)
            written = _write_json(LAUNCH_LEDGER, entries[-LEDGER_LIMIT:])
    except Exception:  # noqa: BLE001 — 记账失败最多让左栏认不出这层关系
        logger.debug("could not record relation for %s", child_session_id, exc_info=True)
        return False
    # 刚记的这条要让下一次取清单就看得见，NEVER 让它在进程内那份索引里再躺半分钟。
    _memo = None
    return written


def record_launch(
    *,
    child_session_id: str,
    parent_session_id: str | None,
    agent_type: str,
    cwd: str,
    prompt_head: str = "",
) -> None:
    """记一笔"这场会话是谁派出去的"（种类为派活）。

    ``parent_session_id`` 为空就只记这场是 worker，不记谁派的——服务端的常驻会话、
    定时任务派出去的活都属于这种，它们本来就没有一个"上级会话"可指。
    """
    record_relation(
        kind="dispatch",
        child_session_id=child_session_id,
        parent_session_id=parent_session_id,
        agent_type=agent_type,
        cwd=cwd,
        prompt_head=prompt_head,
    )


def _parse_entry(item: Any) -> dict[str, Any] | None:
    """一条账读成统一的样子；读不懂返回 None，由调用方跳过。

    缺 ``kind`` 的是升级之前的老记录，一律当派活。
    """
    if not isinstance(item, dict):
        return None
    child = item.get("child")
    if not isinstance(child, str) or not child.strip():
        return None
    kind = item.get("kind", "dispatch")
    if kind is None:
        kind = "dispatch"
    if kind not in RELATION_KINDS:
        return None
    parent = item.get("parent")
    if parent is not None and not isinstance(parent, str):
        return None
    closed_at = item.get("closed_at")
    return {
        **item,
        "child": child.strip(),
        "parent": (parent or "").strip() or None,
        "kind": kind,
        "closed_at": closed_at if isinstance(closed_at, int) else None,
    }


@dataclass(frozen=True)
class SessionRelation:
    """一场会话作为子会话的那层关系：种类与收口没有。会话清单原样带给页面。"""

    kind: RelationKind
    closed: bool = False


def _ledger_pairs() -> tuple[dict[str, str], set[str], dict[str, SessionRelation]]:
    """账本里的 (子会话 → 父会话)、"确定是 worker"的那批编号、以及每场子会话的关系。

    同一场子会话记过好几条时，以后记的为准。
    """
    parents: dict[str, str] = {}
    workers: set[str] = set()
    relations: dict[str, SessionRelation] = {}
    for item in _ledger_entries():
        entry = _parse_entry(item)
        if entry is None:
            continue
        child = entry["child"]
        kind = entry["kind"]
        relations[child] = SessionRelation(kind=kind, closed=entry["closed_at"] is not None)
        if kind == "dispatch":
            workers.add(child)
        if kind not in ("dispatch", "branch"):
            continue
        parent = entry["parent"]
        # 自己不能是自己的父亲：真出现了就是记账时把编号取错了，认下来会让那一行
        # 在清单里既是主干又是它自己的子项。
        if parent and parent != child:
            parents[child] = parent
    return parents, workers, relations


def find_relation(child_session_id: str) -> dict[str, Any] | None:
    """关系账里这场子会话最后记的那一条（读成统一的样子）。没有就是 None。"""
    found: dict[str, Any] | None = None
    for item in _ledger_entries():
        entry = _parse_entry(item)
        if entry is not None and entry["child"] == child_session_id:
            found = entry
    return found


def close_relation(
    *, child_session_id: str, parent_session_id: str, closed_by: CloseBy
) -> dict[str, Any] | None:
    """把一条分支记为已收口，返回改完的那一条；账上没有这条分支返回 None。

    已经收口过的不再改写时刻与来路：第一次收口才是事实，后来的重复点击不该把它冲掉。
    写入走整份原子替换，别的记录原样留着——老记录里多出来、这里不认得的字段也一并保留。

    与记账不同，这里写不进去要抛 ``OSError``：收口是人点出来的动作，没记上必须告诉他，
    NEVER 让页面以为收了口、刷新之后虚线又回来。
    """
    global _memo
    with _ledger_lock:
        entries = _ledger_entries()
        hit: int | None = None
        for i, item in enumerate(entries):
            entry = _parse_entry(item)
            if (
                entry is not None
                and entry["kind"] == "branch"
                and entry["child"] == child_session_id
                and entry["parent"] == parent_session_id
            ):
                hit = i
        if hit is None:
            return None
        item = entries[hit]
        if item.get("closed_at") is None:
            item["closed_at"] = int(_now())
            item["closed_by"] = closed_by
            if not _write_json(LAUNCH_LEDGER, entries):
                raise OSError(f"关系账写不进去：{LAUNCH_LEDGER}")
    _memo = None
    return _parse_entry(item)


# ── 判据二：从旧会话记录里捞父子关系 ────────────────────────────────────────


def _run_rg(args: list[str]) -> str | None:
    """跑一趟 ripgrep，返回标准输出；跑不成返回 None。

    与内容检索那边的同名助手是同一段管道代码，不是同一条判据——那边决定"搜什么词"，
    这边决定"认哪一句回显"，各自的判据都留在各自模块里。
    """
    if shutil.which("rg") is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - 参数全部由本模块构造
            ["rg", *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("ripgrep invocation failed", exc_info=True)
        return None
    # 一条都没命中时 ripgrep 返回 1，那不是失败。
    if proc.returncode not in (0, 1):
        logger.debug("ripgrep exited %s: %s", proc.returncode, proc.stderr[:400])
        return None
    return proc.stdout


def _derive_claude_session_id(frago_session_id: str) -> str | None:
    """frago 那一侧的编号 → claude 那一侧的真实编号。

    派生规则只有一处，在 claude 那家的 driver 里（``_launch`` 起会话时用的就是它）。
    这里延迟导入而不是自己再算一遍：命名空间抄第二份的话，哪天 driver 改了规则，
    界面上的父子关系会安静地全部对不上，而两边各自看都是对的。
    """
    try:
        from frago.agent_driver.drivers.claude import claude_session_uuid

        return claude_session_uuid(frago_session_id)
    except Exception:  # noqa: BLE001 — 派生不出来只是少认几场，NEVER 让清单取不出来
        logger.debug("could not derive claude session id", exc_info=True)
        return None


def _scan_launch_echoes(projects_root: Path, *, only: list[Path] | None = None) -> dict[str, str]:
    """扫会话库，把派活留下的父子关系捞出来：{子会话编号: 派活的会话编号}。

    痕迹里拿到的是 frago 那一侧的编号或会话名，要再派生一次才是 claude 那边的真实编号——
    清单上摆的是后者。派生不出来的就不认，NEVER 拿 frago 那一侧的编号硬当会话编号用：
    它在会话库里根本没有对应的文件，认下来等于凭空多出一行点不开的卡片。

    **同名归时刻最贴近的那一场。** 常驻会话的名字是全局的，好几场主会话都用过 ``w1`` 很常见。
    判据是「哪一场主会话的活动时刻离这个 worker 最近」，NEVER 取「最近活动的那一场」——
    后者会把一个九月八号干完活的 worker 判给今天某场只是碰巧也用了 ``w1`` 这个名字的会话，
    而那场会话根本没碰过它。
    """
    if not projects_root.is_dir():
        return {}
    if only is not None and not only:
        return {}
    # 一趟就够：内容检索那边要分两趟，是因为它的词在语料里命中上百万处、要行号会炸；
    # 派活这几句在整个会话库里只有几千处，一趟带正则直接取出来，秒级。
    args = ["-o", "--no-heading", "--with-filename"]
    for pattern in _SCAN_PATTERNS:
        args += ["-e", pattern]
    if only is None:
        args += ["--glob", "*.jsonl", str(projects_root)]
    else:
        # 增量：只把这几个文件交给它。``--with-filename`` 不能省——只给一个文件时
        # ripgrep 默认不打文件名，而文件名正是"这条痕迹出自哪场主会话"。
        args += [str(p) for p in only]
    out = _run_rg(args)
    if not out:
        return {}

    # 每场 worker 先把所有可能的主会话都收下来，等下再决胜。
    candidates: dict[str, set[str]] = {}
    for line in out.splitlines():
        head, sep, rest = line.partition(".jsonl:")
        if not sep:
            continue
        parent = head.rsplit("/", 1)[-1]
        echo = _LAUNCH_ECHO.search(rest)
        start = _RESIDENT_START.search(rest)
        drive = _RESIDENT_DRIVE.search(rest)
        if echo is not None:
            key = echo.group(2)
        elif start is not None:
            key = start.group(1)
        elif drive is not None:
            key = drive.group(1)
        else:
            continue
        child = _derive_claude_session_id(key)
        if child is None or child == parent:
            continue
        candidates.setdefault(child, set()).add(parent)

    # 会话最后活动的时刻。一次扫盘全取回来，免得每判一次冲突就去翻一遍目录。
    mtimes: dict[str, float] = {}
    for path in projects_root.glob("*/*.jsonl"):
        try:
            mtimes[path.stem] = path.stat().st_mtime
        except OSError:
            continue

    pairs: dict[str, str] = {}
    for child, parents in candidates.items():
        if len(parents) == 1:
            pairs[child] = next(iter(parents))
            continue
        child_at = mtimes.get(child)
        if child_at is None:
            # 这场 worker 的记录已经不在了，谁也验证不了，取最近活动的那个主会话收场。
            pairs[child] = max(parents, key=lambda p: mtimes.get(p, 0.0))
            continue
        pairs[child] = min(parents, key=lambda p: abs(mtimes.get(p, 0.0) - child_at))
    return pairs


def _changed_since(projects_root: Path, since: float) -> list[Path] | None:
    """``since`` 之后动过的会话文件。多到一定程度就返回 None，让调用方改走全扫。"""
    changed: list[Path] = []
    for path in projects_root.glob("*/*.jsonl"):
        try:
            if path.stat().st_mtime >= since:
                changed.append(path)
        except OSError:
            continue
        if len(changed) > INCREMENTAL_FILE_CAP:
            return None
    return changed


def _scanned_pairs(projects_root: Path, *, now: float) -> dict[str, str]:
    """缓存过的那份扫描结果，按需刷新。

    三档，代价差着两个量级：
    - 缓存还新鲜（``SCAN_REFRESH_S`` 以内）：直接用，零开销。
    - 稍旧：**增量**——只扫上次扫过之后动过的那几个会话文件，把新认到的并进去。人一直在
      用、会话一直在新建，关系不能落后太多；而这一趟通常只有个位数的文件，毫秒级。
    - 很旧（``SCAN_MAX_AGE_S`` 以外）或从来没扫过：整库全扫一趟。它管的是那些从没被扫到
      的老会话——那部分不会自己变，所以按天来就够。
    """
    raw = _read_json(PARENT_SCAN_CACHE)
    cached: dict[str, str] = {}
    at: float | None = None
    if isinstance(raw, dict):
        pairs = raw.get("pairs")
        stamp = raw.get("at")
        if isinstance(stamp, int | float) and isinstance(pairs, dict):
            at = float(stamp)
            cached = {str(k): str(v) for k, v in pairs.items()}

    if at is not None and now - at < SCAN_REFRESH_S:
        return cached

    if at is not None and now - at < SCAN_MAX_AGE_S:
        changed = _changed_since(projects_root, at - INCREMENTAL_OVERLAP_S)
        if changed is not None:
            fresh = _scan_launch_echoes(projects_root, only=changed) if changed else {}
            merged = {**cached, **fresh}
            _write_json(PARENT_SCAN_CACHE, {"at": int(now), "pairs": merged})
            return merged

    pairs = _scan_launch_echoes(projects_root)
    _write_json(PARENT_SCAN_CACHE, {"at": int(now), "pairs": pairs})
    return pairs


# ── 合并成一份索引 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OriginIndex:
    """一份判完的出身索引。清单每取一次用同一份，免得同一批卡片按两份数据判。"""

    parents: dict[str, str]
    """子会话编号 → 派活的那场会话的编号。只收认得出父亲的那些。"""

    workers: frozenset[str]
    """账本里明确记过的 worker（种类为派活）。编号形状认不出的那两家（codex/opencode）全靠它。"""

    relations: dict[str, SessionRelation] = field(default_factory=dict)
    """子会话编号 → 它作为子会话的种类与收口状态。账本里的按各自种类，扫描认出的一律算派活。"""

    def parent_of(self, session_id: str) -> str | None:
        return self.parents.get(session_id)

    def relation_of(self, session_id: str) -> SessionRelation | None:
        return self.relations.get(session_id)

    def origin_of(self, session_id: str) -> SessionOrigin:
        """这场会话是谁开的。

        账上记为派活的是 worker；记为分支的是人开的——它是人亲自在谈的一场，只是从别的
        会话里分出来。其余再看扫描有没有认出它被派过、编号形状像不像派生的，都不命中就是
        人开的。
        """
        if session_id in self.workers:
            return "worker"
        relation = self.relations.get(session_id)
        if relation is not None and relation.kind == "branch":
            return "human"
        if session_id in self.parents:
            return "worker"
        return "worker" if is_worker_shape(session_id) else "human"


_memo: tuple[float, OriginIndex] | None = None


def load_origin_index(
    *,
    projects_root: Path | None = None,
    now: float | None = None,
    use_memo: bool = True,
) -> OriginIndex:
    """取出身索引。同一进程内 :data:`MEMO_TTL_S` 秒内复用上一份。"""
    global _memo
    clock = _now() if now is None else now
    if use_memo and _memo is not None and clock - _memo[0] < MEMO_TTL_S:
        return _memo[1]

    parents, workers, relations = _ledger_pairs()
    # 账本记的是当场看见的事实，扫描是事后从记录里捞的；两边都说了话时以账本为准。
    scanned = _scanned_pairs(projects_root or CLAUDE_PROJECTS_DIR, now=clock)
    merged = dict(scanned)
    merged.update(parents)
    # 扫描认出的关系一律算派活（判据只认派活留下的痕迹）。
    merged_relations = {child: SessionRelation(kind="dispatch") for child in scanned}
    merged_relations.update(relations)
    index = OriginIndex(parents=merged, workers=frozenset(workers), relations=merged_relations)
    if use_memo:
        _memo = (clock, index)
    return index


def clear_cache() -> None:
    """把扫描缓存与进程内那份都丢掉。改了判据、或者要立刻重扫时用。

    **账本不动。** 那是记下来的事实，不是算出来的结果，删掉就再也捞不回来了。
    """
    global _memo
    _memo = None
    with contextlib.suppress(OSError):
        PARENT_SCAN_CACHE.unlink()
