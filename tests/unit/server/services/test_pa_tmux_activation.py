"""Phase 3 单测：PA 本体接常驻 tmux。

PaTmuxRunner 会话复用 / bootstrap 注入语义、tmux 输出走 _handle_pa_output 路由、
rotation 驱逐 resident 会话。

后端选择本身已无测点：Phase 5 起 tmux 是唯一后端，resolve_backend() 这个恒返回
常量的函数随之删除（生产侧零调用方）。
"""

from __future__ import annotations

import asyncio

import frago.server.services.primary_agent_service as pa_mod
from frago.agent_driver.tmux_session import TurnResult
from frago.server.services.pa_tmux_runner import PaTmuxRunner
from frago.server.services.primary_agent_service import PrimaryAgentService

# ── Phase 3 helpers ──────────────────────────────────────────────────────────


class FakePool:
    """A WarmSessionPool stand-in recording runs and tracking live session keys."""

    def __init__(self) -> None:
        self.live: set[str] = set()
        self.runs: list[tuple[str, str]] = []   # (session_id, prompt)
        self.evicted: list[str] = []
        self.reply_text = "[]"
        self.status = "ok"
        self.raw_delta = ""

    def has(self, session_id: str) -> bool:
        return session_id in self.live

    def peek(self, session_id: str):  # noqa: ARG002
        # 喂料门 / 收尾的真空闲判定取活会话对象。这些单测聚焦投递/挂起/轮换逻辑，
        # 不模拟真实 tmux pane，统一返回 None → 真空闲门短路（无活会话=立即放行）。
        return None

    def run(self, prompt, *, agent_type, session_id, cwd, conv_key=None, timeout_s=120.0, resume_hook=None):  # noqa: ARG002
        self.runs.append((session_id, prompt))
        self.live.add(session_id)
        return TurnResult(
            text=self.reply_text, raw_delta=self.raw_delta, status=self.status, duration_ms=1,
        )

    def evict(self, session_id: str) -> bool:
        self.evicted.append(session_id)
        existed = session_id in self.live
        self.live.discard(session_id)
        return existed

    def shutdown(self) -> None:
        self.live.clear()


def _fresh_pa() -> PrimaryAgentService:
    svc = PrimaryAgentService.__new__(PrimaryAgentService)
    svc.__init__()
    return svc


# ── Phase 3 tests ────────────────────────────────────────────────────────────


def test_runner_reuses_session_and_injects_bootstrap_once():
    """同一 session_key 连发两条：首轮 bootstrap 独立一轮 + 消息一轮，次轮只发 prompt、复用同一会话。"""
    pool = FakePool()
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")

    runner.run("thread-A", "msg-1", bootstrap="BOOT")
    runner.run("thread-A", "msg-2", bootstrap="BOOT")

    assert [sid for sid, _ in pool.runs] == ["thread-A", "thread-A", "thread-A"]
    # 首轮：bootstrap 作为独立一轮先注入，再发 msg-1；次轮只发 msg-2（会话已暖，不重注入）。
    assert pool.runs[0][1] == "BOOT"
    assert pool.runs[1][1] == "msg-1"
    assert pool.runs[2][1] == "msg-2"


def test_runner_fallback_key_when_no_thread():
    pool = FakePool()
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    runner.run(None, "msg", bootstrap="BOOT")
    assert pool.runs[0][0] == PaTmuxRunner.FALLBACK_KEY


def test_runner_evict_rebuilds_with_bootstrap():
    """evict 后下一轮 run 重新注入 bootstrap（会话已不在）。"""
    pool = FakePool()
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    runner.run("thread-A", "msg-1", bootstrap="BOOT")  # runs: BOOT, msg-1
    assert runner.evict("thread-A") is True
    runner.run("thread-A", "msg-2", bootstrap="BOOT")  # 会话已驱逐 → 重注入: BOOT, msg-2
    assert pool.runs[2][1] == "BOOT"
    assert pool.runs[3][1] == "msg-2"
    assert pool.evicted == ["thread-A"]


def test_ok_branch_does_not_deliver_delivery_decoupled(monkeypatch):
    """Phase 6: ok 分支 NEVER 自己 deliver——投递解耦给 transcript 持续转发器。

    dispatch 只喂 prompt + 等真空闲再返回；本轮终答由 watcher 按 transcript marker
    去重投递（见 test_pa_transcript_watcher）。这里验证 dispatch 不再双投。
    """
    svc = _fresh_pa()
    pool = FakePool()
    pool.reply_text = "你好，已经查好了。"
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")

    # bootstrap 构建走真实路径成本高且依赖 board；mock 成轻量返回。
    monkeypatch.setattr(svc, "_build_bootstrap_prompt", lambda **kw: ("BOOT", "route"))  # noqa: ARG005

    delivered: list[tuple[str, dict]] = []

    async def _deliver(text, route):
        delivered.append((text, route))

    monkeypatch.setattr(svc, "deliver", _deliver)

    group = [{"type": "user_message", "channel": "lark", "prompt": "yo", "thread_id": "thread-A"}]
    asyncio.run(svc._dispatch_group_tmux("thread-A", group))

    assert delivered == []                  # dispatch 不投递（解耦给 watcher）
    assert pool.runs[0][0] == "thread-A"     # 同一 thread 复用同一 session_key


