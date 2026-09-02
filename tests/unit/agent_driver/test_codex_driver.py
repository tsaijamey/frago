"""codex driver 的单测。

重点守两件事：

1. **就绪信号绝不命中启动命令的回显**。首版占位实现的就绪式子是
   ``(?i)codex|>\\s``，tmux 敲进 shell 的那行 ``codex …`` 自己就命中了，于是提示词
   被投进 shell、永远到不了 codex，本轮无答案无报错地空等到超时。这是本 driver
   历史上最贵的一个 bug，回归测试钉在这里。
2. **写目录信任 NEVER 把用户的 config.toml 弄坏**。表已存在时再追加一个同名表头
   会让整份 TOML 非法（重复键），codex 会直接拒绝加载配置并退出——那等于用一次
   "帮你省事"把用户的 codex 彻底弄坏。
"""

import tomllib

import pytest

from frago.agent_driver.drivers import codex as codex_driver

BANNER_PANE = """
╭──────────────────────────────────────────────────────╮
│ >_ OpenAI Codex (v0.147.0)                           │
│ model:     deepseek-v4-flash high   /model to change │
╰──────────────────────────────────────────────────────╯
"""
FOOTER_PANE = "  deepseek-v4-flash high · /Users/x/Repos/frago\n"
SHELL_ECHO_PANE = (
    " ~/Repos/frago  main !1 ····················· 23:14:42 ─╮\n"
    "❯ codex -c check_for_update_on_startup=false "
    "--dangerously-bypass-hook-trust --dangerously-bypass-approvals-and-sandbox\n"
)
# 20260902 本机实测：同一场 codex 会话已经有一个活着的写者时，第二次 resume 的末屏。
# 原样抄下来，一个字都没改——判据是照着真实终端写的，改一个字这条回归就不算数了。
RESUME_WRITER_LOCK_PANE = (
    "╭───────────────────────────────────────────────────────╮\n"
    "│ >_ OpenAI Codex (v0.149.0)                            │\n"
    "│                                                       │\n"
    "│ model:     loading   /model to change                 │\n"
    "│ directory: /private/tmp/claude-502/…/scratchpad/smoke │\n"
    "╰───────────────────────────────────────────────────────╯\n"
    "  Resuming session…\n"
    "\n"
    "› Error: Failed to resume session from /Users/frago/.codex/sessions/2026/09/02/"
    "rollout-2026-09-02T11-18-49-01a06020-618c-7cf3-ab26-359977260ba7.jsonl: "
    "thread/resume failed during TUI bootstrap: thread\n"
    "/resume failed: thread 01a06020-618c-7cf3-ab26-359977260ba7 already has an "
    "active writer (code -32600)\n"
    "\n"
    " /private/tm/cl/-Users-frago-Repos-f/53/scratchpad/smoke ······· 17s  11:32:33 ─╮\n"
    "❯                                                                             ─╯\n"
)


# ── 就绪 / 完成 / 阻断 ──────────────────────────────────────────────
@pytest.mark.parametrize("pane", [BANNER_PANE, FOOTER_PANE])
def test_ready_matches_a_live_tui(pane):
    assert codex_driver._READY.matches(pane) is True


def test_ready_never_matches_the_launch_command_echo():
    """回归：命中这一屏就等于在 TUI 起来之前投喂，本轮必定静默挂死。"""
    assert codex_driver._READY.matches(SHELL_ECHO_PANE) is False


def test_ready_never_matches_a_resume_that_failed_on_the_writer_lock():
    """回归：横幅在，不等于会话活着。

    codex 0.149 给每场会话上了单写者锁，同一场第二次 ``codex resume`` 会在 TUI
    bootstrap 阶段失败。**这一屏上启动横幅是在的**——codex 先画横幅、再回放会话、才
    失败——所以只看结构信号会当场判就绪，接着 codex 自己退出、pane 落回 shell 提示符，
    而用户那句话被打进了 shell 当命令执行，完成信号永不出现，本轮空等到超时。

    下面这一屏是 20260902 本机实测抓下来的原样，一个字都没改。
    """
    assert codex_driver._READY.matches(RESUME_WRITER_LOCK_PANE) is False


def test_ready_still_matches_a_healthy_resume():
    """守另一边：正常 resume 回放完的那一屏 MUST 仍然算就绪。

    只钉住"起不来那一屏不算就绪"，很容易顺手把判据收紧到连正常会话都起不来——那时
    每一场 codex 会话都会以启动超时收场，比原来的 bug 影响面还大。
    """
    assert codex_driver._READY.matches(BANNER_PANE) is True


def test_done_requires_the_absence_of_the_interrupt_hint():
    assert codex_driver._DONE.matches(FOOTER_PANE) is True
    assert codex_driver._DONE.matches(FOOTER_PANE + "  Esc to interrupt\n") is False


