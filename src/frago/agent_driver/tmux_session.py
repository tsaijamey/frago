"""tmux 驱动主路径 —— 统一、零 agent 分支。

封装 tmux 三件套（new-session / send-keys / capture-pane）与通用原语
"发送前抓 pane 快照 → send-keys → 轮询到 done_signal → 抓全 scrollback → 取 delta"。
主路径只管"取增量"这件通用的事，driver 管"判完成 + 清 chrome"这件 agent 特异的事。

NEVER 在本文件出现 ``if agent == "claude"``；一切 agent 差异经 AgentDriver 注入。
"""

from __future__ import annotations

import contextlib
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from frago.agent_driver.driver import (
    AgentDriver,
    CompletionVerdict,
    LaunchCtx,
    load_driver,
)

# 注入点：测试以 fake runner 替换真实 tmux 调用，单测不拉真实 tmux。
TmuxRunner = Callable[[list[str]], str]


def _default_runner(argv: list[str]) -> str:
    """跑一条 tmux 命令，返回 stdout。"""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


@dataclass
class TurnResult:
    """一轮 send→done 的归一化结果。"""

    text: str
    raw_delta: str
    status: Literal["ok", "timeout", "needs_input", "error"]
    duration_ms: int


def _compute_delta(pre_snapshot: str, scrollback: str) -> str:
    """从完成后的全 scrollback 减去发送前快照，取本轮新增文本。

    pre_snapshot 的非空行出现在 scrollback 里；其后即本轮增量。难点是底部那行
    输入提示符在投喂后会变（"> " → "> hi"），用它做锚点会落空或定位到本轮末尾的
    新提示符。因此从 pre_snapshot 末行往上逐行试锚点，挑第一个"最后一次出现后仍
    有非空增量"的稳定行。全部落空时退化为返回整块 scrollback。
    """
    pre_lines = [ln for ln in pre_snapshot.splitlines() if ln.strip()]
    if not pre_lines:
        return scrollback
    sb_lines = scrollback.splitlines()
    for anchor in reversed(pre_lines):
        for idx in range(len(sb_lines) - 1, -1, -1):
            if sb_lines[idx] == anchor:
                remainder = sb_lines[idx + 1 :]
                if remainder:
                    return "\n".join(remainder)
                break
    return scrollback


