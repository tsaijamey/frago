"""虚拟桌面舞台的单测。原件是配方目录里的 test_agent_os.py（自造 harness），
搬进本体时改成 pytest；验的事情一条没减，基类那几条换成了搬家之后的对应物。

⚠ **这台机器上舞台是常驻的**：broker 在 8770、tmux 会话叫 frago-stage、
9222 上还住着演员浏览器。测试碰它们就等于在人干活的时候把画面掐了。所以
subprocess / urllib / time / shutil **全部换成模块全局上的假货**——
换名字而不是 patch 深层函数：漏了哪条路会当场 AttributeError，
不会静默走到真端口、真进程上去。落点一律临时目录。

    真进程：0 个（数 FakeSubprocess.popen）
    真请求：0 条（FakeNet 记下每一条 URL，一条都没出去）
    真注册表：不碰（registry 用的是真语义，落点被顶成临时目录）

验的是看输出看不出来的事：

  · 端口上已经活着就复用，一次子进程都不起
  · broker 用 frago 自己的解释器按模块起，不再是 `uv run broker.py`
  · 桌面页地址只由 health.expected_desktop_url 算
  · 算出来的地址随 cfg 交给 broker——录制机位打开的就是它
  · uiVersion 是资产内容的函数（wheel 里 mtime 会被归一化，从前那个口径失效）
  · 不传 open 时要核对 content_id，别人那块荧幕不算数
  · 自检恒不抛异常：查不了就 unavailable，up 照常成功
"""

from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import pytest

from frago.desktop import broker, health, refs, registry, stage

CONTENT_ID = registry.content_id_for("default")
DESKTOP_URL = health.expected_desktop_url(CONTENT_ID)

UP_FIELDS = {
    "success", "id", "url", "instance", "runtime", "control", "status",
    "content_id", "tmux_session", "browser_opened", "screen_reused",
    "health", "hint",
}

LIVE_BROKER = {
    "pid": 68848, "content_id": CONTENT_ID, "clients_count": 1,
    "clients": [{"primary": True, "contentId": CONTENT_ID, "instanceId": "default"}],
    "layout_reported": True, "ui_ready": True, "frame_age_sec": 0.4,
    "actor_viewport": {"w": 1280, "h": 800}, "focus": "browser",
    "windows_open": ["term", "browser"], "foreign_clients": [],
    "duplicate_clients": [], "stale_clients": [],
    "cdp_ports": {"stage": 9222, "record": 9223},
    "recorder": {"recording": False},
}

NOBODY = {**LIVE_BROKER, "clients_count": 0, "clients": []}


# ── 桩点：换掉模块全局，别去 patch 深层函数 ──────────────────────────────

class FakeClock:
    """顶掉 time：sleep 不真等，只记账。

    time() 跟着 sleep 的次数走（一次算 1 秒），所以 `deadline = time() + 90`
    这种写法在假时钟下照样收敛——90 次 sleep 之后就到点，实测零等待。
    """

    def __init__(self):
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def monotonic(self):
        return float(len(self.sleeps))

    def time(self):
        return 1756270000.0 + len(self.sleeps)

    def strftime(self, *a, **k):
        import time as _t
        return _t.strftime(*a, **k)


class FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid


class FakeSubprocess:
    """顶掉 subprocess：一个真进程都不起。

    stage 只用 Popen（起 broker）。哪天有人在这儿加了 subprocess.run，
    下面那句 AssertionError 会当场把它喊出来——而不是让测试安静地去跑真命令。
    """

    def __init__(self):
        self.popen: list[dict] = []

    def Popen(self, argv, **kw):  # noqa: N802 顶的就是 subprocess.Popen 这个名字
        self.popen.append({"argv": list(argv), "kw": kw})
        return FakeProc()

    def run(self, *a, **k):
        raise AssertionError("stage 走到了 subprocess.run —— 测试里不许起真进程")


class FakeShutil:
    """顶掉 shutil：stage 只用 which("tmux") 探本机有没有终端。"""

    def __init__(self, tmux=True):
        self.tmux = tmux
        self.calls: list[str] = []

    def which(self, name):
        self.calls.append(name)
        return "/opt/homebrew/bin/tmux" if self.tmux else None


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload, ensure_ascii=False).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """顶掉 urllib：一条真请求都出不去。

    8770 上住着人正在用的那台 broker，测试打过去就是在碰真舞台；
    registry 自己也有一份 urllib（探活用），一并换掉。
    """

    def __init__(self):
        self.request = types.SimpleNamespace(urlopen=self._urlopen)
        self.error = types.SimpleNamespace(URLError=OSError, HTTPError=OSError)
        self.calls: list[str] = []
        self._fixed = None
        self._queue = None

    def serve(self, status):
        self._fixed, self._queue = status, None

    def serve_sequence(self, items):
        self._fixed, self._queue = None, list(items)

    def _next(self):
        if self._queue:
            item = self._queue.pop(0)
            if not self._queue:
                self._fixed = item
            return item
        return self._fixed

    def _urlopen(self, url, timeout=None):
        self.calls.append(str(url))
        status = self._next()
        if status is None:
            raise OSError(f"connection refused: {url}")
        return FakeResponse(status)


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeHealthSubprocess:
    """顶掉 health 里的 subprocess：自检那一项要 `tmux capture-pane`。

    真跑它会去抓人正在用的那个 frago-stage 会话——读是无害的，但既然规矩是
    「不碰真舞台」，就一条都不碰。
    """

    def __init__(self, returncode=0, boom=None):
        self.returncode = returncode
        self.boom = boom
        self.calls: list[list[str]] = []

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        if self.boom is not None:
            raise self.boom
        return FakeCompleted(self.returncode, stdout="frago@stage ~ %\n")


