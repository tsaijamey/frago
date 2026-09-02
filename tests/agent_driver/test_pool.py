"""Phase 3 单测：WarmSessionPool 保活、复用、LRU 驱逐、崩溃重建。

仍用 FakeTmux 替身，不拉真实 tmux。FakeTmux 默认对 has-session 返回成功
(is_alive=True)，个别用例脚本化为崩溃。
"""

from __future__ import annotations

from frago.agent_driver.pool import WarmSessionPool
from tests.agent_driver.test_tmux_session import FakeTmux


class AlivePane:
    """capture 永远返回 opencode 就绪+完成的屏，has-session 永远成功。"""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.killed: list[str] = []
        self.alive: dict[str, bool] = {}

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        verb = argv[1] if len(argv) > 1 else ""
        if verb == "capture-pane":
            return "Ask anything\n▣ Build · m · 1.0s\nanswer"
        if verb == "has-session":
            name = argv[argv.index("-t") + 1]
            if not self.alive.get(name, True):
                raise _CalledProcessError(argv)
            return ""
        if verb == "kill-session":
            self.killed.append(argv[argv.index("-t") + 1])
        return ""


class _CalledProcessError(Exception):
    """模拟 subprocess.CalledProcessError（is_alive 捕获它）。"""

    def __init__(self, argv):
        super().__init__(argv)


# is_alive() 捕获的是 subprocess.CalledProcessError；用真实类型。
import subprocess  # noqa: E402


def _make_runner():
    fake = AlivePane()

    def runner(argv):
        try:
            return fake(argv)
        except _CalledProcessError as exc:
            raise subprocess.CalledProcessError(1, exc.args[0]) from exc

    runner.fake = fake
    return runner


def test_acquire_reuses_alive_session() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    s1 = pool.acquire("opencode", "sid", "/tmp")
    s2 = pool.acquire("opencode", "sid", "/tmp")
    assert s1 is s2
    assert len(pool) == 1
    # 只 open 一次：new-session 只出现一次。
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 1


def test_lru_eviction_kills_oldest() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(max_size=2, runner=runner)
    pool.acquire("opencode", "a", "/tmp")
    pool.acquire("opencode", "b", "/tmp")
    # 触碰 a 使其变为最近使用，b 成为最久未用。
    pool.acquire("opencode", "a", "/tmp")
    pool.acquire("opencode", "c", "/tmp")  # 超限 → 驱逐 b
    assert set(pool.active_ids()) == {"a", "c"}
    assert "frago-agent-b" in runner.fake.killed


def test_dead_session_is_rebuilt_with_resume_hook() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    pool.acquire("opencode", "x", "/tmp")
    # 标记该 tmux 会话已死。
    runner.fake.alive["frago-agent-x"] = False

    resumed = []
    pool.acquire("opencode", "x", "/tmp", resume_hook=lambda s: resumed.append(s.session_id))
    # 触发了重建 + resume_hook。
    assert resumed == ["x"]
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 2  # 首建 + 重建


def test_run_keeps_session_alive_for_reuse() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    r1 = pool.run("hi", agent_type="opencode", session_id="s", cwd="/tmp", timeout_s=5)
    r2 = pool.run("yo", agent_type="opencode", session_id="s", cwd="/tmp", timeout_s=5)
    assert r1.status == "ok" and r2.status == "ok"
    # 第二轮复用，未再 new-session。
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 1


def test_evict_and_shutdown() -> None:
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    pool.acquire("opencode", "a", "/tmp")
    pool.acquire("opencode", "b", "/tmp")
    assert pool.evict("a") is True
    assert pool.evict("missing") is False
    pool.shutdown()
    assert len(pool) == 0
    assert "frago-agent-a" in runner.fake.killed
    assert "frago-agent-b" in runner.fake.killed


def test_invalid_max_size_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        WarmSessionPool(max_size=0)


def test_fake_runner_helper_unused_import_guard() -> None:
    # 守护：FakeTmux 仍可从同目录导入（被其它用例间接依赖）。
    assert FakeTmux is not None


