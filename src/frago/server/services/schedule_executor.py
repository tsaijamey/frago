"""Schedule executor — 定时任务的执行与通知。

## 为什么有这个模块

在此之前，所有到期的定时任务都只有一条出路：投进 PA 队列，由常驻 agent 会话
读一句「执行 recipe xxx」再去执行。对一个纯机械的任务（拉个接口、跑个脚本）来说，
中间那个 agent 既不做判断也不该做判断，却把「任务能不能跑」绑在了「agent 会话
能不能起来」上——agent 起不来，任务就无声地不发生。

所以执行按性质分家：

- **命令**和**配方**是确定性的，frago 自己执行，不经过任何 agent。
- **自然语言任务**本来就需要理解和判断，仍然交给 PA。

PA 从执行链路上的必经之路，变成三种任务形态之一的执行者；同时它可以反过来调
``frago schedule add`` 来给自己或给系统安排任务。

## 通知回路

定时任务最危险的失败不是报错，是**无声**——它没跑，而你以为它跑了。所以这里的
通知不是「把结果写进日志」，而是推到人已经在看的地方（复用 frago 已有的 channel
notify recipe，飞书回推走的就是这条路）。

四条规矩写死在代码里：

1. **该说话时才说话。** 默认 ``on=change``：任务自己说有新鲜事才推送。一个每天
   两次、每次都说「没有变化」的任务，会在两周内把人训练成无视它。
2. **什么算「有变化」由任务自己定。** 调度器不可能知道某个任务的「变化」是什么，
   任务永远知道。约定：配方在结果 JSON 里给一个 ``notify`` 字段，那句话就是这次
   要说的；没有这个字段就是没什么可说的。命令则比对输出的指纹。
3. **失败一定说话，但会收敛。** 首次失败推一条，连续失败不再刷屏（第 2、5、10、
   20 次各推一条），恢复正常时推一条「恢复了」——恢复不通知，人就永远不知道该
   停止担心。
4. **没跑本身也是事件。** 超过三个周期没有成功运行就推一条。这条专门对付上面
   说的那种无声失败。
"""

import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
CONFIG_FILE = FRAGO_HOME / "config.json"

# 通知里带的输出片段最多这么长。再长的东西属于「去看详情」，不属于一条通知。
NOTIFY_EXCERPT_LIMIT = 600

# 连续失败推送到第几次为止仍然说话。中间的沉默不是丢失，是刻意收敛。
FAILURE_ESCALATION_POINTS = (1, 2, 5, 10, 20, 50, 100)

# 超过几个周期没成功就算「没跑」。三个周期给了足够的容错，又不至于拖到第二天。
STALENESS_PERIODS = 3

VALID_NOTIFY_ON = ("change", "always", "failure", "never")
VALID_KINDS = ("recipe", "command", "prompt")


@dataclass
class RunOutcome:
    """一次执行的结果。三种任务形态统一成这一个形状，通知逻辑才不用分叉。"""

    ok: bool
    kind: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    error: str = ""
    # 任务自己写的那句话（配方结果里的 notify 字段）。有它就说明有新鲜事。
    notify_text: str | None = None
    # 用来判断「跟上次比有没有变」的指纹
    digest: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


