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
    # 旧版三角色舞台自动劫持与男声 PresenterDaemon 已退役，is_stage_session 恒返回 False
    assert so.is_stage_session(skills=["how-frago-agent-runs-an-agent-os"]) is False
    assert so.is_stage_session(skills=["other-skill"]) is False
    assert (
        so.is_stage_session(prompt='<must-use-skill name="how-frago-agent-runs-an-agent-os">')
        is False
    )
    assert so.is_stage_session(prompt="hello world") is False
    # 默认嗓音全面统一为女声体系（中文晓晓 / 英文 Ava），彻底移除男声 Andrew
    assert so.DEFAULT_ZH_VOICE == "zh-CN-XiaoxiaoNeural"
    assert so.DEFAULT_EN_VOICE == "en-US-AvaMultilingualNeural"
    assert so.DEFAULT_VOICE == "en-US-AvaMultilingualNeural"
    assert "Andrew" not in so.DEFAULT_VOICE


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

    # inject_stage_directive 已退役为 no-op，直接原样返回 prompt
    assert so.inject_stage_directive(raw, "sid_1", tmp_path / "ledger.md") == raw
    # 针对历史存量带有 DIRECTIVE_HEADER 尾缀的文本，clean_user_requirement 仍能干净剥离
    legacy_with_directive = f"{raw}\n\n---\n{so.DIRECTIVE_HEADER}\n旧版硬编排尾缀"
    assert so.clean_user_requirement(legacy_with_directive) == "介绍一下stock volatility adaptive lab这个配方"


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

    # inject_stage_directive 已退役为 no-op，不再向 prompt 注入旧版三角色硬编排尾缀
    directive = so.inject_stage_directive("演示 google", "sid_1", tmp_path / "ledger.md")
    assert directive == "演示 google"
    assert so.DIRECTIVE_HEADER not in directive


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

    assert injected_once == orig_prompt
    assert injected_twice == orig_prompt
    assert so.DIRECTIVE_HEADER not in injected_once


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

    # orchestrate_stage_session 与 PresenterDaemon 已退役为 no-op：不篡改 prompt、不启动后台男声线程
    assert result_prompt == prompt
    assert so.DIRECTIVE_HEADER not in result_prompt
    assert session_id not in so._presenters
    daemon = so.ensure_presenter(session_id, tmp_path / "ledger.md", prompt)
    assert daemon.thread is None
    assert session_id not in so._presenters
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

    so._presenters["core_old_1"] = so.PresenterDaemon("core_old_1", tmp_path / "l1.md", "演示配方 A")
    so._presenters["core_old_2"] = so.PresenterDaemon("core_old_2", tmp_path / "l2.md", "演示配方 B")
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