# ── 健康的会话不许杀了重来 ──────────────────────────────────────────
class TrackingPane:
    """比 AlivePane 更贴真实 tmux：**只有真的建过（或明说是孤儿）的会话名才存在**。

    AlivePane 对从没建过的名字也答 has-session 成功，于是每一次新建都会先走一遍
    "同名会话已存在"的分支。用它测"孤儿怎么处理"，测的是替身的形状而不是代码的行为。
    """

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.killed: list[str] = []
        self.existing: dict[str, str] = {}  # 会话名 → pane 前台跑的命令
        self.cleared: list[str] = []
        # 读屏内容。默认是一屏"就绪 + 已完成"，也就是输入框空着——接管时无需清空。
        # 想测"框里有残留"的用例把它换成一屏不含就绪信号的内容。
        self.pane_text = "Ask anything\n▣ Build · m · 1.0s\nanswer"

    def seed_orphan(self, name: str, pane_command: str) -> None:
        """预置一场"内存池不认识、但 tmux 里还在"的会话——服务重启后就是这个状态。"""
        self.existing[name] = pane_command

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        verb = argv[1] if len(argv) > 1 else ""
        name = argv[argv.index("-t") + 1] if "-t" in argv else ""
        if verb == "new-session":
            self.existing[argv[argv.index("-s") + 1]] = "agent"
            return ""
        if verb == "has-session":
            if name not in self.existing:
                raise _CalledProcessError(argv)
            return ""
        if verb == "display-message":
            return self.existing.get(name, "") + "\n"
        if verb == "kill-session":
            self.killed.append(name)
            self.existing.pop(name, None)
            return ""
        if verb == "send-keys" and "C-u" in argv:
            self.cleared.append(name)
            return ""
        if verb == "capture-pane":
            return self.pane_text
        return ""


def _tracking_runner():
    fake = TrackingPane()

    def runner(argv):
        try:
            return fake(argv)
        except _CalledProcessError as exc:
            raise subprocess.CalledProcessError(1, exc.args[0]) from exc

    runner.fake = fake
    return runner


def test_a_healthy_orphan_is_adopted_not_killed_and_relaunched() -> None:
    """服务重启后内存池是空的，但 tmux 里那场还活着——**接管它，不许杀了重起**。

    杀掉再 resume 拿到的是同一段上下文，代价却是十几秒冷启动；它要是正干着活，那一轮
    的工具调用与后台 worker 还会一起丢。人在页面上只会看到"它怎么从头开始了"。
    """
    runner = _tracking_runner()
    # claude 把进程名设成自己的版本号，实测 pane_current_command 报的就是这个。
    runner.fake.seed_orphan("frago-agent-sid", "2.1.250")
    pool = WarmSessionPool(runner=runner)
    session = pool.acquire("opencode", "sid", "/tmp")

    assert runner.fake.killed == [], "健康的孤儿会话一个都不该被杀"
    assert not [c for c in runner.fake.commands if c[1:2] == ["new-session"]], (
        "接管就不该再起一个新的 tmux 会话"
    )
    assert session.adopted is True
    assert pool.has("sid")