class FakeAppState:
    """顶掉 app_state：页面状态记下来，不落盘。

    真 publish 会写 ~/.frago/app-state/agent_os/default.json —— 那是人手里
    那张桌面页正在读的文件。
    """

    def __init__(self):
        self.published: list[tuple[str, dict, str]] = []

    def publish(self, name, state, slot="default"):
        self.published.append((name, state, slot))
        return Path("/dev/null")


class Stage:
    """一台全是假货的舞台。属性就是各路通话记录。"""

    def __init__(self, data: Path):
        self.data = data
        self.shutil = FakeShutil()
        self.subprocess = FakeSubprocess()
        self.clock = FakeClock()
        self.net = FakeNet()
        self.app_state = FakeAppState()
        self.opened: list[str] = []
        self.open_ok = True

    @property
    def published(self):
        return self.app_state.published


@pytest.fixture
def st(tmp_path, monkeypatch):
    """摆好一台全是假货的舞台，落点是本用例专属的临时目录。

    每个用例一个新目录：共用一个目录时，前一个用例写下的注册表记录会让后一个
    用例「碰巧通过」，而且是那种改了顺序才暴露的通过。
    """
    data = tmp_path / "landing"
    data.mkdir()
    fake = Stage(data)

    # 落点：顶掉 registry 自己求落点那一步。真的求出来会指向人正在用的台账。
    monkeypatch.setattr(registry, "_instances_dir", lambda: data)

    monkeypatch.setattr(stage, "shutil", fake.shutil)
    monkeypatch.setattr(stage, "subprocess", fake.subprocess)
    monkeypatch.setattr(stage, "time", fake.clock)
    monkeypatch.setattr(stage, "urllib", fake.net)
    monkeypatch.setattr(stage, "app_state", fake.app_state)
    # 注册表探活也走 urllib，一并换掉：真打到 8770 上就是在碰真 broker。
    monkeypatch.setattr(registry, "urllib", fake.net)
    monkeypatch.setattr(health, "subprocess", FakeHealthSubprocess())
    # 自检会扫 ~/.frago/profiles/edge/ 找孤儿 profile。换到落点底下，
    # 免得测试结果被这台机器上真实的 profile 目录左右。
    monkeypatch.setattr(health, "BROWSER_PROFILES_DIR", data / "profiles" / "edge")

    def _open(url):
        fake.opened.append(url)
        return fake.open_ok

    monkeypatch.setattr("frago.viewer.browser.open_url", _open)
    return fake


def item(report, name):
    return next((c for c in report["checks"] if c["item"] == name), None)