def test_desktop_operator_employee_and_speech_summarizer(tmp_path, monkeypatch):
    """验证 desktop-operator 员工岗位创建（仅填必填项，资源留空由巡检自动整理）以及 LightAgent 增量语音总结公式。"""
    from frago.employee import (
        DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC,
        ensure_builtin_desktop_operator_employee,
    )

    assert DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["knowledge_domains"] == []
    assert DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["recipes"] == []
    assert DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["data_slots"] == []
    assert DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["schedule_ids"] == []

    emp_dir = tmp_path / "employees"
    record = ensure_builtin_desktop_operator_employee(base_dir=emp_dir)
    assert record.member_post_id == "desktop-operator"
    assert record.title == "桌面主操作员"
    assert record.schedule_ids == []

    # 模拟操作员 2 轮响应（包含工具调用语义与长文本回答，不截断字数）
    fake_records = [
        UnifiedRecord(
            id="r1",
            session_id="core_op_test",
            group_id=None,
            seq=1,
            ts=1000,
            kind="user.say",
            payload={"text": "帮我打开浏览器看看新闻"},
        ),
        UnifiedRecord(
            id="r2",
            session_id="core_op_test",
            group_id=None,
            seq=2,
            ts=1001,
            kind="tool.call",
            payload={
                "name": "Bash",
                "input": {"command": "frago desktop browser open https://news.ycombinator.com"},
            },
        ),
        UnifiedRecord(
            id="r3",
            session_id="core_op_test",
            group_id=None,
            seq=3,
            ts=1002,
            kind="tool.result",
            payload={"is_error": False, "output": '{"ok": true}'},
        ),
        UnifiedRecord(
            id="r4",
            session_id="core_op_test",
            group_id=None,
            seq=4,
            ts=1003,
            kind="agent.say",
            payload={"text": "我已经为您在虚拟桌面浏览器中打开了 Hacker News 首页。"},
        ),
    ]
    monkeypatch.setattr(
        "frago.session.record_reader.read_records",
        lambda sid, limit=250, tail=True, after=None: fake_records,
    )

    turns = so.extract_recent_operator_turns("core_op_test", max_turns=3)
    assert len(turns) == 1
    assert turns[0]["user_text"] == "帮我打开浏览器看看新闻"
    assert len(turns[0]["events"]) == 3

    prompt = so.build_speech_summarizer_prompt(
        turns,
        previous_summary="上一轮已问候用户。",
        human_asr="帮我打开浏览器看看新闻",
        screen_context="当前聚焦窗口: win:browser | 已打开虚拟应用窗口: win:term, win:browser\n[虚拟浏览器 win:browser] 标题: Hacker News | URL: https://news.ycombinator.com",
        spoken_history=["好的，我马上为您打开浏览器查看新闻。", "上一轮已问候用户。"],
    )
    assert "<human_voice_asr>\n帮我打开浏览器看看新闻\n</human_voice_asr>" in prompt
    assert "<operator_actions>" in prompt
    assert "<operator_responses>" in prompt
    assert "<agent_os_screen_context>" in prompt
    assert "标题: Hacker News | URL: https://news.ycombinator.com" in prompt
    assert "<previous_spoken_summary>\n上一轮已问候用户。\n</previous_spoken_summary>" in prompt
    assert "<spoken_stream_so_far>\n1. 好的，我马上为您打开浏览器查看新闻。\n2. 上一轮已问候用户。\n</spoken_stream_so_far>" in prompt
    assert "<response_stage>INCREMENTAL_UPDATE</response_stage>" in prompt
    assert "frago desktop browser open https://news.ycombinator.com" in prompt
    assert "我已经为您在虚拟桌面浏览器中打开了 Hacker News 首页。" in prompt

    # 验证第三人称「让主操作员/主操作员正在」自动矫正为第一人称「我」
    rewritten_zh = so._clean_spoken_summary(
        "好的，我这就让主操作员去研究一下，看看为什么花瓣监听器会报错，以及怎么在前端配置。",
        previous_summary="",
    )
    assert "主操作员" not in rewritten_zh
    assert "操作员" not in rewritten_zh
    assert rewritten_zh.startswith("好的，我这就去研究一下")

    # 验证 desktop-operator 业务语境注入包含「像人类使用操作系统一样使用 Agent OS（最捷径原则与两层硬边界）」
    from frago.employee.service import EmployeeOntologyService

    ctx_block = EmployeeOntologyService(base_dir=emp_dir).build_business_context_block("desktop-operator")
    assert "像人类使用操作系统一样使用 Agent OS" in ctx_block
    assert "最捷径原则" in ctx_block
    assert "严禁主操作员亲自改代码" in ctx_block

    # 验证「第一时间响应 / 暖场响应」阶段：收到新的 human_asr 且主操作员尚未操作时
    warmup_prompt = so.build_speech_summarizer_prompt(
        [],
        previous_summary="",
        human_asr="帮我查一下当前目录的 git 状态",
    )
    assert "<response_stage>FIRST_RESPONSE_WARMUP</response_stage>" in warmup_prompt
    assert "<human_voice_asr>\n帮我查一下当前目录的 git 状态\n</human_voice_asr>" in warmup_prompt
    assert "<agent_os_screen_context>" in warmup_prompt
    assert "严禁掺杂自己对 prompt 的理解" in warmup_prompt

    from frago.agent_driver.kernel_backend import KernelTurn

    captured_calls = []

    def fake_run_chat_turn(p, *, cwd, role="lightagent", timeout_s=35.0):
        captured_calls.append({"prompt": p, "cwd": cwd, "role": role})
        return KernelTurn(
            text="我已经帮你在桌面浏览器里打开了 Hacker News 首页，请过目。",
            status="ok",
            duration_ms=820,
            tmux_name=None,
        )

    monkeypatch.setattr("frago.agent_driver.kernel_backend.run_chat_turn", fake_run_chat_turn)
    monkeypatch.setattr(
        so,
        "fetch_agent_os_screen_context",
        lambda port=8770, timeout=2.5: "[虚拟终端 win:term (cli) 屏幕可见内容]:\n$ git status\nOn branch main",
    )
    spoken = so.summarize_operator_for_speech("core_op_test", "上一轮已问候用户。")
    assert spoken == "我已经帮你在桌面浏览器里打开了 Hacker News 首页，请过目。"
    assert "KernelTurn" not in spoken
    assert len(captured_calls) == 1
    assert captured_calls[0]["role"] == "lightagent"
    assert "[虚拟终端 win:term (cli) 屏幕可见内容]:" in captured_calls[0]["prompt"]

    # 若 LightAgent 返回 <SILENCE>，则静默不播报
    monkeypatch.setattr(
        "frago.agent_driver.kernel_backend.run_chat_turn",
        lambda p, **kw: KernelTurn(text="<SILENCE>", status="ok", duration_ms=100),
    )
    assert so.summarize_operator_for_speech("core_op_test", spoken) == ""


