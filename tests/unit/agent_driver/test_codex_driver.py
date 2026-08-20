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


# ── 就绪 / 完成 / 阻断 ──────────────────────────────────────────────
@pytest.mark.parametrize("pane", [BANNER_PANE, FOOTER_PANE])
def test_ready_matches_a_live_tui(pane):
    assert codex_driver._READY.matches(pane) is True


def test_ready_never_matches_the_launch_command_echo():
    """回归：命中这一屏就等于在 TUI 起来之前投喂，本轮必定静默挂死。"""
    assert codex_driver._READY.matches(SHELL_ECHO_PANE) is False


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