# --- 执行 ------------------------------------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def execute_recipe(
    recipe: str, params: dict[str, Any] | None, timeout: int,
) -> RunOutcome:
    """直接跑配方。不经过 PA，不起 agent 会话。"""
    started = time.monotonic()
    try:
        from frago.recipes.runner import RecipeRunner

        runner = RecipeRunner()
        result = runner.run(recipe, params=params or {}, timeout=timeout)
    except Exception as e:  # noqa: BLE001 — 执行器不能因为一个任务炸掉整个调度循环
        logger.exception("[schedule] recipe %s raised", recipe)
        return RunOutcome(
            ok=False, kind="recipe", error=str(e),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    duration = int((time.monotonic() - started) * 1000)
    payload = _coerce_payload(result)
    stdout = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload else str(result)

    # 配方失败有两种表达：抛异常（上面接住了）和返回 success=false。
    ok = True
    error = ""
    if isinstance(payload, dict) and payload.get("success") is False:
        ok = False
        error = str(payload.get("error") or "配方返回 success=false")

    return RunOutcome(
        ok=ok,
        kind="recipe",
        exit_code=0 if ok else 1,
        stdout=stdout,
        error=error,
        duration_ms=duration,
        notify_text=_extract_notify_field(payload),
        digest=_digest(_stable_for_digest(payload, stdout)),
        payload=payload if isinstance(payload, dict) else {},
    )


def execute_command(command: str, timeout: int, cwd: str | None = None) -> RunOutcome:
    """直接跑一条 shell 命令。

    走 login shell 是必需的：调度器由服务端守护进程拉起，它的 PATH 跟人在终端里
    看到的往往不是一回事。不走 login shell 的话，一条在终端里跑得好好的命令，
    到了定时任务里就是 command not found，而且只有翻日志才看得见。
    """
    started = time.monotonic()
    shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    try:
        proc = subprocess.run(
            [shell, "-lc", command],
            capture_output=True, text=True, timeout=timeout,
            cwd=cwd or str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        return RunOutcome(
            ok=False, kind="command", error=f"命令超时（{timeout}s 未结束）",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as e:  # noqa: BLE001
        return RunOutcome(
            ok=False, kind="command", error=str(e),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    duration = int((time.monotonic() - started) * 1000)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    ok = proc.returncode == 0

    return RunOutcome(
        ok=ok,
        kind="command",
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration,
        error="" if ok else (stderr or stdout or f"退出码 {proc.returncode}")[:NOTIFY_EXCERPT_LIMIT],
        # 命令没法像配方那样自报「有没有新鲜事」，所以拿输出的指纹当变化判据
        digest=_digest(stdout),
    )


def _coerce_payload(result: Any) -> Any:
    """RecipeRunner 的返回可能是 dict，也可能是带 JSON 的字符串。"""
    if isinstance(result, dict):
        # runner 常见形状：{"success":..., "output": <配方自己的 JSON>}
        inner = result.get("output")
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return result
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}
    return {"raw": str(result)}


def _extract_notify_field(payload: Any) -> str | None:
    """任务自己写的那句话。这是「什么算有新鲜事」的唯一权威。"""
    if not isinstance(payload, dict):
        return None
    for key in ("notify", "summary", "notify_text"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# 每次都会变的字段不能进指纹，否则「有没有变化」永远是「有」。
_VOLATILE_KEYS = frozenset({
    "generated_at", "created_at", "at", "at_local", "timestamp", "elapsed_sec",
    "duration_ms", "last_run_at", "last_run_local", "rate_remaining", "api_cost",
    "pages_fetched", "stopped_reason", "url", "data_dir",
})


def _stable_for_digest(payload: Any, fallback: str) -> str:
    """算指纹前先把「每次都不一样」的字段摘掉。"""
    if not isinstance(payload, dict):
        return fallback
    stable = {k: v for k, v in payload.items() if k not in _VOLATILE_KEYS}
    return json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str)


# --- 该不该通知 -------------------------------------------------------------


@dataclass
class NotifyDecision:
    should: bool
    text: str = ""
    reason: str = ""


def decide_notification(
    schedule: dict[str, Any], outcome: RunOutcome, prev: dict[str, Any],
) -> NotifyDecision:
    """决定这一轮要不要说话、说什么。

    prev 是这条 schedule 上一轮留下的状态（上次指纹、连续失败次数）。
    """
    notify_cfg = schedule.get("notify") or {}
    on = notify_cfg.get("on", "change")
    name = schedule.get("name") or schedule.get("id", "")

    if on == "never":
        return NotifyDecision(False, reason="notify.on=never")

    # --- 失败：永远说话，但收敛 ---
    if not outcome.ok:
        fails = int(prev.get("consecutive_failures", 0)) + 1
        if fails in FAILURE_ESCALATION_POINTS:
            detail = (outcome.error or outcome.stderr or "（没有错误信息）")[:NOTIFY_EXCERPT_LIMIT]
            times = "" if fails == 1 else f"（已连续失败 {fails} 次）"
            return NotifyDecision(
                True,
                f"❌ 定时任务「{name}」失败{times}\n{detail}",
                reason=f"failure #{fails}",
            )
        return NotifyDecision(False, reason=f"failure #{fails} 收敛中")

    # --- 从失败恢复：一定说话，否则人不知道什么时候可以停止担心 ---
    if int(prev.get("consecutive_failures", 0)) > 0 and on != "failure":
        prior = prev["consecutive_failures"]
        tail = outcome.notify_text or "本轮已正常完成"
        return NotifyDecision(
            True,
            f"✅ 定时任务「{name}」恢复正常（此前连续失败 {prior} 次）\n{tail}",
            reason="recovered",
        )

    if on == "failure":
        return NotifyDecision(False, reason="notify.on=failure 且本轮成功")

    if on == "always":
        return NotifyDecision(
            True, _success_text(name, outcome, always=True), reason="notify.on=always",
        )

    # --- on=change：任务自己说了算 ---
    if outcome.kind == "recipe":
        if outcome.notify_text:
            return NotifyDecision(True, f"「{name}」{outcome.notify_text}", reason="recipe 报了 notify")
        return NotifyDecision(False, reason="recipe 没报 notify，视为无新鲜事")

    # 命令：输出指纹变了才说话。首轮没有基线，不说话，只记指纹。
    prev_digest = prev.get("last_digest")
    if not prev_digest:
        return NotifyDecision(False, reason="首轮，只记基线不通知")
    if outcome.digest != prev_digest:
        return NotifyDecision(
            True, _success_text(name, outcome, always=False), reason="输出与上次不同",
        )
    return NotifyDecision(False, reason="输出与上次相同")


def _success_text(name: str, outcome: RunOutcome, *, always: bool) -> str:
    head = f"「{name}」" + ("本轮完成" if always else "输出有变化")
    body = outcome.notify_text or outcome.stdout or "（无输出）"
    if len(body) > NOTIFY_EXCERPT_LIMIT:
        body = body[:NOTIFY_EXCERPT_LIMIT] + "…（已截断，完整结果见任务产出）"
    return f"{head}\n{body}"


def staleness_text(schedule: dict[str, Any], overdue: timedelta) -> str:
    name = schedule.get("name") or schedule.get("id", "")
    hours = overdue.total_seconds() / 3600
    span = f"{hours:.0f} 小时" if hours >= 1 else f"{overdue.total_seconds() / 60:.0f} 分钟"
    return (
        f"⚠️ 定时任务「{name}」已经 {span} 没有成功运行了。\n"
        f"最后一次成功：{schedule.get('last_success_at') or '从来没有成功过'}。\n"
        f"这条提醒本身说明调度器还活着——不跑的是这个任务，去看 "
        f"frago schedule history {schedule.get('id')}。"
    )


# --- 投递 ------------------------------------------------------------------


def _resolve_channel_names() -> list[str]:
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    channels = (raw.get("task_ingestion") or {}).get("channels") or []
    return [c.get("name") for c in channels if c.get("name")]


def deliver(
    schedule: dict[str, Any], text: str, pa_enqueue: Any = None,
) -> dict[str, Any]:
    """把一条通知推出去。

    三种落点，按「人在哪儿看」选：

    - 已配置的 channel（飞书、语音……）：复用 channel 的 notify recipe，
      也就是 PA 回话走的那条出站路。这是默认且推荐的。
    - ``desktop``：本机系统通知。没有配 channel 时的兜底。
    - ``pa``：投给常驻 agent，让它读到这件事并可以接着做点什么。
      注意这跟旧架构的区别——这里 agent 是通知的**消费者**，不是执行的必经之路。
    """
    cfg = schedule.get("notify") or {}
    target = cfg.get("to") or "desktop"
    context = cfg.get("context") or {}

    if target == "pa":
        if not pa_enqueue:
            return {"status": "error", "error": "PA 队列不可用"}
        return {"status": "queued", "target": "pa", "message": text}

    if target == "desktop":
        return _deliver_desktop(schedule, text)

    if target in _resolve_channel_names():
        try:
            from frago.server.services.task_lifecycle import TaskLifecycle

            r = TaskLifecycle().deliver(
                channel=target,
                reply_params={"text": text},
                reply_context=context,
            )
            return {"status": r.get("status", "ok"), "target": target}
        except Exception as e:  # noqa: BLE001
            logger.exception("[schedule] deliver via channel %s failed", target)
            return {"status": "error", "target": target, "error": str(e)}

    return {
        "status": "error",
        "target": target,
        "error": f"通知落点 '{target}' 不是已配置的 channel，也不是 desktop / pa。"
                 f" 现有 channel：{_resolve_channel_names() or '（一个都没配）'}",
    }


def _deliver_desktop(schedule: dict[str, Any], text: str) -> dict[str, Any]:
    """本机系统通知。macOS 走 osascript，Linux 走 notify-send。"""
    title = f"frago · {schedule.get('name') or '定时任务'}"
    body = text.replace("\n", " ")[:240]
    try:
        if shutil.which("osascript"):
            subprocess.run(
                ["osascript", "-e",
                 f'display notification {json.dumps(body)} with title {json.dumps(title)}'],
                capture_output=True, timeout=15,
            )
            return {"status": "ok", "target": "desktop"}
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, body], capture_output=True, timeout=15)
            return {"status": "ok", "target": "desktop"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "target": "desktop", "error": str(e)}
    return {"status": "error", "target": "desktop", "error": "本机没有可用的系统通知命令"}


async def run_scheduled(schedule: dict[str, Any]) -> RunOutcome:
    """按 kind 执行。阻塞动作丢进线程，别把调度循环卡住。"""
    kind = schedule.get("kind") or ("recipe" if schedule.get("recipe") else "prompt")
    timeout = int(schedule.get("timeout") or 300)

    if kind == "command":
        return await asyncio.to_thread(
            execute_command, schedule.get("command") or "", timeout, schedule.get("cwd"),
        )
    if kind == "recipe":
        return await asyncio.to_thread(
            execute_recipe, schedule.get("recipe") or "", schedule.get("params") or {}, timeout,
        )
    raise ValueError(f"run_scheduled 不处理 kind={kind}（prompt 型走 PA）")


def is_stale(schedule: dict[str, Any], now: datetime, period_seconds: int | None) -> timedelta | None:
    """这条任务是不是已经该跑而没跑。返回逾期了多久，没逾期返回 None。"""
    if not period_seconds or period_seconds <= 0:
        return None
    last_ok = schedule.get("last_success_at")
    ref = None
    if last_ok:
        try:
            ref = datetime.fromisoformat(last_ok).replace(tzinfo=None)
        except ValueError:
            ref = None
    if ref is None:
        try:
            ref = datetime.fromisoformat(schedule["created_at"]).replace(tzinfo=None)
        except (KeyError, ValueError):
            return None
    overdue = now - ref - timedelta(seconds=period_seconds * STALENESS_PERIODS)
    return overdue if overdue.total_seconds() > 0 else None