def test_needs_input_only_fires_on_explicit_failures():
    assert codex_driver._NEEDS_INPUT.matches("Error: unauthorized") is True
    assert codex_driver._NEEDS_INPUT.matches("invalid API key") is True
    # 启动横幅与普通正文里的良性字眼 MUST 不命中，否则本轮刚提交就误判返回。
    assert codex_driver._NEEDS_INPUT.matches(BANNER_PANE) is False
    assert codex_driver._NEEDS_INPUT.matches("请先 login 到网站看看") is False


# ── 目录信任写入 ────────────────────────────────────────────────────
def test_appends_the_table_when_the_directory_is_unknown():
    text = 'model = "gpt-5"\n'
    updated = codex_driver._write_trust(text, "/repo")
    parsed = tomllib.loads(updated)
    assert parsed["model"] == "gpt-5"
    assert parsed["projects"]["/repo"]["trust_level"] == "trusted"


def test_updates_in_place_when_the_table_already_exists():
    """表已存在时 MUST 就地改，追加同名表头会让整份 TOML 变成非法。"""
    text = '[projects."/repo"]\ntrust_level = "untrusted"\n'
    updated = codex_driver._write_trust(text, "/repo")
    parsed = tomllib.loads(updated)  # 非法 TOML 会在这里炸
    assert parsed["projects"]["/repo"]["trust_level"] == "trusted"


def test_inserts_the_key_when_the_table_exists_without_it():
    text = '[projects."/repo"]\nsomething_else = 1\n\n[tui]\ntheme = "dark"\n'
    updated = codex_driver._write_trust(text, "/repo")
    parsed = tomllib.loads(updated)
    assert parsed["projects"]["/repo"]["trust_level"] == "trusted"
    assert parsed["projects"]["/repo"]["something_else"] == 1
    assert parsed["tui"]["theme"] == "dark"


def test_preserves_comments_and_neighbouring_tables():
    """配置是用户手写手维护的：注释、键序、空行都得原样留着。"""
    text = (
        "# my codex config\n"
        'model = "gpt-5"\n'
        "\n"
        "[model_providers.deepseek]\n"
        '# 别动这行\n'
        'base_url = "https://api.deepseek.com/"\n'
    )
    updated = codex_driver._write_trust(text, "/repo")
    assert "# my codex config" in updated
    assert "# 别动这行" in updated
    parsed = tomllib.loads(updated)
    assert parsed["model_providers"]["deepseek"]["base_url"] == (
        "https://api.deepseek.com/"
    )
    assert parsed["projects"]["/repo"]["trust_level"] == "trusted"


def test_recognises_an_already_trusted_directory():
    text = '[projects."/repo"]\ntrust_level = "trusted"\n'
    assert codex_driver._already_trusted(text, "/repo") is True
    assert codex_driver._already_trusted(text, "/other") is False
    assert codex_driver._already_trusted("", "/repo") is False


def test_unparseable_config_is_treated_as_not_trusted():
    """解析不了就当没有：宁可多走一次写入路径，也不能当作已信任而放过那道菜单。"""
    assert codex_driver._already_trusted("{ not toml", "/repo") is False


def test_ensure_trusted_is_idempotent_and_writes_the_real_file(tmp_path, monkeypatch):
    home = tmp_path / ".codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    (home / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")

    codex_driver._ensure_workspace_trusted(str(tmp_path))
    first = (home / "config.toml").read_text(encoding="utf-8")
    codex_driver._ensure_workspace_trusted(str(tmp_path))
    assert (home / "config.toml").read_text(encoding="utf-8") == first

    parsed = tomllib.loads(first)
    assert parsed["projects"][str(tmp_path)]["trust_level"] == "trusted"


