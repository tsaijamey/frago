"""Tests for frago.server.services.stage_orchestrator module.

验证舞台硬编排器（Stage Orchestrator）：
1. 舞台会话判定（skills 包含或 prompt 嵌入 marker）；
2. 用户需求清洗（剥离 <must-use-skill> 与硬编排尾缀，杜绝账本污染）；
3. 纯英文语音门禁保障（所有转写输出 100% 通过 frago.desktop.voice.assert_english_only）；
4. 协同目录、ledger.md 初始化与参谋首轮自动推演；
5. 主操作员指令幂等注入（要求前台幕脚本自带同步英文配音）；
6. 驻场主持人盯面板、盯账本新增进展排队播报与生命周期管理。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.desktop.voice import check_language
from frago.server.services import stage_orchestrator as so
from frago.session.unified_record import UnifiedRecord


def assert_english_only(text: str) -> None:
    check_language(text, so.DEFAULT_VOICE)


@pytest.fixture(autouse=True)
def clean_presenters():
    with so._presenters_lock:
        for p in list(so._presenters.values()):
            p.stop()
        so._presenters.clear()
    yield
    with so._presenters_lock:
        for p in list(so._presenters.values()):
            p.stop()
        so._presenters.clear()


def test_is_stage_session():
    assert so.is_stage_session(skills=["how-frago-agent-runs-an-agent-os"]) is True
    assert so.is_stage_session(skills=["other-skill"]) is False
    assert (
        so.is_stage_session(prompt='<must-use-skill name="how-frago-agent-runs-an-agent-os">')
        is True
    )
    assert so.is_stage_session(prompt="hello world") is False


def test_clean_user_requirement_strips_skill_and_directive(tmp_path):
    raw = (
        '<must-use-skill name="how-frago-agent-runs-an-agent-os" path="/tmp/SKILL.md">\n'
        "16KB skill content here...\n"
        "</must-use-skill>\n\n"
        "介绍一下stock volatility adaptive lab这个配方"
    )
    cleaned = so.clean_user_requirement(raw)
    assert cleaned == "介绍一下stock volatility adaptive lab这个配方"
    assert "<must-use-skill" not in cleaned

    # 即使已经注入过硬编排指令，也能干净剥离
    with_directive = so.inject_stage_directive(raw, "sid_1", tmp_path / "ledger.md")
    assert so.clean_user_requirement(with_directive) == "介绍一下stock volatility adaptive lab这个配方"


def test_english_sanitization_passes_voice_guard():
    # 含中文与全角标点的输入经过清洗或账本转写后，必须 100% 通过 voice.assert_english_only
    s1 = so.sanitize_english_for_tts("Received: 介绍一下 stock_volatility_adaptive_lab（v2.0.0）！")
    assert_english_only(s1)
    assert "stock_volatility_adaptive_lab" in s1

    lines = [
        ("参谋挑刺与备选方案", "- 参谋首轮推演（20:55）：针对「介绍一下stock volatility adaptive lab」建议分三幕呈现"),
        ("主操拍板与当前动作", "- 20:57 已核实配方真实存在：stock_volatility_adaptive_lab v2.0.0"),
        ("主操拍板与当前动作", "- 20:58 第一幕上台：终端真实执行 frago recipe info stock_volatility_adaptive_lab"),
        ("主操拍板与当前动作", "- 20:59 第二幕：在浏览器打开真实页面 http://127.0.0.1:8093/app/stock_volatility_adaptive_lab/"),
        ("主操拍板与当前动作", "- 拍板：三个 mode 用终端真回执讲，五层算法用全屏讲稿讲"),
    ]
    for sec, line in lines:
        en = so.translate_ledger_item_to_english(sec, line)
        assert en
        assert_english_only(en)
        assert "operator" not in en.lower()


def test_presenter_perspective_blocks_operator_phrasing(tmp_path):
    # 即使输入中混入操作员自报家门或第三人称转述，统一把关函数也会将其过滤/改写为第一人称
    raw_op_intro = (
        "Hi, this is your operator speaking. You asked me to show you how to use Google."
    )
    cleaned = so.sanitize_english_for_tts(raw_op_intro, speaker="presenter")
    assert_english_only(cleaned)
    assert "operator" not in cleaned.lower()
    assert cleaned.startswith("You asked me to show you how to use Google")

    raw_bystander = "Now the operator is speaking and our operator has verified the page."
    cleaned_bystander = so.sanitize_english_for_tts(raw_bystander, speaker="presenter")
    assert_english_only(cleaned_bystander)
    assert "operator" not in cleaned_bystander.lower()

    # 检查注入给主操作员的硬编排指令已明令禁止自报 operator 身份
    directive = so.inject_stage_directive("演示 google", "sid_1", tmp_path / "ledger.md")
    assert "NEVER 出现 `this is your operator speaking`" in directive


def test_init_collaboration_dir_and_advisor_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    session_id = "core_1234567890abcdef"
    raw_prompt = (
        '<must-use-skill name="how-frago-agent-runs-an-agent-os">skill body</must-use-skill>\n'
        "验证 stock_volatility_adaptive_lab 配方功能"
    )
    stage_dir, ledger_path = so.init_collaboration_dir(session_id, raw_prompt)

    assert stage_dir.is_dir()
    assert ledger_path.is_file()
    assert stage_dir.parent == so.STAGE_DATA_ROOT

    content = ledger_path.read_text(encoding="utf-8")
    assert "<must-use-skill" not in content
    assert "验证 stock_volatility_adaptive_lab 配方功能" in content

    # 执行参谋首轮推演
    so.run_initial_advisor_pass(ledger_path, raw_prompt)
    updated = ledger_path.read_text(encoding="utf-8")
    assert "参谋首轮推演" in updated
    assert "stock_volatility_adaptive_lab" in updated


def test_inject_stage_directive_idempotent_and_beat_voice(tmp_path):
    ledger = tmp_path / "ledger.md"
    orig_prompt = "请帮我运行一次配方"
    injected_once = so.inject_stage_directive(orig_prompt, "sid_abc", ledger)
    injected_twice = so.inject_stage_directive(injected_once, "sid_abc", ledger)

    assert injected_once == injected_twice
    assert injected_once.count(so.DIRECTIVE_HEADER) == 1
    assert "前台「一拍一动（Beat-by-Beat）」幕脚本（`acts/actN.txt`）MUST 自带同步英文配音" in injected_once


def test_presenter_daemon_flow_and_ledger_narration(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    stage_dir, ledger_path = so.init_collaboration_dir(
        "core_test_flow", "介绍一下 stock_volatility_adaptive_lab 这个配方"
    )

    posts = []

    def mock_post(rec, steps, timeout=5.0):
        posts.extend(steps)
        return {"ok": True}

    monkeypatch.setattr(
        "frago.desktop.registry.read_instance",
        lambda _id: {"status": "running", "port": 8770},
    )
    monkeypatch.setattr("frago.desktop.aos.post", mock_post)

    daemon = so.PresenterDaemon(
        "core_test_flow", ledger_path, "介绍一下 stock_volatility_adaptive_lab 这个配方"
    )

    # 1. 开场应答（纯英文检验）
    daemon._say_interject("Welcome to the live stage.", "接活：介绍配方")
    say_steps = [s for s in posts if s.get("op") == "say"]
    assert len(say_steps) >= 1
    for s in say_steps:
        assert_english_only(s["text"])

    # 2. 参谋与主操更新账本后，主持人自动扫描并排入纯英文解说队列
    posts.clear()
    so.run_initial_advisor_pass(ledger_path, "介绍一下 stock_volatility_adaptive_lab 这个配方")
    content = ledger_path.read_text(encoding="utf-8")
    content = content.replace(
        "# 主操拍板与当前动作\n",
        "# 主操拍板与当前动作\n- 20:58 第一幕上台：终端真实执行 frago recipe info stock_volatility_adaptive_lab\n",
    )
    ledger_path.write_text(content, encoding="utf-8")

    daemon._check_ledger_updates()
    ledger_say_steps = [s for s in posts if s.get("op") == "say"]
    assert len(ledger_say_steps) == 2
    for s in ledger_say_steps:
        assert_english_only(s["text"])
        assert s["interject"] is False

    # 3. 模拟观众在面板追加中文需求
    posts.clear()
    mock_record = UnifiedRecord(
        id="rec_1",
        session_id="core_test_flow",
        group_id=None,
        seq=1,
        ts=1000,
        kind="user.say",
        payload={"text": "再重点讲一下回测胜率 backtest metrics"},
    )
    monkeypatch.setattr(
        "frago.session.record_reader.read_records", lambda sid, after, limit: [mock_record]
    )

    daemon._check_new_user_messages()
    interject_steps = [s for s in posts if s.get("op") == "say"]
    assert len(interject_steps) == 1
    assert_english_only(interject_steps[0]["text"])
    assert "Received, passing it on" in interject_steps[0]["text"]
    ledger_text = ledger_path.read_text(encoding="utf-8")
    assert "再重点讲一下回测胜率 backtest metrics" in ledger_text


def test_orchestrate_stage_session(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "frago.desktop.registry.read_instance",
        lambda _id: {"status": "running", "port": 8770},
    )
    monkeypatch.setattr(
        "frago.desktop.aos.post", lambda rec, steps, timeout=5.0: {"ok": True}
    )
    monkeypatch.setattr("frago.desktop.stage.up", lambda opts: {"ok": True})

    session_id = "core_orch_123"
    prompt = '<must-use-skill name="how-frago-agent-runs-an-agent-os">body</must-use-skill>\n请演示 stock_volatility_adaptive_lab 配方'
    result_prompt = so.orchestrate_stage_session(session_id, prompt)

    assert so.DIRECTIVE_HEADER in result_prompt
    assert session_id in so._presenters
    so.cleanup_presenter(session_id)
    assert session_id not in so._presenters


def test_reset_stage_sessions_cleans_presenters_and_stops_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "frago.desktop.registry.read_instance",
        lambda _id: {"status": "running", "port": 8770},
    )
    monkeypatch.setattr(
        "frago.desktop.aos.post", lambda rec, steps, timeout=5.0: {"ok": True}
    )
    monkeypatch.setattr("frago.desktop.stage.up", lambda opts: {"ok": True})

    stopped_calls = []

    def mock_stop(sid, *, by=""):
        stopped_calls.append((sid, by))
        return {"running": True, "stopped": True, "busy": True, "dropped": 0}

    monkeypatch.setattr("frago.server.services.coreagent_runner.stop", mock_stop)
    monkeypatch.setattr(
        "frago.server.services.tmux_sessions_service.find_for_session", lambda _sid: None
    )

    so.orchestrate_stage_session("core_old_1", "演示配方 A")
    so.orchestrate_stage_session("core_old_2", "演示配方 B")
    assert "core_old_1" in so._presenters
    assert "core_old_2" in so._presenters

    res = so.reset_stage_sessions("core_old_1")
    assert so._presenters == {}
    assert set(res["stopped_presenters"]) == {"core_old_1", "core_old_2"}
    assert set(res["stopped_sessions"]) == {"core_old_1", "core_old_2"}
    assert any(sid == "core_old_1" for sid, _ in stopped_calls)


def test_idle_pad_stops_once_operator_ready_and_never_loops(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    stage_dir, ledger_path = so.init_collaboration_dir(
        "core_pad_guard", "展示如何使用 google 搜索"
    )
    posts = []
    monkeypatch.setattr(
        "frago.desktop.registry.read_instance",
        lambda _id: {"status": "running", "port": 8770},
    )
    monkeypatch.setattr(
        "frago.desktop.aos.post", lambda rec, steps, timeout=5.0: posts.extend(steps) or {"ok": True}
    )
    monkeypatch.setattr(
        "frago.desktop.stage._fetch_status",
        lambda _port: {"focus": "browser", "speech": {"current": None, "queued": []}, "strap": None},
    )

    daemon = so.PresenterDaemon("core_pad_guard", ledger_path, "展示如何使用 google 搜索")

    # 场景 A：操作员已写出 acts/act0.txt（已就绪上台），即使语音超时也绝不再插垫音催促
    acts_dir = stage_dir / "acts"
    acts_dir.mkdir(parents=True, exist_ok=True)
    (acts_dir / "act0.txt").write_text('say "Opening Google now." --speak\n', encoding="utf-8")
    daemon.last_voice_time -= 60.0
    daemon._check_idle_pad(force_in_test=True)
    assert posts == []
    assert daemon.operator_ready is True

    # 场景 B：操作员尚未就绪时，单轮最多只补 1 句过渡说明，绝不死循环，且不含 next stage 傻话
    (acts_dir / "act0.txt").unlink()
    daemon2 = so.PresenterDaemon("core_pad_guard_2", ledger_path, "展示如何使用 google 搜索")
    for _ in range(5):
        daemon2.last_voice_time -= 60.0
        daemon2._check_idle_pad(force_in_test=True)
    say_steps = [s for s in posts if s.get("op") == "say"]
    assert len(say_steps) == 1
    assert_english_only(say_steps[0]["text"])
    assert "next stage" not in say_steps[0]["text"].lower()
    assert "next visual act" not in say_steps[0]["text"].lower()


