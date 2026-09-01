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
from datetime import UTC, datetime
from typing import Literal, NoReturn

from frago.agent_driver.driver import (
    AgentDriver,
    CompletionVerdict,
    LaunchCtx,
    load_driver,
)

# 注入点：测试以 fake runner 替换真实 tmux 调用，单测不拉真实 tmux。
TmuxRunner = Callable[[list[str]], str]


class TmuxStartupError(RuntimeError):
    """会话启动失败：投喂启动命令后等不到 ready_signal。

    过去 open() 等不到就绪也无条件标 status='ready'，于是启动其实已崩溃（claude
    撞 session-id 冲突退出、认证墙、二进制缺失等）的死会话被当活会话复用，往 shell
    敲字、探针超时、空文本被跳过——永久静默。改为显式抛此异常，让上层据其判定
    "这是启动失败、不是一轮超时"，做针对性处置（丢弃该轮而非无限重投）。
    """

    def __init__(self, tmux_name: str, tail: str) -> None:
        self.tmux_name = tmux_name
        self.tail = tail
        super().__init__(
            f"tmux session {tmux_name!r} never reached ready signal; pane tail:\n{tail}"
        )


class _SessionVanished(RuntimeError):
    """抓屏失败且复核确认 tmux 会话已不存在。

    模块内部信号，NEVER 逸出到调用方——open() 把它转成 TmuxStartupError、send()
    把它转成 status='error' 的一轮结果。裸 CalledProcessError 穿透出去会绕开上层
    已有的启动失败处置（末屏 + 清半死会话 + 登记），调用方只拿到一页调用栈。
    """

    def __init__(self, last_pane: str, saw_pane: bool) -> None:
        self.last_pane = last_pane
        # 是否曾成功抓到过至少一次 pane：决定错误消息里给不给末屏。
        self.saw_pane = saw_pane
        super().__init__("tmux session vanished")


def _default_runner(argv: list[str]) -> str:
    """跑一条 tmux 命令，返回 stdout。"""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


# pane 里跑着这些名字，说明**没有** agent 在跑：agent 早退了，只剩一个 shell 壳。
# 判据取「前台跑的是不是登录 shell」而不是「是不是叫 claude」：claude 把进程名设成
# 自己的版本号（实测 pane_current_command 报 ``2.1.250``），codex / opencode 各叫各的，
# 按名字白名单认 agent 等于每接一家改一次表，还会在版本一变时集体失灵。
_SHELL_COMMANDS = frozenset(
    {"zsh", "bash", "sh", "fish", "dash", "ksh", "tcsh", "csh", "login", "-zsh", "-bash"}
)


def tmux_name_for(session_id: str) -> str:
    """把 session_id 映射成它的 tmux 会话名。

    tmux 会话名禁止 ':' 和 '.'（它们是 tmux 的 session:window.pane 分隔符），故把非
    [A-Za-z0-9_-] 的字符统一替换为 '_'。抽成模块级函数是因为调用方（如 CLI 的 --json
    停机摘要）需要在不持有 session 对象时报出同一个名字——规则必须只有一处。
    """
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in session_id)
    return f"frago-agent-{safe}"


@dataclass
class TurnResult:
    """一轮 send→done 的归一化结果。"""

    text: str
    raw_delta: str
    status: Literal["ok", "timeout", "needs_input", "error"]
    duration_ms: int