def test_asr_profile_resolution_and_desktop_operator_tool_boundary(tmp_path, monkeypatch):
    """验证 ASR 鉴权从 Profile (profiles.json) 读取，且 desktop-operator 会话强制限定仅允许调用 frago desktop 工具。"""
    from frago.init.profile_manager import APIProfile, ProfileStore, resolve_asr_profile, save_profiles
    from frago.server.services import coreagent_runner

    profiles_file = tmp_path / "profiles.json"
    monkeypatch.setattr("frago.init.profile_manager.PROFILES_PATH", profiles_file)

    groq_prof = APIProfile(
        id="prof_groq",
        name="Groq",
        kind="endpoint",
        endpoint_type="custom",
        url="https://api.groq.com/openai/v1",
        default_model="whisper-large-v3-turbo",
        api_key="gsk_test_profile_key_123",
    )
    store = ProfileStore(profiles=[groq_prof], asr_profile_id="prof_groq")
    save_profiles(store)

    resolved = resolve_asr_profile()
    assert resolved is not None
    assert resolved.id == "prof_groq"
    assert resolved.api_key == "gsk_test_profile_key_123"

    api_key, transcription_url, model = so.resolve_asr_connection()
    assert api_key == "gsk_test_profile_key_123"
    assert transcription_url == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert model == "whisper-large-v3-turbo"
    assert so.resolve_groq_whisper_api_key() == "gsk_test_profile_key_123"

    # 验证未配置 ASR 连接且无 GROQ_API_KEY 环境变量时，报错信息引导前往 WebUI「设置 → 常规设置 → 旁路与轻量 AI」
    save_profiles(ProfileStore(profiles=[]))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="常规设置 → 旁路与轻量 AI"):
        so.resolve_asr_connection()

    # 验证 desktop-operator 会话构建命令时强制注入 --allowed-tools 与 --disallowed-tools
    monkeypatch.setattr(coreagent_runner, "binary", lambda: Path("/usr/local/bin/frago-core"))
    cmd = coreagent_runner.build_command(
        "core_op_bound",
        cwd=str(tmp_path),
        desktop_operator=True,
    )
    assert "--allowed-tools" in cmd
    assert cmd[cmd.index("--allowed-tools") + 1] == "Bash(frago desktop:*)"
    assert "--disallowed-tools" in cmd
    assert cmd[cmd.index("--disallowed-tools") + 1] == "Bash(frago desktop say:*)"


