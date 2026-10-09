"""CoreAgent 内核后端 —— ``frago agent`` 里那条不挂 tmux 的执行路径。

## 为什么这一家不进 driver 注册表

claude / codex / opencode / codebuddy 都是**挂在 tmux 里的交互程序**：起一次挂着，之后
每句话 send-keys 进它的输入框。:class:`~frago.agent_driver.driver.AgentDriver` 那份契约
（``launch_command`` / ``ready_signal`` / ``submit`` / ``done_signal`` / ``read_answer``
/ ``clear_input``）从头到尾都是 pane 语义。

CoreAgent 不是那样的东西：它是"交一件事、跑完就退"的进程，**没有可挂的 TUI、没有屏**。
把它塞进 ``AgentDriver`` 等于写一个"在非 pane 进程上假装有 pane"的适配器，纯属自欺。
所以它在 ``frago agent`` 里走这条并列的后端，判据见
:func:`frago.agent_driver.driver.runs_on_kernel`。

## 一次一轮

``frago-core -p -`` 收一件事、跑、把结果**作为一个 JSON 对象打在 stdout 上**，然后退出
（Claude Code 的 ``result`` 形状）。任务从 stdin 喂：正文常常很长，拼进命令行会进 shell
历史、留在屏上，也顶不住长度上限。

## 连接只按 id 给，不给环境变量

内核不认 ``ANTHROPIC_*``——它自己读 ``~/.frago/profiles.json``，``--as-profile <id>``
按 **id**（不是名字）取一条连接。名字到 id 的翻译落在调用方
（:mod:`frago.cli.agent_command`），这里只收 id；给 None 就等于"用内核自己那条默认连接"。

分层：与各 driver 同级。可 import ``init/`` 与 ``session/``，NEVER import ``cli/`` 或
``server/``。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: 内核报的连接/凭据问题都带这个 ``error_kind``（实测：``--as-profile`` 给一个
#: profiles.json 里没有的 id → ``credential``）。这一类"再试一次还是同样的结果，得人去
#: 修"，与 :data:`_AUTH_WALL` 归同一档。
_ERROR_KIND_NEEDS_HUMAN = frozenset({"credential"})

#: 模型那一轮失败时的文案里，哪些属于"人去修才有用"（换 key / 续订阅 / 充钱 / 重新登录），
#: 哪些属于"再试一次也许就好了"。
#:
#: **各持一份，故意不与 claude driver 共用。** 那份认证墙词法（``claude._AUTH_WALL_PAT``）
#: 是对着 claude 自己的失败话术写的，codebuddy 也另有一份（``codebuddy._AUTH_WALL``）——
#: 失败文案是各家自己产的，matcher 就得对着它写。照抄别家的词法只会让这一家该认的认不出、
#: 不该认的乱认。这里认的是内核与上游 provider 实际打的字（2026-10-09 实测样本：
#: ``HTTP 400 {"error":{"code":"InvalidSubscription"...``、``invalid api key``、
#: ``unauthorized``、``credit balance``）。
_AUTH_WALL = re.compile(
    r"invalid\s+api\s+key|api\s+key.{0,24}(?:invalid|expired|revoked)"
    r"|unauthorized|authentication\s+failed|not\s+logged\s+in|invalidsubscription"
    r"|credit\s+balance|insufficient\s+(?:balance|quota|credit)|quota\s+exceeded"
    r"|subscription.{0,24}(?:expired|invalid|not\s+valid)"
    r"|未授权|余额|欠费|订阅.{0,8}(?:过期|失效)",
    re.IGNORECASE,
)

#: 一轮跑完后，从杀掉到放弃之间给内核收场的时间。它捕到 SIGTERM 会把正在跑的命令连进程组
#: 一起终止（见 frago-core 的 ``tools::kill_live_groups``），所以要给它机会走到那一步；
#: 等不到才补 SIGKILL——SIGKILL 之下它没有收尾的机会，拉起的命令会被 init 收养接着跑。
_TERM_GRACE_S = 5.0
_KILL_GRACE_S = 3.0


@dataclass(frozen=True)
class KernelTurn:
    """内核一轮的归一化结果。字段与 :class:`~frago.agent_driver.tmux_session.TurnResult`
    对齐，好让 ``frago agent`` 两条后端在同处发射停机摘要。"""

    text: str
    status: Literal["ok", "timeout", "needs_input", "error"]
    duration_ms: int


def kernel_path() -> Path:
    """内核二进制在哪。

    与 hook 引擎是同一个文件（见 ``frago.init.hook_binary`` 模块头）。路径知识住在那里，
    这里只把它的两个出口拼起来——服务端那边（``coreagent_runner.binary``）也走同一对出口，
    两边各报各的错（一个给页面看，一个给终端看），但"文件在哪"只有一份。
    """
    from frago.init.hook_binary import get_binary_name, get_hook_deploy_dir

    return get_hook_deploy_dir() / get_binary_name()


def new_session_id() -> str:
    """现发一个 CoreAgent 会话编号。

    ``core_`` 前缀是会话页/清单认出"这一场属于 CoreAgent"的唯一判据
    （见 :func:`frago.session.record_reader.detect_family`）。发起方自己发，这一场在跑起来
    之前就归好了家——不自己发的话它顶着一个裸 uuid，会被当成一场 Claude Code 会话。
    """
    return f"core_{uuid.uuid4().hex}"


def build_command(
    *,
    session_id: str,
    cwd: str,
    profile_id: str | None,
) -> list[str]:
    """拼一次性那一条命令。

    ``-p -`` 表示任务从 stdin 来（``--prompt-file`` 读出来的正文很长，拼进命令行会进
    shell 历史也顶不住长度）。**不传 ``--input-format stream-json``**：那是常驻进程、
    一行一条消息的写法，与一次一件事的 ``-p`` 语义冲突（内核自己那句 help：``-p -``
    就是 stdin，默认 text 形状）。
    """
    cmd = [
        str(kernel_path()),
        "--mode", "agent",
        "--output-format", "json",
        "--session-id", session_id,
        "--cwd", cwd,
    ]
    if profile_id:
        cmd += ["--as-profile", profile_id]
    cmd += ["-p", "-"]
    return cmd


def run_turn(
    prompt_text: str,
    *,
    session_id: str,
    cwd: str,
    profile_id: str | None = None,
    timeout_s: float | None = None,
    env: Mapping[str, str] | None = None,
    on_spawn: Callable[[int], None] | None = None,
) -> KernelTurn:
    """把一件事交给内核跑一轮，返回归一化结果。

    ``timeout_s`` 为 None（``frago agent --timeout 0`` 的缺省）时**不设墙钟上限**：一轮该
    跑多久由任务决定。给了正数才在到点时收场——先 SIGTERM 让内核把它拉起的命令一起收掉，
    收不掉再 SIGKILL。

    **上限由这里判，不借内核的 ``--timeout``。** 那个开关有它自己一套输出形状（它会把
    「超时」写进 result 的不同字段），转译过来多一层反推、也多一处会与 frago 的四态脱节。
    这边的墙钟就是 frago 契约里那个墙钟，一处判、一处报。

    ``on_spawn`` 在进程起来之后、喂任务之前被叫一次，带上内核那个进程号——调用方拿它登记
    名册（内核 worker 没有 tmux 会话，能按名字收走它靠的就是这个号）。
    """
    cmd = build_command(session_id=session_id, cwd=cwd, profile_id=profile_id)
    run_env = {**os.environ, **(env or {})}
    started = time.monotonic()

    try:
        proc = subprocess.Popen(  # noqa: S603 — 命令由本模块拼，无 shell
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=run_env,
        )
    except FileNotFoundError:
        return KernelTurn(
            text=f"内核不在：{kernel_path()} 找不到。跑一次 frago init 补上。",
            status="error",
            duration_ms=0,
        )

    if on_spawn is not None:
        with contextlib.suppress(Exception):
            on_spawn(proc.pid)

    # communicate(input=...) 写完就把 stdin 关掉——内核读到 EOF 才会开跑（``-p -`` 的
    # 读法），留着不关它会一直等第二行。
    try:
        if timeout_s and timeout_s > 0:
            out, err = proc.communicate(input=prompt_text, timeout=timeout_s)
        else:
            out, err = proc.communicate(input=prompt_text)
    except subprocess.TimeoutExpired:
        _reap(proc)
        return KernelTurn(
            text="",
            status="timeout",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — 起/读内核的任何失败都属 error 档
        _reap(proc)
        return KernelTurn(
            text=f"内核那一轮没跑起来：{type(exc).__name__}: {exc}",
            status="error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return _classify(out, err, proc.returncode, duration_ms)


def _classify(stdout: str, stderr: str, returncode: int | None, duration_ms: int) -> KernelTurn:
    """把内核的 ``(returncode, stdout JSON)`` 翻成 frago 的四态。

    内核自报的退出码只有三档（``--help``）：``0`` 有最终答案 / ``1`` 没有最终答案 /
    ``2`` 用法错或连接没解析出来。**这三档与 frago 的 ``0/1/2/3`` 同名不同义**
    （frago 的 2 是 needs_input），所以 MUST 逐条翻译，NEVER 原样透出。

    ``result`` 那个 JSON 对象无论成败都在 stdout 上（实测错误路径也照打），所以判据以它
    为准、returncode 只当兜底：JSON 读不出来时只能按 returncode 粗判。
    """
    payload = _parse_payload(stdout)
    if payload is None:
        # 连 result 对象都没有：多半是用法错（我们拼错了命令）或内核启动就崩了。
        note = (stderr or stdout or "").strip()
        return KernelTurn(text=note[:500], status="error", duration_ms=duration_ms)

    text = str(payload.get("result") or "")
    if not payload.get("is_error"):
        if returncode:
            # **自相矛盾：result 说自己没出错，内核却以非零退出。** 以退出码为准——一轮
            # 出了事却报成成功，比多报一次失败坏得多（调用方会拿着半截产出当成品）。
            note = (stderr or text or "").strip()
            return KernelTurn(text=note[:500], status="error", duration_ms=duration_ms)
        return KernelTurn(text=text, status="ok", duration_ms=duration_ms)

    kind = str(payload.get("error_kind") or "")
    if kind in _ERROR_KIND_NEEDS_HUMAN or _AUTH_WALL.search(text):
        # 认证墙 / 连接没解析出来：再试一次还是同样的结果，须真人去换 key、续订阅或挑连接。
        return KernelTurn(text=text, status="needs_input", duration_ms=duration_ms)
    return KernelTurn(text=text, status="error", duration_ms=duration_ms)


def _parse_payload(stdout: str) -> dict | None:
    """从 stdout 里取出内核那个 ``result`` 对象。

    正常情况下 stdout 上就这一行 JSON。内核也可能在它前面打过别的行（进度/提示），所以
    逐行倒着找第一个能解析出 ``type == "result"`` 的对象；找不到返回 None。
    """
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(got, dict) and got.get("type") == "result":
            return got
    return None


def _reap(proc: subprocess.Popen) -> None:
    """收掉一轮已经等不下去的内核进程：先礼后兵，且**先 SIGTERM 后 SIGKILL**。

    关 stdin 这一下同时是「礼」和「实活」：内核读到 EOF 会先把手上的活收掉（正在跑的那条
    命令连进程组一起终止），然后干净退出。走不通才动硬的——SIGKILL 捕不住，内核来不及收
    它拉起的命令，那些命令会被 init 收养、接着跑。
    """
    with contextlib.suppress(Exception):
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    with contextlib.suppress(Exception):
        proc.send_signal(signal.SIGTERM)
    with contextlib.suppress(Exception):
        proc.wait(timeout=_TERM_GRACE_S)
        return
    with contextlib.suppress(Exception):
        proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=_KILL_GRACE_S)
