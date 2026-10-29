"""CoreAgent 内核后端 —— ``frago agent`` 里那条不挂 tmux 的执行路径。

## 为什么这一家不进 driver 注册表

claude / codex / opencode / agy 都是**挂在 tmux 里的交互程序**：起一次挂着，之后
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

## 两种形状：agent 干活，chat 出文本

同一件事有两种问法，挑哪种看**调用方要的是活儿还是文字**：

  ``--mode agent``  带工具、能改文件，一轮跑完在 ``~/.frago/coreagent/sessions/`` 下
                    **留一场会话**——这是 ``frago agent`` 那条路，会话本来就该留下
  ``--mode chat``   问一句答一句，没有工具、**一场会话都不留**，输出是 frago 自己的
                    ``final`` 对象（:func:`run_chat_turn`）

第二条是给"顺手问模型一句"的调用方准备的：`frago session search` 的关键词扩展就是这一类，
它每次都调一次，若走 agent 模式，等于每检索一次就往被检索的语料里塞一场新会话。

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
#: 是对着 claude 自己的失败话术写的——失败文案是各家自己产的，matcher 就得对着它写。
#: 照抄别家的词法只会让这一家该认的认不出、
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
    tmux_name: str | None = None


_REAL_POPEN = subprocess.Popen


def _should_use_tmux() -> bool:
    """``run_turn``（agent 模式）是否通过 tmux 承载。

    - 单测把 ``subprocess.Popen`` 换成替身时不走 tmux；
    - 本机无 ``tmux`` 或显式设了 ``FRAGO_COREAGENT_NO_TMUX=1`` 时自动回退直跑。
    """
    if subprocess.Popen is not _REAL_POPEN:
        return False
    from frago.agent_driver.coreagent_pane_host import tmux_available

    return tmux_available()


def _notify_spawn(
    on_spawn: Callable[..., None] | None, pid: int, tmux_name: str | None = None
) -> None:
    if on_spawn is None:
        return
    with contextlib.suppress(Exception):
        try:
            on_spawn(pid, tmux_name)
        except TypeError:
            on_spawn(pid)


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


def _base_command(
    mode: str,
    *,
    cwd: str,
    profile_id: str | None,
    session_id: str | None = None,
    model: str | None = None,
    wire: str | None = None,
) -> list[str]:
    """两种形状共用的那一截：定模式、定输出格式、定工作目录与连接，任务从 stdin 来。

    ``-p -`` 表示任务从 stdin 来（``--prompt-file`` 读出来的正文很长，拼进命令行会进
    shell 历史也顶不住长度）。**不传 ``--input-format stream-json``**：那是常驻进程、
    一行一条消息的写法，与一次一件事的 ``-p`` 语义冲突（内核自己那句 help：``-p -``
    就是 stdin，默认 text 形状）。

    ``session_id`` 只影响"这一轮要不要续/落一场会话"：agent 模式必须给（内核按它写记录），
    chat 模式不给（问一句就走，不留痕）。
    """
    cmd = [str(kernel_path()), "--mode", mode, "--output-format", "json"]
    if session_id:
        cmd += ["--session-id", session_id]
    cmd += ["--cwd", cwd]
    if profile_id:
        cmd += ["--as-profile", profile_id]
    if model and model.strip():
        cmd += ["--model", model.strip()]
    if wire and wire.strip():
        cmd += ["--wire", wire.strip().lower()]
    cmd += ["-p", "-"]
    return cmd


def build_command(
    *,
    session_id: str,
    cwd: str,
    profile_id: str | None,
    model: str | None = None,
    wire: str | None = None,
) -> list[str]:
    """拼 ``frago agent`` 那一条一次性命令（agent 模式，带工具，落会话记录）。"""
    return _base_command(
        "agent",
        cwd=cwd,
        profile_id=profile_id,
        session_id=session_id,
        model=model,
        wire=wire,
    )


def build_chat_command(
    *,
    cwd: str,
    profile_id: str | None,
    model: str | None = None,
    wire: str | None = None,
) -> list[str]:
    """拼"问一句、答一句"那一条命令（chat 模式，无工具，不留会话记录）。"""
    return _base_command(
        "chat", cwd=cwd, profile_id=profile_id, model=model, wire=wire
    )


def _run_process(
    cmd: list[str],
    prompt_text: str,
    *,
    cwd: str,
    timeout_s: float | None,
    env: Mapping[str, str] | None,
    on_spawn: Callable[[int], None] | None = None,
) -> KernelTurn | tuple[str, str, int | None, int]:
    """起进程 → 喂任务 → 收 ``(stdout, stderr, 退出码, 耗时)``。

    两种形状（agent / chat）在这一层走同一套起停：**"内核不在 / 超时 / 起不来"这三种
    收不了场的失败就地归一成 :class:`KernelTurn` 返回**，调用方 isinstance 判一下——
    拿到 KernelTurn 就原样往上交，拿到四元组才继续判成败。这样超时收场的时机、SIGTERM
    与 SIGKILL 的先后，两种形状不可能各走各的。
    """
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

    return out, err, proc.returncode, int((time.monotonic() - started) * 1000)


def _run_tmux_process(
    cmd: list[str],
    prompt_text: str,
    *,
    session_id: str,
    cwd: str,
    timeout_s: float | None,
    env: Mapping[str, str] | None,
    on_spawn: Callable[..., None] | None = None,
) -> KernelTurn | tuple[str, str, int | None, int, str]:
    """在 ``frago-agent-<session_id>`` tmux 会话内跑一轮 ``frago-core``，回传 ``stdout`` 与退出码。"""
    from frago.agent_driver.coreagent_pane_host import TmuxCoreProcess

    if not kernel_path().exists():
        return KernelTurn(
            text=f"内核不在：{kernel_path()} 找不到。跑一次 frago init 补上。",
            status="error",
            duration_ms=0,
        )

    started = time.monotonic()
    proc = TmuxCoreProcess(
        session_id=session_id,
        cmd=cmd,
        cwd=cwd,
        env=env,
        mode="oneshot",
        prompt_text=prompt_text,
    )
    try:
        _notify_spawn(on_spawn, proc.pid or os.getpid(), proc.tmux_name)
        try:
            if timeout_s and timeout_s > 0:
                proc.wait(timeout=timeout_s)
            else:
                proc.wait()
        except subprocess.TimeoutExpired:
            _reap(proc)
            return KernelTurn(
                text="",
                status="timeout",
                duration_ms=int((time.monotonic() - started) * 1000),
                tmux_name=proc.tmux_name,
            )
        except Exception as exc:  # noqa: BLE001
            _reap(proc)
            return KernelTurn(
                text=f"内核那一轮没跑起来：{type(exc).__name__}: {exc}",
                status="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                tmux_name=proc.tmux_name,
            )

        out = proc.read_stdout()
        err = proc.read_stderr()
        rc = proc.returncode
        return out, err, rc, int((time.monotonic() - started) * 1000), proc.tmux_name
    finally:
        proc.cleanup_runtime_dir()


def run_turn(
    prompt_text: str,
    *,
    session_id: str,
    cwd: str,
    profile_id: str | None = None,
    model: str | None = None,
    wire: str | None = None,
    timeout_s: float | None = None,
    env: Mapping[str, str] | None = None,
    on_spawn: Callable[..., None] | None = None,
) -> KernelTurn:
    """把一件事交给内核跑一轮，返回归一化结果。

    ``timeout_s`` 为 None（``frago agent --timeout 0`` 的缺省）时**不设墙钟上限**：一轮该
    跑多久由任务决定。给了正数才在到点时收场——先 SIGTERM 让内核把它拉起的命令一起收掉，
    收不掉再 SIGKILL。

    **上限由这里判，不借内核的 ``--timeout``。** 那个开关有它自己一套输出形状（它会把
    「超时」写进 result 的不同字段），转译过来多一层反推、也多一处会与 frago 的四态脱节。
    这边的墙钟就是 frago 契约里那个墙钟，一处判、一处报。

    ``on_spawn`` 在进程起来之后、喂任务之前被叫一次，带上内核那个进程号（以及 tmux 会话名，
    若本轮跑在 tmux 内）——调用方拿它登记名册。本机无 tmux 时自动回退为直接子进程。
    """
    cmd = build_command(
        session_id=session_id,
        cwd=cwd,
        profile_id=profile_id,
        model=model,
        wire=wire,
    )
    if _should_use_tmux():
        try:
            tmux_collected = _run_tmux_process(
                cmd,
                prompt_text,
                session_id=session_id,
                cwd=cwd,
                timeout_s=timeout_s,
                env=env,
                on_spawn=on_spawn,
            )
            if isinstance(tmux_collected, KernelTurn):
                return tmux_collected
            out, err, returncode, duration_ms, tmux_name = tmux_collected
            return _classify(out, err, returncode, duration_ms, tmux_name=tmux_name)
        except Exception:  # noqa: BLE001 — tmux 启动异常时自动回退直跑
            pass

    collected = _run_process(
        cmd,
        prompt_text,
        cwd=cwd,
        timeout_s=timeout_s,
        env=env,
        on_spawn=on_spawn,
    )
    if isinstance(collected, KernelTurn):
        return collected
    out, err, returncode, duration_ms = collected
    return _classify(out, err, returncode, duration_ms)


def run_chat_turn(
    prompt_text: str,
    *,
    cwd: str,
    profile_id: str | None = None,
    model: str | None = None,
    wire: str | None = None,
    timeout_s: float | None = None,
    env: Mapping[str, str] | None = None,
) -> KernelTurn:
    """问内核一句话，拿回一句（``--mode chat``，无工具、不留会话记录）。

    给"顺手问模型一句"的调用方用（`frago session search` 的关键词扩展就是这一类）。
    与 :func:`run_turn` 的区别只在模式：这条路上内核不挂会话、不写
    ``~/.frago/coreagent/sessions/``，因此不会把调用方自己的语料越搜越脏。

    连接同上：``--as-profile`` 收 **id**；给 None 就用内核自己那条默认连接。
    """
    cmd = build_chat_command(
        cwd=cwd, profile_id=profile_id, model=model, wire=wire
    )
    collected = _run_process(cmd, prompt_text, cwd=cwd, timeout_s=timeout_s, env=env)
    if isinstance(collected, KernelTurn):
        return collected
    out, err, returncode, duration_ms = collected
    return _classify_chat(out, err, returncode, duration_ms)


def _classify(
    stdout: str,
    stderr: str,
    returncode: int | None,
    duration_ms: int,
    *,
    tmux_name: str | None = None,
) -> KernelTurn:
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
        return KernelTurn(
            text=note[:500], status="error", duration_ms=duration_ms, tmux_name=tmux_name
        )

    text = str(payload.get("result") or "")
    if not payload.get("is_error"):
        if returncode:
            # **自相矛盾：result 说自己没出错，内核却以非零退出。** 以退出码为准——一轮
            # 出了事却报成成功，比多报一次失败坏得多（调用方会拿着半截产出当成品）。
            note = (stderr or text or "").strip()
            return KernelTurn(
                text=note[:500], status="error", duration_ms=duration_ms, tmux_name=tmux_name
            )
        return KernelTurn(
            text=text, status="ok", duration_ms=duration_ms, tmux_name=tmux_name
        )

    return KernelTurn(
        text=text,
        status=_failure_status(payload, text),
        duration_ms=duration_ms,
        tmux_name=tmux_name,
    )


def _classify_chat(
    stdout: str, stderr: str, returncode: int | None, duration_ms: int
) -> KernelTurn:
    """把 chat 那一轮的 ``final`` 对象翻成 frago 的四态。

    形状与 agent 那条不同：正文在 ``text``、失败原因在 ``error``、成败看 ``ok``
    （实测样本：连接没解析出来时 ``ok=false``、``error_kind=credential``，
    ``text`` 是空的而 ``error`` 带着那句人话）。所以正文取 ``text or error``——
    失败时把原因当正文往上交，"没跑成"才不会退化成一个没有理由的空串。

    分类的尾部（凭据 / 认证墙 ⇒ 需人介入）与 agent 那条共用 :func:`_failure_status`：
    那是"再试一次也没用"这件事本身的判据，与输出是哪个形状无关。
    """
    payload = _parse_payload(stdout, kind="final")
    if payload is None:
        # 连 final 对象都没有：多半是用法错（我们拼错了命令）或内核启动就崩了。
        note = (stderr or stdout or "").strip()
        return KernelTurn(text=note[:500], status="error", duration_ms=duration_ms)

    text = str(payload.get("text") or payload.get("error") or "")
    if bool(payload.get("ok")):
        if returncode:
            # 与 agent 那条同一条规矩：自报成功却非零退出，以退出码为准。
            note = (stderr or text or "").strip()
            return KernelTurn(text=note[:500], status="error", duration_ms=duration_ms)
        return KernelTurn(text=text, status="ok", duration_ms=duration_ms)

    return KernelTurn(
        text=text, status=_failure_status(payload, text), duration_ms=duration_ms
    )


def _failure_status(payload: dict, text: str) -> str:
    """失败那一轮归 error 还是 needs_input。

    认证墙 / 连接没解析出来：再试一次还是同样的结果，须真人去换 key、续订阅或挑连接，
    归 ``needs_input``；其余（网络抖动、上游 5xx）都归 ``error``，再试一次也许就好。
    """
    kind = str(payload.get("error_kind") or "")
    if kind in _ERROR_KIND_NEEDS_HUMAN or _AUTH_WALL.search(text):
        return "needs_input"
    return "error"


def _parse_payload(stdout: str, *, kind: str = "result") -> dict | None:
    """从 stdout 里取出内核打的那个对象。

    正常情况下 stdout 上就这一行 JSON。内核也可能在它前面打过别的行（进度/提示），所以
    逐行倒着找第一个能解析出 ``type`` 等于 ``kind`` 的对象；找不到返回 None。

    ``kind`` 就是两种形状的名字：agent 模式是 Claude Code 形状的 ``result``，chat 模式是
    frago 自己的 ``final``。MUST 指名道姓——不看 ``type`` 就认，agent 那条会把 chat 的
    ``final`` 读成一个字段全对不上的 ``result``，一路错到"输出不是 JSON"。
    """
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(got, dict) and got.get("type") == kind:
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