def test_runner_returns_full_turnresult():
    """PaTmuxRunner.run 返回整个 TurnResult（含 status / raw_delta），不再只取 .text。"""
    pool = FakePool()
    pool.reply_text = "hi"
    pool.status = "needs_input"
    pool.raw_delta = "menu"
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    res = runner.run("thread-A", "msg")
    assert isinstance(res, TurnResult)
    assert res.text == "hi"
    assert res.status == "needs_input"
    assert res.raw_delta == "menu"


def test_needs_input_delivers_prompt_and_suspends_without_requeue(monkeypatch):
    """status==needs_input：投递"需要你选…"回 chat，挂起 conv，不重入队列、不 rotate。"""
    svc = _fresh_pa()
    pool = FakePool()
    pool.status = "needs_input"
    pool.raw_delta = "╭────────╮\n│ Do you want to proceed?\n│ ❯ 1. Yes\n│   2. No\n╰────────╯"
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    monkeypatch.setattr(svc, "_build_bootstrap_prompt", lambda **kw: ("BOOT", "route"))  # noqa: ARG005

    rotated: list[str | None] = []

    async def _rot(tid=None):
        rotated.append(tid)

    monkeypatch.setattr(svc, "_rotate_tmux_session", _rot)
    # 让 token 超阈值，验证 needs_input 分支早返回、确实没触发 rotation。
    svc._accumulated_tokens["thread-A"] = pa_mod.ROTATION_TOKEN_THRESHOLD + 1

    delivered: list[tuple[str, dict]] = []

    async def _deliver(text, route):
        delivered.append((text, route))

    monkeypatch.setattr(svc, "deliver", _deliver)

    group = [{"type": "lark", "channel": "lark", "task_id": "t1", "msg_id": "m1",
              "prompt": "yo", "thread_id": "thread-A"}]
    asyncio.run(svc._dispatch_group_tmux("thread-A", group))

    assert rotated == []                        # 没 rotate
    assert "thread-A" in svc._suspended_convs   # 挂起标记
    assert len(delivered) == 1
    text, route = delivered[0]
    assert route["channel"] == "lark"
    assert route["task_id"] == "t1"
    assert "需要你选" in text
    assert "1. Yes" in text                # 菜单文本带出
    assert "╭" not in text                 # 边框 chrome 抠掉


def test_ok_status_clears_suspended(monkeypatch):
    """status==ok：清除挂起标记（投递已解耦给 watcher，dispatch 自身不投）。"""
    svc = _fresh_pa()
    pool = FakePool()
    pool.reply_text = "好的，处理完了。"
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._suspended_convs.add("thread-A")
    monkeypatch.setattr(svc, "_build_bootstrap_prompt", lambda **kw: ("BOOT", "route"))  # noqa: ARG005

    delivered: list[tuple[str, dict]] = []

    async def _deliver(text, route):
        delivered.append((text, route))

    monkeypatch.setattr(svc, "deliver", _deliver)

    group = [{"type": "user_message", "channel": "lark", "prompt": "yo", "thread_id": "thread-A"}]
    asyncio.run(svc._dispatch_group_tmux("thread-A", group))

    assert "thread-A" not in svc._suspended_convs
    assert delivered == []   # dispatch 不投递


def test_rotation_evicts_resident_session_and_resets_counter():
    """token 超阈值触发 rotation → evict 该 key 并复位计数器（无 claude-p 子进程可拆）。"""
    svc = _fresh_pa()
    pool = FakePool()
    pool.live.add("thread-A")  # 假装会话已活
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._accumulated_tokens["thread-A"] = pa_mod.ROTATION_TOKEN_THRESHOLD + 1
    svc._rotation_count["thread-A"] = 2

    asyncio.run(svc._rotate_tmux_session("thread-A"))

    assert pool.evicted == ["thread-A"]
    assert svc._accumulated_tokens["thread-A"] == 0
    assert svc._rotation_count["thread-A"] == 3


def test_rotate_session_dispatches_to_compact_when_backend_tmux(monkeypatch, tmp_path):
    """Phase 7: rotate_session 路由到 _compact_tmux_session（就地 /compact，不再 evict）。"""
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", tmp_path / "config.json")  # 默认 tmux
    svc = _fresh_pa()

    called: list[str | None] = []

    async def _compact(tid=None):
        called.append(tid)

    monkeypatch.setattr(svc, "_compact_tmux_session", _compact)

    asyncio.run(svc.rotate_session(thread_id="thread-A"))
    assert called == ["thread-A"]


