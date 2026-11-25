"""WebUI 会话集群的空闲回收巡检 —— Phase 2 生命周期状态机。

spec 20260625-webui-session-lifecycle-mediator / Phase 2：server lifespan 内的
周期后台任务，定期扫描 UI runner 常驻的 tmux claude 会话，把「自最后一个终结性
stop_reason 起静默超过 idle_timeout_secs」的会话关掉（kill tmux），释放内存。

设计要点：
- **停没停看记录、停了多久看池**：「最新一轮终结没有」问会话自己的记录（claude 的
  jsonl / codex 的 rollout / opencode 的会话库），不看页面有没有输入——手动 attach
  敲入也落同一份记录，双驾驶来源天然统一；而静默时长从 ``session.last_active_at``
  起算，NEVER 用记录里的时间戳（``--resume`` 一个旧 transcript 时那个时间戳是几小时
  前的，会把刚起来的会话当场判成「闲了几小时」回收，见 ui_session_runner._idle_age）。
- **干活中绝不误杀**：最新一轮还没终结、或本进程正驱动着这一轮的会话不计时。具体
  逻辑在 UiSessionRunner.evict_idle，本服务只管周期触发。
- **复用同一 runner 单例**：操作的就是 ui_session_runner.get_runner() 持有的那个 pool。
- **阈值实时取 config**：每轮读 ~/.frago/config.json -> webui_sessions.idle_timeout_secs，
  改配置无需重启即生效。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 巡检间隔：远小于默认 30min 阈值，保证回收及时又不空转。
_SCAN_INTERVAL_S = 60.0
_SHELL_NAMES = frozenset({"zsh", "bash", "sh", "fish", "dash", "tcsh", "ksh"})


@dataclass(frozen=True)
class _OrphanTmuxPane:
    tmux_name: str
    session_id: str
    attached_count: int
    activity_ts: float
    pane_cmd: str
    pane_dead: bool


def _list_coreagent_tmux_panes() -> list[_OrphanTmuxPane]:
    """Enumerate live ``frago-agent-core_*`` tmux sessions with attachment, idle, and foreground cmd."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    try:
        sess_res = subprocess.run(
            [
                "tmux",
                "list-sessions",
                "-F",
                "#{session_name}\t#{session_attached}\t#{session_activity}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if sess_res.returncode != 0:
        return []

    pane_info: dict[str, tuple[str, bool]] = {}
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        pane_res = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}\t#{pane_current_command}\t#{pane_dead}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if pane_res.returncode == 0:
            for line in (pane_res.stdout or "").splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    sname = parts[0].strip()
                    cmd = parts[1].strip().lower()
                    dead = parts[2].strip() == "1"
                    pane_info.setdefault(sname, (cmd, dead))

    out: list[_OrphanTmuxPane] = []
    for line in (sess_res.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        sname = parts[0].strip()
        if not sname.startswith("frago-agent-core_"):
            continue
        sid = sname[len("frago-agent-") :]
        try:
            attached = int(parts[1].strip() or "0")
        except ValueError:
            attached = 0
        try:
            act_ts = float(parts[2].strip() or "0")
        except ValueError:
            act_ts = 0.0
        cmd, dead = pane_info.get(sname, ("", False))
        out.append(
            _OrphanTmuxPane(
                tmux_name=sname,
                session_id=sid,
                attached_count=attached,
                activity_ts=act_ts,
                pane_cmd=cmd,
                pane_dead=dead,
            )
        )
    return out


def _kill_tmux_session(tmux_name: str) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        res = subprocess.run(
            ["tmux", "kill-session", "-t", tmux_name],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class UiSessionLifecycleService:
    """周期回收空闲 WebUI 会话的后台服务（单例）。"""

    _instance: UiSessionLifecycleService | None = None

    def __init__(self, *, scan_interval_s: float = _SCAN_INTERVAL_S) -> None:
        self._scan_interval_s = scan_interval_s
        self._task: asyncio.Task[None] | None = None

    @classmethod
    def get_instance(cls) -> UiSessionLifecycleService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        with contextlib.suppress(Exception):
            summary = await asyncio.to_thread(self.reconcile_startup_orphans)
            if any(summary.values()):
                logger.info("Startup orphan reconciliation summary: %s", summary)
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "UiSessionLifecycleService started (scan every %.0fs)",
            self._scan_interval_s,
        )

    def reconcile_startup_orphans(
        self,
        *,
        now_s: float | None = None,
        resident_idle_timeout_s: float = 1800.0,
        worker_idle_timeout_s: float = 300.0,
    ) -> dict[str, int]:
        """Take over and clean up orphaned ``frago-agent-core_*`` tmux panes, markers, and stale states on startup."""
        from frago.agent_driver.coreagent_pane_host import (
            _pid_is_alive,
            active_run_marker_path,
            panes_dir,
        )
        from frago.init.config_manager import load_config
        from frago.server.services import coreagent_runner
        from frago.session import coreagent_store
        from frago.session.models import SessionStatus
        from frago.session.service import (
            can_write_ontology_store,
            collect_live_runtime_probes,
            get_default_session_service,
        )

        cur_now = float(now_s if now_s is not None else time.time())
        try:
            cfg = load_config().webui_sessions
            if getattr(cfg, "idle_timeout_secs", None):
                resident_idle_timeout_s = float(cfg.idle_timeout_secs)
        except Exception:  # noqa: BLE001
            pass

        in_process_sids = set(coreagent_runner.live_states().keys())
        probes = collect_live_runtime_probes(now_s=cur_now)
        onto_svc = get_default_session_service()
        can_write_onto = can_write_ontology_store(onto_svc)

        markers_cleaned = 0
        tmux_killed = 0
        onto_reconciled = 0

        # 1. Clean dead .active_run markers
        live_marker_sids: set[str] = set()
        with contextlib.suppress(Exception):
            pdir = panes_dir()
            if pdir.is_dir():
                for marker in pdir.glob("*.active_run"):
                    keep = False
                    run_sid = marker.stem
                    with contextlib.suppress(OSError):
                        run_str = marker.read_text(encoding="utf-8", errors="replace").strip()
                        if run_str:
                            run_dir = Path(run_str)
                            pid_file = run_dir / "core.pid"
                            if (
                                run_dir.is_dir()
                                and not (run_dir / "exit.code").is_file()
                                and not (run_dir / "superseded").is_file()
                                and pid_file.is_file()
                            ):
                                pid = int(pid_file.read_text(encoding="utf-8").strip())
                                if _pid_is_alive(pid):
                                    keep = True
                                    launch_file = run_dir / "launch.json"
                                    if launch_file.is_file():
                                        with contextlib.suppress(Exception):
                                            ldata = json.loads(
                                                launch_file.read_text(encoding="utf-8")
                                            )
                                            if isinstance(ldata, dict) and ldata.get("session_id"):
                                                run_sid = str(ldata["session_id"]).strip()
                    if keep:
                        live_marker_sids.add(marker.stem)
                        if run_sid:
                            live_marker_sids.add(run_sid)
                    else:
                        with contextlib.suppress(OSError):
                            marker.unlink(missing_ok=True)
                            markers_cleaned += 1

        # 2. Reconcile orphaned frago-agent-core_* tmux panes
        onto_updates: list[tuple[Any, ...]] = []
        panes = _list_coreagent_tmux_panes()
        for pane in panes:
            sid = pane.session_id
            if (
                sid in in_process_sids
                or pane.attached_count > 0
                or sid in probes.live_drive_pids
                or sid in probes.live_dispatch_targets
            ):
                continue

            onto_rec = onto_svc.get_session(sid)
            is_worker = bool(
                onto_rec is not None
                and (onto_rec.is_worker or onto_rec.origin == "worker")
            )
            idle_limit = worker_idle_timeout_s if is_worker else resident_idle_timeout_s

            stats = None
            with contextlib.suppress(Exception):
                sfile = coreagent_store.find_session_file(sid)
                if sfile is not None:
                    stats = coreagent_store.inspect_session_file(sfile)

            has_live_core_proc = sid in live_marker_sids
            pane_shell_exited = pane.pane_dead or pane.pane_cmd in _SHELL_NAMES
            should_kill = False
            if pane_shell_exited or not has_live_core_proc:
                should_kill = True
            else:
                last_act_ts = pane.activity_ts
                if stats is not None and stats.last_activity is not None:
                    last_act_ts = max(last_act_ts, stats.last_activity.timestamp())
                if last_act_ts > 0 and (cur_now - last_act_ts) >= idle_limit:
                    should_kill = True

            if should_kill:
                if _kill_tmux_session(pane.tmux_name):
                    tmux_killed += 1
                with contextlib.suppress(OSError):
                    active_run_marker_path(sid).unlink(missing_ok=True)
                if onto_rec is not None and onto_rec.lifecycle_state in ("running", "queued"):
                    if stats is not None and stats.status == SessionStatus.ERROR:
                        onto_updates.append((sid, "error", "startup_orphan_error"))
                    elif stats is not None and stats.last_event_kind in (
                        "assistant_tool",
                        "assistant_think",
                        "user",
                    ):
                        onto_updates.append((sid, "error", "startup_orphan_interrupted"))
                    else:
                        onto_updates.append((sid, "completed", ""))
            elif (
                onto_rec is not None
                and onto_rec.lifecycle_state in ("running", "queued")
                and stats is not None
            ):
                if stats.status == SessionStatus.ERROR:
                    onto_updates.append((sid, "error", "startup_orphan_error"))
                elif stats.last_event_kind in ("assistant_text", "turn_end"):
                    onto_updates.append((sid, "awaiting_input", None, "end_turn"))

        # 3. Reconcile stale coreagent ontology records with zero live runtime processes
        pane_sids = {p.session_id for p in panes}
        queued_sids = {u[0] for u in onto_updates}
        for rec in onto_svc.list_sessions():
            sid = rec.session_id
            if (
                not sid
                or rec.agent_kernel != "coreagent"
                or rec.lifecycle_state not in ("running", "queued")
                or sid in queued_sids
                or sid in in_process_sids
                or sid in live_marker_sids
                or sid in pane_sids
                or sid in probes.live_drive_pids
                or sid in probes.live_dispatch_targets
            ):
                continue
            if (cur_now - float(rec.updated_at or 0)) < 60.0:
                continue
            stats = None
            with contextlib.suppress(Exception):
                sfile = coreagent_store.find_session_file(sid)
                if sfile is not None:
                    stats = coreagent_store.inspect_session_file(sfile)
            if stats is not None and stats.status == SessionStatus.ERROR:
                onto_updates.append((sid, "error", "startup_orphan_error"))
            elif stats is not None and stats.last_event_kind in ("assistant_text", "turn_end"):
                onto_updates.append((sid, "completed", ""))
            elif stats is not None and stats.last_event_kind in (
                "assistant_tool",
                "assistant_think",
                "user",
            ):
                onto_updates.append((sid, "error", "startup_orphan_interrupted"))

        if onto_updates and can_write_onto:
            with contextlib.suppress(Exception):
                onto_reconciled = onto_svc.store.batch_reconcile_states(onto_updates)

        return {
            "markers_cleaned": markers_cleaned,
            "tmux_killed": tmux_killed,
            "onto_reconciled": onto_reconciled,
        }

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._scan_interval_s)
            try:
                await self._scan_once()
            except Exception as e:  # 单轮失败不拖垮巡检循环
                logger.warning("UI session idle scan failed: %s", e)

    async def _scan_once(self) -> None:
        from frago.init.config_manager import load_config
        from frago.server.services.harness_lifecycle_coordinator import (
            AgentHarnessLifecycleCoordinator,
        )

        cfg = load_config().webui_sessions
        if getattr(cfg, "global_reclaim_enabled", False):
            coordinator = AgentHarnessLifecycleCoordinator.get_instance()
            results = await coordinator.scan_once()
            if results:
                reclaimed_names = [str(r.get("harness")) for r in results if r.get("ok")]
                if reclaimed_names:
                    logger.info(
                        "Reclaimed %d idle harness(es) via coordinator: %s",
                        len(reclaimed_names),
                        ", ".join(reclaimed_names),
                    )
            return

        from frago.server.services.ui_session_runner import get_runner

        timeout_s = cfg.idle_timeout_secs
        runner = get_runner()
        # 探针读 jsonl + tmux kill 都是阻塞 IO，挪到线程里跑。
        evicted = await asyncio.to_thread(runner.evict_idle, float(timeout_s))
        if evicted:
            logger.info(
                "Reclaimed %d idle WebUI session(s): %s",
                len(evicted),
                ", ".join(evicted),
            )