def _pane_tail(pane: str, *, lines: int = 20) -> str:
    """从一屏 pane 里取"有内容的末尾若干行"，供启动失败上报。

    为什么不是直接 ``splitlines()[-lines:]``：claude 这类 TUI 把首启菜单（如
    workspace-trust 确认框、认证墙）渲染在屏幕上半区，下半区全是空行。取最后 20 行
    只会捞到一片空白——启动失败最需要看的那块屏反而被丢掉，用户/排查者只剩一句
    "never reached ready signal"、无从下手（这正是 workspace-trust 卡死当初报错空白
    的第二层原因）。故先滤掉纯空白行再取末尾 ``lines`` 行，让顶端锚定的菜单也露出来。
    """
    meaningful = [ln for ln in pane.splitlines() if ln.strip()]
    return "\n".join(meaningful[-lines:])


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
        conv_key: str | None = None,
        env: dict[str, str] | None = None,
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
        # 干净的 conv_key（如 ``feishu:oc_xxx``）。区别于 session_id（PA 路径恰好等于
        # conv_key，但 WebUI native 路径是 claude uuid）：起会话时经 ``new-session -e``
        # 注入 FRAGO_CONV_KEY，让会话内的 ``frago agent attach`` 自解析自己归属哪个 conv。
        self.conv_key = conv_key
        # 额外注入会话环境的 KEY=VAL（如 --use-profile 解析出的 ANTHROPIC_BASE_URL /
        # ANTHROPIC_MODEL / ANTHROPIC_API_KEY）。经 new-session -e 注入，让会话内 claude
        # TUI 用指定 profile 的 endpoint/model/key 运行。值必须是字符串（tmux -e 要求）。
        self.env = env or {}
        self.cwd = cwd
        self.width = width
        self.height = height
        # conv_key 形如 ``feishu:oc_xxx`` 带冒号，原样当会话名会让 new-session 退非零、
        # 整条 channel 永远建不起会话。每个 session_id 仍稳定映射到唯一的名字
        # （claude --session-id 仍用原始 session_id 派生）。
        self.tmux_name = tmux_name_for(session_id)
        self._run = runner or _default_runner
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep
        self._clock = clock
        self.status: Literal["starting", "ready", "busy", "idle", "dead"] = "starting"
        # 最后一次成功抓到的可见 pane。抓屏偶发失败时顶上（本拍当作没有新内容），
        # 会话确认消失时作为末屏证据随异常/错误结果上报。None = 一次都没抓到过。
        self._last_pane: str | None = None
        # 这一场是被接管来的（tmux 里本来就活着），而不是本进程冷启动出来的。调用方
        # 据此如实报告"这一轮到底有没有付冷启动的代价"，NEVER 把接管说成冷启动。
        self.adopted = False
        # 该活会话在「本池实例」里自己的最后活动时间（wall clock）。open() 与每轮 send()
        # 结束时刷新。空闲回收据此算 idle 时长——NEVER 用 transcript 时间戳：--resume 一个
        # 旧 transcript 时它的最后记录可能是几小时前，会让刚预热的会话被秒判「闲了几小时」回收。
        self.last_active_at: datetime | None = None

    # ── tmux 三件套 ────────────────────────────────────────────────
    def _tmux(self, *args: str) -> str:
        return self._run(["tmux", *args])

    def capture_pane(self, *, full: bool = False) -> str:
        """读屏。full=True 抓全 scrollback（-S -），否则只抓可见 pane。"""
        argv = ["capture-pane", "-p", "-t", self.tmux_name]
        if full:
            argv += ["-S", "-"]
        return self._tmux(*argv)

    def _capture_resilient(self, *, full: bool = False) -> str:
        """轮询专用读屏：把"抓不到"和"会话没了"分开。

        `tmux capture-pane` 对已消失的会话退非零，而会话消失的原因可能是 agent 自己
        崩了、也可能只是这一拍 tmux 忙。两者后果天差地别，故失败后必先复核会话是否
        还活着：活着就沿用上一拍的 pane 当本拍内容继续轮询（NEVER 因一次瞬时失败判死），
        确认已死才抛 _SessionVanished 交给上层收口。
        """
        try:
            pane = self.capture_pane(full=full)
        except Exception:
            if self.is_alive():
                return self._last_pane or ""
            raise _SessionVanished(self._last_pane or "", self._last_pane is not None) from None
        if not full:
            self._last_pane = pane
        return pane

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
        ctx = LaunchCtx(
            cwd=self.cwd,
            session_id=self.session_id,
            native_session_id=self.native_session_id,
        )
        argv = [
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
        ]
        # 把干净 conv_key 注入会话环境（tmux 3.0+ 支持 ``-e``）：会话内任何子命令
        # （尤其 ``frago agent attach``）据 FRAGO_CONV_KEY 自解析自己归属哪个 conv，
        # 把产出文件登记进该 conv 的 outbox。conv_key 缺省（WebUI 等非 PA 路径）时不注入。
        if self.conv_key:
            argv += ["-e", f"FRAGO_CONV_KEY={self.conv_key}"]
        # driver 自己声明的基线环境变量（如 opencode 的权限放行配置）先落，调用方
        # 传进来的 env（profile 翻译结果、自定义端点等）后落、同名键覆盖它——profile
        # 版本的配置自带权限放行，覆盖基线是预期行为。未声明 session_env 的 driver
        # 行为完全不变。
        merged_env: dict[str, str] = {}
        if self.driver.session_env is not None:
            with contextlib.suppress(Exception):
                merged_env.update(self.driver.session_env(ctx))
        merged_env.update(self.env)
        # profile/自定义端点等注入的环境变量，同样经 new-session -e 落进会话环境。
        for _k, _v in merged_env.items():
            argv += ["-e", f"{_k}={_v}"]
        self._tmux(*argv)
        self.send_text(self.driver.launch_command(ctx))
        self.send_keys("Enter")
        try:
            reached = self._wait_for(self.driver.ready_signal.matches, ready_timeout_s)
        except _SessionVanished as vanished:
            # agent 在就绪前自己退了（崩溃 / 启动失败 / 撞 id），tmux 会话随之消失。
            # 这同样是启动失败，走与"等不到就绪"完全相同的处置，只是末屏取最后一份
            # 还抓得到的内容；一份都没有时在消息里写明会话已消失。
            tail = _pane_tail(vanished.last_pane)
            self._fail_startup(tail or "(会话在就绪前已消失，未留下任何屏幕内容)")
        if not reached:
            # 等不到就绪 = 启动失败。NEVER 盲标 ready 让死会话进池被当活会话复用。
            # 抓 pane 末尾若干行随异常上抛便于排查（认证墙 / 二进制缺失 / 撞 id 等），
            # 并 kill 掉这具半死的 tmux 壳，不留孤儿会话累积。
            tail = ""
            with contextlib.suppress(Exception):
                tail = _pane_tail(self.capture_pane())
            self._fail_startup(tail)
        # 一次性异常处理（更新模态 → Esc 等），只在会话首启发生一次。逐个处理器各抓
        # 一次屏（前一个处理器的动作会改变屏幕），抓不到就当本处理器不触发——就绪已
        # 确认，这里再抓失败不值得把整次启动判失败。
        for handler in self.driver.exception_handlers:
            pane_now = ""
            with contextlib.suppress(Exception):
                pane_now = self.capture_pane()
            if handler.trigger.matches(pane_now):
                handler.action(self)
        self.status = "ready"
        self.adopted = False
        self.last_active_at = datetime.now(UTC)

    def _fail_startup(self, tail: str) -> NoReturn:
        """启动失败的统一收口：清半死的 tmux 壳、标死、抛 TmuxStartupError。"""
        with contextlib.suppress(Exception):
            self.close()
        self.status = "dead"
        raise TmuxStartupError(self.tmux_name, tail)

    def close(self) -> None:
        self._tmux("kill-session", "-t", self.tmux_name)
        self.status = "dead"

    def is_alive(self) -> bool:
        try:
            self._tmux("has-session", "-t", self.tmux_name)
            return True
        except subprocess.CalledProcessError:
            return False

    def pane_command(self) -> str:
        """pane 里此刻跑在前台的是什么。问不出来返回空串，NEVER 抛。"""
        try:
            return self._tmux(
                "display-message", "-p", "-t", self.tmux_name, "#{pane_current_command}"
            ).strip()
        except Exception:
            return ""

    def has_live_agent(self) -> bool | None:
        """这个 tmux 会话里还有没有一个活着的 agent 进程。**三态，不是布尔。**

        - ``True``  —— 前台跑着非 shell 的东西，也就是 agent 还在
        - ``False`` —— 前台就是登录 shell，agent 早退了，只剩一个空壳
        - ``None``  —— 问不出来（tmux 这一拍不答、版本不支持这个格式）

        必须三态，因为**两个调用点的安全方向正好相反**：复用一场自己起的会话时，一次
        瞬时问不出来绝不能当成"它死了"——那会把一场健康的常驻会话杀了重建，正是要消灭
        的浪费；而接管一场来路不明的孤儿时，问不出来就绝不能当成"它活着"——那会把话打
        进一个其实没人接的窗口，这一轮永久静默。合并成布尔，必然在其中一边犯错。

        **这是"能不能说话"的判据，不是"闲不闲"的判据。** 会话在忙同样返回 ``True``——
        忙着正说明它活得好好的，该做的是把话排给它，而不是把它杀了重来。
        """
        command = self.pane_command()
        if not command:
            return None
        return command not in _SHELL_COMMANDS

    # ── 通用原语：发送前快照 → 提交 → 轮询完成 → 取 delta ──────────────
    def send(self, prompt: str, *, timeout_s: float | None = None) -> TurnResult:
        """投喂一轮并等到它停下来。

        ``timeout_s=None``（缺省）或 ``<=0`` = **本轮不设时间上限**：一直等到答完 /
        撞上 needs_input 门 / 会话消失。一轮任务该跑多久由任务决定，不由一个拍脑袋
        的秒数决定——墙钟到点就把还在干活的 worker 判死，产出丢失且无人知道它其实
        还在跑。要上限的调用方自己传一个正数。
        """
        start = self._clock()
        self.status = "busy"
        try:
            return self._send_turn(prompt, start=start, timeout_s=timeout_s)
        except _SessionVanished as vanished:
            # 会话在本轮途中消失（agent 崩溃 / 被外部 kill）。这一轮没有答案，但它是
            # 一个可报告的结果而不是异常：调用方据 status='error' 走既有的失败分支，
            # NEVER 把裸 CalledProcessError 抛给它。
            self.status = "dead"
            self.last_active_at = datetime.now(UTC)
            tail = "\n".join(vanished.last_pane.splitlines()[-20:])
            note = (
                f"tmux session {self.tmux_name!r} disappeared mid-turn; "
                "the agent process is gone and this turn produced no answer."
            )
            if tail:
                note = f"{note}\n--- last pane ---\n{tail}"
            return TurnResult(
                text=note,
                raw_delta=vanished.last_pane,
                status="error",
                duration_ms=int((self._clock() - start) * 1000),
            )

    def _send_turn(self, prompt: str, *, start: float, timeout_s: float | None) -> TurnResult:
        pre_snapshot = self._capture_resilient()

        # 权威完成探针（如 claude 的 transcript JSONL）。在提交前先读一次取 baseline
        # marker：常驻多轮会话里，文件尾此刻仍是上一轮的 end_turn，本轮答完时 marker
        # 会推进，据此区分「答完的是本轮」而非误采上一轮残留。
        probe = self.driver.completion_probe
        baseline_marker: str | None = None
        if probe is not None:
            with contextlib.suppress(Exception):
                pre = probe(self)
                baseline_marker = pre.marker if pre else None

        try:
            self.driver.submit(self, prompt)
        except subprocess.CalledProcessError:
            # 投喂本身退非零：会话若已消失，与轮询期消失同等处理；仍活着说明是别的
            # tmux 故障，原样上抛不掩盖。
            if self.is_alive():
                raise
            raise _SessionVanished(self._last_pane or "", self._last_pane is not None) from None

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
            pane = self._capture_resilient()
            text = self.driver.read_answer(pane, prompt)
            raw_delta = pane
        else:
            scrollback = self._capture_resilient(full=True)
            raw_delta = _compute_delta(pre_snapshot, scrollback)
            text = self.driver.extract(raw_delta)
        duration_ms = int((self._clock() - start) * 1000)
        self.status = "idle"
        self.last_active_at = datetime.now(UTC)
        status: Literal["ok", "timeout", "needs_input", "error"] = outcome or "timeout"
        # 探针可以把一轮"结束了但结束得不正常"降级（如答完却零产出，通常是鉴权失败
        # 或 provider 拒绝）。轮次确实终结了，所以轮询该停；但它 NEVER 是成功——
        # 静默返回空答案会让调用方以为一切正常，而实际上什么都没发生。
        if outcome == "ok" and verdict is not None and verdict.status != "ok":
            status = verdict.status
        return TurnResult(
            text=text,
            raw_delta=raw_delta,
            status=status,
            duration_ms=duration_ms,
        )

    # ── 轮询辅助 ───────────────────────────────────────────────────
    def _wait_for(self, predicate: Callable[[str], bool], timeout_s: float | None) -> bool:
        """轮询 pane 直到 predicate 命中或超时；命中返回 True，超时 False。"""
        return self._wait_for_any({"hit": predicate}, timeout_s) == "hit"

    def _wait_for_any(
        self, predicates: dict[str, Callable[[str], bool]], timeout_s: float | None
    ) -> str | None:
        """轮询 pane，命中任一 predicate 返回其 key；超时返回 None。

        同屏多个命中时按 predicates 的插入顺序取第一个（done 优先于 needs_input）。

        ``timeout_s`` 为 None 或 <=0 → **不设墙钟上限**，一直轮询到某个 predicate
        命中，或会话消失（``_capture_resilient`` 抛 _SessionVanished）为止。等待不是
        空转：每拍都在读屏，会话真死了当拍就会被发现，NEVER 变成静默挂起。
        """
        deadline = None if timeout_s is None or timeout_s <= 0 else self._clock() + timeout_s
        while True:
            pane = self._capture_resilient()
            for key, predicate in predicates.items():
                if predicate(pane):
                    return key
            if deadline is not None and self._clock() >= deadline:
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
        conv_key: str | None = None,
        env: dict[str, str] | None = None,
    ) -> TmuxAgentSession:
        driver = load_driver(agent_type)
        session = TmuxAgentSession(
            session_id=session_id,
            driver=driver,
            cwd=cwd,
            native_session_id=native_session_id,
            conv_key=conv_key,
            env=env,
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
        conv_key: str | None = None,
        env: dict[str, str] | None = None,
        keep_alive: bool = False,
        timeout_s: float | None = None,
    ) -> TurnResult:
        """开会话（或复用）→ 投喂一轮 → 取归一化结果。

        Phase 1 无 warm pool，默认每次开新会话并在结束后 kill；keep_alive=True
        时保活会话供后续复用（Phase 3 warm pool 的雏形）。

        ``timeout_s`` 缺省 None = 本轮不设时间上限（见 ``TmuxAgentSession.send``）。
        """
        session = self.open_session(
            agent_type,
            session_id,
            cwd,
            native_session_id=native_session_id,
            conv_key=conv_key,
            env=env,
        )
        try:
            return session.send(prompt, timeout_s=timeout_s)
        finally:
            if not keep_alive:
                with contextlib.suppress(Exception):
                    session.close()
