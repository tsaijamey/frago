"""桌面页那四个前端文件。原件是配方 agent_os_ui 的 test_agent_os_ui.py，
搬进本体时大幅缩水：那个配方的三个 mode 里，install（把文件铺到某目录）和
assets（把内容念出来）都没有意义了——文件就在包里，服务端直接从这儿发。
剩下的只有一件事：**这四个文件真的跟着 wheel 走**。

为什么这条要写成断言而不是靠「实测过一次」：打包配置里
``packages = ["src/frago"]`` 已经把整棵包树纳入，底下那张按扩展名列的 include
是叠加的、实际冗余的——所以 .js / .css / .html 今天都进得去。但哪天有人加一条
exclude 把 assets 排掉，wheel 少了这四个文件，装起来一切正常，只有点开桌面页
的那个人看到一张打不开的页面。这条断言就是为那一天写的。
"""

from __future__ import annotations

import hashlib
from importlib.resources import files

from frago.desktop import stage

#: 桌面页的正身。少一个都是一张打不开的页面。
ASSET_NAMES = ("index.html", "style.css", "app.js", "ansi.js")


def test_assets_ship_with_the_package():
    """按包资源取，不按仓库路径取——装到别处也必须找得到。"""
    for name in ASSET_NAMES:
        assert files("frago.desktop").joinpath("assets", name).is_file(), name


def test_asset_files_lists_exactly_those_four_in_name_order():
    assert [p.name for p in stage.asset_files()] == sorted(ASSET_NAMES)


def test_the_page_is_a_page():
    """index.html 得真的是一张 HTML，别哪天被换成一个占位符。"""
    index = files("frago.desktop").joinpath("assets", "index.html").read_text(
        encoding="utf-8")
    assert "<html" in index.lower()


