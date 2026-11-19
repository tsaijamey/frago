"""会话详情页的「派生子会话与运行中子进程」只读探测服务。

解决用户在会话详情页看不到「谁起的、派生了哪些子会话/子进程、现在是否还在跑」的盲区：
1. ``session_origin``（关系账 + 历史扫描缓存）：覆盖 ``dispatch``（worker）、``branch``（分支）、
   ``handoff``（交接）父子关系，同时给出本会话自身「由谁启动」（``launched_by``）。
2. ``async_dispatch``（异步派发任务单）：覆盖正在排队/运行/回传中的 worker 与员工调用，
   即使目标会话尚未落盘首条记录也能立即看到。
3. 进程树探测（``tmux list-panes`` + ``ps`` + ``coreagent_runner``）：覆盖 ``claude --resume``、
   ``agy``、``codex``、``opencode``、``frago-core`` 等在会话运行期间直接拉起的后台命令、
   subshell 与 CLI 子进程（包括在外部终端直接执行 ``claude --resume <sid>`` 启动的场景）。

分层：服务层。可 import ``session/`` 与同级 ``services/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.agent_driver.tmux_session import _SHELL_COMMANDS, tmux_name_for
from frago.server.services import (
    coreagent_runner,
    tmux_sessions_service,
    workbench_groups,
    workbench_titles,
)
from frago.session import record_reader, session_origin
from frago.session.record_reader import UnknownSessionFamily
from frago.session.session_index import IN_PROGRESS_KINDS

logger = logging.getLogger(__name__)

_DISPATCH_STARTUP_GRACE_MS = 60_000
_DISPATCH_STALE_DELIVERING_MS = 1_800_000
_DISPATCH_REPLY_OVERTAKEN_GRACE_MS = 5_000
_MAX_DESCENDANT_DEPTH = 8

_AGENT_COMM_HINTS = ("claude", "codex", "opencode", "agy", "frago-core")
_WRAPPER_COMMS = {"python", "python3", "python3.11", "python3.12", "python3.13", "python3.14", "uv"}
_PROBE_COMMS = {"ps", "tmux"}
_LINKED_SID_RE = re.compile(
    r"(?:--session-id|--resume|--conversation)(?:=|\s+)([A-Za-z0-9_-]{8,128})"
)
_CLI_SID_PATTERN_TMPL = (
    r"(?:--resume|--session-id|--conversation)(?:=|\s+){sid}(?:\s|$)"
    r"|(?:^|\s)(?:claude|codex|opencode|agy)\b[^\n]*\s-r\s+{sid}(?:\s|$)"
)


@dataclass(frozen=True)
class _ProcInfo:
    pid: int
    ppid: int
    state: str
    etime: str
    comm: str
    args: str


@dataclass(frozen=True)
class _PaneInfo:
    session_name: str
    pane_pid: int
    pane_command: str


def _iso_to_epoch_ms(raw: str | None) -> int | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _short_comm(raw_comm: str, args: str) -> str:
    cleaned = (raw_comm or "").strip()
    if cleaned:
        name = Path(cleaned).name
        if name:
            return name
    first = (args or "").strip().split(" ", 1)[0]
    return Path(first).name if first else "process"


def _is_shell_comm(comm: str) -> bool:
    base = Path(comm).name.lstrip("-").lower()
    return base in _SHELL_COMMANDS or f"-{base}" in _SHELL_COMMANDS


def _is_zombie(state: str) -> bool:
    return (state or "").strip().upper().startswith("Z")


def _snapshot_processes() -> tuple[dict[int, _ProcInfo], dict[int, list[int]]]:
    """一次 ``ps`` 抓取进程表与父子 PID 映射。异常时返回空表，绝不阻断接口。"""
    comm_col = "ucomm=" if sys.platform == "darwin" else "comm="
    try:
        proc = subprocess.run(
            ["ps", "-eo", f"pid=,ppid=,state=,etime=,{comm_col},args="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return {}, {}
    except (OSError, subprocess.SubprocessError):
        return {}, {}

    procs: dict[int, _ProcInfo] = {}
    children_by_pid: dict[int, list[int]] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        state = parts[2].strip()
        etime = parts[3].strip()
        raw_comm = parts[4].strip()
        args = parts[5].strip() if len(parts) > 5 else raw_comm
        comm = _short_comm(raw_comm, args)
        procs[pid] = _ProcInfo(
            pid=pid,
            ppid=ppid,
            state=state,
            etime=etime,
            comm=comm,
            args=args,
        )
        children_by_pid.setdefault(ppid, []).append(pid)
    return procs, children_by_pid


def _tmux_panes() -> dict[str, list[_PaneInfo]]:
    """通过 tmux_sessions_service._tmux 抓取全部活跃窗格及根 PID。"""
    out: dict[str, list[_PaneInfo]] = {}
    try:
        raw = tmux_sessions_service._tmux(
            "list-panes",
            "-a",
            "-F",
            "#{session_name}\t#{pane_pid}\t#{pane_current_command}",
        )
    except Exception:  # noqa: BLE001
        return {}
    for line in (raw or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sname = parts[0].strip()
        try:
            pane_pid = int(parts[1].strip())
        except ValueError:
            continue
        pane_cmd = parts[2].strip() if len(parts) > 2 else ""
        if sname:
            out.setdefault(sname, []).append(
                _PaneInfo(session_name=sname, pane_pid=pane_pid, pane_command=pane_cmd)
            )
    return out


def _matches_session_cli(args: str, sid: str) -> bool:
    if not args or not sid or sid not in args:
        return False
    pattern = re.compile(_CLI_SID_PATTERN_TMPL.format(sid=re.escape(sid)), re.IGNORECASE)
    return pattern.search(args) is not None


def _is_agent_process(proc: _ProcInfo) -> bool:
    low_comm = proc.comm.lower()
    low_args = proc.args.lower()
    if any(hint in low_comm for hint in _AGENT_COMM_HINTS):
        return True
    if any(
        token in low_args
        for token in (
            "frago-core",
            "@anthropic-ai/claude-code",
            "/claude ",
            "claude --resume",
            "claude --session-id",
            "agy --",
            "codex ",
            "opencode ",
        )
    ):
        return True
    # Claude Code 在 macOS 上常把 argv[0] 设为版本号（如 2.1.281）
    return bool(re.match(r"^\d+\.\d+\.\d+$", low_comm))


def _is_coreagent_pane_host(proc: _ProcInfo) -> bool:
    return "frago.agent_driver.coreagent_pane_host" in proc.args


def _extract_linked_sid(args: str, self_sid: str) -> str | None:
    for m in _LINKED_SID_RE.finditer(args or ""):
        cand = m.group(1).strip()
        if cand and cand != self_sid:
            return cand
    return None


def _classify_process_kind(proc: _ProcInfo) -> str:
    low_args = proc.args.lower()
    if (
        "frago agent" in low_args
        or "frago employee" in low_args
        or _is_agent_process(proc)
    ):
        return "agent_cli"
    if _is_shell_comm(proc.comm):
        return "subshell"
    return "command"


def _clip_title(title: str, limit: int = 36) -> str:
    collapsed = " ".join((title or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _relation_label(
    relation_kind: str | None,
    *,
    is_direct: bool,
    launcher_title: str,
    dispatch_kind: str | None = None,
) -> str:
    prefix = "由当前会话" if is_direct else f"由子会话「{_clip_title(launcher_title)}」"
    if relation_kind == "branch":
        return f"{prefix}分出分支"
    if relation_kind == "handoff":
        return f"{prefix}交接"
    if dispatch_kind == "employee":
        return f"{prefix}调用员工"
    return f"{prefix}派发"


def _collect_session_processes(
    target_sid: str,
    *,
    host_title: str,
    is_main_session: bool,
    procs: dict[int, _ProcInfo],
    children_by_pid: dict[int, list[int]],
    panes_by_name: dict[str, list[_PaneInfo]],
    core_snaps: dict[str, coreagent_runner.LiveSessionSnapshot],
    resolved_tmux_name: str | None = None,
) -> tuple[bool, list[dict[str, Any]], set[str]]:
    """探测某场会话此刻活着的宿主进程及其全部派生子进程。

    返回 ``(host_alive, child_processes, linked_session_ids_found_in_args)``。
    """
    if not procs:
        return False, [], set()

    self_pid = os.getpid()
    host_alive = False
    agent_root_pids: list[int] = []
    extra_child_seeds: list[tuple[int, int, str]] = []  # (pid, launcher_pid, launcher_comm)
    seen_roots: set[int] = set()

    # 1. Tmux 窗格：frago-agent-<sid> 或屏幕反查命中的 tmux 会话
    tmux_names: list[str] = []
    expected_tmux = tmux_name_for(target_sid)
    if expected_tmux in panes_by_name:
        tmux_names.append(expected_tmux)
    if resolved_tmux_name and resolved_tmux_name in panes_by_name and resolved_tmux_name not in tmux_names:
        tmux_names.append(resolved_tmux_name)

    for tname in tmux_names:
        for pane in panes_by_name.get(tname, []):
            ppid = pane.pane_pid
            pane_proc = procs.get(ppid)
            if pane_proc is None or _is_zombie(pane_proc.state):
                continue

            if _is_coreagent_pane_host(pane_proc):
                for cid in children_by_pid.get(ppid, []):
                    cproc = procs.get(cid)
                    if cproc is None or _is_zombie(cproc.state):
                        continue
                    if _is_agent_process(cproc):
                        host_alive = True
                        if cid not in seen_roots:
                            seen_roots.add(cid)
                            agent_root_pids.append(cid)
                    elif cproc.comm not in _PROBE_COMMS:
                        extra_child_seeds.append((cid, ppid, pane_proc.comm))
            elif _is_shell_comm(pane_proc.comm):
                direct_kids = [
                    cid
                    for cid in children_by_pid.get(ppid, [])
                    if cid in procs and not _is_zombie(procs[cid].state)
                ]
                main_agent_cid: int | None = None
                for cid in direct_kids:
                    cproc = procs[cid]
                    if _is_agent_process(cproc) or (
                        not _is_shell_comm(cproc.comm)
                        and cproc.comm not in _PROBE_COMMS
                        and cproc.comm == pane.pane_command
                    ):
                        main_agent_cid = cid
                        break
                if main_agent_cid is not None:
                    host_alive = True
                    if main_agent_cid not in seen_roots:
                        seen_roots.add(main_agent_cid)
                        agent_root_pids.append(main_agent_cid)
                for cid in direct_kids:
                    if cid == main_agent_cid:
                        continue
                    cproc = procs[cid]
                    if cproc.comm in _PROBE_COMMS:
                        continue
                    extra_child_seeds.append((cid, ppid, pane_proc.comm))
            elif _is_agent_process(pane_proc):
                host_alive = True
                if ppid not in seen_roots:
                    seen_roots.add(ppid)
                    agent_root_pids.append(ppid)

    # 2. CoreAgent 进程内常驻 runner PID
    snap = core_snaps.get(target_sid)
    if snap is not None and snap.pid and snap.pid in procs and not _is_zombie(procs[snap.pid].state):
        host_alive = True
        if snap.pid not in seen_roots:
            seen_roots.add(snap.pid)
            agent_root_pids.append(snap.pid)

    # 3. 命令行直连（典型如外部终端执行的 `claude --resume <sid>` / `agy --conversation <sid>`）
    cli_matched_pids: list[int] = []
    for pid, proc in procs.items():
        if _is_zombie(proc.state):
            continue
        if _matches_session_cli(proc.args, target_sid):
            cli_matched_pids.append(pid)
    cli_matched_set = set(cli_matched_pids)
    for pid in cli_matched_pids:
        if pid in seen_roots:
            continue
        proc = procs[pid]
        # 若同 sid 下已有更内层的真实 agent 子进程匹配，则跳过外层 wrapper shell / python / uv
        if (_is_shell_comm(proc.comm) or proc.comm in _WRAPPER_COMMS) and any(
            cid in cli_matched_set for cid in children_by_pid.get(pid, [])
        ):
            continue
        parent = procs.get(proc.ppid)
        if parent is not None and parent.pid in cli_matched_set and not (
            _is_shell_comm(parent.comm) or parent.comm in _WRAPPER_COMMS
        ):
            continue
        host_alive = True
        seen_roots.add(pid)
        agent_root_pids.append(pid)

    # 4. 沿进程树遍历全部派生子进程
    collected: list[dict[str, Any]] = []
    visited_child_pids: set[int] = set(seen_roots)
    linked_sids: set[str] = set()
    tmux_label = tmux_names[0] if tmux_names else None
    source = "tmux_pane" if tmux_names else ("coreagent_runner" if snap is not None else "process_tree")

    def _walk(pid: int, direct_parent_pid: int, is_direct_from_agent: bool, root_comm: str) -> None:
        if pid in visited_child_pids or pid == self_pid:
            return
        proc = procs.get(pid)
        if proc is None or _is_zombie(proc.state):
            return
        # 跳过探针自身与无意义的 `ps` 命令
        if proc.comm in _PROBE_COMMS and ("pid=,ppid=" in proc.args or "list-panes" in proc.args):
            return
        visited_child_pids.add(pid)

        parent_proc = procs.get(direct_parent_pid)
        parent_comm = parent_proc.comm if parent_proc else root_comm
        clipped_host = _clip_title(host_title)
        if is_direct_from_agent:
            if is_main_session:
                launched_by_label = f"由当前会话主进程 ({parent_comm} · PID {direct_parent_pid}) 启动"
            else:
                launched_by_label = (
                    f"由子会话「{clipped_host}」主进程 ({parent_comm} · PID {direct_parent_pid}) 启动"
                )
        else:
            if is_main_session:
                launched_by_label = f"由子进程 {parent_comm} (PID {direct_parent_pid}) 启动"
            else:
                launched_by_label = (
                    f"由子会话「{clipped_host}」子进程 {parent_comm} (PID {direct_parent_pid}) 启动"
                )

        linked_sid = _extract_linked_sid(proc.args, target_sid)
        if linked_sid:
            linked_sids.add(linked_sid)

        collected.append(
            {
                "pid": proc.pid,
                "ppid": proc.ppid,
                "comm": proc.comm,
                "command": proc.args,
                "elapsed": proc.etime,
                "state": proc.state,
                "is_running": True,
                "kind": _classify_process_kind(proc),
                "source": source,
                "tmux_name": tmux_label,
                "host_session_id": target_sid,
                "launched_by_pid": direct_parent_pid,
                "launched_by_comm": parent_comm,
                "launched_by_session_id": target_sid,
                "launched_by_label": launched_by_label,
                "linked_session_id": linked_sid,
            }
        )
        for next_pid in children_by_pid.get(pid, []):
            _walk(next_pid, pid, False, root_comm)

    for root_pid in agent_root_pids:
        root_proc = procs.get(root_pid)
        root_comm = root_proc.comm if root_proc else "agent"
        for cid in children_by_pid.get(root_pid, []):
            _walk(cid, root_pid, True, root_comm)

    for cid, lpid, lcomm in extra_child_seeds:
        _walk(cid, lpid, True, lcomm)

    return host_alive, collected, linked_sids


def probe_session_children(sid: str) -> dict[str, Any]:
    """探测会话 ``sid`` 的启动来源、派生子会话与运行中子进程。

    会话编号不属于任何已知家族时抛出 :class:`UnknownSessionFamily`。
    """
    clean_sid = (sid or "").strip()
    record_reader.detect_family(clean_sid)

    cards = record_reader.list_sessions()
    titles = workbench_titles.load()
    open_names = tmux_sessions_service.open_session_names()
    core_alive = coreagent_runner.live_states()
    core_snaps = {s.session_id: s for s in coreagent_runner.live_snapshot()}
    local_ops_ids = workbench_groups.local_ops_session_ids()
    origin_idx = session_origin.load_origin_index()
    procs, children_by_pid = _snapshot_processes()
    panes_by_name = _tmux_panes()

    try:
        from frago.session.async_dispatch import list_dispatch_jobs

        dispatch_jobs = list_dispatch_jobs(active_only=False)
    except Exception:  # noqa: BLE001
        dispatch_jobs = []

    cards_by_sid = {c.session_id: c for c in cards}

    def _title_of(target: str) -> str:
        if target in titles:
            return titles[target]
        card = cards_by_sid.get(target)
        if card is not None and card.title:
            return card.title
        return target

    # 1. 从关系账 + SessionCard 归并全部父子边（包含尚未落盘进 SessionCard 的新记账条目）
    ledger_entries_by_child: dict[str, dict[str, Any]] = {}
    for raw_item in session_origin._ledger_entries():
        parsed = session_origin._parse_entry(raw_item)
        if parsed is not None:
            ledger_entries_by_child[parsed["child"]] = parsed

    children_by_parent: dict[str, list[str]] = {}
    parent_of: dict[str, str] = {}
    relation_of: dict[str, str] = {}

    def _register_edge(parent_id: str | None, child_id: str | None, rel_kind: str | None) -> None:
        p = (parent_id or "").strip()
        c = (child_id or "").strip()
        if not p or not c or p == c:
            return
        parent_of[c] = p
        if rel_kind:
            relation_of[c] = rel_kind
        bucket = children_by_parent.setdefault(p, [])
        if c not in bucket:
            bucket.append(c)

    for c in cards:
        rel_kind = c.relation.kind if c.relation is not None else (
            "dispatch" if c.origin == "worker" else None
        )
        _register_edge(c.parent_session_id, c.session_id, rel_kind)

    for child_id, p_id in origin_idx.parents.items():
        rel = origin_idx.relation_of(child_id)
        _register_edge(p_id, child_id, rel.kind if rel is not None else "dispatch")

    for child_id, entry in ledger_entries_by_child.items():
        _register_edge(entry.get("parent"), child_id, entry.get("kind"))

    # 2. 解析当前会话自身的「由谁启动」(launched_by)
    own_card = cards_by_sid.get(clean_sid)
    own_parent = parent_of.get(clean_sid) or (own_card.parent_session_id if own_card else None)
    own_rel_kind = relation_of.get(clean_sid) or (
        own_card.relation.kind if own_card and own_card.relation else None
    )
    own_origin = (
        "schedule"
        if clean_sid in local_ops_ids
        else (own_card.origin if own_card else origin_idx.origin_of(clean_sid))
    )
    inbound_job = next(
        (j for j in reversed(dispatch_jobs) if (j.target_session_id or "").strip() == clean_sid),
        None,
    )
    launched_by: dict[str, Any] | None = None
    if own_parent:
        parent_title = _title_of(own_parent)
        clipped_parent = _clip_title(parent_title)
        parent_card = cards_by_sid.get(own_parent)
        if own_rel_kind == "branch":
            lb_label = f"从「{clipped_parent}」分出分支"
        elif own_rel_kind == "handoff":
            lb_label = f"从「{clipped_parent}」交接延续"
        elif inbound_job is not None and inbound_job.kind == "employee":
            lb_label = f"由「{clipped_parent}」调用员工启动"
        else:
            lb_label = f"由「{clipped_parent}」派发启动"
        launched_by = {
            "session_id": own_parent,
            "title": parent_title,
            "family": parent_card.family if parent_card else None,
            "relation_kind": own_rel_kind or "dispatch",
            "origin": own_origin,
            "source": "session_origin" if clean_sid in parent_of else "async_dispatch",
            "label": lb_label,
        }
    elif inbound_job is not None and (inbound_job.caller_session_id or "").strip():
        caller_id = inbound_job.caller_session_id.strip()
        caller_title = _title_of(caller_id)
        clipped_caller = _clip_title(caller_title)
        caller_card = cards_by_sid.get(caller_id)
        launched_by = {
            "session_id": caller_id,
            "title": caller_title,
            "family": caller_card.family if caller_card else None,
            "relation_kind": "dispatch",
            "origin": own_origin,
            "source": "async_dispatch",
            "label": (
                f"由「{clipped_caller}」调用员工启动"
                if inbound_job.kind == "employee"
                else f"由「{clipped_caller}」派发启动"
            ),
        }
    elif clean_sid in local_ops_ids:
        launched_by = {
            "session_id": None,
            "title": None,
            "family": None,
            "relation_kind": None,
            "origin": "schedule",
            "source": "local_ops",
            "label": "由本机定时任务 / 自动管理触发",
        }
    elif own_origin == "worker":
        launched_by = {
            "session_id": None,
            "title": None,
            "family": None,
            "relation_kind": "dispatch",
            "origin": "worker",
            "source": "session_origin",
            "label": "由 frago agent 派发启动（未记录上游会话）",
        }

    # 3. 向下收集全部派生子会话（支持多层嵌套派发）
    descendant_edges: list[tuple[str, str]] = []  # (parent_sid, child_sid)
    seen_descendants: set[str] = {clean_sid}
    queue: list[tuple[str, int]] = [(clean_sid, 0)]
    while queue:
        cur_sid, depth = queue.pop(0)
        if depth >= _MAX_DESCENDANT_DEPTH:
            continue
        for kid_sid in children_by_parent.get(cur_sid, []):
            if kid_sid in seen_descendants:
                continue
            seen_descendants.add(kid_sid)
            descendant_edges.append((cur_sid, kid_sid))
            queue.append((kid_sid, depth + 1))

    # 同时纳入以 clean_sid 或其后代为 caller 的 async_dispatch 任务（覆盖 send/resume 到已有员工会话）
    now_ms = int(time.time() * 1000)
    jobs_by_target: dict[str, list[Any]] = {}
    for job in dispatch_jobs:
        cid = (job.caller_session_id or "").strip()
        tid = (job.target_session_id or "").strip()
        if not cid or not tid or cid not in seen_descendants or tid == clean_sid:
            continue
        jobs_by_target.setdefault(tid, []).append(job)
        if tid not in seen_descendants:
            seen_descendants.add(tid)
            descendant_edges.append((cid, tid))

    # 4. 探测主会话自身的宿主与子进程树
    resolved_own_tmux: str | None = None
    if tmux_name_for(clean_sid) not in panes_by_name and panes_by_name:
        with contextlib.suppress(Exception):
            link = tmux_sessions_service.find_for_session(clean_sid)
            if link is not None:
                resolved_own_tmux = link.name

    host_alive, main_procs, _ = _collect_session_processes(
        clean_sid,
        host_title=_title_of(clean_sid),
        is_main_session=True,
        procs=procs,
        children_by_pid=children_by_pid,
        panes_by_name=panes_by_name,
        core_snaps=core_snaps,
        resolved_tmux_name=resolved_own_tmux,
    )
    # 常驻 CoreAgent 进程答完一轮后会进入 20 分钟 idle 等待（core_alive[sid] is False），
    # 若此时无任何活跃子进程，不应把常驻缓存误报为「外部进程运行中」。
    if core_alive.get(clean_sid) is False and not main_procs:
        host_alive = False

    # 5. 组装 child_sessions 并探测活跃子会话的进程树
    child_sessions: list[dict[str, Any]] = []
    all_processes: list[dict[str, Any]] = list(main_procs)
    seen_proc_pids: set[int] = {p["pid"] for p in all_processes}

    def _job_rank(job: Any) -> tuple[int, int]:
        st = (getattr(job, "status", None) or "").strip().lower()
        ds = (getattr(job, "delivery_state", None) or "").strip().lower()
        active_score = 3 if st in ("pending", "running") else (2 if st == "delivering" or ds in ("queued", "delivering") else 1)
        ts = _iso_to_epoch_ms(getattr(job, "updated_at", None)) or _iso_to_epoch_ms(getattr(job, "created_at", None)) or 0
        return (active_score, ts)

    for parent_sid, child_sid in descendant_edges:
        card = cards_by_sid.get(child_sid)
        ledger = ledger_entries_by_child.get(child_sid)
        rel_jobs = jobs_by_target.get(child_sid, [])
        latest_job = max(rel_jobs, key=_job_rank) if rel_jobs else None

        tname = tmux_name_for(child_sid)
        in_tmux = tname in open_names
        snap = core_snaps.get(child_sid)
        core_busy = core_alive.get(child_sid)
        child_host_alive, child_procs, _ = _collect_session_processes(
            child_sid,
            host_title=_title_of(child_sid),
            is_main_session=False,
            procs=procs,
            children_by_pid=children_by_pid,
            panes_by_name=panes_by_name,
            core_snaps=core_snaps,
        )
        for cp in child_procs:
            if cp["pid"] not in seen_proc_pids:
                seen_proc_pids.add(cp["pid"])
                all_processes.append(cp)

        alive = bool(
            in_tmux
            or child_sid in core_alive
            or snap is not None
            or child_host_alive
        )

        # 判子会话真实运行态：结合卡片、进程、tmux、async_dispatch 四方实况
        card_status = card.status if card is not None else "idle"
        if card is not None and card_status != "error":
            if alive and card.last_kind in IN_PROGRESS_KINDS:
                card_status = "running"
            elif not alive and card_status == "running":
                card_status = "done" if card.last_kind == "agent.say" else "idle"

        job_status = (getattr(latest_job, "status", None) or "").strip().lower()
        job_delivery = (getattr(latest_job, "delivery_state", None) or "").strip().lower()
        job_created_ms = _iso_to_epoch_ms(getattr(latest_job, "created_at", None))
        job_completed_ms = _iso_to_epoch_ms(getattr(latest_job, "completed_at", None))
        job_updated_ms = _iso_to_epoch_ms(getattr(latest_job, "updated_at", None))

        job_live_running = False
        job_delivering = False
        if latest_job is not None:
            if job_status in ("pending", "running"):
                if alive or (
                    job_created_ms is not None and (now_ms - job_created_ms) <= _DISPATCH_STARTUP_GRACE_MS
                ):
                    job_live_running = True
            elif job_status == "delivering" or (
                job_status == "completed" and job_delivery in ("queued", "delivering")
            ):
                stale_delivering = (
                    job_status == "delivering"
                    and job_completed_ms is None
                    and job_updated_ms is not None
                    and (now_ms - job_updated_ms) > _DISPATCH_STALE_DELIVERING_MS
                    and not alive
                )
                parent_reply = cards_by_sid.get(parent_sid)
                parent_reply_ms = getattr(parent_reply, "last_reply_at", None)
                job_ts_ms = job_completed_ms or job_updated_ms
                overtaken = (
                    job_ts_ms is not None
                    and isinstance(parent_reply_ms, int)
                    and parent_reply_ms > job_ts_ms + _DISPATCH_REPLY_OVERTAKEN_GRACE_MS
                )
                if not stale_delivering and not overtaken:
                    job_delivering = True

        rel_kind = relation_of.get(child_sid) or (
            card.relation.kind if card and card.relation else "dispatch"
        )
        # 对一次性 worker（dispatch），只要承载进程或任务单还在跑就算运行中（排除已闲置的常驻 CoreAgent）；
        # 对 branch / handoff，则以实际回合忙碌或进程活跃为准
        is_running = bool(
            core_busy is True
            or job_live_running
            or card_status == "running"
            or bool(child_procs)
            or (rel_kind == "dispatch" and child_host_alive and core_busy is not False)
        )
        if is_running:
            effective_status = "running"
        elif job_delivering:
            effective_status = "delivering"
        elif card_status == "error" or job_status == "failed":
            effective_status = "error"
        elif card_status == "done" or job_status == "completed":
            effective_status = "done"
        else:
            effective_status = "idle"

        prompt_head = (
            (getattr(latest_job, "task_summary", None) or "").strip()
            or ((ledger or {}).get("prompt_head") or "").strip()
        )
        resolved_title = _title_of(child_sid)
        if resolved_title == child_sid and prompt_head:
            resolved_title = prompt_head[:80]

        launcher_title = _title_of(parent_sid)
        dispatch_kind = getattr(latest_job, "kind", None) if latest_job else None
        source = (
            "both"
            if (card is not None or ledger is not None) and latest_job is not None
            else ("async_dispatch" if latest_job is not None else "session_origin")
        )
        started_at = (
            card.created_at
            if card is not None
            else (
                job_created_ms
                or (int(ledger["at"]) * 1000 if ledger and ledger.get("at") else None)
            )
        )

        child_sessions.append(
            {
                "session_id": child_sid,
                "title": resolved_title,
                "family": (
                    card.family
                    if card is not None
                    else (
                        getattr(latest_job, "agent", None)
                        or (ledger or {}).get("agent_type")
                        or "unknown"
                    )
                ),
                "relation_kind": rel_kind,
                "origin": (
                    card.origin
                    if card is not None
                    else ("human" if rel_kind == "branch" else "worker")
                ),
                "status": effective_status,
                "is_running": is_running,
                "alive": alive,
                "in_tmux": in_tmux,
                "tmux_name": tname if in_tmux else None,
                "launched_by_session_id": parent_sid,
                "launched_by_title": launcher_title,
                "launched_by_label": _relation_label(
                    rel_kind,
                    is_direct=(parent_sid == clean_sid),
                    launcher_title=launcher_title,
                    dispatch_kind=dispatch_kind,
                ),
                "source": source,
                "job_id": getattr(latest_job, "job_id", None) if latest_job else None,
                "delivery_state": getattr(latest_job, "delivery_state", None) if latest_job else None,
                "employee_id": (
                    (card.employee_id if card else None)
                    or (getattr(latest_job, "employee_id", None) if latest_job else None)
                ),
                "prompt_head": prompt_head,
                "started_at": started_at,
                "last_active_at": card.last_active_at if card is not None else job_updated_ms,
            }
        )

    # 运行中 / 待回传排在最前，其余按最近活动或开始时刻倒序
    _status_order = {"running": 0, "delivering": 1, "error": 2, "idle": 3, "done": 4}
    child_sessions.sort(
        key=lambda item: (
            _status_order.get(item["status"], 9),
            -(item.get("last_active_at") or item.get("started_at") or 0),
        )
    )

    running_children = sum(1 for c in child_sessions if c["is_running"])
    delivering_children = sum(1 for c in child_sessions if c["status"] == "delivering")
    running_processes = sum(1 for p in all_processes if p["is_running"])

    return {
        "session_id": clean_sid,
        "launched_by": launched_by,
        "summary": {
            "total_children": len(child_sessions),
            "running_children": running_children,
            "delivering_children": delivering_children,
            "total_processes": len(all_processes),
            "running_processes": running_processes,
            "has_running": bool(running_children > 0 or delivering_children > 0 or running_processes > 0),
            "host_alive": host_alive,
        },
        "child_sessions": child_sessions,
        "child_processes": all_processes,
    }


__all__ = ["probe_session_children"]