def test_desktop_operator_single_employee_tag_without_duplicate_directive_tail(tmp_path, monkeypatch):
    """验证主操作员会话仅在首轮注入 <frago-employee> 标签（职责契约完全写在 employee 内），后续轮次仅发纯文本。"""
    sent_prompts: list[tuple[str, str]] = []
    existing_sessions: set[str] = set()

    emp_dir = tmp_path / "employees"
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    monkeypatch.setattr(
        "frago.employee.store.employees_dir",
        lambda base_dir=None: Path(base_dir) if base_dir else emp_dir,
    )
    monkeypatch.setattr(so, "ensure_stage_up", lambda: None)
    monkeypatch.setattr(
        "frago.session.coreagent_store.session_exists",
        lambda sid: sid in existing_sessions,
    )
    monkeypatch.setattr(
        "frago.session.record_reader.read_records",
        lambda sid, limit=1, **kw: [object()] if sid in existing_sessions else [],
    )

    class _DummySummarizer:
        def __init__(self):
            self.notified: list[str] = []

        def notify_human_asr(self, text: str) -> None:
            self.notified.append(text)

    dummy_daemon = _DummySummarizer()
    monkeypatch.setattr(so, "ensure_speech_summarizer", lambda sid, cwd=None: dummy_daemon)
    monkeypatch.setattr(
        "frago.server.services.session_send.send_queued",
        lambda sid, prompt, cwd_hint=None: sent_prompts.append((sid, prompt)),
    )

    # 第 1 轮（新建会话）：仅前置 <frago-employee id="desktop-operator">
    res1 = so.dispatch_desktop_voice_command("测试一下", session_id="core_clean_test", cwd=str(tmp_path))
    assert res1["session_id"] == "core_clean_test"
    assert len(sent_prompts) == 1
    first_prompt = sent_prompts[0][1]
    assert '<frago-employee id="desktop-operator" title="桌面主操作员"' in first_prompt
    assert first_prompt.endswith("</frago-employee>\n\n测试一下")

    # 第 2 轮（存量会话）：不再重复包裹 <frago-employee>，仅发送纯净用户原话
    existing_sessions.add("core_clean_test")
    so.dispatch_desktop_voice_command("你能听见我说话吗？", session_id="core_clean_test", cwd=str(tmp_path))
    assert len(sent_prompts) == 2
    second_prompt = sent_prompts[1][1]
    assert second_prompt == "你能听见我说话吗？"
    assert "<frago-employee" not in second_prompt


def test_anti_premature_completion_speech_guard_and_spawn_incomplete_signal(tmp_path, monkeypatch):
    """验证语音文本大模型包含防过早断言完成（Anti-Premature-Completion）戒备规则，且 employee invoke --spawn 返回显式未完成信号。"""
    import json
    from click.testing import CliRunner
    from frago.cli import employee_commands as emp_cli
    from frago.server.services import workbench_new_session

    # 1. 验证 SPEECH_SUMMARIZER_SYSTEM_PROMPT 包含防过早断言完成戒备条款
    assert "Anti-Premature-Completion" in so.SPEECH_SUMMARIZER_SYSTEM_PROMPT
    assert "严防把「刚启动/已派活/8秒首屏返回」误判为「任务已完成」" in so.SPEECH_SUMMARIZER_SYSTEM_PROMPT
    assert "running_in_background" in so.SPEECH_SUMMARIZER_SYSTEM_PROMPT
    assert "我已经启动了研发代理开始处理" in so.SPEECH_SUMMARIZER_SYSTEM_PROMPT

    prompt = so.build_speech_summarizer_prompt(
        [
            {
                "user_text": "帮我修复花瓣监听器报错",
                "start_seq": 1,
                "end_seq": 3,
                "events": [
                    {
                        "seq": 2,
                        "type": "tool.call",
                        "name": "Bash",
                        "input": "frago desktop term run \"frago employee invoke frago-developer --spawn --json '修复花瓣报错'\"",
                    },
                    {
                        "seq": 3,
                        "type": "tool.result",
                        "is_error": False,
                        "output": '{"status": "accepted", "session_id": "b992e069", "completion_state": "running_in_background", "is_completed": false}',
                    },
                ],
            }
        ],
        human_asr="帮我修复花瓣监听器报错",
    )
    assert "Anti-Premature-Completion" in prompt

    # 2. 验证 frago employee invoke --spawn 回执包含显式未完成信号
    emp_dir = tmp_path / "employees"
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    monkeypatch.setattr(
        "frago.employee.store.employees_dir",
        lambda base_dir=None: Path(base_dir) if base_dir else emp_dir,
    )
    runner = CliRunner()
    hire_res = runner.invoke(
        emp_cli.employee_group,
        [
            "hire",
            "frago-developer",
            "--title",
            "Frago Developer",
            "--kernel",
            "agy",
            "--no-schedule",
        ],
    )
    assert hire_res.exit_code == 0, hire_res.output

    monkeypatch.setattr(
        workbench_new_session,
        "start_with_id",
        lambda agent_type, cwd, prompt, *, session_id=None: workbench_new_session.PendingLaunch(
            handle="webui-spawn-test-01",
            agent_type=agent_type,
            display_name="Antigravity",
            cwd=cwd,
            session_id="b992e069-aa9a-4689-a3d5-1bc7488c23cf",
        ),
    )

    spawn_res = runner.invoke(
        emp_cli.employee_group,
        ["invoke", "frago-developer", "修复花瓣报错", "--spawn", "--json"],
    )
    assert spawn_res.exit_code == 0, spawn_res.output
    payload = json.loads(spawn_res.output)
    assert payload["session_id"] == "b992e069-aa9a-4689-a3d5-1bc7488c23cf"
    assert payload["completion_state"] == "running_in_background"
    assert payload["is_completed"] is False
    assert "【未完成信号】" in payload["notice"]
    assert "严禁将此启动回执当作任务已完成" in payload["notice"]


