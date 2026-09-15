"""虚拟桌面的语音：合成与缓存（voice.py）、broker 的语音队列、命令行的写法。

与 test_desktop.py 同一条纪律：**这台机器上舞台是常驻的**，测试不碰真端口、
真进程、真网络。edge-tts 换成假的模块，broker 的 subprocess / urllib 换成会当场
炸的假货，缓存落点顶成临时目录。

验的是看输出看不出来的事：

  · 同样的输入只合成一次；一条句子时间都没有的结果不算成功，也不进缓存
  · 网络与服务端的错会重试，参数写错不重试
  · 缓存按最久没用的删，刚写进来的那句不删
  · 纯字幕的 say 一个字节都没变；开口的 say 默认等讲完
  · page 出声时没人报"开始放了"，回执说没人听见，不把"发出去了"说成"说出来了"
  · 合成失败退回字幕，照常往下走，回执写明这句没出声
  · 打断会掐掉正在说的与排着的
  · 录制音轨的 ffmpeg 命令：画面不重编码，每句按开口时刻推后再叠
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import types

import pytest

from frago.desktop import aos, broker, voice

from .test_desktop import ExplodingNet, ExplodingSubprocess, FakeCompleted, post_control


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    """与 test_desktop 的 sealed_broker 同一份做法：build 期碰真进程、真请求就当场炸。"""
    monkeypatch.setattr(broker, "subprocess", ExplodingSubprocess())
    monkeypatch.setattr(broker, "urllib", ExplodingNet())
    clips = tmp_path / "broker-clips"
    clips.mkdir()
    return {
        "id": "default", "port": 18770,
        "desktop": {"w": 1920, "h": 1080}, "browser": {"w": 1280, "h": 800},
        "term": {"cols": 100, "rows": 30}, "start_url": "about:blank",
        "desktop_url": "http://127.0.0.1:8093/app/agent_os",
        "tmux_session": "test-not-a-real-session", "clips_dir": str(clips),
        "stage_port": 19222, "record_port": 19223, "fps": 30,
        "content_id": "test-content", "ui_version": 1, "actor_headless": True,
    }


# ── 假的 edge-tts ────────────────────────────────────────────────────────

class FakeEdge:
    """记下每次合成，按脚本给出音频与句子时间，或者抛错。"""

    def __init__(self, script=None):
        # script 里每一项是一次合成的结局：dict(audio=, marks=) 或一个异常
        self.script = list(script or [])
        self.calls: list[dict] = []
        edge = self

        class Communicate:
            def __init__(self, text, voice, **kw):
                edge.calls.append({"text": text, "voice": voice, **kw})

            async def stream(self):
                turn = edge.script.pop(0) if edge.script else {}
                if isinstance(turn, Exception):
                    raise turn
                yield {"type": "audio", "data": turn.get("audio", b"\xff" * 6000)}
                for mark in turn.get("marks", [(100, 900, "第一句。")]):
                    start, dur, text = mark
                    yield {"type": "SentenceBoundary", "offset": start * 10_000,
                           "duration": dur * 10_000, "text": text}

        self.module = types.SimpleNamespace(Communicate=Communicate)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "CACHE_ROOT", tmp_path / "tts")
    monkeypatch.setattr(voice, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(voice, "RETRY_DELAYS", (0.0, 0.0))
    return tmp_path


@pytest.fixture
def edge(monkeypatch):
    def install(script=None):
        fake = FakeEdge(script)
        monkeypatch.setitem(sys.modules, "edge_tts", fake.module)
        return fake
    return install


# ── 合成与缓存 ──────────────────────────────────────────────────────────

def test_fingerprint_covers_every_input_but_not_outer_whitespace():
    base = voice.cache_key("你好。", "v", "+0%", "+0%", "+0Hz")
    assert voice.cache_key("  你好。\n", "v", "+0%", "+0%", "+0Hz") == base
    # 标点一个不动：它决定停顿与语气，换了就是另一句话。
    assert voice.cache_key("你好！", "v", "+0%", "+0%", "+0Hz") != base
    for changed in (("你好。", "w", "+0%", "+0%", "+0Hz"),
                    ("你好。", "v", "+5%", "+0%", "+0Hz"),
                    ("你好。", "v", "+0%", "+5%", "+0Hz"),
                    ("你好。", "v", "+0%", "+0%", "+5Hz")):
        assert voice.cache_key(*changed) != base


def test_same_line_is_synthesized_once(cache, edge):
    fake = edge()
    first = voice.synthesize_sync("第一句。")
    again = voice.synthesize_sync("第一句。")
    assert len(fake.calls) == 1, "第二次应当命中缓存，不再联网"
    assert first["cached"] is False and again["cached"] is True
    # 48kbps 恒定码率：6000 字节 = 1000 毫秒。
    assert first["duration_ms"] == 1000
    assert first["sentences"] == [{"start_ms": 100, "end_ms": 1000,
                                   "text": "第一句。"}]
    assert fake.calls[0]["boundary"] == "SentenceBoundary"
    assert os.path.isfile(first["audio"]) and os.path.isfile(first["meta"])


def test_no_sentence_times_is_a_failure_and_is_not_cached(cache, edge):
    """拿不到句子时间，字幕和对齐都无从谈起——这不算合成成功。"""
    edge([{"marks": []}] * 3)
    with pytest.raises(voice.VoiceFailed):
        voice.synthesize_sync("第一句。")
    assert voice.stats()["lines"] == 0


def test_network_errors_are_retried(cache, edge):
    fake = edge([ConnectionError("503"), {}])
    out = voice.synthesize_sync("第一句。")
    assert len(fake.calls) == 2
    assert "503" in out["retried"][0]


def test_bad_params_fail_before_the_network(cache, edge):
    fake = edge()
    with pytest.raises(ValueError, match="语速"):
        voice.synthesize_sync("第一句。", rate="fast")
    assert fake.calls == []


def test_missing_edge_tts_says_frago_is_incomplete(cache, monkeypatch):
    """edge-tts 是必装依赖。缺了就是 frago 没装完整——回执叫人重装 frago，
    NEVER 叫人去单独补装一个包：用户不该知道 frago 底下还有这么一个包。"""
    monkeypatch.setitem(sys.modules, "edge_tts", None)   # import 时抛 ImportError
    with pytest.raises(voice.VoiceUnavailable) as exc:
        voice.synthesize_sync("第一句。")
    assert "重新安装 frago" in str(exc.value)
    assert "pip install" not in str(exc.value)


def test_edge_tts_is_a_required_dependency():
    """语音随 frago 一起装上：edge-tts 必须在必装依赖里，不能落进可选依赖。"""
    import tomllib
    from pathlib import Path

    root = Path(voice.__file__).resolve().parents[3]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    required = [d.replace(" ", "") for d in project["dependencies"]]
    assert f"edge-tts>={voice.MIN_EDGE_TTS}" in required


def test_eviction_drops_least_recently_used_first(cache, edge):
    edge([{"audio": b"\xff" * 400_000}] * 3)
    (cache / "config.json").write_text(json.dumps({"tts": {"cache_max_mb": 1}}))
    old = voice.synthesize_sync("旧的一句。")
    mid = voice.synthesize_sync("中间一句。")
    past = time.time() - 3600
    os.utime(old["meta"], (past, past))       # 旧的那句一小时没人用
    new = voice.synthesize_sync("新的一句。")
    assert new["evicted"]["files"] == 1
    assert not os.path.exists(old["meta"]) and not os.path.exists(old["audio"])
    assert os.path.exists(mid["meta"]) and os.path.exists(new["meta"])


def test_audio_path_only_accepts_fingerprints(cache, edge):
    edge()
    out = voice.synthesize_sync("第一句。")
    assert str(voice.audio_path(out["key"])) == out["audio"]
    for bad in ("../../etc/passwd", "", "abc", out["key"][:-1] + "/"):
        assert voice.audio_path(bad) is None


def test_clear_leaves_nothing(cache, edge):
    edge()
    voice.synthesize_sync("第一句。")
    out = voice.clear()
    assert out["removed_lines"] == 1
    assert voice.stats()["lines"] == 0


# ── broker 的语音队列 ────────────────────────────────────────────────────

@pytest.fixture
def fake_synth(tmp_path, monkeypatch):
    """顶掉合成：按文字给时长（毫秒），文字里带「失败」就抛 VoiceFailed。"""
    calls: list[dict] = []

    async def synthesize(text, voice_name, rate, volume, pitch):
        calls.append({"text": text, "voice": voice_name, "rate": rate})
        if "失败" in text:
            raise voice.VoiceFailed("Edge 语音合成试了 3 次都没成")
        audio = tmp_path / f"{len(calls)}.mp3"
        audio.write_bytes(b"\xff")
        ms = 120 if "长" not in text else 5000
        return {"key": "a" * 64, "voice": voice_name, "duration_ms": ms,
                "cached": False, "audio": str(audio), "sentences": []}

    monkeypatch.setattr(broker.voice, "synthesize", synthesize)
    monkeypatch.setattr(broker, "SPEECH_START_GRACE_SEC", 0.05)
    monkeypatch.setattr(broker, "SPEECH_END_GRACE_SEC", 0.05)
    return calls


def only(out):
    assert len(out["results"]) == 1, out["results"]
    return out["results"][0]


def test_plain_say_is_exactly_what_it_was(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "旁白", "ms": 2600}]})
    r = only(out)
    assert r["status"] == "ok" and r["said"] == "旁白"
    assert "speech" not in r and fake_synth == [], "不带 speak 就不许合成"


def test_spoken_say_waits_until_it_is_done(sealed, fake_synth):
    t0 = time.time()
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "开口", "speak": True, "out": "none"}]})
    r = only(out)
    assert r["status"] == "ok" and r["spoken"] is True
    assert r["speech"]["state"] == "done"
    assert r["speech"]["ended_by"] == "clock"
    assert time.time() - t0 >= 0.1, "默认要等讲完才返回"


def test_async_say_returns_at_once_and_wait_catches_up(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "边说边做", "speak": True, "out": "none",
         "async": True},
        {"op": "sleep", "ms": 0},
        {"op": "speech.wait", "target": "1"}]})
    said, _, waited = out["results"]
    assert said["speech"]["state"] in ("queued", "playing")
    assert "wait --speech 1" in said["hint"]
    assert waited["status"] == "ok" and waited["speech"]["state"] == "done"


def test_second_line_queues_behind_the_first(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "第一句", "speak": True, "out": "none", "async": True},
        {"op": "say", "text": "第二句", "speak": True, "out": "none", "async": True},
        {"op": "speech.wait", "target": "all"}]})
    first, second, waited = out["results"]
    assert second["queued_behind"] == ["1"]
    assert second["starts_in_ms"] > 0
    assert waited["waited_sec"] >= 0.2, "两句是排队说的，不是叠在一起"


def test_page_speech_nobody_heard_is_said_out_loud(sealed, fake_synth):
    """没有一块荧幕报开始放——回执必须说没人听见。"""
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "对着空屋子", "speak": True}]})
    sp = only(out)["speech"]
    assert sp["out"] == "page" and sp["state"] == "done"
    assert sp["heard"] is False and sp["heard_by_screens"] == 0
    assert sp["ended_by"] == "clock"
    assert "没有人开着桌面页" in sp["note"]


def test_synthesis_failure_falls_back_to_caption(sealed, fake_synth):
    code, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "这句会失败", "speak": True},
        {"op": "sleep", "ms": 0}]})
    r = out["results"][0]
    assert code == 200 and r["status"] == "ok", "一句没声音不至于让整批作废"
    assert r["spoken"] is False and "没出声" in r["note"]
    assert out["results"][1]["status"] == "ok"


def test_interrupt_cuts_the_current_and_the_queued(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 50},
        {"op": "say", "text": "插话", "speak": True, "out": "none",
         "interrupt": True}]})
    cut = out["results"][3]
    assert cut["status"] == "ok"
    assert cut["interrupted"] == {"stopped": "1", "dropped": ["2"]}
    assert cut["speech"]["state"] == "done"


def test_voice_stop_on_silence_is_a_noop(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [{"op": "speech.stop"}]})
    r = only(out)
    assert r["status"] == "ok" and r["noop"] is True


def test_waiting_on_an_unknown_line_says_so(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "speech.wait", "target": "42"}]})
    r = only(out)
    assert r["status"] == "failed" and "--speech all" in r["error"]


def test_unknown_output_is_refused(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "x", "speak": True, "out": "耳机"}]})
    r = only(out)
    assert r["status"] == "failed"
    for where in broker.SPEECH_OUTS:
        assert where in r["error"]
    assert fake_synth == [], "位置写错不该先去联网合成"


def test_voice_route_only_serves_fingerprints(sealed, cache, edge):
    edge()
    syn = voice.synthesize_sync("第一句。")
    app = broker.build_app(dict(sealed))
    route = next(r for r in app.routes if getattr(r, "path", None) == "/voice/{name}")
    assert asyncio.run(route.endpoint(name=f"{syn['key']}.mp3")).status_code == 200
    for bad in ("../config.json", f"{syn['key']}.json", "x.mp3"):
        assert asyncio.run(route.endpoint(name=bad)).status_code == 404


def test_status_reports_the_speech_queue(sealed):
    app = broker.build_app(dict(sealed))
    status = next(r for r in app.routes if getattr(r, "path", None) == "/status")
    st = asyncio.run(status.endpoint())
    assert st["speech"] == {"current": None, "queued": [], "listening_screens": 0}


# ── 录制音轨 ────────────────────────────────────────────────────────────

def test_voice_track_keeps_the_picture_and_delays_each_line(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_run(cmd, timeout=180):
        seen.append(cmd)
        open(cmd[-1], "wb").close()          # ffmpeg 产出了临时文件
        return FakeCompleted(0)

    monkeypatch.setattr(broker, "_run", fake_run)
    mp4 = tmp_path / "take.mp4"
    mp4.write_bytes(b"picture")
    lines = [{"id": "1", "at": 1.5, "duration_ms": 900, "text": "一",
              "file": str(tmp_path / "001.mp3")},
             {"id": "2", "at": 4.25, "duration_ms": 800, "text": "二",
              "file": str(tmp_path / "002.mp3")}]
    out = broker._mux_voice(mp4, lines, tmp_path / "take-voice.json")
    cmd = seen[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "adelay=delays=1500:all=1" in graph and "adelay=delays=4250:all=1" in graph
    assert "amix=inputs=2:normalize=0" in graph
    assert cmd[cmd.index("-c:v") + 1] == "copy", "画面不许重编码"
    assert out["muxed"] is True and out["lines"] == 2
    assert json.loads((tmp_path / "take-voice.json").read_text())["lines"] == lines


def test_interrupted_line_is_cut_in_the_recording(sealed, fake_synth, tmp_path,
                                                 monkeypatch):
    """录制中被打断的那句，录制记录里要记着它实际说了多久。

    不记的话停录贴音轨时整句贴进去，和打断它的那句叠着响——2026-09-14 的
    voice-demo-20260914 就是这样：画面上是打断，耳朵听到的是两句混在一起。
    """
    rigs: list = []

    class RollingRecorder(broker.StageRecorder):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.recording, self.name, self._t0 = True, "take", time.time() - 1
            rigs.append(self)

    monkeypatch.setattr(broker, "StageRecorder", RollingRecorder)
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "sleep", "ms": 300},
        {"op": "say", "text": "插话", "speak": True, "out": "none",
         "interrupt": True},
        {"op": "speech.wait", "target": "1"}]})
    cut = out["results"][3]["speech"]
    assert cut["state"] == "interrupted"
    assert 250 <= cut["cut_ms"] < 5000, "实际说了多久，不是整句 5000 毫秒"
    first, second = rigs[0].voice_lines
    assert first["cut_ms"] == cut["cut_ms"]
    assert "cut_ms" not in second, "说完的那句不截"


def test_voice_track_hard_cuts_an_interrupted_line(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_run(cmd, timeout=180):
        seen.append(cmd)
        open(cmd[-1], "wb").close()
        return FakeCompleted(0)

    monkeypatch.setattr(broker, "_run", fake_run)
    mp4 = tmp_path / "take.mp4"
    mp4.write_bytes(b"picture")
    lines = [{"id": "4", "at": 31.539, "duration_ms": 7536, "cut_ms": 2505,
              "text": "被打断", "file": str(tmp_path / "004.mp3")},
             {"id": "5", "at": 34.05, "duration_ms": 3600, "text": "打断的",
              "file": str(tmp_path / "005.mp3")}]
    broker._mux_voice(mp4, lines, tmp_path / "take-voice.json")
    graph = seen[0][seen[0].index("-filter_complex") + 1]
    assert "[1:a]atrim=end=2.505,adelay=delays=31539:all=1[a1]" in graph
    assert "[2:a]adelay=delays=34050:all=1[a2]" in graph
    # 打断就是打断：到点直接掐，不淡出。
    assert "afade" not in graph


def test_voice_track_failure_keeps_the_silent_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "_run",
                        lambda cmd, timeout=180: FakeCompleted(1, stderr="boom"))
    mp4 = tmp_path / "take.mp4"
    mp4.write_bytes(b"picture")
    out = broker._mux_voice(mp4, [{"id": "1", "at": 0.0, "duration_ms": 1,
                                   "text": "一", "file": "x.mp3"}],
                            tmp_path / "take-voice.json")
    assert out["muxed"] is False and "boom" in out["error"]
    assert mp4.read_bytes() == b"picture", "音轨失败不许动已经录好的片子"


# ── 命令行写法 ──────────────────────────────────────────────────────────

def test_voice_flags_without_speak_are_refused():
    with pytest.raises(aos.Fail) as exc:
        aos.parse(["say", "旁白", "--async"])
    assert "--speak" in exc.value.payload["error"]


def test_spoken_say_does_not_take_ms():
    with pytest.raises(aos.Fail):
        aos.parse(["say", "旁白", "--speak", "--ms", "3000"])


def test_speak_switches_become_one_step():
    kind, steps = aos.parse(["say", "旁白", "--speak", "--async", "--interrupt",
                             "--out", "both", "--rate", "+10%"])
    assert kind == "steps"
    assert steps == [{"op": "say", "text": "旁白", "speak": True, "out": "both",
                      "rate": "+10%", "async": True, "interrupt": True}]


def test_wait_speech_rides_in_the_same_batch():
    assert aos.parse(["wait", "--speech", "all"]) == (
        "steps", [{"op": "speech.wait", "target": "all"}])
    with pytest.raises(aos.Fail):
        aos.parse(["wait", "--speech", "上一句"])


def test_voice_synth_needs_no_stage():
    kind, _ = aos.parse(["voice", "synth", "先合成好"])
    assert kind == "free"
