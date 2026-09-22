"""把页面上打的一句话交给 CoreAgent，在那一场会话上接着跑。

## 为什么这一家不走另外三家那条路

工作台里的 Claude Code、codex、opencode 都是**交互式命令行程序**：起一个 tmux、把它挂在
那儿，之后每句话 send-keys 进去，上下文一直在它自己的进程里。CoreAgent 不是那样的东西，
它是 frago 自己的 agent 循环——交一件事、跑、给答案、进程退出。没有可以挂着的 TUI，也就
没有 send-keys 这回事。

接着说话靠的是另一件事：内核认 ``--session-id``，给它一个已经有记录的会话编号，它会先把
那一场的对话读回来当这一轮的记忆（见 frago-core 的 ``transcript_log::replay``）。所以这里
每一轮都是**新起一个进程**，代价是每轮要把历史重新交给模型一次，换来的是页面上那一场会话
真的能一句接一句说下去。

## 一场会话同一时刻只许一个进程

两个进程对着同一个编号跑，会往同一份记录里交替写行：记录读回来是两轮串在一起的胡话，
而页面上看不出任何异样。所以这里有一道占位闸——那一场还在跑的时候，第二句话当场拒掉并
说明理由，NEVER 收下再让它去覆盖别人写的行。

## 不等它跑完

一轮可能跑几分钟。页面要的不是这一轮的返回值——记录流那条路本来就在盯着那份 jsonl，
一行写下去页面就看得见。所以这里等一个不长的时限，到点还没完就先回「在跑」，进程照常
在后台跑到底。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path

from frago.server.services.ui_session_runner import SessionActivation

logger = logging.getLogger(__name__)

#: 一轮的墙钟上限，交给内核自己收场（它超时会把这件事写进会话记录）。
#: 给得比一次问答宽得多：CoreAgent 在页面上接的多半是「帮我把这件事办完」。
TURN_TIMEOUT_S = 1800.0

#: 等一轮答完最多等多久再先回「在跑」。与另外三家那条路的一轮等待量级一致。
WAIT_S = 180.0

#: 进程比内核自己的收场时限多给一分钟，兜的是它连收场都做不到的情况。
_REAP_GRACE_S = 60.0

_running: dict[str, float] = {}
_lock = threading.Lock()


class CoreAgentBusy(RuntimeError):
    """这一场正在跑，这句话现在发不进去。

    单立一档：让它落进通用的 500，页面上只剩一句「没发出去」，人会以为出了故障，
    而实际只需要等它答完。
    """


class CoreAgentUnavailable(RuntimeError):
    """内核不在，或者它一上来就起不来（多半是没给 CoreAgent 配连接）。"""


def running(session_id: str) -> bool:
    """这一场现在有没有进程在跑。"""
    with _lock:
        return session_id in _running


def _claim(session_id: str) -> None:
    with _lock:
        started = _running.get(session_id)
        if started is not None:
            waited = int(time.time() - started)
            raise CoreAgentBusy(
                f"这一场 CoreAgent 还在跑（已经 {waited} 秒），等它答完再说。"
                "两个进程对着同一场会话写记录，会把两轮搅成一场"
            )
        _running[session_id] = time.time()


def _release(session_id: str) -> None:
    with _lock:
        _running.pop(session_id, None)


def new_session_id() -> str:
    """现发一个 CoreAgent 会话编号。

    ``core_`` 前缀是会话页认出"这一场属于 CoreAgent"的唯一判据（内核那边生成编号时
    写的也是它）。发起方自己发编号，才能在会话跑起来之前就把它归好组、记进执行记录。
    """
    return f"core_{uuid.uuid4().hex}"


def start_local_ops(title: str) -> str:
    """给 frago 自己要起的一场 CoreAgent 会话备好编号，并归到「本机管理」那一组。

    定时任务、待办拟稿、外部命令审计都从这里拿编号。两件事在这里一起做完，是因为它们
    在别处一起漏掉过：编号不自己发，这一场就只能叫开口第一句——那是一整段说明书，二十
    场长得一模一样；不归组，它们就堆在左栏未分组区，把人自己那几场埋掉。

    归组失败只记一句日志：归类不成是左栏难看，而让一次定时任务因此不跑是另一个量级的事。

    **名字要调用方自己交给内核**（拼命令时带上 ``--title``）：这几处各自拼自己那条命令，
    这里拿到名字只为写进日志，好在日志里对上号。走 :func:`send` 的那条路把名字直接交给它。
    """
    session_id = new_session_id()
    try:
        from frago.server.services import workbench_groups

        workbench_groups.file_under(
            session_id,
            workbench_groups.LOCAL_OPS_TAG,
            key=workbench_groups.LOCAL_OPS_KEY,
        )
    except Exception:  # noqa: BLE001 — 归组不成不该把任务本身拦下
        logger.warning("把 %s 归到「本机管理」组时出错", session_id, exc_info=True)
    logger.info("coreagent local-ops session %s（%s）", session_id, title)
    return session_id


def binary() -> Path:
    """内核二进制在哪。跟 hook 引擎是同一个文件，不带 ``--engine`` 就是内核。"""
    from frago.init.hook_binary import get_binary_name, get_hook_deploy_dir

    path = get_hook_deploy_dir() / get_binary_name()
    if not path.exists():
        raise CoreAgentUnavailable(
            "frago 的内核还没装好（~/.frago/bin 下找不到），跑一次 frago init 补上"
        )
    return path


def build_command(
    session_id: str,
    prompt: str,
    *,
    cwd: str,
    title: str | None = None,
    timeout_s: float = TURN_TIMEOUT_S,
) -> list[str]:
    """这一轮交给内核的那条命令。

    ``--session-id`` 是续接的全部：编号指向的记录已经存在时，内核先把那一场读回来。
    工具不加限制——人在页面上跟自己的 agent 说话，与在终端里跑 ``frago-core`` 是同一件
    事，而每一步仍然要过 frago 的规则闸（内核自己在 PreToolUse 那一刻问规则引擎）。
    """
    cmd = [
        str(binary()),
        "--mode", "agent",
        "--output-format", "json",
        "--session-id", session_id,
        "--cwd", cwd,
        "--timeout", str(int(timeout_s)),
        "--prompt", prompt,
    ]
    if title:
        cmd += ["--title", title]
    return cmd


def _run(
    session_id: str,
    prompt: str,
    *,
    cwd: str,
    title: str | None,
    timeout_s: float,
    result: dict[str, object],
) -> None:
    """跑完一整轮。占位在这里释放，失败原因记进 ``result``。"""
    from frago.server.services.subprocess_utils import get_utf8_env

    try:
        cmd = build_command(session_id, prompt, cwd=cwd, title=title, timeout_s=timeout_s)
        proc = subprocess.run(  # noqa: S603 — 命令由本模块拼，无 shell
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s + _REAP_GRACE_S,
            cwd=cwd,
            env=get_utf8_env(),
        )
    except subprocess.TimeoutExpired:
        result["error"] = f"CoreAgent 超时（{int(timeout_s)} 秒没结束）"
        logger.warning("coreagent turn timed out (session=%s)", session_id)
        return
    except Exception as e:  # noqa: BLE001 — 起不来照实记下，页面据此报
        result["error"] = str(e)
        logger.warning("coreagent turn failed to start (session=%s)", session_id, exc_info=True)
        return
    finally:
        _release(session_id)

    final = _final_line(proc.stdout or "")
    result["exit_code"] = proc.returncode
    if final is None:
        detail = (proc.stderr or "").strip().splitlines()
        result["error"] = detail[-1] if detail else f"CoreAgent 没交结论，退出码 {proc.returncode}"
        return
    result["text"] = str(final.get("text") or "")
    if not final.get("ok") or proc.returncode != 0:
        result["error"] = str(final.get("error") or final.get("error_kind") or "CoreAgent 没办完")


def _final_line(stdout: str) -> dict | None:
    """内核结束时交的那一行结论。标准输出里别的行不认。"""
    import json

    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict) and row.get("type") == "final":
            return row
    return None


def send(
    session_id: str,
    prompt: str,
    *,
    cwd: str,
    title: str | None = None,
    wait_s: float = WAIT_S,
) -> SessionActivation:
    """在这一场上跑一轮，最多等 ``wait_s``，到点先回「在跑」。

    等到了而这一轮是失败收场，就抛 :class:`CoreAgentUnavailable`——失败得早的那几种
    （没配连接、内核不在）压根没在会话记录里留下任何一行，页面上除了这句抛出来的话
    没有别的线索。等不到就只记日志：那时记录里已经有行在写了，人看得见。
    """
    _claim(session_id)
    result: dict[str, object] = {}
    thread = threading.Thread(
        target=_run,
        args=(session_id, prompt),
        kwargs={"cwd": cwd, "title": title, "timeout_s": TURN_TIMEOUT_S, "result": result},
        name=f"coreagent-turn-{session_id[:16]}",
        daemon=True,
    )
    thread.start()
    thread.join(timeout=wait_s)
    if thread.is_alive():
        logger.info("coreagent turn still running after %ss (session=%s)", wait_s, session_id)
        return SessionActivation(session_id=session_id, status="activating", text="")
    error = result.get("error")
    if error:
        raise CoreAgentUnavailable(str(error))
    return SessionActivation(
        session_id=session_id, status="activating", text=str(result.get("text") or "")
    )


def send_queued(
    session_id: str,
    prompt: str,
    *,
    cwd: str,
    title: str | None = None,
) -> str:
    """同 :func:`send`，但一步都不等：占位当场占上，进程在后台跑。

    占位仍在调用线程里占——「这一场正在跑」必须当场回给页面，NEVER 收下再在后台
    静默地把别人的记录搅掉。返回线程名，便于日志对号。
    """
    _claim(session_id)
    result: dict[str, object] = {}

    def _feed() -> None:
        _run(
            session_id,
            prompt,
            cwd=cwd,
            title=title,
            timeout_s=TURN_TIMEOUT_S,
            result=result,
        )
        if result.get("error"):
            logger.warning("queued coreagent turn failed: %s", result["error"])

    thread = threading.Thread(
        target=_feed, name=f"coreagent-turn-{session_id[:16]}", daemon=True
    )
    thread.start()
    return thread.name