def looks_like_path(value, where=""):
    """挑出所有看起来像路径的字符串。判据抄自配方基类的 _refuse_paths。"""
    import re
    pattern = re.compile(r"^(/|~/|\.{1,2}/|[A-Za-z]:[\\/])")
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            out += looks_like_path(v, f"{where}.{k}" if where else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += looks_like_path(v, f"{where}[{i}]")
    elif isinstance(value, str) and pattern.match(value.strip()):
        out.append((where, value[:60]))
    return out


# ── 对外承诺：改了就收不回来 ──────────────────────────────────────────────

def test_content_id_is_stable():
    """桌面页的门牌号。它一变，人手里那个标签页就永远等不到画面。"""
    assert CONTENT_ID == "bc98c2f8114b"
    assert DESKTOP_URL == "http://127.0.0.1:8093/app/agent_os"


def test_landing_spot_name_unchanged():
    """落点名字不能换：369 个片子和台账都挂在 agent_os 这个名字上。"""
    assert registry.DATA_NAME == "agent_os"
    assert stage.APP_NAME == "agent_os"


def test_instances_dir_no_longer_reads_env(monkeypatch):
    """落点自己求，不再等谁用环境变量交代——那份口头约定烂过 4005 次。"""
    monkeypatch.delenv("FRAGO_RECIPE_DATA_DIR", raising=False)
    monkeypatch.setattr(
        "frago.recipes.context.default_identity", lambda **kw: "someone")
    assert registry._instances_dir().name == "agent_os"
    assert registry._instances_dir().parent.name == "recipe-data"


# ── 致命，且零副作用 ──────────────────────────────────────────────────────

def assert_no_side_effects(st: Stage):
    """致命的时候，一件事都不许发生过。"""
    assert st.published == []
    assert st.subprocess.popen == []
    assert st.opened == []
    assert list(st.data.iterdir()) == []


def test_no_tmux_is_fatal_before_anything_else(st):
    st.shutil.tmux = False
    st.net.serve(None)
    with pytest.raises(stage.StageFailed, match="tmux"):
        stage.up()
    assert_no_side_effects(st)


def test_only_default_id_accepted(st):
    st.net.serve(None)
    with pytest.raises(stage.StageFailed, match="stage2"):
        stage.up({"id": "stage2"})
    assert_no_side_effects(st)


def test_actor_mode_has_exactly_two_settings(st):
    st.net.serve(None)
    with pytest.raises(stage.StageFailed) as err:
        stage.up({"actor_mode": "offscreen"})
    msg = str(err.value)
    assert "headless" in msg and "head" in msg
    # offscreen 是撤掉的那一档，MUST 点名，NEVER 悄悄当默认值处理。
    assert "offscreen" in msg
    assert_no_side_effects(st)


# ── 拉 broker ─────────────────────────────────────────────────────────────

def test_live_port_is_reused_without_starting_a_process(st, caplog):
    st.net.serve(LIVE_BROKER)
    with caplog.at_level("INFO", logger="frago.desktop.stage"):
        out = stage.up()
    assert out["success"] is True
    # 两个 broker 抢同一个 tmux 会话会互相 kill。
    assert st.subprocess.popen == []
    assert any("复用" in r.getMessage() for r in caplog.records)
    assert all(u.startswith("http://127.0.0.1:8770/status") for u in st.net.calls)


def test_up_receipt_fields_are_verbatim(st):
    st.net.serve(LIVE_BROKER)
    out = stage.up()
    assert set(out) == UP_FIELDS
    # 地址算式只有一处。localhost 那个串一旦混进来，自检从此每次都报「地址变了」。
    assert out["url"] == DESKTOP_URL
    assert "localhost" not in json.dumps(out, ensure_ascii=False)
    assert out["control"] == "http://127.0.0.1:8770/control"
    assert out["status"] == "http://127.0.0.1:8770/status"
    assert out["content_id"] == CONTENT_ID
    assert out["tmux_session"] == "frago-stage"
    assert set(out["instance"]) == set(registry.IDENTITY_FIELDS)
    assert set(out["runtime"]) == set(registry.RUNTIME_FIELDS)
    assert out["instance"]["desktop_url"] == DESKTOP_URL
    assert (st.data / "default.json").is_file()
    assert out["screen_reused"] is True and out["browser_opened"] is False
    assert st.opened == []


def test_published_state_is_five_render_fields_and_no_path(st):
    st.net.serve(LIVE_BROKER)
    stage.up()
    assert len(st.published) == 1
    name, state, slot = st.published[0]
    assert name == "agent_os"
    assert set(state) == {"brokerWs", "desktop", "uiVersion", "contentId", "instanceId"}
    assert state["brokerWs"] == "ws://127.0.0.1:8770/stream"
    assert state["desktop"] == {"w": 1920, "h": 1080}
    # contentId 是荧幕归属的依据，instanceId 是人读得懂的名字。两个都写，缺一不可。
    assert state["contentId"] == CONTENT_ID
    assert state["instanceId"] == "default"
    assert slot == "default"
    # 页面是前端、模块是后端，前端不碰后端的文件系统。
    assert looks_like_path(state) == []


def test_broker_starts_with_fragos_own_interpreter(st):
    # 第一次探（起之前）没人应答，起完之后第二次探还没就绪，第三次活了。
    st.net.serve_sequence([None, None, LIVE_BROKER])
    out = stage.up()
    assert len(st.subprocess.popen) == 1, "恰好起了一次 broker，不是每秒起一次"
    popen = st.subprocess.popen[0]
    # 从前是 `uv run broker.py`，靠文件头的 PEP 723 块现装依赖。那个块随搬家
    # 去掉了，改由 frago 自己的解释器按模块起。
    assert popen["argv"][0].endswith(("python", "python3", "python3.13"))
    assert popen["argv"][1:3] == ["-m", "frago.desktop.broker"]
    assert popen["kw"]["cwd"] == str(Path(stage.__file__).resolve().parent)
    # broker 不跟着调用方进程一起走。
    assert popen["kw"].get("start_new_session") is True
    assert "env" not in popen["kw"]
    assert popen["kw"].get("stdout") is popen["kw"].get("stderr")
    assert (st.data / "broker.log").is_file()

    cfg = json.loads(popen["argv"][3])
    # 录制机位打开的就是它。不交代的话机位拍的不是舞台，而 record.stop 照常报成功。
    assert cfg["desktop_url"] == DESKTOP_URL
    assert Path(cfg["clips_dir"]).is_relative_to(st.data)
    assert cfg["content_id"] == CONTENT_ID
    assert cfg["ui_version"] == stage.ui_version()
    assert (cfg["port"], cfg["stage_port"], cfg["record_port"]) == (8770, 9222, 9223)
    assert cfg["actor_headless"] is True
    assert out["success"] is True


def test_broker_never_ready_is_fatal_and_names_the_log(st):
    st.net.serve_sequence([None])          # 端口一直没人应答
    with pytest.raises(stage.StageFailed) as err:
        stage.up()
    assert str(st.data / "broker.log") in str(err.value)
    assert len(st.subprocess.popen) == 1, "只起了一次进程，没有反复重起"
    # 等了 90 次，一秒一次，且一秒都没真等。
    assert len(st.clock.sleeps) == 90
    assert set(st.clock.sleeps) == {1}


# ── uiVersion ─────────────────────────────────────────────────────────────

def test_ui_version_is_a_function_of_asset_content(tmp_path, monkeypatch):
    """口径必须是内容，不能是 mtime。

    wheel 里每个条目的时间戳被归一化成固定值，装完之后 mtime 至多是安装时刻——
    两个内容不同的 frago 版本完全可能算出同一个数，而 broker 拿它做**相等**比对，
    一样就当成同一版资产，旧标签的几何照收，画面变形而没有一处报错。
    """
    fake_assets = tmp_path / "assets"
    fake_assets.mkdir()
    (fake_assets / "index.html").write_text("<html>")
    (fake_assets / "app.js").write_text("let a=1")
    monkeypatch.setattr(stage, "ASSETS_DIR", fake_assets)

    first = stage.ui_version()
    # 只碰 mtime，不碰内容：版本号 MUST 不动。
    import os as _os
    _os.utime(fake_assets / "app.js", (1_700_000_000, 1_700_000_000))
    assert stage.ui_version() == first

    # 内容改了：版本号 MUST 动。
    (fake_assets / "app.js").write_text("let a=2")
    assert stage.ui_version() != first

    # 文件名也进哈希：少一个文件、改一个名字，都是资产变了。
    (fake_assets / "app.js").rename(fake_assets / "app2.js")
    assert stage.ui_version() != first


def test_ui_version_survives_a_javascript_round_trip():
    """桌面页把这个数原样带回来比对，超过 2^53 就不再是精确整数。"""
    version = stage.ui_version()
    assert isinstance(version, int)
    assert 0 < version < 2 ** 53


def test_missing_assets_are_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(stage, "ASSETS_DIR", tmp_path / "nope")
    with pytest.raises(stage.StageFailed, match="assets 目录不存在"):
        stage.ui_version()
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(stage, "ASSETS_DIR", empty)
    with pytest.raises(stage.StageFailed, match="一个常规文件都没有"):
        stage.ui_version()


# ── 开不开桌面页 ──────────────────────────────────────────────────────────

def test_probe_must_check_content_id(st):
    """探到的是**别人**那台 broker（primary 是别人的荧幕）→ 不算复用。"""
    st.net.serve({**LIVE_BROKER, "content_id": "ffffffffffff",
                  "clients": [{"primary": True, "contentId": "ffffffffffff",
                               "instanceId": "someone-else"}]})
    out = stage.up()
    assert out["screen_reused"] is False
    assert out["browser_opened"] is True
    assert st.opened == [DESKTOP_URL]


def test_no_screen_attached_opens_a_tab(st):
    st.net.serve(NOBODY)
    out = stage.up()
    assert out["screen_reused"] is False and out["browser_opened"] is True


def test_failing_to_open_is_not_fatal(st, caplog):
    st.net.serve(NOBODY)
    st.open_ok = False
    with caplog.at_level("WARNING", logger="frago.desktop.stage"):
        out = stage.up()
    assert out["success"] is True and out["browser_opened"] is False
    assert any(DESKTOP_URL in r.getMessage() for r in caplog.records)


def test_explicit_open_wins(st):
    st.net.serve(NOBODY)
    out = stage.up({"open": False})
    assert out["browser_opened"] is False and out["screen_reused"] is False
    assert st.opened == [], "open=false 连探都不探"


def test_explicit_open_true_always_opens_a_new_tab(st):
    st.net.serve(LIVE_BROKER)
    out = stage.up({"open": True})
    assert out["browser_opened"] is True and out["screen_reused"] is False
    assert st.opened == [DESKTOP_URL]


# ── 自检 ──────────────────────────────────────────────────────────────────

def test_health_never_raises(st, monkeypatch):
    """某一项自己出错，up 照样成功，那一项标 unavailable，NEVER 当 pass。"""
    monkeypatch.setattr(health, "subprocess",
                        FakeHealthSubprocess(boom=RuntimeError("tmux 炸了")))
    st.net.serve(LIVE_BROKER)
    out = stage.up()
    assert out["success"] is True
    assert item(out["health"], "tmux_session")["level"] == "unavailable"
    assert len(out["health"]["checks"]) == 8
    assert out["health"]["unavailable_count"] >= 1


def test_health_guard_covers_every_check(st, monkeypatch):
    """换一项抛异常，结论一样——_guard 这道网不是只包住了 tmux 那一条。"""
    def boom():
        raise OSError("目录读不了")

    monkeypatch.setattr(health, "check_orphan_profiles", boom)
    st.net.serve(LIVE_BROKER)
    out = stage.up()
    assert out["success"] is True
    assert item(out["health"], "orphan_profiles")["level"] == "unavailable"


def test_health_reads_this_runs_clips_dir_not_the_ledgers(st):
    """老记录里的 clips_dir 可能指着一个早就不存在的目录。

    自检读注册表那条的话，它在查一个空气目录，报「尚未创建（还没录过）」并标 ok
    ——一句错话，而且是自检最不该说的那种错话。
    """
    st.net.serve(LIVE_BROKER)
    registry.ensure_identity("default", desktop_url=DESKTOP_URL,
                             clips_dir="/nowhere/agent-os/clips",
                             tmux_session="frago-stage")
    (st.data / "clips").mkdir()
    (st.data / "clips" / "demo.mp4").write_bytes(b"x" * 10)
    out = stage.up()
    # 身份层永不重算：回执里那份 instance 照旧是台账原文的忠实回声。
    assert out["instance"]["clips_dir"] == "/nowhere/agent-os/clips"
    clips = item(out["health"], "clips")
    assert clips["path"] == str(st.data / "clips")
    assert clips["files"] == 1, "数到的是真片子，不是对着空气报「还没录过」"


def test_mismatched_clips_dir_is_said_out_loud(st, caplog):
    """两条对不上时 MUST 喊出来。

    悄悄换成对的再假装没事，是这条断裂当初能藏三个多月的原因：回执里 instance
    报着登记那天的路径、自检报着真落点，两个字段各说一个地方，而没有任何一层
    说「它俩对不上」。
    """
    st.net.serve(LIVE_BROKER)
    registry.ensure_identity("default", desktop_url=DESKTOP_URL,
                             clips_dir="/nowhere/agent-os/clips",
                             tmux_session="frago-stage")
    with caplog.at_level("WARNING", logger="frago.desktop.stage"):
        stage.up()
    warns = " ".join(r.getMessage() for r in caplog.records)
    assert "台账里登记的录屏落点" in warns
    assert "/nowhere/agent-os/clips" in warns
    assert str(st.data / "clips") in warns
    assert "找素材去后者" in warns
    assert "这个目录已经不存在" in warns


def test_matching_clips_dir_stays_quiet(st, caplog):
    """两条一致时不该喊——狼来了的告警报几次就没人看了。"""
    st.net.serve(LIVE_BROKER)
    (st.data / "clips").mkdir()
    registry.ensure_identity("default", desktop_url=DESKTOP_URL,
                             clips_dir=str(st.data / "clips"),
                             tmux_session="frago-stage")
    with caplog.at_level("WARNING", logger="frago.desktop.stage"):
        stage.up()
    warns = " ".join(r.getMessage() for r in caplog.records)
    assert "台账里登记的录屏落点" not in warns


def test_status_path_warns_too(st, caplog):
    """up 与 status 各调一次，只守住一处等于没守。"""
    st.net.serve(LIVE_BROKER)
    registry.ensure_identity("default", desktop_url=DESKTOP_URL,
                             clips_dir="/nowhere/agent-os/clips",
                             tmux_session="frago-stage")
    with caplog.at_level("WARNING", logger="frago.desktop.stage"):
        stage.status()
    warns = " ".join(r.getMessage() for r in caplog.records)
    assert "台账里登记的录屏落点" in warns


def test_no_desktop_page_is_warned_but_not_fatal(st, caplog):
    st.net.serve({**NOBODY, "ui_ready": False, "layout_reported": False})
    with caplog.at_level("WARNING", logger="frago.desktop.stage"):
        out = stage.up({"open": False})
    assert out["success"] is True
    assert item(out["health"], "ui_ready")["level"] == "warn"
    assert out["health"]["warn_count"] >= 1
    assert out["health"].get("agent_must_respond")
    assert any("桌面页" in r.getMessage() for r in caplog.records)


# ── status ────────────────────────────────────────────────────────────────

def test_status_when_broker_is_unreachable(st):
    st.net.serve(None)                       # 端口上没人
    out = stage.status()
    assert out["broker"]["reachable"] is False
    # 不可达时其余字段一律 null，NEVER 拿 0 或 false 顶上去——「没有客户端连着」
    # 和「问不到」是两件事，补救动作也不同。
    assert all(out["broker"][k] is None for k in (
        "clients", "clients_count", "layout_reported", "ui_ready",
        "frame_age_sec", "actor_viewport", "focus", "windows_open",
        "cdp_ports", "pid", "recording"))
    assert [item(out["health"], n)["level"] for n in
            ("ui_ready", "screen_ownership", "screen_duplicates")] \
        == ["unavailable"] * 3
    assert st.subprocess.popen == []
    # 没有实例记录时 instance / runtime 如实为空，不编。
    assert set(out["instance"]) == set(registry.IDENTITY_FIELDS)
    assert all(v is None for v in out["instance"].values())
    assert out["control"] is None


def test_status_is_read_only(st):
    st.net.serve(LIVE_BROKER)
    registry.ensure_identity("default", desktop_url=DESKTOP_URL,
                             clips_dir=str(st.data / "clips"),
                             tmux_session="frago-stage")
    import os
    registry.mark_running("default", pid=os.getpid(), port=8770)
    before = (st.data / "default.json").read_text()

    out = stage.status()
    assert out["broker"]["reachable"] is True
    assert out["broker"]["clients"] == LIVE_BROKER["clients"]
    assert (out["broker"]["clients_count"], out["broker"]["layout_reported"],
            out["broker"]["ui_ready"]) == (1, True, True)
    assert out["broker"]["recording"] is False
    assert out["broker"]["cdp_ports"] == {"stage": 9222, "record": 9223}
    assert out["control"] == "http://127.0.0.1:8770/control"
    assert st.subprocess.popen == []
    assert st.published == []
    assert st.opened == []

    stage.status()
    assert (st.data / "default.json").read_text() == before


# ══════════════════════════════════════════════════════════════════════
# 以下两节验的是 broker.py，不是 stage.py。
#
# build_app(cfg) 只造对象、挂路由，lifespan 归 uvicorn 跑，所以这里依旧是
# 零进程、零请求。为保险仍把 broker 的 subprocess / urllib 换成会当场炸的
# 假货——哪天有人在 build 期加了一条真调用，测试会喊出来，而不是安静地去碰
# 人正在用的那台舞台。
# ══════════════════════════════════════════════════════════════════════

class ExplodingSubprocess:
    def run(self, *a, **k):
        raise AssertionError(f"broker 在 build 期调了 subprocess.run: {a[:1]}")

    def Popen(self, *a, **k):  # noqa: N802
        raise AssertionError(f"broker 在 build 期调了 subprocess.Popen: {a[:1]}")


class ExplodingNet:
    def _boom(self, url, **k):
        raise AssertionError(f"broker 在 build 期打了真请求: {url}")

    def __init__(self):
        self.request = types.SimpleNamespace(urlopen=self._boom)
        self.error = types.SimpleNamespace(URLError=OSError, HTTPError=OSError)


@pytest.fixture
def sealed_broker(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "subprocess", ExplodingSubprocess())
    monkeypatch.setattr(broker, "urllib", ExplodingNet())
    clips = tmp_path / "broker-clips"
    clips.mkdir()
    return {
        "id": "default", "port": 18770,
        "desktop": {"w": 1920, "h": 1080},
        "browser": {"w": 1280, "h": 800},
        "term": {"cols": 100, "rows": 30},
        "start_url": "about:blank",
        "desktop_url": "http://127.0.0.1:8093/app/agent_os",
        "tmux_session": "test-not-a-real-session",
        "clips_dir": str(clips),
        "stage_port": 19222, "record_port": 19223, "fps": 30,
        "content_id": "test-content", "ui_version": 1,
        "actor_headless": True,
    }


def post_control(cfg, body: dict) -> tuple[int, dict]:
    """拿到 /control 那个 handler 并调它。build_app 不跑 lifespan，世界一动不动。"""
    app = broker.build_app(dict(cfg))
    route = next(r for r in app.routes if getattr(r, "path", None) == "/control")
    resp = asyncio.run(route.endpoint(body))
    return resp.status_code, json.loads(resp.body)


class FakePage:
    """顶掉 broker.page_query / selector_is_valid：记下每一跳问了什么。

    验的正是判型——同一个字符串先被当成什么、不成再当成什么——所以要看的是
    调用序列，不是 JS 长什么样。
    """

    def __init__(self, table=None, valid=None):
        self.table = table or {}
        self.valid = valid or {}
        self.calls: list[dict] = []

    async def query(self, _evaluate, text=None, selector=None, *,
                    frame=False, expand_to=None):
        how = "text" if text is not None else "selector"
        needle = text if text is not None else selector
        self.calls.append({"how": how, "needle": needle, "frame": frame})
        return list(self.table.get((how, needle), []))

    async def valid_selector(self, _evaluate, selector):
        self.calls.append({"how": "valid?", "needle": selector})
        return self.valid.get(selector, True)


@pytest.fixture
def fake_page(monkeypatch):
    def install(table=None, valid=None):
        page = FakePage(table, valid)
        monkeypatch.setattr(broker, "page_query", page.query)
        monkeypatch.setattr(broker, "selector_is_valid", page.valid_selector)
        return page
    return install


HIT = [{"x": 10, "y": 20, "w": 30, "h": 40, "tag": "h1", "text": "Example Domain",
        "reachable": True, "covered_by": None}]


def test_page_ref_forms():
    """判型靠内容，不靠引号——引号在命令行上活不到这一步。"""
    forms = {a: refs.parse_page_ref(a)["form"] for a in
             ('"Example Domain"', "text:Example Domain", "css:.tray-done",
              "Example Domain", "")}
    assert forms == {'"Example Domain"': "quoted", "text:Example Domain": "text",
                     "css:.tray-done": "css", "Example Domain": "bare",
                     "": "empty"}


def test_bare_string_falls_back_to_text(fake_page):
    """命令行 `--ref page:"文字"` 里的双引号被 shell 吃掉，送到这里是裸串。

    旧判据据此判成 CSS 选择器，找不到就报「ref 未命中」——照字面读等于
    「页面上没这个元素」，排查方向从第一步就偏。
    """
    page = fake_page(table={("text", "Example Domain"): HIT})
    found = asyncio.run(broker.page_locate(None, "Example Domain"))
    assert found["matched_by"] == "text" and len(found["hits"]) == 1
    assert [c["how"] for c in page.calls if c["how"] != "valid?"] \
        == ["selector", "text"]
    assert "可见文字" in (found["note"] or "")


def test_selector_hit_never_falls_back(fake_page):
    page = fake_page(table={("selector", "h1"): HIT})
    found = asyncio.run(broker.page_locate(None, "h1"))
    assert found["matched_by"] == "selector"
    assert [c["how"] for c in page.calls] == ["selector"]
    assert found["note"] is None


def test_quoted_form_only_tries_text(fake_page):
    """既有脚本全都在用引号写法，不受影响。"""
    page = fake_page(table={("text", "Example Domain"): HIT})
    found = asyncio.run(broker.page_locate(None, '"Example Domain"'))
    assert found["matched_by"] == "text"
    assert [c["how"] for c in page.calls] == ["text"]


def test_css_prefix_never_falls_back(fake_page):
    """人明说了按选择器找，悄悄按文字命中一个别的元素比直接报错更难查。"""
    page = fake_page(valid={".tray-done": True})
    found = asyncio.run(broker.page_locate(None, "css:.tray-done"))
    assert found["matched_by"] is None
    assert [c["how"] for c in page.calls] == ["selector", "valid?"]


def test_miss_message_separates_the_two_causes(fake_page):
    fake_page(valid={"确认": False})
    found = asyncio.run(broker.page_locate(None, "确认"))
    msg = refs.miss_message("page:确认", found["tried"])
    assert "不是合法选择器" in msg
    assert "shell" in msg and "page:text:" in msg


def test_empty_page_ref_says_so(fake_page):
    fake_page()
    found = asyncio.run(broker.page_locate(None, ""))
    assert "空的" in refs.miss_message("page:", found["tried"])


def test_pointing_and_framing_share_one_judgement(sealed_broker, fake_page):
    """resolve_ref（鼠标/点击）与 camera_target（取景）必须问同样的问题。

    它们曾各抄一份判据，漂移的表现是 mouse to 找得到而 camera focus 找不到。
    """
    page = fake_page()
    post_control(sealed_broker, {"steps": [{"op": "cursor", "ref": "page:确认"}]})
    mouse = [(c["how"], c["needle"]) for c in page.calls if c["how"] != "valid?"]
    page.calls.clear()
    post_control(sealed_broker, {"steps": [{"op": "camera.focus",
                                            "refs": ["page:确认"],
                                            "zoom": 1.8, "ms": 0}]})
    cam = [(c["how"], c["needle"]) for c in page.calls if c["how"] != "valid?"]
    assert mouse == cam == [("selector", "确认"), ("text", "确认")]


OK_STEP = {"op": "say", "text": "。", "ms": 0}
BAD_STEP = {"op": "win", "win": "不存在的窗口", "action": "open"}


def test_batch_all_ok(sealed_broker):
    code, out = post_control(sealed_broker, {"steps": [OK_STEP, OK_STEP]})
    assert code == 200 and out["ok"] is True
    assert [(r["index"], r["status"]) for r in out["results"]] \
        == [(0, "ok"), (1, "ok")]
    assert out["steps"] == {"total": 2, "executed": 2, "failed": 0,
                            "not_reached": 0, "failed_at": None,
                            "on_error": "stop"}


def test_batch_failure_keeps_the_whole_ledger(sealed_broker):
    """原来的 results 到失败那条就断了，看不出是「没轮到」还是「跑了但没记」。"""
    code, out = post_control(sealed_broker,
                             {"steps": [OK_STEP, BAD_STEP, OK_STEP, OK_STEP]})
    assert len(out["results"]) == 4
    assert [r["status"] for r in out["results"]] \
        == ["ok", "failed", "not_reached", "not_reached"]
    assert out["steps"] == {"total": 4, "executed": 1, "failed": 1,
                            "not_reached": 2, "failed_at": 1, "on_error": "stop"}
    assert all("不再执行" in r["why"] for r in out["results"]
               if r["status"] == "not_reached")
    assert code == 500 and out["ok"] is False
    assert out["error"] == out["results"][1]["error"]


def test_closing_step_still_runs(sealed_broker):
    """开录—动线—停录是一个必须闭合的组，漏掉停录留下的是帧目录不回收。"""
    _, out = post_control(sealed_broker,
                          {"steps": [BAD_STEP, OK_STEP, {"op": "record.stop"}]})
    tail = out["results"][-1]
    assert tail["op"] == "record.stop" and tail["status"] != "not_reached"
    assert out["results"][1]["status"] == "not_reached"


def test_on_error_continue(sealed_broker):
    _, out = post_control(sealed_broker,
                          {"steps": [OK_STEP, BAD_STEP, OK_STEP],
                           "on_error": "continue"})
    assert [r["status"] for r in out["results"]] == ["ok", "failed", "ok"]
    assert out["steps"]["on_error"] == "continue"


def test_on_error_only_takes_two_values(sealed_broker):
    code, out = post_control(sealed_broker,
                             {"steps": [OK_STEP], "on_error": "随便写的"})
    assert code == 400 and out["ok"] is False


def test_unknown_op_stops_the_whole_batch(sealed_broker):
    """动词先全查一遍：有一个不认识就整批一步都不执行。"""
    code, out = post_control(sealed_broker,
                             {"steps": [OK_STEP, {"op": "根本没有这个动词"}, OK_STEP]})
    assert code == 400 and out["executed"] == 0 and out["results"] == []
    assert out["unknown_ops"][0]["index"] == 1


# ── frago desktop up：这条路不再绕平台 ────────────────────────────────────
#
# 从前 `up` 是 `frago recipe run agent_os` 起一个子进程。搬进本体之后包里就有
# stage.up()，但这一跳在 Phase 1 里没跟着改——留着的话，旧配方一退役这条路就断，
# 而断的表现是一句「配方没能把舞台拉起来」，指向一个根本不存在的原因。
#
# 这几条验的是接线，不是舞台：stage.up 被顶掉，一个进程都不起。

def test_up_calls_the_stage_in_this_process(monkeypatch):
    """不再有子进程，也不再有 `frago recipe run` 这一跳。"""
    from frago.desktop import aos

    seen = {}

    def fake_up(params=None):
        seen["params"] = params
        return {"success": True, "id": "default", "url": "http://127.0.0.1:8093/app/agent_os"}

    monkeypatch.setattr(stage, "up", fake_up)
    monkeypatch.setattr(aos.subprocess, "run", _refuse_subprocess)

    out = aos.cmd_up({})
    assert out["ok"] is True and out["success"] is True
    assert seen["params"] == {}


def test_up_passes_the_two_flags_through(monkeypatch):
    from frago.desktop import aos

    seen = {}
    monkeypatch.setattr(stage, "up", lambda params=None: seen.setdefault("p", params) or {"success": True})
    monkeypatch.setattr(aos.subprocess, "run", _refuse_subprocess)

    aos.cmd_up({"start-url": "https://example.com", "actor-mode": "head"})
    assert seen["p"] == {"start_url": "https://example.com", "actor_mode": "head"}


def test_a_stage_failure_keeps_its_own_wording(monkeypatch):
    """致命从前经基类信封变成 ok:false，现在由 cmd_up 绑定。措辞一字不改。"""
    from frago.desktop import aos

    def boom(params=None):
        raise stage.StageFailed("本机没有 tmux，舞台终端无法启动")

    monkeypatch.setattr(stage, "up", boom)
    with pytest.raises(aos.Fail) as caught:
        aos.cmd_up({})
    assert caught.value.payload == {
        "ok": False, "error": "本机没有 tmux，舞台终端无法启动",
    }


def test_an_unexpected_crash_is_still_one_line_of_json(capsys, monkeypatch):
    """aos 与 CLI 现在同一个进程，漏网的异常会变成堆栈而不是回执。

    调用方多半拿 json.loads 读 stdout，它看到的会是"命令没有输出"。
    """
    from frago.desktop import aos

    monkeypatch.setattr(aos, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("裂开了")))
    code = aos.main(["status"])
    printed = capsys.readouterr().out
    assert code == 1
    assert len(printed.strip().splitlines()) == 1
    payload = json.loads(printed)
    assert payload["ok"] is False and payload["unexpected"] is True
    assert "裂开了" in payload["error"] and "RuntimeError" in payload["traceback"]