class TmuxAgentSession:
    """一个常驻 tmux 会话的句柄 + 驱动原语。"""

    def __init__(
        self,
        session_id: str,
        driver: AgentDriver,
        cwd: str,
        *,
        native_session_id: bool = False,
        width: int = 200,
        height: int = 50,
        runner: TmuxRunner | None = None,
        poll_interval_s: float = 0.3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.driver = driver
        # session_id 是否已是 agent 原生真实会话 id（透传给 driver 决定是否跳过派生）。
        self.native_session_id = native_session_id
        self.cwd = cwd
        self.width = width
        self.height = height
        self.tmux_name = f"frago-agent-{session_id}"
        self._run = runner or _default_runner
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep
        self._clock = clock
        self.status: Literal["starting", "ready", "busy", "idle", "dead"] = "starting"

    # ── tmux 三件套 ────────────────────────────────────────────────
    def _tmux(self, *args: str) -> str:
        return self._run(["tmux", *args])

    def capture_pane(self, *, full: bool = False) -> str:
        """读屏。full=True 抓全 scrollback（-S -），否则只抓可见 pane。"""
        argv = ["capture-pane", "-p", "-t", self.tmux_name]
        if full:
            argv += ["-S", "-"]
        return self._tmux(*argv)

    def send_keys(self, *keys: str) -> None:
        """投喂按键/文本。键名（如 "Enter" / "Escape"）由调用方给。"""
        self._tmux("send-keys", "-t", self.tmux_name, *keys)

    # tmux send-keys 单条命令行有长度上限（实测约 15KB 触发 "command too long"）。
    # PA 的启动提示词（system prompt + bootstrap）可达 ~19KB，故按码点切块顺序发送。
    # 1000 码点：中文按 3 字节算约 3KB/块，远低于上限；切点落在码点边界，不裂字。
    _SEND_TEXT_CHUNK = 1000

    def send_text(self, text: str) -> None:
        """以字面文本发送（-l），不解释键名。

        - `--` 终止 tmux 选项解析：否则以 `-` 开头的文本（如 PA 提示词的
          `--- 待处理消息（N 条）---` 前缀）会被 send-keys 当成非法 flag 而退非零。
        - 超长文本按块切分多次发送：claude TUI 字面模式下不带 Enter，分块投喂
          会原样拼接成同一行输入，提交（Enter）由 submit 单独负责。
        """
        if not text:
            self._tmux("send-keys", "-t", self.tmux_name, "-l", "--", "")
            return
        for i in range(0, len(text), self._SEND_TEXT_CHUNK):
            chunk = text[i : i + self._SEND_TEXT_CHUNK]
            self._tmux("send-keys", "-t", self.tmux_name, "-l", "--", chunk)

    # ── 生命周期 ───────────────────────────────────────────────────
    def open(self, *, ready_timeout_s: float = 30.0) -> None:
        """起 detached 会话、投喂启动命令、等就绪、跑一次性异常处理。"""
        self._tmux(
            "new-session",
            "-d",
            "-s",
            self.tmux_name,
            "-x",
            str(self.width),
            "-y",
            str(self.height),
            "-c",
            self.cwd,
        )
        ctx = LaunchCtx(
            cwd=self.cwd,
            session_id=self.session_id,
            native_session_id=self.native_session_id,
        )
        self.send_text(self.driver.launch_command(ctx))
        self.send_keys("Enter")
        self._wait_for(self.driver.ready_signal.matches, ready_timeout_s)
        # 一次性异常处理（更新模态 → Esc 等），只在会话首启发生一次。
        for handler in self.driver.exception_handlers:
            if handler.trigger.matches(self.capture_pane()):
                handler.action(self)
        self.status = "ready"

    def close(self) -> None:
        self._tmux("kill-session", "-t", self.tmux_name)
        self.status = "dead"

    def is_alive(self) -> bool:
        try:
            self._tmux("has-session", "-t", self.tmux_name)
            return True
        except subprocess.CalledProcessError:
            return False

    # ── 通用原语：发送前快照 → 提交 → 轮询完成 → 取 delta ──────────────
    def send(self, prompt: str, *, timeout_s: float = 120.0) -> TurnResult:
        start = self._clock()
        self.status = "busy"
        pre_snapshot = self.capture_pane()

        # 权威完成探针（如 claude 的 transcript JSONL）。在提交前先读一次取 baseline
        # marker：常驻多轮会话里，文件尾此刻仍是上一轮的 end_turn，本轮答完时 marker
        # 会推进，据此区分「答完的是本轮」而非误采上一轮残留。
        probe = self.driver.completion_probe
        baseline_marker: str | None = None
        if probe is not None:
            with contextlib.suppress(Exception):
                pre = probe(self)
                baseline_marker = pre.marker if pre else None

        self.driver.submit(self, prompt)

        # 轮询直到本轮答完 / 撞上 needs_input 门（认证墙、权限门、澄清门）/ 超时。
        needs_input = self.driver.needs_input_signal
        # ok 判定：有探针时优先采信 JSONL 权威信号（marker 须推进过 baseline 才算
        # 本轮新完成）；探针不可用（返回 None / 抛错）当帧退回 pane done_signal，
        # 保证无 transcript 时与原行为一致、绝不卡死。pane 仍独占 needs_input 门。
        probe_box: dict[str, CompletionVerdict | None] = {"verdict": None}

        def _ok(pane: str) -> bool:
            if probe is None:
                return self.driver.done_signal.matches(pane)
            try:
                verdict = probe(self)
            except Exception:
                verdict = None
            if verdict is None:
                return self.driver.done_signal.matches(pane)
            if verdict.done and verdict.marker != baseline_marker:
                probe_box["verdict"] = verdict
                return True
            return False

        outcome = self._wait_for_any(
            {
                "ok": _ok,
                **({"needs_input": needs_input.matches} if needs_input else {}),
            },
            timeout_s,
        )
        # 探针给出本轮 verdict 且带文本时，直接采用其权威文本（绕开读屏抠答案）。
        verdict = probe_box["verdict"]
        if outcome == "ok" and verdict is not None and verdict.text is not None:
            text = verdict.text
            raw_delta = verdict.text
        # driver 提供 read_answer 时，从完成时可见 pane 直接抽答案（claude 这类
        # 固定底部输入框 + alt-screen 无 scrollback 的 TUI，通用 delta 锚点失效）；
        # 否则走通用"全 scrollback 减发送前快照"取 delta 的路径。
        elif self.driver.read_answer is not None:
            pane = self.capture_pane()
            text = self.driver.read_answer(pane, prompt)
            raw_delta = pane
        else:
            scrollback = self.capture_pane(full=True)
            raw_delta = _compute_delta(pre_snapshot, scrollback)
            text = self.driver.extract(raw_delta)
        duration_ms = int((self._clock() - start) * 1000)
        self.status = "idle"
        status: Literal["ok", "timeout", "needs_input", "error"] = outcome or "timeout"
        return TurnResult(
            text=text,
            raw_delta=raw_delta,
            status=status,
            duration_ms=duration_ms,
        )

    # ── 轮询辅助 ───────────────────────────────────────────────────
    def _wait_for(self, predicate: Callable[[str], bool], timeout_s: float) -> bool:
        """轮询 pane 直到 predicate 命中或超时；命中返回 True，超时 False。"""
        return self._wait_for_any({"hit": predicate}, timeout_s) == "hit"

    def _wait_for_any(
        self, predicates: dict[str, Callable[[str], bool]], timeout_s: float
    ) -> str | None:
        """轮询 pane，命中任一 predicate 返回其 key；超时返回 None。

        同屏多个命中时按 predicates 的插入顺序取第一个（done 优先于 needs_input）。
        """
        deadline = self._clock() + timeout_s
        while True:
            pane = self.capture_pane()
            for key, predicate in predicates.items():
                if predicate(pane):
                    return key
            if self._clock() >= deadline:
                return None
            self._sleep(self._poll_interval_s)


class SessionLauncher:
    """调用方入口：按 agent_type 加载 driver、开会话、跑一轮。"""

    def __init__(self, *, runner: TmuxRunner | None = None) -> None:
        self._runner = runner

    def open_session(
        self,
        agent_type: str,
        session_id: str,
        cwd: str,
        *,
        native_session_id: bool = False,
    ) -> TmuxAgentSession:
        driver = load_driver(agent_type)
        session = TmuxAgentSession(
            session_id=session_id,
            driver=driver,
            cwd=cwd,
            native_session_id=native_session_id,
            runner=self._runner,
        )
        session.open()
        return session

    def run(
        self,
        prompt: str,
        *,
        agent_type: str,
        session_id: str,
        cwd: str,
        native_session_id: bool = False,
        keep_alive: bool = False,
        timeout_s: float = 120.0,
    ) -> TurnResult:
        """开会话（或复用）→ 投喂一轮 → 取归一化结果。

        Phase 1 无 warm pool，默认每次开新会话并在结束后 kill；keep_alive=True
        时保活会话供后续复用（Phase 3 warm pool 的雏形）。
        """
        session = self.open_session(
            agent_type, session_id, cwd, native_session_id=native_session_id
        )
        try:
            return session.send(prompt, timeout_s=timeout_s)
        finally:
            if not keep_alive:
                with contextlib.suppress(Exception):
                    session.close()