def test_an_empty_shell_orphan_is_cleaned_up_and_rebuilt() -> None:
    """agent 早退了、只剩一个停在提示符上的 shell 壳——那种才该清掉重建。

    不清就复用的话，话会打进 shell 提示符里，探针等不到任何东西，这一轮永久静默。
    """
    runner = _tracking_runner()
    runner.fake.seed_orphan("frago-agent-sid", "zsh")
    pool = WarmSessionPool(runner=runner)
    session = pool.acquire("opencode", "sid", "/tmp")

    assert runner.fake.killed == ["frago-agent-sid"]
    assert [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert session.adopted is False


def test_unanswerable_pane_query_is_not_treated_as_a_live_agent() -> None:
    """问不出前台跑的是什么时**不接管**：不知道那窗口里是什么，就不能把话打进去。

    与复用自己那场会话时的默认方向相反（见下一个用例）——两个方向都要有用例钉住，
    合成一个布尔必然在其中一边犯错。
    """
    runner = _tracking_runner()
    runner.fake.seed_orphan("frago-agent-sid", "")  # tmux 这一拍什么都不答
    pool = WarmSessionPool(runner=runner)
    pool.acquire("opencode", "sid", "/tmp")
    assert runner.fake.killed == ["frago-agent-sid"]


def test_reuse_survives_a_transient_pane_query_failure() -> None:
    """复用自己那场会话时，一次问不出来绝不能当成"它死了"。

    那是一场本进程起的、一直在驱动的会话；为一次瞬时查询失败把它杀了重建，正是要
    消灭的那种浪费。
    """
    runner = _tracking_runner()
    pool = WarmSessionPool(runner=runner)
    first = pool.acquire("opencode", "sid", "/tmp")
    runner.fake.existing["frago-agent-sid"] = ""  # 下一拍 tmux 不答
    second = pool.acquire("opencode", "sid", "/tmp")
    assert first is second
    assert runner.fake.killed == []


def test_reuse_drops_a_session_whose_agent_has_exited() -> None:
    """反过来：明确看见前台只剩 shell，说明 agent 退了，那就得丢掉重建。"""
    runner = _tracking_runner()
    pool = WarmSessionPool(runner=runner)
    first = pool.acquire("opencode", "sid", "/tmp")
    runner.fake.existing["frago-agent-sid"] = "zsh"
    second = pool.acquire("opencode", "sid", "/tmp")
    assert first is not second


def test_adoption_clears_leftover_text_in_the_input_box() -> None:
    """接管前先清输入框：那个 TUI 不是本进程起的，框里可能躺着别人打了一半的话。

    不清就打字，用户那句话会被这段陌生的残留顶在前面送出去——他看到的是自己没写过的
    内容，而且完全无从解释。这是"原样透传"的必要条件。
    """
    from frago.agent_driver.driver import load_driver

    runner = _tracking_runner()
    runner.fake.seed_orphan("frago-agent-sid", "2.1.250")
    pool = WarmSessionPool(runner=runner)

    # 框里躺着上一个人打了一半没发出去的话——屏上因此看不到"就绪"那一行。
    runner.fake.pane_text = "▣ Build · m · 1.0s\n> 把路径那条边界报给平台"

    cleared: list[str] = []
    driver = load_driver("opencode")
    object.__setattr__(
        driver, "clear_input", lambda s: (cleared.append(s.tmux_name), True)[1]
    )
    try:
        pool.acquire("opencode", "sid", "/tmp")
        assert cleared == ["frago-agent-sid"]
    finally:
        object.__setattr__(driver, "clear_input", None)


def test_adoption_does_not_pay_for_clearing_when_the_box_is_already_empty() -> None:
    """框本来就是空的就什么都不做。

    清空动作要发键、打探针字符、再轮询确认重绘，最坏耗掉好几秒——那是接管这条路上
    唯一新增的等待，只该花在真有残留的时候。绝大多数接管（包括会话正忙着的那些，
    它们的框本来就空）走的是这条免费的路。
    """
    from frago.agent_driver.driver import load_driver

    runner = _tracking_runner()
    runner.fake.seed_orphan("frago-agent-sid", "2.1.250")
    pool = WarmSessionPool(runner=runner)

    cleared: list[str] = []
    driver = load_driver("opencode")
    object.__setattr__(
        driver, "clear_input", lambda s: (cleared.append(s.tmux_name), True)[1]
    )
    try:
        session = pool.acquire("opencode", "sid", "/tmp")
        assert cleared == [], "框是空的就不该白清一遍"
        assert session.adopted is True
    finally:
        object.__setattr__(driver, "clear_input", None)


def test_adoption_survives_a_driver_that_cannot_clear() -> None:
    """清不干净不阻断接管：带上残留仍然远好过把一个健康会话杀掉重来。"""
    from frago.agent_driver.driver import load_driver

    runner = _tracking_runner()
    runner.fake.seed_orphan("frago-agent-sid", "2.1.250")
    pool = WarmSessionPool(runner=runner)

    runner.fake.pane_text = "▣ Build · m · 1.0s\n> 残留的半句话"
    driver = load_driver("opencode")
    object.__setattr__(driver, "clear_input", lambda s: False)
    try:
        session = pool.acquire("opencode", "sid", "/tmp")
        assert session.adopted is True
        assert runner.fake.killed == []
    finally:
        object.__setattr__(driver, "clear_input", None)


def test_lru_never_kills_a_session_that_is_working() -> None:
    """数量满了按最久未用回收，**但正在干活的一场都不动。**

    从前这里只看谁最久没被碰过。一场跑了二十分钟的长任务，期间人在页面上点开并发话
    给另外若干场会话，它就会被挤掉：那一轮的工具调用、后台起的 worker，连同还没落盘
    的产出一起没，而界面上看不出发生过这件事。
    """
    runner = _tracking_runner()
    pool = WarmSessionPool(max_size=2, runner=runner)
    busy = pool.acquire("opencode", "busy", "/tmp")
    busy.status = "busy"                      # 它正跑着一轮长任务
    pool.acquire("opencode", "b", "/tmp")
    pool.acquire("opencode", "c", "/tmp")     # 超限 → 该踢最久未用的，也就是 busy

    assert "frago-agent-busy" not in runner.fake.killed, "正在干活的会话不许被踢"
    assert runner.fake.killed == ["frago-agent-b"], "该踢的是下一个不忙的"
    assert set(pool.active_ids()) == {"busy", "c"}


def test_over_capacity_is_tolerated_when_everything_is_busy() -> None:
    """全都在忙时宁可暂时超编：多留一个 tmux 进程，好过把一个正在干活的会话杀掉。

    空闲巡检随后会把真正闲下来的收走，超编是暂时的。
    """
    runner = _tracking_runner()
    pool = WarmSessionPool(max_size=1, runner=runner)
    a = pool.acquire("opencode", "a", "/tmp")
    a.status = "busy"
    b = pool.acquire("opencode", "b", "/tmp")
    b.status = "busy"

    assert runner.fake.killed == []
    assert len(pool) == 2


# ── 别名：认领来的原生编号与新建时那个把手，指的是同一场会话 ──────────────


def test_alias_makes_claimed_id_reuse_the_same_session() -> None:
    """页面拿认领到的编号再发话时，MUST 落回同一个 TUI，NEVER 另起一个。

    不这样的话，两个 tmux 会同时对着一份 rollout 说话——人看到的是自己的话被吞掉、
    或者两轮答案交错在一起，而界面上一点异样都没有。
    """
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    launched = pool.acquire("opencode", "webui-handle", "/tmp")

    assert pool.alias("ses_real", "webui-handle") is True

    assert pool.has("ses_real")
    assert pool.peek("ses_real") is launched
    assert pool.acquire("opencode", "ses_real", "/tmp") is launched
    # 只起过一场 tmux：别名没有把它变成两场。
    new_sessions = [c for c in runner.fake.commands if c[1:2] == ["new-session"]]
    assert len(new_sessions) == 1
    # 会话对象自己的编号一个字没改——driver 侧的认领映射正是拿它当键。
    assert launched.session_id == "webui-handle"


def test_alias_refuses_to_point_at_nothing() -> None:
    """目标不在池里就什么都不做：凭空一条别名只会让下次 acquire 拿着空键去起会话。"""
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    assert pool.alias("ses_real", "never-launched") is False
    assert not pool.has("ses_real")


def test_evict_drops_aliases_pointing_at_it() -> None:
    """收走一场会话，指向它的别名跟着清，NEVER 留一张对不上号的映射表。"""
    runner = _make_runner()
    pool = WarmSessionPool(runner=runner)
    pool.acquire("opencode", "webui-handle", "/tmp")
    pool.alias("ses_real", "webui-handle")

    # 用别名驱逐也算数：指的本来就是同一场。
    assert pool.evict("ses_real") is True
    assert not pool.has("ses_real")
    assert not pool.has("webui-handle")

    # 别名清干净了：同名再 acquire 是一场全新的会话，而不是复用一个已被 kill 的把手。
    fresh = pool.acquire("opencode", "ses_real", "/tmp")
    assert fresh.session_id == "ses_real"