def _refuse_subprocess(*args, **kwargs):
    raise AssertionError(f"up 不该再起任何子进程，却要起: {args!r}")


# ── 停录的读超时：回执不能变成一段堆栈 ────────────────────────────────────
#
# 缺陷的形态：post() 把 180 秒交给 urlopen，读超时抛的是 TimeoutError，而它
# **不是** urllib.error.URLError 的子类，那个 except 分支盖不住。于是长镜头
# 停录时这一层"恒为单行 JSON"的承诺破了：人拿不到片子路径、拿不到自检指标，
# 等这个信号的脚本会一直等下去（2026-09-02 就挂死过一个监听进程）。

class TimingOutNet:
    """顶掉 aos 里的 urllib：/status 照常答，/control 一律读超时。

    只让 /control 超时而 /status 不超时，是因为要验的正是"超时之前先问出
    片名"这一步——两个都超时就分不出回执里的片名是从哪来的。
    """

    def __init__(self, status_payload=None):
        import urllib.request as _real
        self.request = types.SimpleNamespace(urlopen=self._urlopen,
                                             Request=_real.Request)
        self.error = types.SimpleNamespace(URLError=OSError,
                                           HTTPError=_NeverHTTPError)
        self.status_payload = status_payload
        self.timeouts: list[float] = []

    def _urlopen(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/status"):
            if self.status_payload is None:
                raise OSError("status 也答不上来")
            return FakeResponse(self.status_payload)
        self.timeouts.append(timeout)
        raise TimeoutError("timed out")


class _NeverHTTPError(Exception):
    """占位：本用例里不会有 HTTPError，但 post() 要拿它做 except。"""


RECORDING_STATUS = {"recorder": {"recording": True, "clip": "long-take",
                                 "clips_dir": "/tmp/clips-for-test"}}


def _rec(port=8770):
    return {"id": "default", "port": port, "status": "running"}


def test_stop_gets_its_own_generous_timeout(monkeypatch):
    """停录与其余动词不是同一档。

    编码加自检的耗时跟片长走（一条 10 分半的片子实测约 4 分钟），180 秒这个
    定数对停录恒为假。其余动词是毫秒到秒级，照旧走 180。
    """
    from frago.desktop import aos

    net = TimingOutNet(RECORDING_STATUS)
    monkeypatch.setattr(aos, "urllib", net)

    with pytest.raises(aos.Fail):
        aos.post(_rec(), [{"op": "record.stop"}])
    with pytest.raises(aos.Fail):
        aos.post(_rec(), [{"op": "say", "text": "x"}])
    assert net.timeouts == [aos.RECORD_STOP_TIMEOUT, aos.DEFAULT_POST_TIMEOUT]
    # 不许改成无限等：broker 真卡死时那会把调用方一起挂住。
    import math
    assert math.isfinite(aos.RECORD_STOP_TIMEOUT)


def test_stop_timeout_becomes_a_receipt_not_a_traceback(monkeypatch):
    """超时之后人要拿得到：片子叫什么、会落在哪、接下来去哪儿看。"""
    from frago.desktop import aos

    monkeypatch.setattr(aos, "urllib", TimingOutNet(RECORDING_STATUS))
    with pytest.raises(aos.Fail) as caught:
        aos.post(_rec(), [{"op": "record.stop"}])
    p = caught.value.payload
    assert p["ok"] is False and p["timed_out"] is True
    # "还没完"而不是"没成"：帧已经收完了，超时的是等回执这件事。
    assert p["still_encoding"] is True
    assert p["clip"] == "long-take"
    assert p["output"] == "/tmp/clips-for-test/long-take.mp4"
    assert p["contact_sheet"] == "/tmp/clips-for-test/long-take-contact.png"
    assert p["broker_log"] == "/tmp/broker.log"
    assert "轮询" in p["hint"]


def test_stop_timeout_survives_a_broker_that_wont_say_the_clip_name(monkeypatch):
    """问不到片名就留白，NEVER 编一个路径出来——编出来的比没有更坏。"""
    from frago.desktop import aos

    monkeypatch.setattr(aos, "urllib", TimingOutNet(None))
    with pytest.raises(aos.Fail) as caught:
        aos.post(_rec(), [{"op": "record.stop"}])
    p = caught.value.payload
    assert p["timed_out"] is True and p["still_encoding"] is True
    assert "clip" not in p and "output" not in p
    assert "问不到正在录的片名" in p["hint"]


def test_a_plain_read_timeout_is_also_a_receipt(monkeypatch):
    """非停录的读超时同样不许漏成堆栈。"""
    from frago.desktop import aos

    monkeypatch.setattr(aos, "urllib", TimingOutNet(RECORDING_STATUS))
    with pytest.raises(aos.Fail) as caught:
        aos.post(_rec(), [{"op": "sleep", "ms": 1}])
    p = caught.value.payload
    assert p["timed_out"] is True and "still_encoding" not in p
    assert "读超时" in p["error"]


# ── camera down：先核对再报 ───────────────────────────────────────────────
#
# 原来是 close() 之后无条件 return {"ok": True, "closed": True}，而 close()
# 自己把那条 `frago browser -b cdp stop` 整段包在 suppress(Exception) 里。
# 两下一凑，机位还活着这件事三层都不报错，自检里那条"重复荧幕"永远消不掉。

@pytest.fixture
def camera_probe(monkeypatch):
    """把"端口上还剩什么"变成可编排的剧本，一个真进程、一条真请求都不出去。"""
    state = {"procs": [0], "cdp": [False], "closed": 0}

    async def fake_close(_self):
        state["closed"] += 1

    def procs(_port):
        return state["procs"][min(len(state["procs"]) - 1,
                                  state["closed"])]

    def cdp(_port):
        return state["cdp"][min(len(state["cdp"]) - 1, state["closed"])]

    async def gone(_port, _timeout):
        return procs(_port) == 0

    monkeypatch.setattr(broker.StageRecorder, "close", fake_close)
    monkeypatch.setattr(broker, "_actor_processes", procs)
    monkeypatch.setattr(broker, "_cdp_answering", cdp)
    monkeypatch.setattr(broker, "_wait_browser_gone", gone)
    return state


def test_camera_down_admits_it_killed_nothing(sealed_broker, camera_probe):
    """机位早就不在了：端口干净是真的，"这一次杀掉了东西"是假的，两件事分开报。"""
    camera_probe["procs"] = [0]
    camera_probe["cdp"] = [False]
    code, out = post_control(sealed_broker, {"steps": [{"op": "camera.down"}]})
    r = out["results"][0]
    assert code == 200 and r["status"] == "ok"
    assert r["closed"] is True
    assert r["killed"] is False, "什么都没杀就不许说杀了"
    assert "本来就没有机位" in r["note"]


def test_camera_down_reports_a_real_kill(sealed_broker, camera_probe):
    """真收掉了：before 有、after 没有。"""
    camera_probe["procs"] = [1, 0]
    camera_probe["cdp"] = [True, False]
    _, out = post_control(sealed_broker, {"steps": [{"op": "camera.down"}]})
    r = out["results"][0]
    assert r["closed"] is True and r["killed"] is True
    assert r["browser_processes"] == {"before": 1, "after": 0}
    assert r["cdp_answering"] == {"before": True, "after": False}


def test_camera_down_refuses_to_call_a_failure_a_success(sealed_broker,
                                                         camera_probe):
    """杀不掉的时候 MUST 报失败。这正是这条缺陷的本体。"""
    camera_probe["procs"] = [1, 1]
    camera_probe["cdp"] = [True, True]
    code, out = post_control(sealed_broker, {"steps": [{"op": "camera.down"}]})
    assert code == 500 and out["ok"] is False
    r = out["results"][0]
    assert r["status"] == "failed"
    assert "机位没收掉" in r["error"]
    # 只说"不行"是没法自救的：核对结果与下一步动作一并带回去。
    assert r["camera"]["browser_processes"] == {"before": 1, "after": 1}
    assert r["camera"]["cdp_answering"]["after"] is True
    assert "cdp stop" in r["camera"]["how_to_fix"]