def test_ensure_trusted_never_raises_when_the_config_cannot_be_written(
    tmp_path, monkeypatch
):
    """信任写入尽力而为：最坏是菜单照常弹，NEVER 让它把 launch 打死。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nope"))
    monkeypatch.setattr(
        codex_driver.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("ro"))
    )
    codex_driver._ensure_workspace_trusted(str(tmp_path))  # 不抛即通过


# ── 启动命令 ────────────────────────────────────────────────────────
def _ctx(tmp_path, session_id="frago-1", native=False):
    return codex_driver.LaunchCtx(
        cwd=str(tmp_path), session_id=session_id, native_session_id=native
    )


def test_launch_carries_the_flags_that_disarm_the_startup_modals(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(codex_driver, "_ensure_workspace_trusted", lambda _c: None)
    monkeypatch.setattr(codex_driver.codex_store, "get_binding", lambda _s: None)
    command = codex_driver._launch(_ctx(tmp_path))
    assert command.startswith("codex ")
    assert "check_for_update_on_startup=false" in command
    assert "--dangerously-bypass-hook-trust" in command
    assert "resume" not in command


def test_launch_resumes_a_bound_session(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_driver, "_ensure_workspace_trusted", lambda _c: None)
    monkeypatch.setattr(codex_driver.codex_store, "get_binding", lambda _s: "codex-9")
    monkeypatch.setattr(codex_driver.codex_store, "session_exists", lambda _s: True)
    assert codex_driver._launch(_ctx(tmp_path)).endswith("resume codex-9")


def test_launch_drops_a_binding_whose_records_are_gone(tmp_path, monkeypatch):
    """记录被删掉后还发 resume 就起不来，本轮等满超时，而绑定还在——下次再死一遍。"""
    dropped = []
    monkeypatch.setattr(codex_driver, "_ensure_workspace_trusted", lambda _c: None)
    monkeypatch.setattr(codex_driver.codex_store, "get_binding", lambda _s: "codex-9")
    monkeypatch.setattr(codex_driver.codex_store, "session_exists", lambda _s: False)
    monkeypatch.setattr(codex_driver.codex_store, "drop_binding", dropped.append)
    command = codex_driver._launch(_ctx(tmp_path))
    assert "resume" not in command
    assert dropped == ["frago-1"]


# ── 单写者锁：起不来那一屏 MUST 快速、如实收场，且绝不把话交给 shell ──────────
def test_needs_input_fires_on_the_writer_lock_screen():
    """回归：这道门是**轮询里**反复看的，就绪那道闸挡不住这个时序。

    实测时序是：横幅先画 → 就绪当场命中、``open()`` 返回 → 提示词打进去 → codex
    这时才失败退出。错误行在就绪判定那一刻还没上屏，所以必须由这道门在轮询中接住，
    否则本轮空等到超时（实测 600s）。
    """
    assert codex_driver._NEEDS_INPUT.matches(RESUME_WRITER_LOCK_PANE) is True


def test_needs_input_still_ignores_benign_text():
    """守另一边：把判据放宽之后，普通答案正文 MUST 仍然不命中。"""
    assert codex_driver._NEEDS_INPUT.matches(BANNER_PANE) is False
    assert codex_driver._NEEDS_INPUT.matches("我把这一版的会话恢复功能写完了") is False


class _FakePane:
    """只答读屏、记下发过哪些键的假会话。"""

    def __init__(self, pane: str) -> None:
        self.pane = pane
        self.keys: list[tuple[str, ...]] = []
        self.texts: list[str] = []
        self.session_id = "sid"
        self.cwd = "/tmp"
        self.native_session_id = True
        self._poll_interval_s = 0

    def capture_pane(self, **_kw) -> str:
        return self.pane

    def send_text(self, text: str) -> None:
        self.texts.append(text)

    def send_keys(self, *keys: str) -> None:
        self.keys.append(keys)

    def _sleep(self, _s: float) -> None:
        return None


def test_submit_never_presses_enter_into_a_dead_tui(monkeypatch):
    """安全闸回归：TUI 已经起不来时 MUST 不按 Enter。

    按下去，用户在页面上打的那句话就落到 shell 上被**当成命令执行**——实测 pane 上
    留下过 ``zsh: command not found: 这句话不该被打进``。这次的内容无害，但页面上的
    一句话本就可能长得像命令，这是整条链路上后果最严重的一种错法。

    文本本身已经发出去了没关系：没有 Enter，它只停在 shell 的行缓冲里，不会执行。
    """
    monkeypatch.setattr(codex_driver, "_claim_once", lambda s: None)
    monkeypatch.setattr(codex_driver, "_rollout_size", lambda s: 0)

    session = _FakePane(RESUME_WRITER_LOCK_PANE)
    codex_driver._submit(session, "rm -rf 看起来像命令的一句话")

    assert session.keys == [], "TUI 已经不在了，一个 Enter 都不该发出去"


def test_submit_still_presses_enter_on_a_healthy_tui(monkeypatch):
    """守另一边：健康会话照常提交，NEVER 因为这道闸把正常的一轮拦下来。"""
    monkeypatch.setattr(codex_driver, "_claim_once", lambda s: None)
    sizes = iter([0, 1, 1, 1, 1])
    monkeypatch.setattr(codex_driver, "_rollout_size", lambda s: next(sizes, 1))

    session = _FakePane(BANNER_PANE + "\n› 干活\n")
    codex_driver._submit(session, "干活")

    assert ("Enter",) in session.keys


def test_tui_is_gone_treats_an_unreadable_pane_as_still_alive(monkeypatch):
    """读不到屏不是"它死了"——单向判据，避免一次瞬时读屏失败拦下健康的一轮。"""

    class _Unreadable(_FakePane):
        def capture_pane(self, **_kw):
            raise RuntimeError("tmux 这一拍不答")

    assert codex_driver._tui_is_gone(_Unreadable("")) is False