# ── Phase 7: token-rotation 就地 /compact ────────────────────────────────────


class _IdleSession:
    """真空闲可控的会话替身：记录 /compact 投喂，idle 标志驱动真空闲判定。"""

    def __init__(self, idle: bool = True) -> None:
        self.idle = idle
        self.sent_text: list[str] = []
        self.sent_keys: list[tuple[str, ...]] = []

    def send_text(self, text: str) -> None:
        self.sent_text.append(text)

    def send_keys(self, *keys: str) -> None:
        self.sent_keys.append(keys)


class _CompactPool(FakePool):
    """FakePool + 可注入活会话对象（peek 返回它），供 compact 路径走真分支。"""

    def __init__(self, session=None) -> None:
        super().__init__()
        self._session = session

    def peek(self, session_id: str):  # noqa: ARG002
        return self._session

    def active_ids(self) -> list[str]:
        return list(self.live)


def test_compact_idle_sends_slash_compact_and_keeps_session_alive(monkeypatch):
    """真空闲：发 /compact + 提交，重置计数 + rotation_count+1，会话保活（未 evict）。"""
    svc = _fresh_pa()
    sess = _IdleSession(idle=True)
    pool = _CompactPool(session=sess)
    pool.live.add("thread-A")
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._accumulated_tokens["thread-A"] = 999
    svc._total_turns["thread-A"] = 7
    svc._rotation_count["thread-A"] = 2

    monkeypatch.setattr(svc, "_is_truly_idle", lambda key: True)  # noqa: ARG005
    seeded: list[str | None] = []
    monkeypatch.setattr(svc, "_seed_marker", lambda ck: seeded.append(ck))

    asyncio.run(svc._compact_tmux_session("thread-A"))

    assert sess.sent_text == ["/compact"]
    assert ("Enter",) in sess.sent_keys
    assert pool.evicted == []                      # 会话保活，NEVER kill
    assert svc._accumulated_tokens["thread-A"] == 0
    assert svc._total_turns["thread-A"] == 0
    assert svc._rotation_count["thread-A"] == 3
    assert seeded == ["thread-A"]                   # baseline 重锚
    assert "thread-A" not in svc._compacting_convs  # 完成后清标记


def test_compact_busy_skips_without_kill(monkeypatch):
    """超时仍 busy：跳过本次 compact，NEVER 发 /compact、NEVER evict、计数不动。"""
    svc = _fresh_pa()
    sess = _IdleSession(idle=False)
    pool = _CompactPool(session=sess)
    pool.live.add("thread-A")
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._accumulated_tokens["thread-A"] = 999
    svc._rotation_count["thread-A"] = 2

    # 喂料门立即返回（不真等），但随后真空闲检测仍为 False → 判定超时跳过。
    async def _no_wait(key):  # noqa: ARG001
        return None

    monkeypatch.setattr(svc, "_wait_until_truly_idle", _no_wait)
    monkeypatch.setattr(svc, "_is_truly_idle", lambda key: False)  # noqa: ARG005

    asyncio.run(svc._compact_tmux_session("thread-A"))

    assert sess.sent_text == []                     # 未发 /compact
    assert pool.evicted == []                       # NEVER kill
    assert svc._accumulated_tokens["thread-A"] == 999  # 计数不动
    assert svc._rotation_count["thread-A"] == 2


def test_compact_no_live_session_resets_counters_only(monkeypatch):
    """无活会话：不发 /compact、不 evict，仅复位计数（下条消息走 --resume 重建）。"""
    svc = _fresh_pa()
    pool = _CompactPool(session=None)
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._accumulated_tokens["thread-A"] = 999
    svc._rotation_count["thread-A"] = 5

    monkeypatch.setattr(svc, "_is_truly_idle", lambda key: True)  # noqa: ARG005

    asyncio.run(svc._compact_tmux_session("thread-A"))

    assert pool.evicted == []
    assert svc._accumulated_tokens["thread-A"] == 0
    assert svc._rotation_count["thread-A"] == 6


def test_watcher_skips_compacting_conv(monkeypatch):
    """compacting 期间转发器跳过该 conv（/compact 产出不被投递）。"""
    svc = _fresh_pa()
    pool = _CompactPool(session=_IdleSession())
    pool.live.add("thread-A")
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._conv_route_cache["thread-A"] = {"channel": "lark", "conv_key": "thread-A", "reply_context": {}}
    svc._compacting_convs.add("thread-A")

    polled: list[str] = []
    monkeypatch.setattr(svc, "_watch_poll", lambda ck, since: polled.append(ck) or (1.0, None))  # noqa: ARG005

    delivered: list = []
    monkeypatch.setattr(svc, "deliver", lambda *a: delivered.append(a))

    asyncio.run(svc._watch_tick())

    assert polled == []        # compacting 的 conv 根本没被 poll
    assert delivered == []