def test_resolve_active_desktop_operator_session_restores_and_mounts_summarizer(
    tmp_path, monkeypatch
):
    """验证 resolve_active_desktop_operator_session 能找回 core_860f773c96193460 并自动挂载 SpeechSummarizerDaemon，且舞台重置后不会恢复已重置的旧会话。"""
    from frago.employee import EmployeeOntologyService, ensure_builtin_desktop_operator_employee, get_post

    emp_dir = tmp_path / "employees"
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    monkeypatch.setattr(
        "frago.employee.store.employees_dir",
        lambda base_dir=None: Path(base_dir) if base_dir else emp_dir,
    )
    so._reset_excluded_sids.clear()
    so.cleanup_all_speech_summarizers()

    ensure_builtin_desktop_operator_employee(base_dir=emp_dir)
    emp_svc = EmployeeOntologyService(base_dir=emp_dir)
    target_sid = "core_860f773c96193460"
    emp_svc.register_session("desktop-operator", target_sid)

    monkeypatch.setattr(
        "frago.session.coreagent_store.session_exists",
        lambda sid: sid == target_sid,
    )

    mounted: list[tuple[str, str | None]] = []

    class _FakeSummarizer:
        def __init__(self, sid: str, cwd: str | None = None):
            self.session_id = sid
            self.cwd = cwd

        def stop(self) -> None:
            pass

    def _fake_ensure(sid: str, *, max_turns: int = 3, cwd: str | None = None):
        mounted.append((sid, cwd))
        d = _FakeSummarizer(sid, cwd)
        so._speech_summarizers[sid] = d  # type: ignore[assignment]
        return d

    monkeypatch.setattr(so, "ensure_speech_summarizer", _fake_ensure)

    res = so.resolve_active_desktop_operator_session(ensure_summarizer=True)
    assert res == {
        "session_id": target_sid,
        "employee": "desktop-operator",
        "restored": True,
    }
    assert len(mounted) == 1
    assert mounted[0][0] == target_sid

    # 用户主动点击「重置」按钮触发 reset_stage_sessions 后，旧会话从 active_session_ids 移除且不再被恢复
    monkeypatch.setattr(
        "frago.server.services.coreagent_runner.stop",
        lambda sid, *, by="": {"running": True, "stopped": True, "busy": False, "dropped": 0},
    )
    monkeypatch.setattr(
        "frago.server.services.tmux_sessions_service.find_for_session",
        lambda _sid: None,
    )
    so.reset_stage_sessions(target_sid)

    post_after_reset = get_post("desktop-operator", base_dir=emp_dir)
    assert post_after_reset is not None
    assert target_sid not in post_after_reset.active_session_ids

    res_after_reset = so.resolve_active_desktop_operator_session(ensure_summarizer=True)
    assert res_after_reset["session_id"] is None
    assert res_after_reset["restored"] is False
    so._reset_excluded_sids.clear()
    so.cleanup_all_speech_summarizers()


