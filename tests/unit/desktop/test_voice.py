"""虚拟桌面的语音：合成与缓存（voice.py）、broker 的语音队列、命令行的写法。

与 test_desktop.py 同一条纪律：**这台机器上舞台是常驻的**，测试不碰真端口、
真进程、真网络。edge-tts 换成假的模块，broker 的 subprocess / urllib 换成会当场
炸的假货，缓存落点顶成临时目录。

验的是看输出看不出来的事：

  · 同样的输入只合成一次；一条句子时间都没有的结果不算成功，也不进缓存
  · 网络与服务端的错会重试，参数写错不重试
  · 合成前把库里写死的旧主机换成新主机那条，两处绑定一起换
  · 这个包整个不能用属「装坏了」，不当成「这句没出声」重试降级
  · 缓存按最久没用的删，刚写进来的那句不删
  · 纯字幕的 say 一个字节都没变；开口的 say 默认等讲完
  · page 出声时没人报"开始放了"，回执说没人听见，不把"发出去了"说成"说出来了"
  · 合成失败退回字幕，照常往下走，回执写明这句没出声
  · 打断会掐掉正在说的与排着的
  · 录制音轨的 ffmpeg 命令：画面不重编码，每句按开口时刻推后再叠
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import sys
import time
import types

import pytest

from frago.desktop import aos, broker, voice

from .test_desktop import ExplodingNet, ExplodingSubprocess, FakeCompleted


async def _drain_speech_tasks(ctrl=None) -> None:
    """事件循环关闭前显式停止并回收挂起的语音后台任务，避免协程泄漏与跨用例 GC 串扰。"""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if not pending:
        return
    if ctrl is not None:
        try:
            await ctrl.endpoint({"steps": [{"op": "speech.stop"}]})
        except Exception:
            pass
        await asyncio.sleep(0)
    for _ in range(32):
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)


def _run_and_drain(coro, *, ctrl=None):
    async def _runner():
        try:
            return await coro
        finally:
            await _drain_speech_tasks(ctrl=ctrl)

    return asyncio.run(_runner())


def post_control(cfg, body: dict) -> tuple[int, dict]:
    """拿到 /control 那个 handler 并调它；退出事件循环前收掉挂起的 speech_worker。"""
    app = broker.build_app(dict(cfg))
    route = next(r for r in app.routes if getattr(r, "path", None) == "/control")
    resp = _run_and_drain(route.endpoint(body), ctrl=route)
    return resp.status_code, json.loads(resp.body)


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    """与 test_desktop 的 sealed_broker 同一份做法：build 期碰真进程、真请求就当场炸。"""
    monkeypatch.setattr(broker, "subprocess", ExplodingSubprocess())
    monkeypatch.setattr(broker, "urllib", ExplodingNet())
    clips = tmp_path / "broker-clips"
    clips.mkdir()
    yield {
        "id": "default", "port": 18770,
        "desktop": {"w": 1920, "h": 1080}, "browser": {"w": 1280, "h": 800},
        "term": {"cols": 100, "rows": 30}, "start_url": "about:blank",
        "desktop_url": "http://127.0.0.1:8093/app/agent_os",
        "tmux_session": "test-not-a-real-session", "clips_dir": str(clips),
        "stage_port": 19222, "record_port": 19223, "fps": 30,
        "content_id": "test-content", "ui_version": 1, "actor_headless": True,
    }
    gc.collect()


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
                for mark in turn.get("marks", [(100, 900, "First line.")]):
                    start, dur, text = mark
                    yield {"type": "SentenceBoundary", "offset": start * 10_000,
                           "duration": dur * 10_000, "text": text}

        # 库的内部结构照实写。换端点那段要改的就是这两个 WSS_URL：communicate
        # 导入时把常量绑进了自己的命名空间，所以它是一份单独的绑定，改漏了照样 403。
        old = ("wss://speech.platform.bing.com/consumer/speech/synthesize/"
               "readaloud/edge/v1?TrustedClientToken=fake-token")
        self.constants = types.SimpleNamespace(
            TRUSTED_CLIENT_TOKEN="fake-token", WSS_URL=old)
        self.communicate = types.SimpleNamespace(WSS_URL=old)
        self.module = types.SimpleNamespace(
            __version__="7.2.8-fake", Communicate=Communicate,
            constants=self.constants, communicate=self.communicate)


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
    first = voice.synthesize_sync("First line.")
    again = voice.synthesize_sync("First line.")
    assert len(fake.calls) == 1, "第二次应当命中缓存，不再联网"
    assert first["cached"] is False and again["cached"] is True
    # 48kbps 恒定码率：6000 字节 = 1000 毫秒。
    assert first["duration_ms"] == 1000
    assert first["sentences"] == [{"start_ms": 100, "end_ms": 1000,
                                   "text": "First line."}]
    assert fake.calls[0]["boundary"] == "SentenceBoundary"
    assert os.path.isfile(first["audio"]) and os.path.isfile(first["meta"])


def test_no_sentence_times_is_a_failure_and_is_not_cached(cache, edge):
    """拿不到句子时间，字幕和对齐都无从谈起——这不算合成成功。"""
    edge([{"marks": []}] * 3)
    with pytest.raises(voice.VoiceFailed):
        voice.synthesize_sync("First line.")
    assert voice.stats()["lines"] == 0


def test_network_errors_are_retried(cache, edge):
    fake = edge([ConnectionError("503"), {}])
    out = voice.synthesize_sync("First line.")
    assert len(fake.calls) == 2
    assert "503" in out["retried"][0]


def test_bad_params_fail_before_the_network(cache, edge):
    fake = edge()
    with pytest.raises(ValueError, match="语速"):
        voice.synthesize_sync("First line.", rate="fast")
    assert fake.calls == []


def test_english_only_rejects_cjk_lines_before_the_network(cache, edge, monkeypatch):
    """当显式开启 ENFORCE_ENGLISH_TEXT 门禁时：中文台词当场拒，一个字节都不联网。"""
    monkeypatch.setattr(voice, "ENFORCE_ENGLISH_TEXT", True)
    fake = edge()
    with pytest.raises(ValueError, match="只说英文"):
        voice.synthesize_sync("这一句是中文。")
    assert fake.calls == []


def test_english_only_rejects_a_non_english_voice(cache, edge, monkeypatch):
    """当显式开启 ENFORCE_ENGLISH_VOICE 门禁时：非 en- 嗓子当场拒。"""
    monkeypatch.setattr(voice, "ENFORCE_ENGLISH_VOICE", True)
    fake = edge()
    with pytest.raises(ValueError, match="只说英文"):
        voice.synthesize_sync("First line.", voice="zh-CN-XiaoxiaoNeural")
    assert fake.calls == []


def test_english_only_relaxes_by_the_switches(cache, edge):
    """默认放开中英文自适应合成，支持多语言情感音色（Ava / Andrew / Xiaoxiao）。"""
    assert voice.ENFORCE_ENGLISH_TEXT is False
    assert voice.ENFORCE_ENGLISH_VOICE is False
    assert voice.detect_language("已经为你打开终端。") == "zh"
    assert voice.detect_language("Terminal is now open.") == "en"
    assert voice.resolve_emotional_voice("你好") == "zh-CN-XiaoxiaoNeural"
    assert voice.resolve_emotional_voice("Hello") == "en-US-AvaMultilingualNeural"
    assert voice.resolve_emotional_voice("Hello", "male") == "en-US-AndrewMultilingualNeural"
    fake = edge()
    out = voice.synthesize_sync("这一句是中文。", voice="zh-CN-XiaoxiaoNeural")
    assert out["voice"] == "zh-CN-XiaoxiaoNeural" and len(fake.calls) == 1


def test_missing_edge_tts_says_frago_is_incomplete(cache, monkeypatch):
    """edge-tts 是必装依赖。缺了就是 frago 没装完整——回执叫人重装 frago，
    NEVER 叫人去单独补装一个包：用户不该知道 frago 底下还有这么一个包。"""
    monkeypatch.setitem(sys.modules, "edge_tts", None)   # import 时抛 ImportError
    with pytest.raises(voice.VoiceUnavailable) as exc:
        voice.synthesize_sync("First line.")
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


def test_endpoint_is_switched_to_the_new_host(cache, edge):
    """库把旧主机写死在自己的常量里，合成前要换成新主机那条。

    旧主机自 2026-10 起对合成那条 WebSocket 一律 403。换端点的事没人看得见，
    只有回头抓握手才发现，所以它得有自己的判据，不能只靠「真打一次通了」——
    那个证明不了两处绑定都换了。
    """
    fake = edge()
    voice.synthesize_sync("First line.")
    url = fake.communicate.WSS_URL
    assert url.startswith(voice.WSS_ENDPOINT + "?"), url
    assert f"{voice.CREDENTIAL_PARAM}=fake-token" in url, url
    # 新主机不认旧参数名：只换主机、留着 TrustedClientToken 一样回 403。
    assert "TrustedClientToken" not in url, url
    assert url == fake.constants.WSS_URL, "两处都要写，communicate 那份是单独绑的"


def test_a_restructured_edge_tts_is_reported_not_retried(cache, monkeypatch):
    """库换了内部结构：当场报出库的版本，不许重试三次再降级成字幕。

    降级那条路是给「这一句没合成成」用的。这个包整个不能用是另一回事，混进去
    会把「装坏了」藏成「这句没声音」。
    """
    monkeypatch.setitem(sys.modules, "edge_tts",
                        types.SimpleNamespace(Communicate=object,
                                              __version__="9.9.9"))
    with pytest.raises(voice.VoiceUnavailable, match="9.9.9"):
        voice.synthesize_sync("First line.")


def test_eviction_drops_least_recently_used_first(cache, edge):
    edge([{"audio": b"\xff" * 400_000}] * 3)
    (cache / "config.json").write_text(json.dumps({"tts": {"cache_max_mb": 1}}))
    old = voice.synthesize_sync("An old line.")
    mid = voice.synthesize_sync("A middle line.")
    past = time.time() - 3600
    os.utime(old["meta"], (past, past))       # 旧的那句一小时没人用
    new = voice.synthesize_sync("A new line.")
    assert new["evicted"]["files"] == 1
    assert not os.path.exists(old["meta"]) and not os.path.exists(old["audio"])
    assert os.path.exists(mid["meta"]) and os.path.exists(new["meta"])


def test_audio_path_only_accepts_fingerprints(cache, edge):
    edge()
    out = voice.synthesize_sync("First line.")
    assert str(voice.audio_path(out["key"])) == out["audio"]
    for bad in ("../../etc/passwd", "", "abc", out["key"][:-1] + "/"):
        assert voice.audio_path(bad) is None


def test_clear_leaves_nothing(cache, edge):
    edge()
    voice.synthesize_sync("First line.")
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
    assert cut["interrupted"] == {"stopped": "1", "dropped": ["2"], "kept": []}
    assert cut["speech"]["state"] == "done"


def test_interject_cuts_the_current_but_keeps_the_queued(sealed, fake_synth):
    """插播：掐掉正在说的那一句，这一句立刻说，排着的留着接着放。

    与 --interrupt 的差别就在 dropped 与 kept 上：那条整队丢掉，这条一个不丢。
    少了这条，想说一句当下的事就只能排到队尾，而队尾可能压着一两分钟的闲话。
    """
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 50},
        {"op": "say", "text": "插播一句", "speak": True, "out": "none",
         "interject": True}]})
    cut = out["results"][3]
    assert cut["status"] == "ok"
    # 正在说的那句被掐掉；排着的那句原样留着（kept 里只是它，不含插播的自己）
    assert cut["interrupted"] == {"stopped": "1", "dropped": [], "kept": ["2"]}
    assert cut["speech"]["state"] == "done", "插播这一句是立刻说的，回执里它已讲完"
    assert cut["interrupted"]["dropped"] == [], "一个排着的都不许丢"


def test_interject_receipt_does_not_count_the_line_it_cut(sealed, fake_synth):
    """插播回执里的 `queued_behind` 是「排在这一句后面的」，不含被它掐掉的那句。

    同一份回执里 `kept` 已经剔掉了插播自己，`queued_behind` 要是还留着刚被掐掉的
    那句，两个字段口径就不一致：导演按它数「后面还压着多少话」会多算一条。
    """
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 50},
        {"op": "say", "text": "插播一句", "speak": True, "out": "none",
         "interject": True, "async": True}]})
    cut = out["results"][3]
    assert cut["status"] == "ok"
    assert cut["interrupted"]["stopped"] == "1"
    assert cut["interrupted"]["kept"] == ["2"]
    assert cut["queued_behind"] == ["2"], "被掐掉的那句不该算进「后面还压着」"


def test_the_kept_queue_carries_on_after_the_interjection(sealed, fake_synth):
    """插播说完之后，原来排着的那句接着放——留在队列里不等于留着不动。"""
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 50},
        {"op": "say", "text": "插播一句", "speak": True, "out": "none",
         "interject": True},
        {"op": "speech.wait", "target": "all"}]})
    assert out["results"][3]["interrupted"]["kept"] == ["2"]
    assert out["results"][4]["status"] == "ok", "队列没接着放，等 all 会等不到"


def test_interject_right_when_the_worker_takes_the_next_line(sealed, fake_synth):
    """插播落在「worker 刚端起下一句、播放任务一步都还没跑」的那一瞬。

    这是插播唯一一处会让整个语音队列停住的窗口。worker 端起一句把它设为「正在
    说」，再建播放任务；两步之间不让出控制权，可插播这一侧是在**同一批事件**里
    被唤醒的（`sleep 0` 让出的那一次），于是它取消的是那个一步都没跑的任务——
    被掐的那句于是从没记下开始时刻。取消分支要是直接取 `item["started_at"]`，
    这里就是 KeyError：worker 死掉，插播自己不出声、排着的也一起停，而回执照常
    写 ok——台上只有声音没了，看不到报错。

    判据取用户能看见的那两条：插播这一句真的说完了，排着的那句接着放。
    """
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "第一句", "speak": True, "out": "none", "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 0},
        {"op": "say", "text": "插播一句", "speak": True, "out": "none",
         "interject": True},
        {"op": "speech.wait", "target": "all"}]})
    cut = out["results"][3]
    assert cut["status"] == "ok"
    assert cut["speech"]["state"] == "done", "插播这一句没说出来——worker 死在这儿了"
    assert out["results"][4]["status"] == "ok", "队列停在插播之后，等 all 会等不到"


def test_voice_stop_keep_queue_leaves_the_queue_alone(sealed, fake_synth):
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 50},
        {"op": "speech.stop", "keep_queue": True},
        {"op": "speech.wait", "target": "all"}]})
    stop = out["results"][3]
    assert stop["status"] == "ok"
    assert stop["stopped"] == "1" and stop["dropped"] == [] and stop["kept"] == ["2"]
    assert out["results"][4]["status"] == "ok", "排着的被掐掉了，等 all 会等不到"


def test_voice_stop_without_the_flag_still_drops_the_queue(sealed, fake_synth):
    """老规矩一个字不改：不带 --keep-queue 就正在说的与排着的一起丢。"""
    _, out = post_control(sealed, {"steps": [
        {"op": "say", "text": "一句很长的话", "speak": True, "out": "none",
         "async": True},
        {"op": "say", "text": "排着的", "speak": True, "out": "none", "async": True},
        {"op": "sleep", "ms": 50},
        {"op": "speech.stop"}]})
    stop = out["results"][3]
    assert stop["stopped"] == "1" and stop["dropped"] == ["2"] and stop["kept"] == []


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
    syn = voice.synthesize_sync("First line.")
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


def test_interject_is_a_switch_on_say():
    kind, steps = aos.parse(["say", "插播一句", "--speak", "--async", "--interject"])
    assert kind == "steps"
    assert steps == [{"op": "say", "text": "插播一句", "speak": True,
                      "out": "page", "async": True, "interject": True}]


def test_interrupt_and_interject_are_mutually_exclusive():
    """两条路各是一种语义，同时给就是没说清要哪种——当场拒，别猜。"""
    with pytest.raises(aos.Fail) as exc:
        aos.parse(["say", "一句", "--speak", "--interrupt", "--interject"])
    assert "只能挑一个" in exc.value.payload["error"]


def test_voice_stop_takes_keep_queue():
    assert aos.parse(["voice", "stop"]) == ("steps", [{"op": "speech.stop"}])
    assert aos.parse(["voice", "stop", "--keep-queue"]) == (
        "steps", [{"op": "speech.stop", "keep_queue": True}])


def test_wait_speech_rides_in_the_same_batch():
    assert aos.parse(["wait", "--speech", "all"]) == (
        "steps", [{"op": "speech.wait", "target": "all"}])
    with pytest.raises(aos.Fail):
        aos.parse(["wait", "--speech", "上一句"])


def test_voice_synth_needs_no_stage():
    kind, _ = aos.parse(["voice", "synth", "先合成好"])
    assert kind == "free"


def test_resolve_emotional_voice_prefers_native_zh_and_en_voices():
    """中文文本必须使用地道中文母语音色（zh-CN-XiaoxiaoNeural），杜绝英文音色念中文；纯英文文本使用英文情感音色。"""
    assert voice.resolve_emotional_voice("你好，我已经帮你打开了终端。") == "zh-CN-XiaoxiaoNeural"
    assert (
        voice.resolve_emotional_voice("你好，世界", "en-US-AvaMultilingualNeural")
        == "zh-CN-XiaoxiaoNeural"
    )
    assert voice.resolve_emotional_voice("你好，世界", "male") == "zh-CN-YunxiNeural"
    assert (
        voice.resolve_emotional_voice("Hello, I have opened the browser for you.")
        == "en-US-AvaMultilingualNeural"
    )
    assert (
        voice.resolve_emotional_voice("Hello world", "zh-CN-XiaoxiaoNeural")
        == "en-US-AvaMultilingualNeural"
    )
    assert voice.resolve_emotional_voice("Hello world", "male") == "en-US-AndrewMultilingualNeural"


def test_two_layer_voice_channel_cli_and_recording_isolation(sealed, fake_synth, monkeypatch):
    """验证双层语音体系（ambient vs narration）：
    1. CLI say 支持 --channel narration|ambient，非法值报错；
    2. 录制期间（recorder.recording == True），channel='ambient' 被直接静默拦截（suppressed=True），
       不触发 TTS 合成、不入队、不进入 StageRecorder.voice_lines；
    3. 默认 channel='narration' 的 say --speak 在录制期间正常合成、播报并写入 StageRecorder.voice_lines。
    """
    kind_amb, steps_amb = aos.parse(["say", "现在开始录制", "--speak", "--channel", "ambient"])
    assert kind_amb == "steps"
    assert steps_amb[0]["channel"] == "ambient"

    kind_nar, steps_nar = aos.parse(["say", "这是正式解说词", "--speak", "--channel", "narration"])
    assert kind_nar == "steps"
    assert steps_nar[0]["channel"] == "narration"

    with pytest.raises(aos.Fail) as exc:
        aos.parse(["say", "测试", "--speak", "--channel", "invalid"])
    assert "--channel 只支持 narration|ambient" in exc.value.payload["error"]

    rigs: list[broker.StageRecorder] = []

    class ActiveRecorder(broker.StageRecorder):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.recording, self.name, self._t0 = True, "two-layer-take", time.time() - 1.0
            rigs.append(self)

    monkeypatch.setattr(broker, "StageRecorder", ActiveRecorder)

    code, out = post_control(
        sealed,
        {
            "steps": [
                {
                    "op": "say",
                    "text": "现在开始录制，我打开了设置页",
                    "speak": True,
                    "out": "none",
                    "channel": "ambient",
                },
                {
                    "op": "say",
                    "text": "在设置页中点击 AI Providers 配置语音识别模型",
                    "speak": True,
                    "out": "none",
                },
            ]
        },
    )
    assert code == 200 and out["ok"] is True
    amb_res, nar_res = out["results"]
    assert amb_res["ok"] is True
    assert amb_res["suppressed"] is True
    assert amb_res["reason"] == "recording_active_ambient_muted"
    assert amb_res["spoken"] is False
    assert nar_res["spoken"] is True
    assert nar_res["channel"] == "narration"

    # TTS 仅对 narration 那一句调用了 1 次，ambient 完全未触发合成
    assert len(fake_synth) == 1
    assert fake_synth[0]["text"] == "在设置页中点击 AI Providers 配置语音识别模型"

    # StageRecorder.voice_lines 仅收录了 narration 那一句，且录制动作日志 journal 也不被 suppressed ambient 污染
    assert len(rigs[0].voice_lines) == 1
    assert rigs[0].voice_lines[0]["text"] == "在设置页中点击 AI Providers 配置语音识别模型"
    assert rigs[0].voice_lines[0]["channel"] == "narration"
    assert len(rigs[0].journal) == 1
    assert rigs[0].journal[0]["params"]["text"] == "在设置页中点击 AI Providers 配置语音识别模型"


# ── 20261012-desktop-speech-queue-single 三处缺陷修复单测 ────────────────


def test_bogus_voice_value_error_falls_back_to_caption_without_retrying_or_stopping_batch(
    sealed, cache, monkeypatch
):
    """en-GB-Bogus 等不被引擎接受的嗓子：不重试 3 次，转为 VoiceFailed，
    由 broker 优雅退回只显示字幕且同批后续步骤继续执行。"""
    calls: list[dict] = []

    class BogusRejectingEdge:
        def __init__(self):
            old = (
                "wss://speech.platform.bing.com/consumer/speech/synthesize/"
                "readaloud/edge/v1?TrustedClientToken=fake-token"
            )
            self.constants = types.SimpleNamespace(
                TRUSTED_CLIENT_TOKEN="fake-token", WSS_URL=old
            )
            self.communicate = types.SimpleNamespace(WSS_URL=old)

            class Communicate:
                def __init__(self, text, voice_name, **kw):
                    calls.append({"text": text, "voice": voice_name, **kw})
                    if voice_name == "en-GB-Bogus":
                        raise ValueError(f"Invalid voice '{voice_name}'.")

                async def stream(self):
                    yield {"type": "audio", "data": b"\xff" * 6000}
                    yield {
                        "type": "SentenceBoundary",
                        "offset": 100 * 10_000,
                        "duration": 900 * 10_000,
                        "text": "ok",
                    }

            self.Communicate = Communicate
            self.__version__ = "7.2.8-fake"

    fake_edge = BogusRejectingEdge()
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge)

    # 1. voice.synthesize 直接将引擎 ValueError 转为 VoiceFailed，且不重试
    with pytest.raises(voice.VoiceFailed, match="en-GB-Bogus"):
        voice.synthesize_sync("Hello world.", voice="en-GB-Bogus")
    assert len(calls) == 1, "嗓子名非法不应重试 3 次"

    # 2. 经 broker /control 同批执行：第 1 步退回字幕，第 2 步照常执行
    calls.clear()
    code, out = post_control(
        sealed,
        {
            "steps": [
                {
                    "op": "say",
                    "text": "Hello with bogus voice.",
                    "speak": True,
                    "voice": "en-GB-Bogus",
                },
                {"op": "sleep", "ms": 0},
            ]
        },
    )
    assert code == 200 and out["ok"] is True
    r0, r1 = out["results"]
    assert r0["status"] == "ok" and r0["spoken"] is False
    assert "没出声" in r0["note"]
    assert "en-GB-Bogus" in r0["error"]
    assert r1["status"] == "ok"
    assert len(calls) == 1


def test_cjk_re_covers_fullwidth_punctuation_and_hangul(cache, edge, monkeypatch):
    """写死全角标点 (U+FF00–U+FFEF) 与韩文 (U+AC00–U+D7AF) 在 _CJK_RE 及双开关下的行为。"""
    # 正则边界覆盖
    assert voice._CJK_RE.search("Hello，world！")  # U+FF0C, U+FF01
    assert voice._CJK_RE.search("\uff00") and voice._CJK_RE.search("\uffef")
    assert voice._CJK_RE.search("안녕하세요")
    assert voice._CJK_RE.search("\uac00") and voice._CJK_RE.search("\ud7af")
    assert not voice._CJK_RE.search("Hello, world! (test) [123]")

    # 默认 ENFORCE_ENGLISH_TEXT=False 时放行，不抛 ValueError
    assert voice.ENFORCE_ENGLISH_TEXT is False
    fake = edge([{}, {}])
    out_fw = voice.synthesize_sync("Hello，world！")
    out_ko = voice.synthesize_sync("안녕하세요")
    assert out_fw["voice"] and out_ko["voice"]
    assert len(fake.calls) == 2

    # 显式开启 ENFORCE_ENGLISH_TEXT=True 时，全角标点与韩文均在联网前立即拦截
    monkeypatch.setattr(voice, "ENFORCE_ENGLISH_TEXT", True)
    fake_blocked = edge()
    for sample in ("Hello，world！", "（bracket）", "안녕하세요"):
        with pytest.raises(ValueError, match="全角标点|只说英文"):
            voice.synthesize_sync(sample)
    assert fake_blocked.calls == [], "拦截发生在联网前"

    # 纯英文半角标点即使开启门禁也放行
    out_en = voice.synthesize_sync("Hello, world! (ok)", voice="en-US-AvaMultilingualNeural")
    assert out_en["voice"] == "en-US-AvaMultilingualNeural"
    assert len(fake_blocked.calls) == 1


def test_voice_prefix_validation_is_case_insensitive(cache, edge, monkeypatch):
    """嗓子名前缀校验不再强制小写（支持 EN-US-... / En-GB-... / ZH-cn-...）。"""
    # 1. 默认自适应模式：大小写混合前缀应被识别并规范化，不误抛弃为默认音色
    assert voice.resolve_emotional_voice("Hello.", "EN-US-AriaNeural") == "en-US-AriaNeural"
    assert voice.resolve_emotional_voice("Hello.", "En-gb-SoniaNeural") == "en-GB-SoniaNeural"
    assert voice.resolve_emotional_voice("你好。", "ZH-cn-XiaoyiNeural") == "zh-CN-XiaoyiNeural"

    # 2. 开启 ENFORCE_ENGLISH_VOICE=True 时，大小写混合英文前缀应正常放行
    monkeypatch.setattr(voice, "ENFORCE_ENGLISH_VOICE", True)
    fake = edge([{}, {}])
    out1 = voice.synthesize_sync("Hello.", voice="EN-US-AvaMultilingualNeural")
    out2 = voice.synthesize_sync("Hello.", voice="En-GB-SoniaNeural")
    assert out1["voice"] == "en-US-AvaMultilingualNeural"
    assert out2["voice"] == "en-GB-SoniaNeural"
    assert len(fake.calls) == 2

    # 非英文前缀仍应准确拦截
    with pytest.raises(ValueError, match="只说英文"):
        voice.synthesize_sync("Hello.", voice="ZH-CN-XiaoxiaoNeural")


def test_speech_worker_logs_and_self_heals_after_crash(sealed, fake_synth, capsys, monkeypatch):
    """worker 意外异常退出时：记录结构化日志、兜底结束当句、自动重建消费后续队列。"""
    real_time = broker.time.time
    crashed = {"count": 0}

    class CrashOnceTime:
        def __getattr__(self, name):
            return getattr(time, name)

        def time(self):
            frame = sys._getframe(1)
            if (
                frame.f_code.co_name == "speech_worker"
                and not isinstance(sys.exc_info()[1], GeneratorExit)
                and crashed["count"] == 0
            ):
                crashed["count"] += 1
                raise RuntimeError("模拟 worker 内部意外崩溃")
            return real_time()

    gc.collect()
    monkeypatch.setattr(broker, "time", CrashOnceTime())

    code, out = post_control(
        sealed,
        {
            "steps": [
                {"op": "say", "text": "第一句会触发崩溃", "speak": True, "out": "none", "async": True},
                {"op": "say", "text": "第二句必须自动续跑", "speak": True, "out": "none", "async": True},
                {"op": "speech.wait", "target": "all"},
                {"op": "speech.wait", "target": "1"},
                {"op": "speech.wait", "target": "2"},
            ]
        },
    )
    assert code == 200 and out["ok"] is True
    assert crashed["count"] == 1
    assert out["results"][2]["status"] == "ok"
    assert out["results"][3]["speech"]["state"] == "failed"
    assert "模拟 worker 内部意外崩溃" in out["results"][3]["speech"]["error"]
    assert out["results"][4]["speech"]["state"] == "done"

    err_log = capsys.readouterr().err
    assert "语音 worker 异常退出" in err_log
    assert "模拟 worker 内部意外崩溃" in err_log
    assert "重建 worker" in err_log


def test_speech_worker_circuit_breaker_stops_infinite_crash_loop(
    sealed, fake_synth, capsys, monkeypatch
):
    """worker 连续异常崩溃达到上限时停止自愈并将剩余条目兜底失败，不死循环空转。"""
    monkeypatch.setattr(broker, "SPEECH_WORKER_MAX_CRASHES", 3)
    monkeypatch.setattr(broker, "SPEECH_WORKER_BACKOFF_SEC", 0.01)
    real_time = broker.time.time
    crashes = {"count": 0}

    class AlwaysCrashWorkerTime:
        def __getattr__(self, name):
            return getattr(time, name)

        def time(self):
            if (
                sys._getframe(1).f_code.co_name == "speech_worker"
                and not isinstance(sys.exc_info()[1], GeneratorExit)
            ):
                crashes["count"] += 1
                raise RuntimeError("模拟持续性 worker 崩溃")
            return real_time()

    gc.collect()
    monkeypatch.setattr(broker, "time", AlwaysCrashWorkerTime())

    code, out = post_control(
        sealed,
        {
            "steps": [
                {"op": "say", "text": f"第{i}句", "speak": True, "out": "none", "async": True}
                for i in range(1, 5)
            ]
            + [
                {"op": "speech.wait", "target": "all"},
                {"op": "speech.wait", "target": "4"},
            ],
        },
    )
    assert code == 200 and out["ok"] is True
    assert crashes["count"] == 3, "达到熔断上限 3 次后必须停止自愈，不能无限死循环"
    assert out["results"][4]["status"] == "ok", "剩余条目应已兜底结束，wait all 不应挂死"
    assert out["results"][5]["speech"]["state"] == "failed"
    assert "连续异常退出" in out["results"][5]["speech"]["error"]
    err_log = capsys.readouterr().err
    assert "连续异常退出达上限（3 次）" in err_log


def test_speech_play_single_item_failure_logs_and_continues(sealed, fake_synth, capsys, monkeypatch):
    """单句播放抛出异常时写错误日志并继续消费后续队列。"""
    calls = {"n": 0}

    class FakeProc:
        def __init__(self):
            self.returncode = 0

        async def wait(self):
            await asyncio.sleep(0.02)
            return 0

        def kill(self):
            pass

    async def flaky_spawn(_path: str):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("音频设备暂不可用")
        return FakeProc()

    monkeypatch.setattr(broker, "_player_cmd", lambda _p: ["afplay", _p])
    monkeypatch.setattr(broker, "_spawn_player", flaky_spawn)

    code, out = post_control(
        sealed,
        {
            "steps": [
                {"op": "say", "text": "第一句放音炸了", "speak": True, "out": "local", "async": True},
                {"op": "say", "text": "第二句正常", "speak": True, "out": "local", "async": True},
                {"op": "speech.wait", "target": "all"},
                {"op": "speech.wait", "target": "1"},
                {"op": "speech.wait", "target": "2"},
            ]
        },
    )
    assert code == 200 and out["ok"] is True
    assert calls["n"] == 2
    assert out["results"][3]["speech"]["state"] == "failed"
    assert "音频设备暂不可用" in out["results"][3]["speech"]["error"]
    assert out["results"][4]["speech"]["state"] == "done"
    err_log = capsys.readouterr().err
    assert "语音播放失败 id=1" in err_log
    assert "音频设备暂不可用" in err_log


def test_speech_wait_extends_deadline_on_interject(sealed, tmp_path, monkeypatch):
    """等待期间插入更长的插播时，按队列尾部重算等待期限，不误报超时且回执标明 extended_by。"""
    async def timed_synth(text, voice_name, rate, volume, pitch):
        audio = tmp_path / "line.mp3"
        audio.write_bytes(b"\xff")
        ms = 550 if "插播" in text else 100
        return {
            "key": "b" * 64,
            "voice": voice_name,
            "duration_ms": ms,
            "cached": False,
            "audio": str(audio),
            "sentences": [],
        }

    monkeypatch.setattr(broker.voice, "synthesize", timed_synth)
    # 收紧默认余量，使 2 句初始总期限仅 ~0.26s，小于插播加入后的总时长 (~0.65s)
    monkeypatch.setattr(broker, "SPEECH_START_GRACE_SEC", 0.01)
    monkeypatch.setattr(broker, "SPEECH_END_GRACE_SEC", 0.01)
    monkeypatch.setattr(broker, "SPEECH_WAIT_SLACK_SEC", 0.02)

    app = broker.build_app(dict(sealed))
    ctrl = next(r for r in app.routes if getattr(r, "path", None) == "/control")

    async def scenario():
        # 先异步排入两句各 100ms
        await ctrl.endpoint(
            {
                "steps": [
                    {"op": "say", "text": "第一句", "speak": True, "out": "none", "async": True},
                    {"op": "say", "text": "第二句", "speak": True, "out": "none", "async": True},
                ]
            }
        )
        wait_task = asyncio.create_task(
            ctrl.endpoint({"steps": [{"op": "speech.wait", "target": "2"}]})
        )
        await asyncio.sleep(0.03)
        # 在等第 2 句的过程中插播一句 550ms 的话（远超最初 ~0.26s deadline）
        interject_resp = await ctrl.endpoint(
            {
                "steps": [
                    {
                        "op": "say",
                        "text": "这是一句较长的插播",
                        "speak": True,
                        "out": "none",
                        "interject": True,
                        "async": True,
                    }
                ]
            }
        )
        wait_resp = await wait_task
        return json.loads(interject_resp.body), json.loads(wait_resp.body)

    interject_out, wait_out = _run_and_drain(scenario(), ctrl=ctrl)
    assert interject_out["ok"] is True
    assert wait_out["ok"] is True
    res = wait_out["results"][0]
    assert res["status"] == "ok", f"插播不应误报超时: {res}"
    assert res["speech"]["id"] == "2" and res["speech"]["state"] == "done"
    assert res["extended_by"] == ["3"]


def test_speech_wait_respects_hard_cap_and_genuine_hang_timeout(sealed, tmp_path, monkeypatch):
    """真正卡死或持续插播超过硬上界时，仍受保护准时超时而不无限死等。"""
    async def synth_ok(text, voice_name, rate, volume, pitch):
        audio = tmp_path / "hang.mp3"
        audio.write_bytes(b"\xff")
        return {
            "key": "c" * 64,
            "voice": voice_name,
            "duration_ms": 80,
            "cached": False,
            "audio": str(audio),
            "sentences": [],
        }

    class HangingProc:
        def __init__(self):
            self.returncode = None

        async def wait(self):
            await asyncio.sleep(10.0)
            return 0

        def kill(self):
            pass

    async def spawn_hanging(_path: str):
        return HangingProc()

    monkeypatch.setattr(broker.voice, "synthesize", synth_ok)
    monkeypatch.setattr(broker, "_player_cmd", lambda _p: ["afplay", _p])
    monkeypatch.setattr(broker, "_spawn_player", spawn_hanging)
    monkeypatch.setattr(broker, "SPEECH_START_GRACE_SEC", 0.01)
    monkeypatch.setattr(broker, "SPEECH_END_GRACE_SEC", 0.01)
    monkeypatch.setattr(broker, "SPEECH_WAIT_SLACK_SEC", 0.05)
    monkeypatch.setattr(broker, "SPEECH_WAIT_MAX_EXTEND_SEC", 0.15)

    # 1. 无插播但本地播放进程卡住：按初始期限直接超时（不被假延长）
    code1, out1 = post_control(
        sealed,
        {
            "steps": [
                {"op": "say", "text": "卡死的一句", "speak": True, "out": "local"},
            ]
        },
    )
    assert code1 == 500 and out1["ok"] is False
    assert "等语音讲完" in out1["error"]

    # 2. 持续插播企图无限续期：必须在硬上界内结束并明确说明「期间又排了 N 句新语音」
    app = broker.build_app(dict(sealed))
    ctrl = next(r for r in app.routes if getattr(r, "path", None) == "/control")

    async def flood_scenario():
        await ctrl.endpoint(
            {"steps": [{"op": "say", "text": "初始卡住", "speak": True, "out": "local", "async": True}]}
        )
        wait_task = asyncio.create_task(
            ctrl.endpoint({"steps": [{"op": "speech.wait", "target": "all"}]})
        )
        for idx in range(5):
            if wait_task.done():
                break
            await asyncio.sleep(0.05)
            await ctrl.endpoint(
                {
                    "steps": [
                        {
                            "op": "say",
                            "text": f"持续新排队{idx}",
                            "speak": True,
                            "out": "local",
                            "async": True,
                        }
                    ]
                }
            )
        resp = await wait_task
        return resp.status_code, json.loads(resp.body)

    code2, out2 = _run_and_drain(flood_scenario(), ctrl=ctrl)
    assert code2 == 500 and out2["ok"] is False
    assert "期间又排了" in out2["error"]


