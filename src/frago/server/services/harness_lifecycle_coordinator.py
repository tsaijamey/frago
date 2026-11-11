"""AgentHarness (tmux) 全域生命周期协调器。

统一收口系统级现存所有 frago-agent-* 承载实例与 CoreAgent 容器实例的生命周期治理，
破除 8093 单进程内存池孤岛，杜绝跨进程异步派发、CLI 唤醒及服务重启遗留会话脱管泄漏。

核心机制：
1. 全域发现：枚举本机全部 frago-agent-* 前缀 tmux 承载与 coreagent_runner 实例；
2. 六道刚性安全保护守卫（Guard 1–6）：
   - Guard 1: 人类终端附着保护（session_attached > 0 绝对豁免）；
   - Guard 2: 宿主借住保护（tmux_target is not None 仅退 shell，严禁 kill-session）；
   - Guard 3: 活跃异步派发单保护（async_dispatch 处于 pending/running/delivering 时，
             target_session_id 与 caller_session_id 双方均刚性豁免）；
   - Guard 4: 待投递消息队列保护（workbench_queue 存在待注入消息时绝对豁免）；
   - Guard 5: 物理忙碌与后台子外壳保护（is_busy 或 shells still running 绝对豁免）；
   - Guard 6: 逐条点名安全关闭铁律（池内委派 WarmSessionPool.evict，池外逐条点名，严禁 kill-server）。
3. 三维安全时间锚点与首次观测安全基线（First-Observed Safety Anchor）：
   - 首次被全域协调器观测到的池外承载必须经历 observed_cooling_grace_secs（默认 120s）
     冷却宽限期，严防服务重启瞬间读到旧文件时间戳误杀刚唤醒会话；
   - 区分一次性后台 Worker 冷却（默认 300s）与普通/工作台会话闲置超时（默认 1800s）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from frago.init.config_manager import load_config
from frago.session.adapters.kernel_adapters import (
    HarnessIdleVerdict,
    get_kernel_session_adapter,
)

logger = logging.getLogger(__name__)

_PREFIX = "frago-agent-"
_SCAN_INTERVAL_S = 60.0

# 测试隔离钩子：允许单测拦截底层 tmux 执行与进程命令获取
_tmux_executor_override: Callable[..., str] | None = None


def _run_tmux(*args: str) -> str:
    """底层调用 tmux 命令，测试时可被 _tmux_executor_override 拦截隔离。"""
    if _tmux_executor_override is not None:
        return _tmux_executor_override(*args)
    try:
        proc = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError) as err:
        logger.debug("tmux command %s failed: %s", args, err)
        return ""


@dataclass(frozen=True)
class TmuxHarnessMeta:
    """物理承载实例元数据。"""

    name: str
    session_id: str
    kernel: str
    created_epoch_secs: float
    attached_clients: int
    pane_command: str = ""
    pane_pid: int | None = None
    pane_text: str = ""
    is_borrowed: bool = False


@dataclass(frozen=True)
class GuardVerdict:
    """安全守卫评估裁决。"""

    is_protected: bool
    guard_name: str = ""
    reason: str = ""


class AgentHarnessLifecycleCoordinator:
    """全域 AgentHarness 生命周期协调器（单例）。"""

    _instance: AgentHarnessLifecycleCoordinator | None = None

    def __init__(self, *, scan_interval_s: float = _SCAN_INTERVAL_S) -> None:
        self._scan_interval_s = scan_interval_s
        self._task: asyncio.Task[None] | None = None
        # 首次观测时间基线字典：harness_name -> float (epoch seconds)
        self._observed_tracker: dict[str, float] = {}

    @classmethod
    def get_instance(cls) -> AgentHarnessLifecycleCoordinator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "AgentHarnessLifecycleCoordinator started (scan interval: %.0fs)",
            self._scan_interval_s,
        )

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
                await self.scan_once()
            except Exception as e:  # 单轮异常不拖垮全局循环
                logger.warning("AgentHarnessLifecycleCoordinator loop scan failed: %s", e)

    async def scan_once(self) -> list[dict[str, Any]]:
        """执行单轮全域承载发现、守卫检查与安全回收。"""
        cfg = load_config().webui_sessions
        if not getattr(cfg, "global_reclaim_enabled", True):
            # 若配置显式关闭全域回收，安全回退至仅回收热池内部
            from frago.server.services.ui_session_runner import get_runner

            timeout_s = float(cfg.idle_timeout_secs)
            evicted = await asyncio.to_thread(get_runner().evict_idle, timeout_s)
            return [{"harness": sid, "status": "evicted_pool_fallback"} for sid in evicted]

        return await asyncio.to_thread(self._scan_and_reclaim_sync, cfg)

    def _scan_and_reclaim_sync(self, cfg: Any) -> list[dict[str, Any]]:
        now = time.time()
        discovered = self.discover_harnesses()
        results: list[dict[str, Any]] = []

        idle_timeout_secs = float(getattr(cfg, "idle_timeout_secs", 1800))
        worker_timeout_secs = float(getattr(cfg, "worker_idle_timeout_secs", 300))
        grace_secs = float(getattr(cfg, "observed_cooling_grace_secs", 120))

        active_names = {h.name for h in discovered}
        # 同步修剪已自然消亡的会话追踪记录，防止内存泄漏
        stale_keys = [k for k in self._observed_tracker if k not in active_names]
        for k in stale_keys:
            self._observed_tracker.pop(k, None)

        for harness in discovered:
            # 1. 执行六大刚性安全守卫过滤
            guard = self.evaluate_guards(harness)
            if guard.is_protected:
                logger.debug(
                    "Harness %s (sid=%s) protected by %s: %s",
                    harness.name,
                    harness.session_id,
                    guard.guard_name,
                    guard.reason,
                )
                continue

            # 2. 多维时间锚点与空闲时长裁决
            idle_age = self.compute_harness_idle_age(harness, now=now, grace_secs=grace_secs)
            if idle_age is None:
                continue

            # 3. 分级阈值判定（一次性后台 Worker vs. 普通工作台/员工会话）
            threshold = self._resolve_timeout_threshold(
                harness.session_id,
                default_timeout=idle_timeout_secs,
                worker_timeout=worker_timeout_secs,
            )

            if idle_age >= threshold:
                reclaimed = self.reclaim_harness(harness)
                results.append(reclaimed)
                if reclaimed.get("ok"):
                    self._observed_tracker.pop(harness.name, None)
                    logger.info(
                        "Reclaimed idle harness %s (sid=%s, idle=%.1fs >= %.1fs, via=%s)",
                        harness.name,
                        harness.session_id,
                        idle_age,
                        threshold,
                        reclaimed.get("via"),
                    )

        return results

    def discover_harnesses(self) -> list[TmuxHarnessMeta]:
        """全域发现本机存活的 frago-agent-* 承载实例与 CoreAgent 容器实例。"""
        from frago.server.services import tmux_sessions_service as tss

        lines = _run_tmux(
            "list-sessions",
            "-F",
            "#{session_name} #{session_created} #{session_attached}",
        ).splitlines()

        harnesses: list[TmuxHarnessMeta] = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            name, created_str, attached_str = parts[0], parts[1], parts[2]
            if not name.startswith(_PREFIX):
                continue

            try:
                created_epoch = float(created_str)
            except ValueError:
                created_epoch = time.time()
            try:
                attached_count = int(attached_str)
            except ValueError:
                attached_count = 0

            pane_ansi = _run_tmux("capture-pane", "-p", "-e", "-t", name)
            pane_text = tss._plain(pane_ansi) if hasattr(tss, "_plain") else pane_ansi
            label = name[len(_PREFIX) :]

            session_id = tss._resolve_session_id(label, pane_text) or label
            kernel = tss._detect_session_kernel(session_id)

            # 获取前台命令与 pid
            pane_info = _run_tmux(
                "list-panes", "-t", name, "-F", "#{pane_current_command} #{pane_pid}"
            )
            pane_cmd = ""
            pane_pid: int | None = None
            if pane_info:
                p_parts = pane_info.strip().split()
                if len(p_parts) >= 1:
                    pane_cmd = p_parts[0]
                if len(p_parts) >= 2:
                    with contextlib.suppress(ValueError):
                        pane_pid = int(p_parts[1])

            # 检查是否为借住模式宿主
            is_borrowed = False
            pooled_session = self._find_pooled_session(session_id)
            if pooled_session is not None:
                is_borrowed = getattr(pooled_session, "tmux_target", None) is not None

            harnesses.append(
                TmuxHarnessMeta(
                    name=name,
                    session_id=session_id,
                    kernel=kernel,
                    created_epoch_secs=created_epoch,
                    attached_clients=attached_count,
                    pane_command=pane_cmd,
                    pane_pid=pane_pid,
                    pane_text=pane_text,
                    is_borrowed=is_borrowed,
                )
            )

        return harnesses

    def evaluate_guards(self, harness: TmuxHarnessMeta) -> GuardVerdict:
        """评估六大刚性安全守卫，任一守卫触发即绝对豁免回收。"""
        # Guard 1: 人类在场与终端附着保护
        if harness.attached_clients > 0:
            return GuardVerdict(
                is_protected=True,
                guard_name="Guard 1 (Human Presence)",
                reason=f"Attached clients: {harness.attached_clients}",
            )

        # Guard 2: 借住模式宿主窗口保护（由销毁策略分流，非 frago-agent- 承载已被前缀过滤）
        if not harness.name.startswith(_PREFIX):
            return GuardVerdict(
                is_protected=True,
                guard_name="Guard 2 (Host Borrowing)",
                reason="Harness does not bear frago-agent- prefix",
            )

        # Guard 3: 活跃异步派发单双向保护（执行方 target 与调用方 caller 均保护）
        if self._is_async_dispatch_active(harness.session_id):
            return GuardVerdict(
                is_protected=True,
                guard_name="Guard 3 (Active Async Dispatch)",
                reason="Session has pending/running dispatch jobs as caller or target",
            )

        # Guard 4: 待投递消息队列保护
        if self._has_pending_workbench_queue(harness.session_id):
            return GuardVerdict(
                is_protected=True,
                guard_name="Guard 4 (Pending Workbench Queue)",
                reason="Session has pending un-injected workbench messages",
            )

        # Guard 5: 物理忙碌与后台运行子外壳保护
        # 先查内存热池状态
        pooled = self._find_pooled_session(harness.session_id)
        if pooled is not None and getattr(pooled, "status", None) == "busy":
            return GuardVerdict(
                is_protected=True,
                guard_name="Guard 5 (Pool Busy)",
                reason="In-memory pooled session is currently busy",
            )

        # 调内核适配器探针
        try:
            adapter = get_kernel_session_adapter(harness.kernel)
            idle_verdict: HarnessIdleVerdict = adapter.probe_harness_idle(
                harness.session_id, harness.pane_text
            )
            if idle_verdict.has_running_subshells:
                return GuardVerdict(
                    is_protected=True,
                    guard_name="Guard 5 (Subshells Running)",
                    reason=f"Background subshells running: {idle_verdict.detail}",
                )
            if idle_verdict.is_busy or not idle_verdict.is_terminal_idle:
                return GuardVerdict(
                    is_protected=True,
                    guard_name="Guard 5 (Harness Busy)",
                    reason=f"Physical harness busy: {idle_verdict.detail}",
                )
        except Exception as err:
            # 判不出忙就当忙，宁可少关一个也不误杀
            return GuardVerdict(
                is_protected=True,
                guard_name="Guard 5 (Probe Error Fallback)",
                reason=f"Adapter probe raised exception: {err}",
            )

        return GuardVerdict(is_protected=False)

    def compute_harness_idle_age(
        self,
        harness: TmuxHarnessMeta,
        *,
        now: float,
        grace_secs: float,
    ) -> float | None:
        """基于三维时间锚点融合算法与首次观测安全基线计算承载静默空闲时长。"""
        session_id = harness.session_id

        # 坏壳特殊收口分支：窗格已完全退回登录 shell，且无未决派发
        is_dead_shell = harness.pane_command.lower() in (
            "zsh",
            "bash",
            "sh",
            "fish",
            "dash",
        )

        # 检查业务轮次是否已终结
        try:
            adapter = get_kernel_session_adapter(harness.kernel)
            completion = adapter.probe_turn_completion(session_id)
            if not completion.done and not is_dead_shell:
                # 轮次未完且不是已退 shell 空壳 → 不算空闲
                return None
        except Exception:
            if not is_dead_shell:
                return None

        # 1. 第一优先级：内存热池本池最后活动时刻
        pooled = self._find_pooled_session(session_id)
        if pooled is not None:
            last_active = getattr(pooled, "last_active_at", None)
            if last_active is None:
                return None
            return max(0.0, now - last_active.timestamp())

        # 2. 第二优先级：异步派发任务账本完成时刻（若来自 async_dispatch）
        completed_dispatch_ts = self._get_latest_dispatch_completion_ts(session_id)
        if completed_dispatch_ts is not None:
            return max(0.0, now - completed_dispatch_ts)

        # 3. 第三优先级：池外遗留实例与跨重启会话 —— 首次观测安全计时基线
        first_observed = self._observed_tracker.setdefault(harness.name, now)
        cooling_duration = now - first_observed

        # 刚重启安全冷却宽限期：任何首次被观测到的池外实例，必须至少在本机稳定被连续观测满 grace_secs
        if cooling_duration < grace_secs:
            logger.debug(
                "Harness %s in cooling grace period (%.1fs < %.1fs), deferred",
                harness.name,
                cooling_duration,
                grace_secs,
            )
            return None

        # 结合创建时间戳与转录文件修改时间戳
        created_at_ts = harness.created_epoch_secs
        transcript_ts = self._get_transcript_mtime(session_id, harness.kernel)

        activity_anchor = max(created_at_ts, transcript_ts or created_at_ts)
        measured_idle = now - activity_anchor

        # 安全下界约束：空闲时长不得大于自首次被观测以来的时间，除非有确凿元数据
        return max(0.0, min(measured_idle, cooling_duration + (now - created_at_ts)))

    def reclaim_harness(self, harness: TmuxHarnessMeta) -> dict[str, Any]:
        """Guard 6 逐条点名安全关闭铁律：池内走 pool.evict，池外逐条点名。"""
        from frago.server.services.ui_session_runner import get_runner

        runner = get_runner()
        session_id = harness.session_id

        # 若在热池内，委派热池安全驱逐（同步清理内部内存状态）
        pool = getattr(runner, "_pool", None)
        if pool is not None and hasattr(pool, "has") and pool.has(session_id):
            evicted = runner.evict(session_id)
            return {
                "harness": harness.name,
                "session_id": session_id,
                "ok": evicted,
                "via": "warm_pool",
            }

        # 若在 coreagent_runner 中有句柄，先停止
        if harness.session_id.startswith("core_"):
            try:
                from frago.server.services import coreagent_runner

                stopped = coreagent_runner.stop(harness.session_id, by="全域生命周期协调器")
                if stopped.get("stopped"):
                    return {
                        "harness": harness.name,
                        "session_id": session_id,
                        "ok": True,
                        "via": "coreagent_runner",
                    }
            except Exception as e:
                logger.debug("coreagent_runner.stop failed for %s: %s", session_id, e)

        # 借住模式宿主窗口：只发送退出键序列，严禁 kill-session
        if harness.is_borrowed:
            self._quit_borrowed_harness(harness)
            return {
                "harness": harness.name,
                "session_id": session_id,
                "ok": True,
                "via": "borrowed_quit",
            }

        # 池外实例：逐条点名关闭
        out = _run_tmux("kill-session", "-t", harness.name)
        ok = not _run_tmux("has-session", "-t", harness.name)
        return {
            "harness": harness.name,
            "session_id": session_id,
            "ok": ok,
            "via": "tmux_named_kill",
            "output": out,
        }

    # ── 内部辅助判据方法 ──────────────────────────────────────────────

    def _find_pooled_session(self, session_id: str) -> Any | None:
        try:
            from frago.server.services.ui_session_runner import get_runner

            runner = get_runner()
            return runner._pool.get(session_id)
        except Exception:
            return None

    def _is_async_dispatch_active(self, session_id: str) -> bool:
        """检查会话作为 caller 或 target 是否有未决未送达的异步派发任务。"""
        if not session_id:
            return False
        try:
            from frago.session.async_dispatch import list_dispatch_jobs

            # 作为目标正在被派发执行的
            target_jobs = list_dispatch_jobs(target_session_id=session_id)
            for j in target_jobs:
                if j.status in ("pending", "running", "delivering"):
                    return True
                if getattr(j, "delivery_state", None) in ("queued", "delivering"):
                    return True

            # 作为调用方正在等待异步回传唤醒的
            caller_jobs = list_dispatch_jobs(caller_session_id=session_id)
            for j in caller_jobs:
                if j.status in ("pending", "running", "delivering"):
                    return True
                if getattr(j, "delivery_state", None) in ("queued", "delivering"):
                    return True
        except Exception as e:
            logger.debug("Failed checking async dispatch jobs: %s", e)
        return False

    def _has_pending_workbench_queue(self, session_id: str) -> bool:
        """检查会话工作台队列是否有尚未弹出的待注入消息。"""
        if not session_id:
            return False
        try:
            from frago.server.services import workbench_queue as wq

            read_idx = getattr(wq, "_read_active_queues_index", None)
            if callable(read_idx) and session_id in read_idx():
                return True
            items = wq.list_queue(session_id)
            return len(items) > 0
        except Exception:
            return False

    def _get_latest_dispatch_completion_ts(self, session_id: str) -> float | None:
        """从 async_dispatch 任务账本提取最后一次已送达完成的时刻戳。"""
        try:
            from frago.session.async_dispatch import list_dispatch_jobs

            jobs = list_dispatch_jobs(target_session_id=session_id)
            if not jobs:
                return None
            completed_jobs = [
                j for j in jobs if j.status == "completed" and j.completed_at
            ]
            if not completed_jobs:
                return None
            latest = max(completed_jobs, key=lambda j: j.completed_at or "")
            if latest.completed_at:
                # 兼容 ISO 格式解析
                dt = datetime.fromisoformat(latest.completed_at.replace("Z", "+00:00"))
                return dt.timestamp()
        except Exception:
            pass
        return None

    def _resolve_timeout_threshold(
        self, session_id: str, *, default_timeout: float, worker_timeout: float
    ) -> float:
        """判定会话应套用一次性后台 Worker 冷却门槛还是默认长闲置门槛。"""
        try:
            from frago.session.async_dispatch import list_dispatch_jobs

            jobs = list_dispatch_jobs(target_session_id=session_id)
            if jobs:
                latest = max(jobs, key=lambda j: j.updated_at)
                # 仅对单轮一次性 worker 且已成功送达的会话应用更快的 worker_timeout
                if (
                    latest.kind == "worker"
                    and latest.mode in ("new", "worker")
                    and latest.delivery_state == "delivered"
                ):
                    return worker_timeout
        except Exception:
            pass
        return default_timeout

    def _get_transcript_mtime(self, session_id: str, kernel: str) -> float | None:
        """获取转录文件的最终修改时间戳。"""
        try:
            adapter = get_kernel_session_adapter(kernel)
            path = adapter.locate_transcript(session_id)
            if path is not None and path.is_file():
                return path.stat().st_mtime
        except Exception:
            pass
        return None

    def _quit_borrowed_harness(self, harness: TmuxHarnessMeta) -> None:
        """向借住模式宿主窗口投喂退出序列，退回 shell，不杀 session。"""
        try:
            adapter = get_kernel_session_adapter(harness.kernel)
            keys = adapter.safe_terminate_command(harness.session_id, is_borrowed=True)
            if not keys:
                keys = ["C-c", "C-c", "exit", "C-d"]
            for k in keys:
                _run_tmux("send-keys", "-t", harness.name, k)
                time.sleep(0.1)
        except Exception as e:
            logger.debug("Failed sending quit keys to borrowed harness %s: %s", harness.name, e)