def test_maybe_ensure_desktop_operator_speech_on_session_send_and_resume(
    tmp_path, monkeypatch
):
    """验证 maybe_ensure_desktop_operator_speech 在普通 session_send 时能识别含 <frago-employee id="desktop-operator" 的会话并自动挂载 SpeechSummarizerDaemon。"""
    from frago.employee import ensure_builtin_desktop_operator_employee, get_post
    from frago.server.services import session_send

    emp_dir = tmp_path / "employees"
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    monkeypatch.setattr(
        "frago.employee.store.employees_dir",
        lambda base_dir=None: Path(base_dir) if base_dir else emp_dir,
    )
    so._reset_excluded_sids.clear()
    so.cleanup_all_speech_summarizers()
    ensure_builtin_desktop_operator_employee(base_dir=emp_dir)

    target_sid = "core_860f773c96193460"
    early_rec = UnifiedRecord(
        id="r_op_1",
        session_id=target_sid,
        group_id=None,
        seq=1,
        ts=1000,
        kind="user.say",
        payload={
            "text": '<frago-employee id="desktop-operator" title="桌面主操作员" kernel="claude">\n职责说明\n</frago-employee>\n\n帮我看一下桌面状态'
        },
    )
    monkeypatch.setattr(
        "frago.session.record_reader.read_records",
        lambda sid, limit=2, tail=False, **kw: [early_rec] if sid == target_sid else [],
    )

    mounted_sids: list[str] = []

    class _DummyDaemon:
        def stop(self) -> None:
            pass

    def _fake_ensure(sid: str, *, max_turns: int = 3, cwd: str | None = None):
        mounted_sids.append(sid)
        return _DummyDaemon()

    monkeypatch.setattr(so, "ensure_speech_summarizer", _fake_ensure)
    monkeypatch.setattr(
        "frago.session.coreagent_store.find_session_file",
        lambda sid, root=None: (tmp_path / f"{sid}.jsonl") if sid == target_sid else None,
    )
    monkeypatch.setattr(
        "frago.server.services.coreagent_runner.send_queued",
        lambda sid, prompt, *, cwd, title=None: "coreagent-feed-mock",
    )

    # 通过普通 session_send.send_queued 发送后续消息（不走 desktop-voice/dispatch）
    thread_name = session_send.send_queued(target_sid, "继续检查终端输出", cwd_hint=str(tmp_path))
    assert thread_name == "coreagent-feed-mock"
    assert target_sid in mounted_sids

    # 并且该会话已被自动补登记回 desktop-operator 的 active_session_ids
    refreshed_post = get_post("desktop-operator", base_dir=emp_dir)
    assert refreshed_post is not None
    assert target_sid in refreshed_post.active_session_ids

    # 若仅在普通开发任务文本中间提及标签字面量（非首部标签），不得误判为 desktop-operator 会话
    worker_sid = "core_worker_mention_only"
    worker_rec = UnifiedRecord(
        id="r_worker_1",
        session_id=worker_sid,
        group_id=None,
        seq=1,
        ts=1001,
        kind="user.say",
        payload={
            "text": '请检查文本中是否包含 <frago-employee id="desktop-operator" 标签字面量'
        },
    )
    monkeypatch.setattr(
        "frago.session.record_reader.read_records",
        lambda sid, limit=2, tail=False, **kw: [worker_rec] if sid == worker_sid else [],
    )
    assert so.is_desktop_operator_session(worker_sid) is False