def test_ui_version_covers_every_asset():
    """版本号是这四个文件（名字 + 内容）的函数，一个都不能漏。

    漏掉一个的后果不是报错：那个文件改了而版本号不动，broker 拿版本号做**相等**
    比对，于是把开着旧资产的标签当成新的，几何照收——画面变形而没有一处报错。
    """
    digest = hashlib.sha256()
    for p in stage.asset_files():
        digest.update(p.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(p.read_bytes())
        digest.update(b"\0")
    assert stage.ui_version() == int(digest.hexdigest()[:12], 16)


def test_human_input_is_a_bottom_right_support_widget():
    """#human-input 常驻右下角：默认露出胶囊图标（#hi-trigger），面板（#hi-panel）按参数展开。"""
    assets = files("frago.desktop").joinpath("assets")
    index = assets.joinpath("index.html").read_text(encoding="utf-8")
    css = assets.joinpath("style.css").read_text(encoding="utf-8")
    js = assets.joinpath("app.js").read_text(encoding="utf-8")

    # 1. DOM 结构：容器不带 hidden（无参数时仍露出右下角图标），面板默认带 hidden
    assert 'id="human-input" class="hi-dock"' in index
    assert 'id="hi-panel"' in index and 'id="hi-trigger"' in index
    for required_id in ("hi-log", "hi-text", "hi-send", "hi-status", "hi-close"):
        assert f'id="{required_id}"' in index, required_id

    # 2. CSS 定位在右下角（right + bottom），不再挂在顶部中央
    hi_block = css.split("#human-input {", 1)[1].split("}", 1)[0]
    assert "right:" in hi_block and "bottom:" in hi_block
    assert "top:" not in hi_block

    # 3. JS 行为：普通荧幕恒显容器，带参数默认展开面板、无参数收起为图标，录制机位隐藏
    assert 'if (ROLE === "camera")' in js
    assert "setExpanded(false);" in js
    assert "setExpanded(true);" in js
    assert "/api/workbench/sessions/" in js
    # 4. 导演对话面板（Director Chat）文本发送与语音交互走同一执行路径（/api/workbench/desktop-voice/dispatch）
    assert '"/api/workbench/desktop-voice/dispatch"' in js
    assert '"how-frago-agent-runs-an-agent-os"' not in js


def test_desktop_stage_suspends_loops_and_polling_when_hidden_or_disconnected():
    """桌面页在切去其它页面（innerWidth===0 / document.hidden / hostVisible=false）
    或虚拟桌面未连接（!state.wsOpen）时，必须暂停动态桌布与扫描灯的 requestAnimationFrame
    循环、暂停会话记录轮询，并对断线重连采取退避；录制机位（ROLE==="camera"）恒视为可见。"""
    assets = files("frago.desktop").joinpath("assets")
    js = assets.joinpath("app.js").read_text(encoding="utf-8")

    assert "function isStageVisible()" in js
    assert "function shouldAnimateStage()" in js
    assert "function wakeStageLoops()" in js
    assert "function scheduleReconnect()" in js
    assert 'd.type === "frago:desktop-visibility"' in js
    assert "if (firstDrawn && !shouldAnimateStage())" in js


def test_petal_listener_ui_and_hotkey_wiring():
    """右下角默认展示彩色偏心花瓣麦克风监听器：支持右Alt按住说话、双击右Ctrl持续监听与Groq Whisper转写。"""
    assets = files("frago.desktop").joinpath("assets")
    index = assets.joinpath("index.html").read_text(encoding="utf-8")
    css = assets.joinpath("style.css").read_text(encoding="utf-8")
    js = assets.joinpath("app.js").read_text(encoding="utf-8")

    # 1. HTML 结构：6 片不同颜色的花瓣围绕同一旋转容器排布
    assert 'id="petal-listener"' in index
    assert 'id="petal-rotor"' in index
    for idx in range(6):
        assert f'class="petal p{idx}"' in index

    # 2. CSS 偏心圆心设计：每片花瓣的旋转/缩放圆心位于花瓣内部且偏心（34% 68%）
    assert "transform-origin: 34% 68%;" in css

    # 3. JS 热键与动画：AltRight 按住说话、ControlRight 双击持续监听、随机缩放与旋转、转写接口
    assert 'e.code === "AltRight"' in js
    assert 'e.code === "ControlRight"' in js
    assert '"/api/workbench/desktop-voice/transcribe"' in js
    assert 'd.type !== "frago:desktop-hotkey"' in js

    # 4. 转写过程不暴露为文字，仅在转写完成后显示纯转写文本；缺配置时引导前往 WebUI「设置 → 常规设置 → 旁路与轻量 AI」
    assert "function showTranscribedText(" in js
    assert "常规设置 → 旁路与轻量 AI" in index
    assert "常规设置 → 旁路与轻量 AI" in js
    assert "Groq Whisper 识别中" not in js
    assert "正在聆听…" not in js
    assert "正在转写上一句" not in js

    # 5. 持续监听防噪门限与 Whisper 幻觉过滤：有效发声跨度不含尾音静音，未达有效人声门限直接丢弃不发 API 请求
    assert "function getSpeechRmsThreshold()" in js
    assert "function hasValidSpeechSegment()" in js
    assert "function updateVadStats(" in js
    assert "function cleanRecognizedSpeechText(" in js
    assert "VAD_MIN_VOICED_MS = 180" in js
    assert "VAD_MIN_SPEECH_SPAN_MS = 220" in js
    assert "MIN_AUDIO_BLOB_BYTES = 1200" in js
    assert "flushContinuousSegment(hasValidSpeechSegment())" in js
    assert "vadLastVoiceAt - vadSpeechStartedAt" in js

    # 6. 若本机有 node，直接实跑前端 VAD 状态机与 cleanRecognizedSpeechText 验证：
    #    - 单帧脉冲 (16ms) + 880ms 静音 -> hasValidSpeechSegment() === false（修复旧版恒为 true 的漏洞）
    #    - 3 帧短促杂音 (48ms) + 880ms 静音 -> hasValidSpeechSegment() === false
    #    - 真实说话 (16 帧 = 256ms, rms=0.065) -> hasValidSpeechSegment() === true
    import shutil
    import subprocess

    node_bin = shutil.which("node")
    if node_bin:
        snippet = js.split("var VAD_NOISE_FLOOR_INIT =", 1)[1].split(
            "// 花瓣动画状态", 1
        )[0]
        harness = (
            "var VAD_NOISE_FLOOR_INIT ="
            + snippet
            + """
resetVadSegmentStats(1000);
// 场景 A：单帧噪音抖动 (16ms, rms=0.032) + 880ms 静音
updateVadStats(0.032, 1000, 16);
for (var t = 1016; t <= 1900; t += 16) updateVadStats(0.005, t, 16);
if (hasValidSpeechSegment() !== false) throw new Error("Single-frame spike should be rejected");

// 场景 B：3 帧轻微杂音/呼吸尾音 (48ms, rms=0.040) + 880ms 静音
resetVadSegmentStats(2000);
updateVadStats(0.040, 2000, 16);
updateVadStats(0.040, 2016, 16);
updateVadStats(0.040, 2032, 16);
for (var t2 = 2048; t2 <= 2950; t2 += 16) updateVadStats(0.006, t2, 16);
if (hasValidSpeechSegment() !== false) throw new Error("48ms noise jitter should be rejected");

// 场景 C：真实短句人声 (16 帧 = 256ms, rms=0.065)
resetVadSegmentStats(3000);
for (var i = 0; i < 16; i++) updateVadStats(0.065, 3000 + i * 16, 16);
if (hasValidSpeechSegment() !== true) throw new Error("Real speech segment should be accepted");

// 场景 D：前端 Whisper 幻觉清洗
if (cleanRecognizedSpeechText("Thank you.") !== "") throw new Error("Thank you. should be filtered");
if (cleanRecognizedSpeechText("...") !== "") throw new Error("... should be filtered");
if (cleanRecognizedSpeechText("做一下本地灯到灯的测试 Thank you.") !== "做一下本地灯到灯的测试") {
  throw new Error("Trailing Thank you. should be stripped");
}
if (cleanRecognizedSpeechText("继续") !== "继续") throw new Error("Short Chinese command should be kept");
console.log("VAD_AND_FILTER_OK");
"""
        )
        proc = subprocess.run(
            [node_bin, "-e", harness], capture_output=True, text=True, timeout=10
        )
        assert proc.returncode == 0, proc.stderr
        assert "VAD_AND_FILTER_OK" in proc.stdout