def test_whisper_hallucination_filter_and_transcribe_route_guard(monkeypatch):
    """验证持续监听下 Whisper 经典静音/尾音幻觉（`Thank you.`、`...` 等）被拦截，且正常短指令不受影响。"""
    import asyncio
    import base64
    import io
    import json
    from frago.server.routes.workbench import (
        DesktopVoiceTranscribeRequest,
        transcribe_desktop_voice,
    )

    # 1. 孤立静音幻觉词与标点必须全部过滤为空字符串
    hallucinations = [
        "Thank you.",
        "Thank you",
        "Thank you!",
        "thank you very much.",
        "Thanks for watching.",
        "Thank you. Thank you.",
        "... Thank you.",
        "...",
        "…",
        "..",
        "?",
        "[Music]",
        "(Silence)",
        "谢谢观看",
        "感谢观看",
        "字幕由 Amara.org 社区提供",
        "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    ]
    for h in hallucinations:
        assert so.is_whisper_hallucination(h) is True, f"Expected hallucination: {h!r}"
        assert so.clean_whisper_transcription(h) == "", f"Expected empty after clean: {h!r}"

    # 2. 高无声概率 (no_speech_prob >= 0.85) 且低对数概率分段判定为静音幻觉
    assert (
        so.clean_whisper_transcription(
            "Okay.",
            segments=[{"no_speech_prob": 0.94, "avg_logprob": -1.32}],
        )
        == ""
    )

    # 3. 正常中文短指令与长句完整保留；若中文句末粘连 Whisper 尾音幻觉则仅剥离幻觉尾缀
    valid_cases = [
        ("好", "好"),
        ("好的", "好的"),
        ("继续", "继续"),
        ("做一下本地灯到灯的测试", "做一下本地灯到灯的测试"),
        ("做一下本地灯到灯的测试 Thank you.", "做一下本地灯到灯的测试"),
        ("做一下本地灯到灯的测试。 Thanks for watching!", "做一下本地灯到灯的测试"),
        ("做一下本地灯到灯的测试 ...", "做一下本地灯到灯的测试"),
        ("帮我看看 thank you 这个词怎么写", "帮我看看 thank you 这个词怎么写"),
    ]
    for raw_in, expected in valid_cases:
        assert so.clean_whisper_transcription(raw_in) == expected

    # 4. 验证 transcribe_audio_with_groq 请求携带 temperature=0 与 verbose_json，并自动过滤 Thank you.
    captured_req: dict[str, bytes] = {}

    class _FakeHttpResp:
        def __init__(self, payload: dict):
            self._raw = json.dumps(payload).encode("utf-8")

        def read(self) -> bytes:
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(req, timeout=25.0):
        captured_req["body"] = req.data
        return _FakeHttpResp({"text": "Thank you.", "language": "en"})

    monkeypatch.setattr(
        so,
        "resolve_asr_connection",
        lambda: ("gsk_test", "https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3-turbo"),
    )
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    asr_out = so.transcribe_audio_with_groq(b"RIFF" + b"\x00" * 512)
    assert b'name="temperature"\r\n\r\n0\r\n' in captured_req["body"]
    assert b'name="response_format"\r\n\r\nverbose_json\r\n' in captured_req["body"]
    assert asr_out["text"] == ""
    assert asr_out["raw_text"] == "Thank you."
    assert asr_out["hallucination_filtered"] is True

    # 5. 验证 /workbench/desktop-voice/transcribe 路由遇到幻觉时不派发给 desktop-operator
    dispatched_calls: list[str] = []
    monkeypatch.setattr(
        so,
        "dispatch_desktop_voice_command",
        lambda text, **kw: dispatched_calls.append(text) or {"session_id": "core_1", "employee": "desktop-operator", "status": "queued"},
    )
    b64_audio = base64.b64encode(b"OggS" + b"\x01" * 256).decode("ascii")
    route_res = asyncio.run(
        transcribe_desktop_voice(
            DesktopVoiceTranscribeRequest(
                audio_base64=b64_audio,
                session_id="core_voice_test",
                auto_send=True,
            )
        )
    )
    assert route_res["text"] == ""
    assert route_res["dispatched"] is False
    assert route_res.get("reason") == "hallucination_filtered"
    assert dispatched_calls == []








