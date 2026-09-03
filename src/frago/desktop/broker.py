"""agent_os 的采集与操控中枢。

它同时是三件事：
  1. 舞台 Chrome 的 CDP 客户端 —— 收 screencast 帧、下发真实输入事件
  2. tmux 会话的轮询器 —— 抓 capture-pane 文本
  3. 一台小服务器 —— WebSocket 把画面推给桌面 UI，HTTP 接受操控指令

桌面 UI 是纯显示器，永远不产生操作；一切真实动作从这里发出，
所以画面里看到的和实际发生的必然一致——这是整个设计的立足点。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from PIL import Image

from . import (
    refs,  # 同包模块，page: 的判型只有这一份，aos 也用它
    registry,  # 同包模块，与 stage.py 共用注册表语义
)

# 演员与机位各是一台独立的无头 CDP 实例，端口分开（2026-08-10 换回来）：
#
# **演员 9222**——`frago browser -b cdp` 的默认端口，profile 是
# `~/.frago/profiles/<浏览器>/9222/`，里面已经攒了一批站点的登录态，换端口就等于
# 让人重新登录一遍。它此前搬进过人日常用的那个浏览器（frago 扩展后端驱动一个真实
# 标签），换回来的直接动因是：扩展只给**前台**标签产帧，演员标签一被切走画面就停，
# 于是那个标签必须一直占着人的屏幕——而这块舞台本来就是为了不占人的屏幕才存在的。
# 无头实例没有前台不前台这回事，帧照产。
#
# **机位 9223**——只是对着桌面页收帧的一台相机，不需要任何登录态，仅在录制期间存在。
# 它必须与演员分开：同一个端口上只有一个实例，机位停录时要 `-b cdp stop` 收走自己，
# 那一下会把演员连同它的登录态一起带走。
#
# 浏览器进程与 profile 一律由 `frago browser -b cdp start` 管理，本文件只连 CDP。
# 扩展后端那套采集能力（capture.screencast_start / capture.cdp）没有撤，它仍在
# frago 那一侧可用，只是舞台不再走它。


def _frago_bin() -> str:
    """只认系统级 frago，绝不用源码 checkout 版（会被"拒绝从源码运行"守卫 exit1）。"""
    def _is_checkout(_fp):
        try:
            _p = Path(_fp).resolve()
        except OSError:
            return False
        if _p.parent.name == "bin" and _p.parent.parent.name == ".venv":
            _root = _p.parent.parent.parent
            if (_root / "pyproject.toml").exists() and (_root / "src" / "frago").is_dir():
                return True
        return False

    _seen: set = set()
    _cands = []
    for _d in os.environ.get("PATH", "").split(os.pathsep):
        if _d:
            _cands.append(str(Path(_d) / "frago"))
    _cands += [
        str(Path.home() / ".local" / "bin" / "frago"),
        "/opt/homebrew/bin/frago",
        "/usr/local/bin/frago",
    ]
    for _c in _cands:
        if _c in _seen:
            continue
        _seen.add(_c)
        if os.path.isfile(_c) and os.access(_c, os.X_OK) and not _is_checkout(_c):
            return _c
    print(
        "⚠️ 找不到系统级 frago（只有源码 checkout 版或未安装），"
        "frago 子命令将失败；请把 frago 装到系统位置（如 ~/.local/bin）",
        file=sys.stderr,
    )
    return "frago"


def _log(msg: str) -> None:
    print(f"[broker] {msg}", file=sys.stderr, flush=True)


class GateError(Exception):
    """开录门禁不通过。

    与 RefError 同构：只说"不让录"是没法自救的，必须把没过的是哪几项、
    每项该敲什么命令一并带回去。门禁是硬拒绝而非警告——playbook 里那两条
    录制纪律以散文形态存在时，实测在同一次会话里各被违反两次（包括在刚刚
    写完反省之后又违反一次）。能被代码拦住的，不该写进文档靠人记。
    """

    def __init__(self, checks: list[dict]):
        super().__init__("开录门禁未通过: "
                         + "、".join(c["item"] for c in checks))
        self.checks = checks


class CameraError(Exception):
    """取景拒绝执行。带上算出来的构图一起抛。

    与 RefError 同构：只说"不行"是没法自救的。倍率越界要说清是清晰度约束
    还是几何约束；目标出框要把取景框和目标矩形都摆出来，让调用方一眼看出
    是该降倍率还是该先把元素挪到画面中间。

    收机位没收干净也走这条：detail 装的是核对结果（端口上还剩几个浏览器主
    进程、CDP 还应不应答），照样落在回执的 camera 字段里。
    """

    def __init__(self, msg: str, detail: dict):
        super().__init__(msg)
        self.detail = detail


class RefError(Exception):
    """ref 解析失败。

    带上当前可寻址元素列表一起抛：调用方拿到"没找到"这三个字是没法自救的，
    它需要知道现在到底有什么可点。绝不退化成坐标点击——那会让一次寻址失败
    伪装成一次成功的操作，故障延后到画面上才暴露。
    """

    def __init__(self, msg: str, available: dict):
        super().__init__(msg)
        self.available = available


# ─────────────────────────── 舞台 Chrome ───────────────────────────


def _dom_has_content(sample: dict) -> bool:
    """DOM 里是否已经渲染出可见内容。

    节点数不是可靠判据：SPA 会先挂一层十几个节点的骨架，文本仍是 0，
    拿节点数当门槛会把骨架误判成"渲染完了"（实测 nodes=17 / len=0）。
    改由探针直接回答——有文本，或有带尺寸的 canvas/svg/img（纯图形页面
    文本本就为 0，不能因此判它没渲染）。
    """
    return bool(sample.get("len")) or bool(sample.get("painted"))


def _running_headful(port: int) -> bool:
    """本端口上是否跑着一个带界面的实例。

    只能从进程命令行读——`frago browser -b cdp status` 不报模式。子进程也带同一个
    端口但参数不全，拿它判会得出错误结论，只认没有 `--type=` 的主进程。

    演员和机位都要问这一句。注意 `frago browser -b cdp start` 本身**不复用**：它默认先
    杀掉端口上已有的实例再起自己的（`kill_existing=True`）。要问的是另一件事——它起出来的
    那台是不是无头。撞上一台有头实例时，若不先停掉再起，人的屏幕上就会多出一扇真窗口，
    而"必须无头"这条约束静默失效，日志里一句异常都没有。
    """
    try:
        out = subprocess.run(
            ["ps", "-Ao", "args"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return False
    for line in out.splitlines():
        if f"remote-debugging-port={port}" not in line or "--type=" in line:
            continue
        return "--headless" not in line
    return False


# 舞台两台浏览器都是 Edge，各占一个 CDP 端口：演员 9222、机位 9223。
#
# **为什么是 Edge**：登录态只能有一份好使的。extension 后端驱动的是 Edge 自己的
# 真实 profile（`~/Library/Application Support/Microsoft Edge`），人平时就在那儿
# 登录；`-b cdp` 的 Edge 实例用 `~/.frago/profiles/edge/<port>/`，首次启动由 frago
# 从那份真实 profile 播种一次（只拷 Local State 与 Default/，跳过锁文件与日志）。
# 于是舞台一起来就带着人已经登过的那批站点，不必再登一遍。
#
# 走 Chrome 那条路已经排除：Chrome Stable 从 v127 起拒绝 `--remote-debugging-port`
# 作用于自己的默认 profile（反侧载加固），只能用隔离拷贝；而隔离拷贝里没有登录态
# ——2026-08-10 实测 `profiles/chrome/9222` 那 641MB 在 x.com / google.com /
# reddit 三站全是游客态。
#
# **品牌仍然显式传 `--browser edge`**，尽管它当前就是默认值：默认值改过一次
# （2026-08-08 从 Chrome 改成 Edge），再改一次舞台就会静默换到另一份 profile，
# 而这种错只在撞上登录墙那一刻才暴露。这是全仓库唯一有理由传 `--browser` 的地方，
# 且只在 CDP 后端成立——默认的 extension 后端下这个参数换不了浏览器，只会让
# profile 目录错位。
#
# **profile 不显式指**：端口推出来的默认目录就是要的那个（9222 → edge/9222），
# 多写一个 `--profile-dir` 只是多一处会漂的重复。
STAGE_BROWSER_BRAND = "edge"


async def _ensure_cdp_instance(port: int, who: str, headless: bool = True) -> None:
    """把这个端口上的 CDP 实例拉到位，模式由调用方点名。

    注意这条路**恒会重起一台**：`-b cdp start` 默认先杀掉端口上已有的实例
    （`kill_existing=True`），没有"已经在跑就复用"这个分支。所以本函数只在
    broker 真正启动那一次被调用——`launch_broker` 探到端口上已有活着的 broker
    就直接返回，压根走不到这里。

    **两种模式的取舍**（2026-08-23 起演员可选，机位仍恒为无头）：

      无头  看不见，但 frago 给它带 `--disable-gpu`，于是**没有 WebGL**。
            纯 HTML/CSS 的页面照录不误，三维场景在里面渲不出来——不是慢，
            是页面停在装配那一步，虚拟浏览器窗口里一片空白。
      有头  一扇真窗口开在人的屏幕上，代价明摆着；换来的是真 GPU。
            演员要演三维内容时只有这一条路。

    中间那档（把窗口挪到屏幕外）已经没有了：它只是给窗口一个 -32000 的坐标，
    macOS 只认进程开的第一扇窗，之后新建的窗口照样落在屏幕上。也就是说它
    从来没兑现过"看不见"，只是让人以为兑现了。

    撞上有头实例时先显式 `-b cdp stop` 再起，不是为了避免重起，是为了让那扇
    真窗口干净地关掉——留着它，人的屏幕上会多出一扇没人管的窗口。
    profile 不受影响：停的是进程，目录里的登录态一个字都不动。
    """
    # **端口上有实例就先显式停掉再等它退干净**，不管它是有头还是无头。
    # 这里曾经只在"旧实例是有头"时才停——理由是要让那扇真窗口干净地关掉。
    # 但真正的风险不在窗口，在 profile 的 Singleton 锁：`-b cdp start` 自己
    # 也是先杀后起，杀完立刻起，同样会撞上锁没释放。2026-08-23 实测，从无头
    # 切到有头正好绕过那个条件，于是竞态原样复现——演员起来几秒后整台浏览器
    # 消失，虚拟浏览器窗口退回一个空白新标签页，而三层回执都说一切正常。
    if await asyncio.to_thread(_cdp_answering, port):
        headful = await asyncio.to_thread(_running_headful, port)
        _log(f"{port} 上已有实例（{'有头' if headful else '无头'}），"
             f"{who}要重起（目标模式：{'无头' if headless else '有头'}），先停掉")
        await asyncio.to_thread(
            subprocess.run,
            [_frago_bin(), "browser", "-b", "cdp", "stop", "--port", str(port)],
            capture_output=True, text=True, timeout=60,
        )
        # **等它真的退干净，不能只 sleep 一个定数。**
        # 旧实例没退净就起新的，新进程撞上 profile 的 Singleton 锁，会把请求
        # 转交给那台正在退出的然后自己退出。表现有两种，都不报错：CDP 迟迟
        # 不上来（演员起不来）；或者 CDP 有应答但应答的是将死的那台，broker
        # 连上去、开好帧流、报"舞台浏览器就绪"，几秒后对面咽气，虚拟浏览器
        # 窗口退回一个空白新标签页。
        # 原来这里是 sleep(1.5)。无头恰好够用，所以这条坑藏了很久；有头退出
        # 要 12 秒上下，改有头演员当天就稳定复现。定数从来不是判据。
        if not await _wait_browser_gone(port, 30.0):
            _log(f"警告：{port} 上的旧浏览器 30 秒后仍在，照常起新的")
    cmd = [_frago_bin(), "browser", "-b", "cdp", "start",
           "--browser", STAGE_BROWSER_BRAND, "--port", str(port)]
    if headless:
        cmd.append("--headless")
    proc = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd[1:])} 失败: {(proc.stderr or proc.stdout)[-400:]}"
        )
    # 起命令返回不等于 CDP 已经挂上——有头实例慢，这里再等一程，
    # 免得下一步拿一个还没就绪的端口去开标签，报一句语焉不详的"未能就绪"。
    if not await _wait_cdp_up(port, 30.0):
        raise RuntimeError(
            f"{who}浏览器起完了但 {port} 上 30 秒内没有 CDP 应答"
        )


def _actor_processes(port: int) -> int:
    """这个端口上还剩几个浏览器主进程。子进程（--type=）不算。"""
    try:
        out = subprocess.run(
            ["ps", "-Ao", "args"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return 0
    return sum(1 for line in out.splitlines()
               if f"remote-debugging-port={port}" in line and "--type=" not in line)


async def _wait_browser_gone(port: int, timeout: float) -> bool:
    """等这个端口上的浏览器**进程**彻底消失。

    判据是进程，不是端口。端口先静默、进程后消失，中间那段窗口正是坑所在：
    老进程还活着就还占着 profile 的 Singleton 锁，这时候起新的，新进程会认为
    已经有实例在跑，把请求转交过去然后自己退出——于是 CDP 迟迟不上来，
    或者上来的是那台将死的。

    **有头浏览器退得很慢**：2026-08-23 实测，从发出 stop 到进程真正消失约 12 秒
    （无头是一两秒）。所以这里的超时给到 30 秒，而不是原来那个 1.5 秒的定数。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await asyncio.to_thread(_actor_processes, port) == 0:
            await asyncio.sleep(1.0)   # 进程没了，再让锁文件一步
            return True
        await asyncio.sleep(0.5)
    return False


async def _wait_cdp_up(port: int, timeout: float) -> bool:
    """等新起的实例把 CDP 端口挂上。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await asyncio.to_thread(_cdp_answering, port):
            return True
        await asyncio.sleep(0.5)
    return False


def _cdp_answering(port: int) -> bool:
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def _broker_alive(port: int) -> bool:
    """这个端口上已经有一台应答得了 /status 的 broker。"""
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/status", timeout=1).read()
        return True
    except Exception:
        return False


# 这些"页面"不是人打开的标签，不该出现在虚拟标签条里，更不该被当成演员。
# 扩展的 offscreen 文档是 page 类型且常常排在真标签前面——2026-08-23 实测
# 一次：演员挑中了 frago 桥扩展的 offscreen.html，于是 navigate 落在一个空
# 文档上、scrollY 恒为 0、一帧都产不出来，而命令、日志、状态三层全部正常。
_NOT_A_TAB = ("chrome-extension://", "devtools://", "edge://extension")


async def _list_pages(port: int) -> list[dict]:
    """这个 CDP 实例当前**属于人的**标签。拿不到就当没有，不抛。"""
    try:
        raw = await asyncio.to_thread(
            lambda: urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=2
            ).read()
        )
        return [t for t in json.loads(raw)
                if t.get("type") == "page"
                and not (t.get("url") or "").startswith(_NOT_A_TAB)]
    except Exception:
        return []


async def _browser_ws(port: int) -> str:
    """浏览器级 CDP 端点。开标签要它——标签级会话开不了新标签。"""
    raw = await asyncio.to_thread(
        lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=5
        ).read()
    )
    return json.loads(raw)["webSocketDebuggerUrl"]


class StageBrowser:
    """驱动一个独立无头 Chrome 实例里的标签页，并把它的画面流出来。

    端口固定 9222——`frago browser -b cdp` 的默认端口，那个 profile 里已经攒了
    一批站点的登录态，换端口等于让人重新登录一遍。

    它此前搬进过人日常用的浏览器（走 frago 扩展后端驱动一个真实标签）。换回
    独立无头实例的直接动因是帧流：扩展只给**前台**标签产帧，演员标签一被切走
    画面就停，于是那个标签必须一直占着人的屏幕。无头实例没有前台这回事，
    页面在后台照样合成，帧照产。
    """

    # 演员标签存活的核对节奏。只在画面已经安静下来之后才去问浏览器：
    # 正常出帧本身就是标签活着的证明，那时候问纯属浪费一次往返。
    VERIFY_INTERVAL = 5.0     # 两次核对之间至少隔这么久
    VERIFY_QUIET_SEC = 8.0    # 画面停够这么久才开始核对

    def __init__(self, port: int, width: int, height: int, start_url: str,
                 headless: bool = True):
        self.port = port
        self.width = width
        self.height = height
        self.start_url = start_url
        # 演员这台浏览器起成无头还是有头。无头看不见但没有 WebGL，
        # 有头占人的屏幕但有真 GPU——要演三维内容就得有头。见
        # _ensure_cdp_instance 的取舍说明。
        self.headless = headless
        self.ws: Any = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        # 演员标签的 CDP targetId（字符串）。CDP 的标签身份就是它，
        # 列表、切换、关闭全部按它对账。
        self.target_id: str | None = None
        # 虚拟标签条的排序账本，按第一次见到的先后记。见 list_tabs：
        # /json/list 给的是最近使用序，直接用它当 tab:<n> 的下标，
        # 随手开一个标签就会让所有既有编号错位。
        self._order: list[str] = []
        self.alive = False
        self.on_frame = None       # async callable(base64_jpeg)
        self.on_nav = None         # async callable(url, loading)
        # 视口读数变化时回调，让上层重算虚拟浏览器窗口的形状。
        self.on_viewport = None    # async callable(w, h, reason)
        self.min_interval = 1 / 30
        self.on_tick = None        # async callable()，每拍调一次，供心跳等搭车
        # 演员标签的存活状态变了就回调，让上层告诉桌面页。
        # 标签没了和页面只是静止在下游看是同一件事——帧不来了——但前者
        # 重开帧流永远不会成功。分不开这两件事，画面就会停在最后一帧，
        # 而任何一层都不会报错。
        self.on_actor_state = None  # async callable(alive: bool, reason: str)
        self.actor_gone = False
        self.actor_gone_reason: str | None = None
        self._last_verify_at = 0.0
        self.latest_frame: str | None = None
        self._sent_frame: str | None = None
        self.last_frame_at: float = 0.0
        self._load_fired = False
        # 视口是**读来的**，不是下过的命令：self.width/height 保存最近一次从演员
        # 标签量到的真实视口。构造入参只是首次读取之前的占位值。
        self.viewport_read_at: float = 0.0
        self.viewport_source: str | None = None

    # ── 生命周期 ──

    async def launch(self) -> None:
        # 浏览器进程与 profile 一律经 frago 的标准入口拉起：profile 固定在
        # ~/.frago/profiles/<浏览器>/<port>/，播种、代理、登录态由 frago 统一管理。
        # 配方不定义 profile 路径、不直接起浏览器进程——那是越权。
        await _ensure_cdp_instance(self.port, "演员", headless=self.headless)
        await self._attach(await self._open_actor_tab())
        # 起始页由这里导航过去：浏览器是 frago 拉起的，argv 不归配方管。
        await self.send("Page.navigate", {"url": self.start_url})
        # 尺寸真值在演员那边：先读它天然的视口，帧流再照这个尺寸开。
        await self.refresh_viewport("实例启动")
        await self.start_stream(30)
        _log(f"舞台浏览器就绪 port={self.port} target={self.target_id} "
             f"视口 {self.width}x{self.height}（读自演员，未覆写）")

    async def _open_actor_tab(self, timeout: float = 40.0) -> dict:
        """**自己开一个标签**当演员，不捡现成的。

        原来这里捡 `/json/list` 的第一个 page。两种坏法都实测到了：

        其一，捡到的可能压根不是标签。frago 桥扩展的 offscreen 文档也是 page
        类型，而且常常排在真标签前面；捡中它之后 navigate 落在一个空文档上，
        一帧都产不出来，而命令、日志、状态三层全部正常，只有画面是错的。
        （这一条现在由 `_list_pages` 的过滤挡住。）

        其二，捡到的标签不归自己管，随时会被别人关掉。浏览器刚起来那几秒，
        frago 的启动清理会关掉"孤儿标签"——不是落地页、不属于任何 group 的
        一律关。broker 捡的正是那个落地页标签，再把它导航到 about:blank，
        于是它当场变成孤儿被关。**无头时看不出来**：无头浏览器没有窗口这回事，
        关掉最后一个标签只是少一个标签；有头时关掉最后一个标签连窗口一起没了，
        演员整个失联。2026-08-23 改用有头演员时这条立刻炸出来，稳定复现。

        自己开的标签两个问题都不存在：身份是自己的，出现时机在清理之后。
        """
        deadline = time.time() + timeout
        created: str | None = None
        with suppress(Exception):
            ws = await websockets.connect(await _browser_ws(self.port),
                                          ping_interval=None)
            try:
                await ws.send(json.dumps({
                    "id": 1, "method": "Target.createTarget",
                    "params": {"url": self.start_url},
                }))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if msg.get("id") == 1:
                        created = (msg.get("result") or {}).get("targetId")
                        break
            finally:
                with suppress(Exception):
                    await ws.close()
        while time.time() < deadline:
            pages = await _list_pages(self.port)
            if created:
                hit = next((t for t in pages if t.get("id") == created), None)
                if hit:
                    _log(f"演员标签由 broker 自己开出 target={created}")
                    return hit
            elif pages:
                # 开标签这条路走不通时的兜底：捡一个真标签，总比没有强。
                _log("开标签失败，退回捡现成标签——它可能被启动清理关掉")
                return pages[0]
            await asyncio.sleep(0.25)
        raise RuntimeError(
            f"演员浏览器（{self.port}）未能就绪——"
            f"`frago browser -b cdp status --port {self.port}` 看它起没起"
        )

    async def _attach(self, page: dict) -> None:
        """连上某个标签的 CDP 会话并把它调成可采集状态。

        launch 与 switch_to 共用这一条。旧连接在新连接建好之后才关，
        中间不留一个"两头都没有"的窗口。
        """
        old = self.ws
        # websockets 默认不发 Origin 头，正好绕开 Chrome 对带 Origin 的调试连接的 403。
        #
        # ping_interval=None 是必须的：默认的保活心跳在 30fps 帧流下会因应答超时
        # 而把连接判死，症状极具迷惑性——浏览器活着、页面也确实跳转了，
        # 只是回执再也送不回来，之后每条命令干等 30 秒超时。
        # 本地 socket 上保活没有任何收益。
        self.ws = await websockets.connect(
            page["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024,
            ping_interval=None,
        )
        self.alive = True
        asyncio.create_task(self._pump(self.ws))
        with suppress(Exception):
            if old is not None:
                await old.close()
        await self._prime_page()
        await self._set_actor_back(page["id"])

    async def _prime_page(self) -> None:
        """把当前附着的标签调成可采集状态。

        视口一个字都不覆写（`Emulation.setDeviceMetricsOverride` 只留给机位）：
        尺寸真值住在演员自己身上，broker 只读它。

        后面那三条是无头浏览器的必需品。无头 Chrome 会把页面判定为不可见而停止
        合成，症状是页面明明加载完了却一帧新画面都不发，画面永远停在白屏；
        手动 scroll 一下又能恢复——正是渲染节流的指纹。
        """
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("DOM.enable")
        for method, params in (
            ("Page.bringToFront", {}),
            ("Page.setWebLifecycleState", {"state": "active"}),
            ("Emulation.setFocusEmulationEnabled", {"enabled": True}),
        ):
            with suppress(Exception):
                await self.send(method, params)

    async def _pump(self, ws: Any) -> None:
        """收 CDP 消息：命令回执唤醒等待者，事件分发出去。

        绑定本连接（入参 ws，不读 self.ws）：切标签之后旧 pump 的收尾
        不得动新连接的状态。
        """
        try:
            async for raw in ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid is not None:
                    fut = self._pending.pop(mid, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                    continue
                method = msg.get("method")
                if method == "Page.screencastFrame":
                    params = msg["params"]
                    # 先 ack 再转发。反过来的话下游一慢就把 Chrome 的发送窗口
                    # 堵死，帧率会阶梯式塌掉。
                    await self.send(
                        "Page.screencastFrameAck",
                        {"sessionId": params["sessionId"]}, wait=False,
                    )
                    # 只记最新帧，绝不在这里 await 广播：下游一慢就会把收消息
                    # 循环卡住，命令回执排在后面读不到，表现为"页面确实跳了却
                    # 报超时"。帧尺寸不校验——没有覆写就没有"目标视口"，
                    # 帧画多大就是演员天然多大。
                    self.latest_frame = params["data"]
                    self.last_frame_at = time.time()
                elif method == "Page.frameStartedNavigating" and self.on_nav:
                    await self.on_nav(msg["params"].get("url", ""), True)
                elif method == "Page.loadEventFired":
                    self._load_fired = True
                    if self.on_nav:
                        await self.on_nav(None, False)
        except Exception as exc:
            _log(f"CDP 连接结束: {type(exc).__name__}: {exc}")
        finally:
            # 若 self.ws 已指向新连接（切标签），这里只是旧连接的谢幕，
            # 全局状态归新 pump 管，不能碰。
            if self.ws is ws:
                self.alive = False
                # 连接一死，所有等待者立刻收到明确错误，而不是各自空等到超时——
                # 超时报出来的是一句没有信息量的空错误，查不出是连接断了。
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(
                            RuntimeError("演员浏览器的 CDP 连接已断开"))
                self._pending.clear()
                # 连接断了不等于标签没了（也可能是浏览器整个被收走）。
                # 究竟是哪一种由 verify_actor 去问 /json/list，这里只把
                # "画面从此不会再来"这件事说出去，免得画面停在最后一帧
                # 假装一切正常。
                await self._set_actor_gone("演员浏览器的 CDP 连接已断开")

    async def verify_actor(self) -> None:
        """定期确认演员标签还在不在，并在它回来时重新附着。

        不把「连接有没有断」当唯一依据：浏览器被别人收走、标签被 Target 域关掉
        这两种情况下连接会静静地断，而下游只看得到"帧不来了"——那正是这套机制
        要消灭的状态。

        只在帧已经停了一段时间之后才问：页面在正常出帧就说明标签必然活着，
        那时候每隔几秒去问一次 /json/list 纯属白费。
        """
        now = time.time()
        if now - self._last_verify_at < self.VERIFY_INTERVAL:
            return
        if not self.actor_gone and (now - self.last_frame_at) < self.VERIFY_QUIET_SEC:
            return
        self._last_verify_at = now
        pages = await _list_pages(self.port)
        if not pages:
            # 整个实例都不在了。这里不自动重拉：重拉要重走导航与帧流，
            # 期间画面是错的，而人此刻多半正在录。说出来交给人决定。
            await self._set_actor_gone(
                f"演员浏览器（{self.port}）不在了——"
                f"`frago desktop down` 再 `frago desktop up` 重起")
            return
        hit = next((p for p in pages if p.get("id") == self.target_id), None)
        if hit is None:
            # 标签没了，但实例还在：接管现有的第一个标签，画面立刻回来。
            # 报错等人来处理的话，舞台会一直停在一张旧帧上。
            hit = pages[0]
            _log(f"演员标签 {self.target_id} 不在了，接管 {hit['id']}")
            await self._attach(hit)
            await self.refresh_viewport("接管新的演员标签")
            await self.start_stream(30)
            return
        if not self.alive:
            # 标签在，连接断了——重连即可。
            await self._attach(hit)
            await self.refresh_viewport("重连演员标签")
            await self.start_stream(30)
            await self.nudge_repaint()
            return
        await self._set_actor_back(hit["id"])

    async def _set_actor_gone(self, reason: str) -> None:
        """标记演员标签失联并通知上层。重复通知没有意义，只报状态变化那一次。"""
        if self.actor_gone:
            return
        self.actor_gone = True
        self.actor_gone_reason = reason
        _log(f"演员标签失联：{reason}")
        if self.on_actor_state:
            with suppress(Exception):
                await self.on_actor_state(False, reason)

    async def _set_actor_back(self, target_id: str) -> None:
        """演员标签重新建立。"""
        was_gone = self.actor_gone
        self.actor_gone = False
        self.actor_gone_reason = None
        self.target_id = target_id
        if target_id not in self._order:
            self._order.append(target_id)
        if was_gone:
            _log(f"演员标签已恢复 target={target_id}")
            if self.on_actor_state:
                with suppress(Exception):
                    await self.on_actor_state(True, "演员标签已恢复")

    async def close(self) -> None:
        with suppress(Exception):
            await self.send("Page.stopScreencast")
        with suppress(Exception):
            if self.ws:
                await self.ws.close()
        self.ws = None
        self.alive = False
        # 浏览器不收：9222 是 `frago browser -b cdp` 的公用实例，profile 里那批
        # 登录态是它存在的理由。停录时收走的是机位（9223），不是这一台。

    # ── 协议 ──

    async def send(self, method: str, params: dict | None = None,
                   wait: bool = True) -> dict:
        """下发一条 CDP 命令。回执就是 CDP 原本的形状。"""
        if not self.alive:
            raise RuntimeError("演员浏览器的 CDP 连接已断开")
        self._msg_id += 1
        mid = self._msg_id
        payload = json.dumps({"id": mid, "method": method, "params": params or {}})
        if not wait:
            await self.ws.send(payload)
            return {}
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(payload)
        return await asyncio.wait_for(fut, timeout=30)

    async def evaluate(self, expression: str) -> Any:
        res = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return res.get("result", {}).get("result", {}).get("value")

    # ── 画面 ──

    async def start_stream(self, fps: int) -> None:
        """开帧流。everyNthFrame 恒为 1，抽稀在下游做。

        踩过的坑：曾按 93fps 裸流除以目标帧率算出 everyNthFrame=3 送给 Chrome，
        结果静态页面一帧都收不到。因为它抽的是"已渲染帧"，而一个加载完就不动的
        页面总共只渲染两三次，三取一正好把仅有的几帧全丢光。
        限流必须发生在有帧可丢的地方，不能发生在源头。
        """
        del fps  # 保留入参形状，实际节流在 pump_frames_forever 里按时间戳做
        await self.send("Page.startScreencast", {
            "format": "jpeg", "quality": 80,
            "maxWidth": self.width, "maxHeight": self.height,
            "everyNthFrame": 1,
        })
        # 助推一次重绘。screencast 只在页面重绘时发帧，而开流那一刻页面往往
        # 已经画完静止了——不推的话首帧永远不来，桌面上的浏览器窗口一直是空的，
        # 且看不出任何报错。
        await self.nudge_repaint()
        _log(f"screencast 已启动 target={self.target_id}")

    async def pump_frames_forever(self) -> None:
        """按目标帧率取当前最新帧发出去。

        取"最新"而不是排队，天然丢掉积压；页面不再重绘时 latest_frame
        停在最后一帧上，下一拍照发不误。
        """
        while True:
            await asyncio.sleep(self.min_interval)
            # 心跳搭这趟车：它无条件每拍都跑，是全程唯一保证在转的循环。
            # 必须在下面的提前 continue 之前调用——页面静止时那个 continue
            # 会跳过整轮。
            if self.on_tick:
                with suppress(Exception):
                    await self.on_tick()
            data = self.latest_frame
            if data is None or data is self._sent_frame or not self.on_frame:
                continue
            self._sent_frame = data
            try:
                await self.on_frame(data)
            except Exception as exc:
                _log(f"帧下发失败: {type(exc).__name__}: {exc}")

    async def nudge_repaint(self) -> None:
        """逼一次重绘。静止页面不重绘就不发帧，画面会停在上一个状态且毫无报错。"""
        with suppress(Exception):
            await self.send("Runtime.evaluate", {"expression": (
                "(()=>{const e=document.documentElement;"
                "e.style.transform='translateZ(0)';"
                "requestAnimationFrame(()=>{e.style.transform='';});"
                "return 1})()")})

    # ── 视口：读，不写 ──
    #
    # 尺寸的真值住在演员标签自己身上——它跟着人那扇真实浏览器窗口走，broker
    # 一个字都不覆写。这条反转掉了此前整套自愈机制存在的理由：既然没人下过
    # 覆写，导航、刷新、debugger 重附着就没有覆写可丢，也就不需要重放、不需要
    # 帧尺寸对账。broker 要做的只剩一件事——把这个尺寸读回来，据它的宽高比
    # 决定虚拟浏览器窗口画多大。

    async def read_viewport(self) -> tuple[int, int, str] | None:
        """读演员标签当前的真实视口，返回 (w, h, 用的是哪条路)。

        主路走 Runtime.evaluate 取 innerWidth/innerHeight：它是全文件里跑得最多、
        最确定能通的一条（导航判定、DOM 探针、元素定位全走它）。
        Page.getLayoutMetrics 语义更准（cssLayoutViewport 不含滚动条），放在
        备用位：主路取不到时才用它。
        """
        with suppress(Exception):
            v = await self.evaluate(
                "({w: window.innerWidth, h: window.innerHeight})")
            if isinstance(v, dict) and v.get("w") and v.get("h"):
                return int(v["w"]), int(v["h"]), "Runtime.evaluate innerWidth"
        with suppress(Exception):
            res = await self.send("Page.getLayoutMetrics", {})
            vp = (res.get("result", {}).get("cssLayoutViewport") or {})
            if vp.get("clientWidth") and vp.get("clientHeight"):
                return (int(vp["clientWidth"]), int(vp["clientHeight"]),
                        "Page.getLayoutMetrics cssLayoutViewport")
        return None

    async def refresh_viewport(self, reason: str) -> dict:
        """重读一次演员视口；变了就把帧流按新尺寸重开。

        帧流的 max_width/max_height 是开流那一刻定死的，视口变了不重开，
        画面仍按旧尺寸缩放送来。
        """
        got = await self.read_viewport()
        if got is None:
            return {"read": False, "reason": reason,
                    "viewport": {"w": self.width, "h": self.height},
                    "note": "读不到演员视口（页面不可执行 JS？），沿用上一次的读数"}
        w, h, source = got
        # 奇数尺寸在录制链路上会被 H.264 拒绝，源头就抹成偶数省得下游补救
        w, h = max(320, w) & ~1, max(240, h) & ~1
        changed = (w, h) != (self.width, self.height)
        self.width, self.height = w, h
        self.viewport_read_at = time.time()
        self.viewport_source = source
        if changed and self.alive:
            with suppress(Exception):
                await self.send("Page.stopScreencast")
            await self.start_stream(30)
            _log(f"演员视口读到 {w}x{h}（{reason}），帧流已按新尺寸重开")
        if changed and self.on_viewport:
            with suppress(Exception):
                await self.on_viewport(w, h, reason)
        return {"read": True, "reason": reason, "changed": changed,
                "viewport": {"w": w, "h": h},
                "aspect_ratio": round(w / h, 4), "source": source}

    def viewport_report(self) -> dict:
        """演员视口现状。它是尺寸真值，虚拟浏览器窗口的形状由它推出来。"""
        return {
            "actor_viewport": {"w": self.width, "h": self.height},
            "aspect_ratio": (round(self.width / self.height, 4)
                             if self.height else None),
            "viewport_source": self.viewport_source,
            "viewport_read_age_sec": (None if not self.viewport_read_at else
                                      round(time.time() - self.viewport_read_at, 2)),
            "frame_age_sec": (None if not self.last_frame_at
                              else round(time.time() - self.last_frame_at, 2)),
        }

    # 帧流的重开不再单独成一条异步路径。演员走扩展后端时它是必需的——扩展的
    # debugger 一 detach 帧流就停，而那条事件到达时正在收消息循环里，不能在
    # 那儿 await。CDP 后端下帧流只会随连接一起断，重开跟重连是同一件事，
    # 归 verify_actor 一处管。

    # ── 标签 ──

    async def list_tabs(self) -> list[dict]:
        """演员浏览器当前的真实标签页列表：id / url / title。

        不做归属过滤——这台实例整个就是虚拟 OS 的，里面没有人的私人标签。
        （演员搬进人日常浏览器的那段时间必须过滤，否则人的邮箱会被镜像进虚拟
        标签条、`tab switch` 还会真的切过去；换回独立实例之后这个问题不存在。）

        **顺序按 _order 记的先后，不用 /json/list 的顺序。** 后者是最近使用序：
        新开一个标签它排第 0，刚切过去的那个也会往前跳——于是 `tab:<n>` 指的是
        谁随时在变，而 tab 是 agent 的寻址方式，编号一跳就是点错标签，
        且回执里看不出任何异常。

        代价要知道：9222 是 `frago browser -b cdp` 的公用端口，别处用它开的标签
        也会出现在这张表里（排在末尾）。想避开就别在舞台跑着的时候用 `-b cdp`
        开标签。
        """
        pages = await _list_pages(self.port)
        by_id = {p.get("id"): p for p in pages}
        # 关掉的标签自然从 by_id 里消失，顺手把账也销了；账本里没有的（别处
        # 开的、或播种 profile 恢复出来的）按发现顺序补在末尾，编号只增不插。
        self._order = [t for t in self._order if t in by_id]
        self._order += [t for t in by_id if t not in self._order]
        return [{"id": t, "url": by_id[t].get("url"), "title": by_id[t].get("title")}
                for t in self._order]

    async def open_tab(self, url: str) -> str:
        """新开一个真实标签并返回它的 targetId。不切过去。"""
        res = await self.send("Target.createTarget", {"url": url})
        tid = res.get("result", {}).get("targetId")
        if not tid:
            raise RuntimeError(f"开标签失败: {res}")
        if tid not in self._order:
            self._order.append(tid)
        return tid

    async def close_tab(self, target_id: str) -> None:
        await self.send("Target.closeTarget", {"targetId": target_id})
        self._order = [t for t in self._order if t != target_id]

    async def switch_to(self, target_id: str) -> None:
        """把采集与输入切到另一个真实标签：换 CDP 连接、重开帧流。"""
        pages = await _list_pages(self.port)
        hit = next((p for p in pages if p.get("id") == target_id), None)
        if hit is None:
            raise ValueError(f"标签不存在: {target_id}")
        await self._attach(hit)
        self._load_fired = True
        # 换了一个标签就是换了一个视口真值：先读它，再按这个尺寸开帧流。
        await self.refresh_viewport("切换演员标签")
        await self.start_stream(30)

    # ── 导航 ──

    async def navigate(self, url: str, wait: bool = True,
                       timeout: float = 30.0) -> dict:
        """导航，并默认等到画面真的换了才返回。

        不等就往下走的话，录制全靠 sleep 猜加载时间——猜短了就把白屏录进片子，
        而这种失败只有回看成片时才发现。等待分两步：先等页面就绪，再等一帧新
        画面到达（渲染结果真的传过来了）。两者缺一都可能录到空白。

        "是否加载完"两条判据并用：`Page.loadEventFired` 是 CDP 的原生信号，
        轮询 `document.readyState` 兜底。留着兜底那条是因为它在演员走扩展后端
        的那段时间是唯一可用的判据（扩展只转发 screencastFrame），而它本身就
        是可观测信号，不是 sleep 猜时间——留着不亏。
        """
        self._load_fired = False
        # 基准帧必须在导航发出**之前**取。取在加载完之后的话，渲染快的页面
        # 早就画完并发了帧，之后再无新帧，于是永远等不到"下一帧"，空转到超时。
        before = self.latest_frame
        await self.send("Page.navigate", {"url": url})
        if not wait:
            return {"waited": False}
        deadline = time.time() + timeout
        loaded = False
        nudged = False
        while time.time() < deadline:
            if not loaded:
                if self._load_fired:
                    loaded = True
                else:
                    state = None
                    with suppress(Exception):
                        state = await self.evaluate("document.readyState")
                    loaded = state == "complete"
            if loaded and self.latest_frame is not before:
                break
            # 导航之后不再有覆写可丢，所以这里不重放任何尺寸。仍要逼一帧：
            # 新页面画完就静止时 screencast 无帧可发，画布会停在上一个页面上，
            # 地址栏换了画面没换，极具误导性。
            if loaded and not nudged:
                nudged = True
                await self.nudge_repaint()
            await asyncio.sleep(0.08)
        settle = await self._settle_dom(deadline)
        # 页面重排可能改变可用视口（比如新页面带了不同的滚动条），读一次。
        vp = await self.refresh_viewport(f"导航完成 {url}")
        if self.on_nav:
            with suppress(Exception):
                await self.on_nav(None, False)
        return {"waited": True, "loaded": loaded,
                "repainted": self.latest_frame is not before,
                "viewport": vp.get("viewport"),
                "viewport_changed": vp.get("changed"), **settle}

    async def _settle_dom(self, deadline: float,
                          stable_needed: int = 3, interval: float = 0.12) -> dict:
        """加载完之后再等 DOM 长稳，客户端渲染的页面此刻往往还是空的。

        实测：http://127.0.0.1:8093/ 的 load 与首帧都到齐了，body 文本却只有
        6 个字符——框架还没挂载。紧接着的 ref 解析于是随机落空，而回执看上去
        一切正常。这违反"效果落定即返回"。

        判据用可观测信号，不是固定 sleep：连续采样文本长度与节点数，连着
        stable_needed 次不再增长才算稳。超时不算失败，如实回报 settled=False。
        """
        js = ("(()=>{const b=document.body;"
              "const vis=[...document.querySelectorAll('canvas,svg,img')]"
              ".some(e=>e.getBoundingClientRect().width>1);return{"
              "len:b?(b.innerText||'').length:0,painted:vis,"
              "nodes:document.getElementsByTagName('*').length};})()")
        stable = 0
        samples = 0
        last: dict | None = None
        while time.time() < deadline:
            cur = None
            with suppress(Exception):
                cur = await self.evaluate(js)
            samples += 1
            if not isinstance(cur, dict):
                # 探针不通（页面还在换、或不许执行 JS）——不能算稳，重新计数。
                stable = 0
                await asyncio.sleep(interval)
                continue
            # 空 DOM 不是合法终态。框架挂载得比采样间隔更慢时，连续几次读到
            # 同一个 0 会被误判成"稳了"——实测录制中真的发生过：navigate 报
            # settled=True 而文本长度为 0，随后 ref 解析全部落空，click 掉进
            # 终端窗口，而回执一路显示正常。复现率低，一旦踩中排查代价极高。
            if not _dom_has_content(cur):
                stable = 0
                last = cur
                await asyncio.sleep(interval)
                continue
            if last is not None and cur == last:
                stable += 1
                if stable >= stable_needed:
                    last = cur
                    break
            else:
                stable = 0
            last = cur
            await asyncio.sleep(interval)
        settled = stable >= stable_needed
        out: dict = {"settled": settled, "settle_samples": samples}
        if isinstance(last, dict):
            out["settle_text_len"] = last.get("len")
            out["settle_nodes"] = last.get("nodes")
        if not settled:
            empty = isinstance(last, dict) and not _dom_has_content(last)
            out["settle_note"] = (
                "超时前 DOM 始终为空——页面已加载但未渲染出任何内容，"
                "此时 ref 解析必然落空，不要据此往下走"
                if empty else
                "超时前 DOM 仍在变化，读数是最后一次采样"
            )
        return out

    # ── 输入 ──

    async def mouse(self, kind: str, x: float, y: float, button: str = "left") -> None:
        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": kind,
                "x": x,
                "y": y,
                "button": button if kind != "mouseMoved" else "none",
                "clickCount": 1 if kind != "mouseMoved" else 0,
            },
        )

    async def insert_text(self, text: str) -> None:
        await self.send("Input.insertText", {"text": text})

    async def key(self, key_name: str) -> None:
        spec = {
            "Enter": ("Enter", 13, "\r"),
            "Tab": ("Tab", 9, None),
            "Escape": ("Escape", 27, None),
            "Backspace": ("Backspace", 8, None),
            "ArrowDown": ("ArrowDown", 40, None),
            "ArrowUp": ("ArrowUp", 38, None),
        }.get(key_name)
        if not spec:
            raise ValueError(f"不支持的按键: {key_name}")
        code, vk, text = spec
        base = {"key": code, "code": code, "windowsVirtualKeyCode": vk}
        await self.send("Input.dispatchKeyEvent", {"type": "keyDown", **base,
                                                   **({"text": text} if text else {})})
        await self.send("Input.dispatchKeyEvent", {"type": "keyUp", **base})


# ─────────────────────────── 舞台终端 ───────────────────────────


def _split_lines(text: str) -> list[str]:
    """capture-pane 的输出切成行。

    末尾那个换行不算一行——空输出是一个单独的 "\\n"，直接 split 会得到一行
    空字符串，缓冲区里就凭空多出一行。
    """
    rows = text.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    return rows


class StageTerminal:
    """一个专供录制的 tmux 会话，按窗口尺寸开，画面靠轮询抓。

    抓的是**历史 + 当前屏**两段，不是只有当前屏。pane 有多高，是虚拟终端
    窗口装得下多少行说了算（见 resize），所以命令输出一长，前面的内容就滚进
    tmux 的 history 里去了。那份内容一直都在，只是从前没人去取——于是画面上
    永远只剩最后一屏，回看不了，录制时每条长输出都只剩个尾巴。

    历史是追加式的，所以只在它变长的时候取新增那几行；tmux 自己数着
    ``#{history_size}``，那就是现成的增量锚点。每轮全量重取等于把同样的
    几千行每秒重抓八遍。当前屏则每轮整段替换——它本来就会被就地改写
    （提示符、进度条、全屏 TUI）。
    """

    # 缓冲区上限。tmux 自己的 history-limit 默认 2000，这里取 4000 是留出
    # "tmux 已经丢掉、这边还留着"的余量：这块缓冲区存在的意义就是回看。
    MAX_LINES = 4000

    def __init__(self, session: str, cols: int, rows: int):
        self.session = session
        self.cols = cols
        self.rows = rows
        self.on_text = None       # async callable(payload: dict)
        self._last = None         # 当前屏原文（带 SGR），detail 回执用
        self._seq = 0
        # 缓冲区分两段：history 只追加、screen 每轮整段替换。
        # 合起来才是"完整内容"，也才是桌面页那扇窗口能滚动回看的东西。
        self.history: list[str] = []
        self.screen: list[str] = []
        self.dropped = 0          # 超出 MAX_LINES 从头部丢掉的行数
        self._hist_size = 0       # 上一轮 tmux 报的 history 行数
        self._resync = True       # 下一轮整段重取（首轮、resize、history 被清）

    # ── 缓冲区 ──

    @property
    def total(self) -> int:
        """至今产生过的总行数（含已从头部丢掉的）。行号的绝对基准。"""
        return self.dropped + len(self.history) + len(self.screen)

    def buffer_lines(self) -> list[str]:
        """整个缓冲区，带 SGR。"""
        return self.history + self.screen

    def plain_lines(self) -> list[str]:
        """整个缓冲区，纯文本。寻址、取景、比对一律用这一份。"""
        return [_plain(x) for x in self.buffer_lines()]

    def snapshot(self) -> dict | None:
        """整段现状，补发给后连上来的客户端（机位就是这种客户端）。

        给它增量没有意义——它手上一行都没有。
        """
        if not self.history and not self.screen:
            return None
        return {"seq": self._seq, "base": self.dropped, "from": self.dropped,
                "lines": self.buffer_lines(), "total": self.total}

    def _tmux(self, *args: str) -> str:
        return subprocess.run(
            ["tmux", *args], capture_output=True, text=True, check=True
        ).stdout

    async def launch(self) -> None:
        exists = subprocess.run(
            ["tmux", "has-session", "-t", self.session],
            capture_output=True,
        ).returncode == 0
        if exists:
            # 复用会跳过尺寸设定、并继承上一次的残留输出，录出来的第一帧
            # 就带着上轮的脏东西。宁可重开。
            await asyncio.to_thread(self._tmux, "kill-session", "-t", self.session)
        await asyncio.to_thread(
            self._tmux, "new-session", "-d", "-s", self.session,
            "-x", str(self.cols), "-y", str(self.rows),
        )
        await asyncio.to_thread(
            self._tmux, "send-keys", "-t", self.session, "clear", "Enter"
        )
        self.history, self.screen = [], []
        self.dropped, self._hist_size = 0, 0
        self._resync = True
        _log(f"tmux 会话 {self.session} 就绪 {self.cols}x{self.rows}")

    def _capture(self) -> tuple[int, list[str]]:
        """一次 tmux 调用同时取回 history 行数与当前屏。

        分两次调用的话，中间那一瞬输出正好滚了一行，取回的行数与屏幕就对不上
        账——缓冲区会重复或漏掉那一行，而这种错在画面上只是"有一行怪怪的"。
        """
        out = self._tmux(
            "display-message", "-p", "-t", self.session, "#{history_size}",
            ";", "capture-pane", "-e", "-p", "-t", self.session,
        )
        head, _, body = out.partition("\n")
        try:
            hist = int(head.strip())
        except ValueError:
            hist = 0
        return hist, _split_lines(body)

    def _capture_history(self, count: int) -> list[str]:
        """可见屏之上的历史行；count <= 0 取全部。

        坐标是 tmux 的：0 是可见屏第一行，负数往历史里数，所以"刚滚出去的
        那 count 行"就是 -count 到 -1。
        """
        start = "-" if count <= 0 else f"-{count}"
        return _split_lines(self._tmux(
            "capture-pane", "-e", "-p", "-t", self.session,
            "-S", start, "-E", "-1",
        ))

    def _trim(self) -> None:
        """超上限就从头部丢，丢了多少如实记进 dropped。

        丢的只可能是历史里最老的一段；当前屏永远留着，它是"现在"。
        """
        excess = len(self.history) + len(self.screen) - self.MAX_LINES
        if excess > 0:
            excess = min(excess, len(self.history))
            del self.history[:excess]
            self.dropped += excess

    def _refresh(self) -> dict | None:
        """抓一轮。返回要推给荧幕的增量，没有变化就返回 None。"""
        hist_size, screen = self._capture()
        # history 变短只有两种来路：会话被重开，或有人 clear-history。
        # 增量锚点这时是错的，整段重来。
        resync = self._resync or hist_size < self._hist_size
        changed_from: int | None = None
        if resync:
            self.history = self._capture_history(0) if hist_size else []
            self.dropped = 0
            self._resync = False
            changed_from = 0
        elif hist_size > self._hist_size:
            # 刚滚出可见屏的那几行。它们是追加上去的，前面的内容一个字没动。
            changed_from = self.dropped + len(self.history)
            self.history.extend(self._capture_history(hist_size - self._hist_size))
        self._hist_size = hist_size

        screen_start = self.dropped + len(self.history)
        if changed_from is None and screen == self.screen:
            return None
        self.screen = screen
        self._last = "\n".join(screen)
        if changed_from is None:
            changed_from = screen_start
        self._trim()
        changed_from = max(changed_from, self.dropped)
        self._seq += 1
        return {"seq": self._seq, "base": self.dropped, "from": changed_from,
                "lines": self.buffer_lines()[changed_from - self.dropped:],
                "total": self.total}

    async def poll_forever(self, interval: float = 0.12) -> None:
        while True:
            try:
                payload = await asyncio.to_thread(self._refresh)
                if payload and self.on_text:
                    await self.on_text(payload)
            except Exception as exc:
                _log(f"capture-pane 失败: {exc}")
            await asyncio.sleep(interval)

    def alive(self) -> tuple[bool, str]:
        """会话此刻还在不在，判据是 capture-pane 真的取得到画面。

        2026-07-24 撞到的形态：`frago desktop down` 在 broker 已失联时返回 None 且没真停，
        下一次 up 复用了这个半死的 broker——它连着 8770、能应答 /status，
        却从没走过建 tmux 会话那一步，于是终端窗口全程空白，只在 broker.log 里
        每 0.12 秒刷一条 `capture-pane 失败`。/status 完全看不出来，
        因为 ui_ready 只反映浏览器画面帧、根本不管终端。

        用 capture-pane 而不是 has-session：前者是终端画面链路的端到端检验，
        后者只答"有这么个名字"。
        """
        try:
            proc = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", self.session],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except Exception as exc:  # noqa: BLE001 tmux 不在也算不可用
            return False, f"{type(exc).__name__}: {exc}"
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout).strip() or "capture-pane 失败"
        return True, f"capture-pane 取到 {len(proc.stdout.splitlines())} 行"

    async def resize(self, cols: int, rows: int) -> bool:
        """把 tmux 网格改成窗口真正装得下的尺寸。

        两边各定各的会让终端显示一个装不进自己窗口的网格，右侧内容被硬切掉——
        现实里没有终端是这样的。尺寸由 UI 按字符格子实测算出，这里只负责落实。

        改完必须整段重取：tmux 会按新宽度重排，历史与可见屏的分界线跟着动，
        `history_size` 那个增量锚点在这一刻是错的。不重取的话，缓冲区会从
        改尺寸那一行起错位，而错位之后每一帧看起来都很正常。
        """
        if (cols, rows) == (self.cols, self.rows):
            return False
        self.cols, self.rows = cols, rows
        await asyncio.to_thread(
            self._tmux, "resize-window", "-t", self.session,
            "-x", str(cols), "-y", str(rows),
        )
        self._resync = True
        _log(f"终端网格改为 {cols}x{rows}")
        return True

    async def send_text(self, text: str) -> None:
        await asyncio.to_thread(
            self._tmux, "send-keys", "-t", self.session, "-l", text
        )

    async def send_key(self, key_name: str) -> None:
        await asyncio.to_thread(
            self._tmux, "send-keys", "-t", self.session, key_name
        )

    async def close(self) -> None:
        with suppress(Exception):
            await asyncio.to_thread(self._tmux, "kill-session", "-t", self.session)


# ─────────────────────────── 运镜（取景框） ───────────────────────────
#
# 词表此前全是"在世界里做事"——鼠标、窗口、终端、浏览器、录制，唯独没有
# **怎么看这个世界**。景别是镜头语言的基本盘，缺了它 agent 没有任何指令能表达
# "这一镜是特写"，只能录完之后在后期靠目测填 `crop=宽:高:x:y`，凭一张缩略图猜
# 元素在哪。而这套系统里元素的真实坐标本来就是一手数据（`frago desktop elements` 给矩形，
# broker 有页面坐标到桌面坐标的换算），手填坐标等于把一手数据丢掉再去猜，
# 与 spec 第 6 节"不做视觉识别、位置是一手数据"直接相反。
#
# **取景不能靠 CDP**（2026-07-24 实测）：录制机位走 `Page.startScreencast`，
# screencast 只有 `maxWidth/maxHeight`，**不吃 `clip` 参数**。所以取景必须做在
# broker 收到帧、落盘之前——按当前取景框裁那一帧。好处是 focus/pan/reset 全部
# 退化成"改一组参数"，帧管线本身一个字都不用动。
#
# 取景框由两个量描述：**中心**（桌面坐标）与**倍率**。三个动词只是关键帧给法
# 不同，插值内核是同一套：
#
#   focus  倍率 1 → k，中心 桌面正中 → 元素中心
#   pan    倍率不变，中心 当前 → 目标元素中心
#   reset  倍率 当前 → 1，中心 当前 → 桌面正中
#
# 所以 reset 与 focus 之间的过渡天然就是一次推拉镜，不需要第四个动词。

# 倍率下限 1.0：即原始镜头，拍的是整个虚拟桌面。低于 1 意味着要拍桌面之外的
# 区域，那里什么都没有，只有黑边。
ZOOM_MIN = 1.0
# 倍率上限 2.5：这是**清晰度**约束，不是几何约束。桌面页按 1920×1080 渲染，
# 推 2 倍就是把 960×540 那块拉满全屏，信息量只有一半。想要真正清晰的特写，
# 得让虚拟浏览器窗口本身更大让页面重排，那是录制前的事，不是镜头的事。
ZOOM_MAX = 2.5

# 居中判定的容差（桌面像素）。实测浮点误差会让 offset 剩 0.1px 时仍报 false，
# 而 0.1 像素的偏差在 1080p 上不存在可见形态——那是一条永远为假的判据。
CENTER_TOL = 1.0

# 多目标取景时外接矩形四周留的安全边距（桌面像素）。贴着边框切等于把元素
# 焊在画面边上，看起来像没框全。
FRAME_MARGIN = 40

FOCUS_DEFAULT_MS = 1200
PAN_DEFAULT_MS = 2000
RESET_DEFAULT_MS = 1200


def _ease_in_out_cubic(t: float) -> float:
    """起止柔和的缓动。

    匀速推拉看起来像机器在拉尺子，不像人在运镜——起步和落位那两下的加速度
    才是"有人在扶着机器"的全部信号。
    """
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    if t < 0.5:
        return 4 * t * t * t
    return 1 - ((-2 * t + 2) ** 3) / 2


class Camera:
    """取景框。中心 + 倍率两个量，逐帧插值，三个动词共用。

    它只影响**落盘的录制帧**，不影响桌面页上人看到的画面：桌面页是荧幕，
    摄像机对着荧幕拍，改的是摄像机怎么取景，不是荧幕上放什么。这也是为什么
    不录制时 `camera focus` 是一条纯预演指令——它照样算出会不会 clamp，
    让调用方在**录制前**就发现"这个元素在 2 倍下没法居中"。
    """

    def __init__(self, dw: int, dh: int):
        self.dw = float(dw)
        self.dh = float(dh)
        self.center = (self.dw / 2, self.dh / 2)
        self.zoom = 1.0
        self._anim: dict | None = None

    # ── 几何：全部可在动之前算出来 ──

    def frame_of(self, cx: float, cy: float,
                 zoom: float) -> tuple[float, float, float, float, list[str]]:
        """取景框矩形（桌面坐标）与它被夹在哪几条边上。

        元素靠近桌面边缘时，取景框移到边界也无法让它完全居中——这不是失败，
        画面确实拍到了、构图可用，只是没能完全居中。夹在哪条边一并回报。
        """
        cw = self.dw / zoom
        ch = self.dh / zoom
        x = cx - cw / 2
        y = cy - ch / 2
        clamped: list[str] = []
        if x < 0:
            x = 0.0
            clamped.append("left")
        elif x + cw > self.dw:
            x = self.dw - cw
            clamped.append("right")
        if y < 0:
            y = 0.0
            clamped.append("top")
        elif y + ch > self.dh:
            y = self.dh - ch
            clamped.append("bottom")
        return x, y, cw, ch, clamped

    def framing(self, cx: float, cy: float, zoom: float,
                rect: dict | None = None) -> dict:
        """三档反馈。**贴边算成功，不算失败。**

        报成失败会逼调用方处理一个不用处理的情况；但静默居中失败更糟——
        那正是 2026-07-24 翻车的模式：以为对准了，实际没对上。

        1. 完全居中          centered=true
        2. 贴边受限          centered=false + clamped + offset，元素仍在画面内
        3. 元素出框          ok=false（倍率太高，或元素本身比取景框还大）

        刻意**不提供** min_zoom_centered 这类"提高倍率就能居中"的建议：数学上
        成立但结论荒谬——左贴边元素要推到 5.33 倍才能居中，那时取景框只剩
        360×203，上下文全切掉，而且 1080p 素材推 5 倍糊得没法看。贴边元素的
        正解是**让它别贴边**，见下面 hint。
        """
        x, y, cw, ch, clamped = self.frame_of(cx, cy, zoom)
        fcx, fcy = x + cw / 2, y + ch / 2
        off = {"x": round(cx - fcx, 2), "y": round(cy - fcy, 2)}
        centered = abs(off["x"]) <= CENTER_TOL and abs(off["y"]) <= CENTER_TOL
        out: dict = {
            "zoom": round(zoom, 4),
            "center": {"x": round(cx, 1), "y": round(cy, 1)},
            "frame": {"x": round(x, 1), "y": round(y, 1),
                      "w": round(cw, 1), "h": round(ch, 1)},
            "centered": centered,
            "offset": off,
        }
        if clamped:
            # clamped 恒为数组，不因为"只夹了一条边"就退化成字符串：角落里的
            # 元素真的会同时夹住两条边，只报一条是撒谎；而同一字段一会儿是
            # 字符串一会儿是数组，正是本项目语法约束要挡的那种形状不一致。
            out["clamped"] = clamped
            out["hint"] = (
                "元素贴着桌面边缘，取景框移到边界也无法让它完全居中。"
                "画面拍到了、构图可用，这不算失败。真要居中就让它别贴边："
                "把虚拟浏览器窗口挪到桌面中间（window move --target browser），"
                "或滚动页面让元素落到视口中部（browser scroll），然后 1.5–2 倍就够。"
                "不要靠提高倍率去凑居中——那会把上下文全切掉且画面糊掉。"
            )
        if rect is not None:
            inside = (rect["x"] >= x - 0.5 and rect["y"] >= y - 0.5
                      and rect["x"] + rect["w"] <= x + cw + 0.5
                      and rect["y"] + rect["h"] <= y + ch + 0.5)
            out["target_rect"] = {k: round(float(rect[k]), 1) for k in "xywh"}
            out["target_in_frame"] = inside
            if not inside:
                out["why_out"] = (
                    f"目标矩形 {int(rect['w'])}×{int(rect['h'])} 装不进 {zoom:g} 倍下的"
                    f"取景框 {int(cw)}×{int(ch)}"
                    if (rect["w"] > cw or rect["h"] > ch) else
                    f"{zoom:g} 倍下取景框被夹在桌面边界（{'/'.join(clamped)}），"
                    "目标落到了框外"
                )
        return out

    def fit_zoom(self, rect: dict) -> float:
        """能把这个矩形（含安全边距）整个装下的最大倍率。"""
        w = rect["w"] + FRAME_MARGIN * 2
        h = rect["h"] + FRAME_MARGIN * 2
        if w <= 0 or h <= 0:
            return ZOOM_MAX
        return min(self.dw / w, self.dh / h)

    # ── 时间：逐帧插值 ──

    def animate(self, center: tuple[float, float], zoom: float, ms: int) -> None:
        c0 = self.center
        z0 = self.zoom
        self.center = (float(center[0]), float(center[1]))
        self.zoom = float(zoom)
        if ms <= 0:
            self._anim = None
            return
        # 两个量**同步**插值：倍率和中心同时走，合起来就是一次推拉镜。
        self._anim = {"t0": time.time(), "dur": ms / 1000.0,
                      "c0": c0, "z0": z0,
                      "c1": self.center, "z1": self.zoom}

    def state(self) -> tuple[float, float, float]:
        """此刻的 (cx, cy, zoom)。动画走完自动落到终点并把关键帧丢掉。"""
        a = self._anim
        if a is None:
            return self.center[0], self.center[1], self.zoom
        t = (time.time() - a["t0"]) / a["dur"]
        if t >= 1:
            self._anim = None
            return self.center[0], self.center[1], self.zoom
        k = _ease_in_out_cubic(t)
        return (a["c0"][0] + (a["c1"][0] - a["c0"][0]) * k,
                a["c0"][1] + (a["c1"][1] - a["c0"][1]) * k,
                a["z0"] + (a["z1"] - a["z0"]) * k)

    def box_now(self) -> tuple[float, float, float, float] | None:
        """此刻该裁的矩形（left, upper, right, lower），原始镜头返回 None。

        返回 None 时整条裁剪路径被跳过——不推近的镜头一个像素都不重采样，
        帧原样落盘，成本与改动之前完全一致。
        """
        cx, cy, zoom = self.state()
        if self._anim is None and zoom <= 1.0 + 1e-9:
            return None
        x, y, cw, ch, _ = self.frame_of(cx, cy, zoom)
        return (x, y, x + cw, y + ch)

    def report(self) -> dict:
        cx, cy, zoom = self.state()
        return {"center": {"x": round(cx, 1), "y": round(cy, 1)},
                "zoom": round(zoom, 4),
                "moving": self._anim is not None,
                "desktop": {"w": int(self.dw), "h": int(self.dh)},
                "zoom_bounds": {"min": ZOOM_MIN, "max": ZOOM_MAX}}


def _reframe_jpeg(raw: bytes, box: tuple[float, float, float, float],
                  out_w: int, out_h: int) -> bytes:
    """按浮点取景框裁一帧并重采样回成片尺寸。

    用 PIL 而不是 ffmpeg 的 `crop`：`crop` 的参数是整数像素，摇镜每一帧的位移
    会被量化到整像素上；PIL 的 `resize(..., box=...)` 直接吃浮点 box，裁剪与
    重采样一次完成，亚像素位移原样保留，这个问题从源头绕开。

    重采样用 BICUBIC 而不是 BILINEAR：这里恒是**放大**（取景框比成片小），
    双线性放大偏软，双三次的锐度更接近原始像素。两者都是亚像素的，
    与整数量化那个问题无关。

    输出恒为 out_w×out_h。帧尺寸必须全程一致——`_encode` 走 concat，
    中途换尺寸 ffmpeg 直接拒。
    """
    im = Image.open(io.BytesIO(raw))
    im.load()
    # 帧的像素尺寸未必等于桌面逻辑尺寸（screencast 会按 maxWidth/maxHeight 缩），
    # box 是桌面坐标，按实际比例换算过去再裁。
    sx = im.width / float(out_w)
    sy = im.height / float(out_h)
    fbox = (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)
    out = im.convert("RGB").resize((out_w, out_h), Image.BICUBIC, box=fbox)
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _write_frame(path: Path, raw: bytes,
                 box: tuple[float, float, float, float] | None,
                 out_w: int, out_h: int) -> None:
    """落盘。裁剪失败不得让整段录制失败——宁可这一帧是全景。"""
    if box is not None:
        try:
            raw = _reframe_jpeg(raw, box, out_w, out_h)
        except Exception as exc:  # noqa: BLE001 单帧裁剪失败只降级
            _log(f"取景裁剪失败，本帧按原图落盘: {type(exc).__name__}: {exc}")
    path.write_bytes(raw)


# ─────────────────────────── 录制机位 ───────────────────────────


class StageRecorder:
    """一台常驻的摄像机，对着桌面页，随时可以开录停录。

    和早先那个一次性录制脚本的区别在于"常驻"：浏览器提前拉起并保持连接，
    start/stop 只是开关帧收集，毫秒级返回。这样录制指令可以和操作指令混在
    同一条流里——准备开一个网页时先发 start，做完发 stop，中间那段自动成片。
    每次重起浏览器要好几秒，那样的延迟没法混进指令流。
    """

    def __init__(self, url: str, width: int, height: int, port: int,
                 fps: int, out_dir: Path):
        self.url = url
        self.width = width
        self.height = height
        self.port = port
        self.fps = fps
        self.out_dir = out_dir
        # 取景框。机位按 1920×1080 拍整个桌面页，camera 决定这一帧最终**留下**
        # 哪一块——裁剪发生在落盘之前，所以成片里就是取好景的画面，
        # 不需要（也不该）在后期再去 crop 一次。
        self.camera = Camera(width, height)
        self.proc: subprocess.Popen | None = None
        self.ws: Any = None
        self.alive = False
        self._msg_id = 0
        self.recording = False
        self.name: str | None = None
        self.frames_dir: Path | None = None
        self.stamps: list[float] = []
        self._idx = 0
        self._t0 = 0.0
        # 动作日志。帧时间戳只够还原节奏，对不上"当时在做什么"；
        # 后期要剪掉无效片段，需要的是一张以开录时刻为零点的动作索引。
        self.journal: list[dict] = []

    async def _send(self, method: str, params: dict | None = None) -> None:
        self._msg_id += 1
        await self.ws.send(json.dumps({"id": self._msg_id, "method": method,
                                       "params": params or {}}))

    async def ensure_open(self) -> None:
        if self.alive:
            return
        # 机位走 frago browser 标准入口，端口 9223，与演员的 9222 分开：停录时
        # 机位要 `-b cdp stop` 收走自己，共用端口那一下会把演员一起带走。
        # 机位不需要任何登录态，profile 用端口推出来的默认目录（edge/9223）即可。
        # 机位拍的是桌面页——纯 HTML/CSS 的二维画面，不需要 GPU，
        # 所以它没有理由跟着演员去开一扇真窗口。恒为无头。
        await _ensure_cdp_instance(self.port, "机位", headless=True)
        ws_url = None
        deadline = time.time() + 40
        while time.time() < deadline:
            pages = await _list_pages(self.port)
            if pages:
                # 播种 profile 可能恢复历史标签，pages[0] 不保证是谁。
                # 优先找已经开着桌面页的那个标签，否则拿第一个标签导航过去。
                hit = next((t for t in pages
                            if (t.get("url") or "").startswith(self.url)),
                           pages[0])
                ws_url = hit["webSocketDebuggerUrl"]
                break
            await asyncio.sleep(0.25)
        if not ws_url:
            raise RuntimeError("录制机位未能就绪")
        self.ws = await websockets.connect(
            ws_url, max_size=64 * 1024 * 1024, ping_interval=None
        )
        self.alive = True
        asyncio.create_task(self._pump())
        await self._send("Page.enable")
        # 对准桌面页，并确保该标签在前台且保持合成——后台标签不产帧，
        # 症状是 record.stop 报"没有收到任何帧"。
        await self._send("Page.navigate", {"url": self.url})
        for method, params in (
            ("Page.bringToFront", {}),
            ("Page.setWebLifecycleState", {"state": "active"}),
            ("Emulation.setFocusEmulationEnabled", {"enabled": True}),
        ):
            with suppress(Exception):
                await self._send(method, params)
        # 视口锁死到精确尺寸，理由同舞台浏览器：--window-size 给的是外窗，
        # 视口比它小且可能是奇数高度，H.264 直接拒绝编码。
        await self._send("Emulation.setDeviceMetricsOverride", {
            "width": self.width, "height": self.height,
            "deviceScaleFactor": 1, "mobile": False,
        })
        _log(f"录制机位就绪 {self.width}x{self.height}")

    async def _pump(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if msg.get("method") != "Page.screencastFrame":
                    continue
                params = msg["params"]
                await self._send("Page.screencastFrameAck",
                                 {"sessionId": params["sessionId"]})
                if not self.recording or self.frames_dir is None:
                    continue
                path = self.frames_dir / f"f{self._idx:06d}.jpg"
                # 取景框在这里生效：box_now() 取的是**这一帧到达时刻**的取景
                # 状态，所以摇镜/推拉是逐帧插值出来的，而不是整段一个固定裁切。
                # 原始镜头返回 None，整条重采样路径被跳过。
                await asyncio.to_thread(
                    _write_frame, path, base64.b64decode(params["data"]),
                    self.camera.box_now(), self.width, self.height,
                )
                self.stamps.append(time.time() - self._t0)
                self._idx += 1
        except Exception as exc:
            _log(f"录制机位连接结束: {type(exc).__name__}: {exc}")
        finally:
            self.alive = False

    async def prepare(self) -> dict:
        """把机位准备到"随时可以开录"，不开录。

        拉起无头浏览器、连上、再给桌面页留一口气连 broker 画出首帧——首次要
        几十秒。把这段独立成一个动作，是为了让开录本身恒为毫秒级：一条时快
        时慢的指令，agent 没法据它安排动作，也说不清自己录的是从哪一刻起。
        """
        fresh = not self.alive
        await self.ensure_open()
        if fresh:
            # 桌面页要一点时间连上 broker 并画出首帧，否则片头会录进一小段空桌面。
            await asyncio.sleep(1.5)
        return {"ready": True, "was_running": not fresh, "port": self.port}

    async def start(self, name: str) -> dict:
        """开录。机位没准备好就先准备——但那样这条指令会慢上几十秒。"""
        prepared = None
        if not self.alive:
            prepared = await self.prepare()
        if self.recording:
            raise RuntimeError(f"已经在录 {self.name}，先 stop")
        self.name = name
        self.frames_dir = Path(tempfile.mkdtemp(prefix="frago-clip-"))
        self.stamps = []
        self.journal = []
        self._idx = 0
        self._t0 = time.time()
        self.recording = True
        await self._send("Page.startScreencast", {
            "format": "jpeg", "quality": 92,
            "maxWidth": self.width, "maxHeight": self.height,
            "everyNthFrame": 1,
        })
        _log(f"开录 {name}")
        # 零点要交给 agent：录制日志里每个动作记的都是"距开录多少秒"，
        # agent 手上没有这个绝对时刻就对不上自己的时间线。机位现拉的那几十秒
        # 里它以为自己已经在录了，实际一帧都没进去——而它无从察觉。
        out = {"clip": name, "started_at": self._t0}
        if prepared is not None:
            out["camera_prepared_now"] = True
            out["note"] = ("机位是这条指令现拉的，开录时刻比你发指令晚了几十秒。"
                           "下次先 `frago desktop camera up`，开录就是毫秒级的。")
        return out

    def note(self, op: str, params: dict, result: Any,
             t_start: float, error: str | None = None,
             observation: dict | None = None) -> None:
        """记一条完整的 观察-动作-结果 三元组，时间以开录时刻为零点。

        记 at 和 until 两个时刻而不只是一个：像 cursor 这种带补间的指令，
        它占用的是一段时间而不是一个瞬间，剪辑时要知道这段动画从哪到哪
        才能干净地切，只有起点会切进半截动作里。

        observation 由调用方在动作**发出之前**采好交进来，这里绝不自己去取——
        note 跑在动作完成之后，此刻的世界已经是结果不是观察了。事后补造的
        观察比缺失的观察更有害：它看上去完整，却把因果关系记反了，
        而且训练时无从分辨。取不到就带着 unavailable 如实留白。
        """
        if not self.recording:
            return
        params = {k: v for k, v in params.items() if k != "op"}
        if isinstance(result, dict):
            outcome = {"ok": True, **result}
        elif error:
            outcome = {"ok": False, "error": error}
        else:
            outcome = {"ok": True}
        entry = {
            "at": round(t_start - self._t0, 3),
            "until": round(time.time() - self._t0, 3),
            # observation 排在 action 之前，读一行 jsonl 的顺序就是因果顺序。
            "observation": observation if observation is not None else {
                "unavailable": {"*": "本条动作未采集观察（不在录制期间发起）"}},
            "action": {"verb": op, "params": params},
            "result": outcome,
            # 下面两个是 v1 就有的字段，语义不变，留着不破坏既有读取方。
            "op": op,
            "params": params,
        }
        if error:
            entry["error"] = error
        self.journal.append(entry)

    async def stop(self) -> dict:
        if not self.recording:
            raise RuntimeError("当前没有在录")
        # 多收一小段收尾：指令跑完后画面往往还在动（补间、字幕淡出），
        # 立刻停会把结尾切掉。
        await asyncio.sleep(0.8)
        self.recording = False
        with suppress(Exception):
            await self._send("Page.stopScreencast")
        frames_dir, stamps, name = self.frames_dir, self.stamps, self.name
        journal = self.journal
        self.frames_dir, self.stamps, self.name = None, [], None
        self.journal = []
        if not stamps:
            shutil.rmtree(frames_dir, ignore_errors=True)
            raise RuntimeError("没有收到任何帧——画面全程静止？")
        out = self.out_dir / f"{name}.mp4"
        await asyncio.to_thread(_encode, frames_dir, stamps, out, self.fps)
        shutil.rmtree(frames_dir, ignore_errors=True)
        log_path = self.out_dir / f"{name}.jsonl"
        log_path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in journal) + "\n"
        )
        _log(f"停录 {name} → {out}（动作 {len(journal)} 条）")
        # 抽帧与冻帧指标恒在这里做，不设开关：靠自觉去抽帧的纪律实测不可靠，
        # 而这两样东西的成本是每段片子几秒钟的 ffmpeg。
        inspect = await asyncio.to_thread(
            _inspect_clip, out, self.out_dir / f"{name}-contact.png", journal)
        _log(f"成片自检 {name}: "
             + json.dumps(inspect, ensure_ascii=False))
        # 摄像机只在录制时存在：停录即收走整个机位实例，
        # 桌面平时只剩舞台一个浏览器。
        await self.close()
        return {
            "clip": name,
            "output": str(out),
            "journal": str(log_path),
            "actions": len(journal),
            "frames": len(stamps),
            "duration_sec": round(stamps[-1], 2),
            "size_bytes": out.stat().st_size,
            **inspect,
        }

    async def close(self) -> None:
        with suppress(Exception):
            if self.ws:
                await self.ws.close()
        self.ws = None
        self.alive = False
        # 机位浏览器由 frago browser 管理，也由它收走。
        with suppress(Exception):
            await asyncio.to_thread(
                subprocess.run,
                [_frago_bin(), "browser", "-b", "cdp", "stop", "--port", str(self.port)],
                capture_output=True, text=True, timeout=30,
            )


def _encode(frames_dir: Path, stamps: list[float], out: Path, fps: int) -> None:
    """按帧的真实到达时刻编码，而不是假设等间隔。

    screencast 只在页面重绘时发帧，静止时一帧不发。若按固定间隔拼装，
    静止的两秒会被压成两帧的时长，整段的节奏就全错了。
    """
    lines = []
    for i, ts in enumerate(stamps):
        nxt = stamps[i + 1] if i + 1 < len(stamps) else ts + 1 / fps
        lines.append(f"file '{frames_dir / f'f{i:06d}.jpg'}'")
        lines.append(f"duration {max(nxt - ts, 1 / 120):.5f}")
    lines.append(f"file '{frames_dir / f'f{len(stamps) - 1:06d}.jpg'}'")
    listing = frames_dir / "frames.txt"
    listing.write_text("\n".join(lines))

    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-vsync", "cfr", "-r", str(fps),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", str(out),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-1200:]}")


# ─────────────────────── 成片自检（抽帧与冻帧） ───────────────────────
#
# 停录回执里"返回码 0 / frames 几百 / 体积正常"三件事都不能证明画面是对的：
# 实测过一条 76 秒之后彻底冻住的素材，这三项全部正常，旁白讲着技能市场而画面
# 是上一个项目的橘猫，差点作为成片交付。所以停录**自动**产出两样东西：
# 一张 2×3 宫格供人扫一眼，以及一组不用眼睛也能判读的数字。
#
# 一切计算交给 ffmpeg，绝不在 Python 里逐像素循环——shotstat 第一版就栽在这，
# 差三个数量级。

# 取帧位置。首尾一律不取：首帧常是过渡态（扩展重设设备指标引发的横幅、
# 尚未落定的布局），末帧在冻帧故障里恰好是最没有信息量的那一张。
CONTACT_PCTS = (0.08, 0.25, 0.42, 0.58, 0.75, 0.92)

# 尾部冻结多久算异常。main-acts 那次是从 76 秒起一直冻到结尾，
# 而正常素材里页面停下来等一两秒是常态，取 3 秒把两者分开。
FROZEN_TAIL_WARN_SEC = 3.0


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    # check=False：自检环节的每一次失败都要变成回执里的一句话，
    # 而不是一个把停录整个掀翻的异常。
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=False)


def _ffprobe_duration(mp4: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(mp4)]).stdout.strip()
    return float(out) if out else 0.0


def _count_frames(mp4: Path) -> int:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-count_frames", "-show_entries", "stream=nb_read_frames",
                "-of", "default=nw=1:nk=1", str(mp4)]).stdout.strip()
    return int(out) if out.isdigit() else 0


def _count_unique_frames(mp4: Path) -> int:
    """去重后还剩几帧。判据用 mpdecimate，不自己比像素。

    这个比值是冻帧故障最早的可见信号，比人肉眼看宫格更早：实测那条素材
    声明 30fps、1488 帧，去重后只剩 313 帧，真实帧率约 6.3fps，79% 是重复帧。
    """
    proc = _run(["ffmpeg", "-v", "info", "-i", str(mp4), "-vf", "mpdecimate",
                 "-fps_mode", "vfr", "-an", "-f", "null", "-"])
    kept = 0
    for m in re.finditer(r"frame=\s*(\d+)", proc.stderr):
        kept = int(m.group(1))
    return kept


def _frozen_tail_sec(mp4: Path, duration: float) -> float:
    """从末尾往前数，连续相同的画面持续了多久。

    freezedetect 会成对报 freeze_start / freeze_end；最后一段只有 start 没有
    end，说明它一直冻到片尾——那正是 main-acts 那次的形态：指令全部生效、
    回执全部正常、画面停在某一帧。
    """
    proc = _run(["ffmpeg", "-v", "info", "-i", str(mp4),
                 "-vf", "freezedetect=n=-60dB:d=0.5", "-map", "0:v",
                 "-an", "-f", "null", "-"])
    events = re.findall(r"freezedetect\.freeze_(start|end):\s*([0-9.]+)",
                        proc.stderr)
    if not events or events[-1][0] != "start":
        return 0.0
    return max(0.0, round(duration - float(events[-1][1]), 2))


def _contact_sheet(mp4: Path, duration: float, out_png: Path) -> list[float]:
    """按时长百分位抽 6 帧拼成 2×3 宫格，返回实际取帧的时刻。"""
    stamps = [round(duration * p, 3) for p in CONTACT_PCTS]
    tmp = Path(tempfile.mkdtemp(prefix="frago-contact-"))
    try:
        shots = []
        for i, t in enumerate(stamps):
            shot = tmp / f"s{i}.png"
            # -ss 放在 -i 之前是关键帧级快速定位，够用且快；抽单帧后缩到
            # 640 宽，六张拼起来正好是一张能一眼扫完的图。
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}",
                  "-i", str(mp4), "-frames:v", "1",
                  "-vf", "scale=640:-2", str(shot)])
            if shot.exists():
                shots.append(shot)
        if len(shots) < 6:
            raise RuntimeError(f"只抽到 {len(shots)} 帧，无法拼 2×3 宫格")
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for s in shots:
            cmd += ["-i", str(s)]
        tile = ("[0][1][2]hstack=inputs=3[a];[3][4][5]hstack=inputs=3[b];"
                "[a][b]vstack=inputs=2")
        cmd += ["-filter_complex", tile, str(out_png)]
        proc = _run(cmd)
        if proc.returncode != 0 or not out_png.exists():
            raise RuntimeError(f"拼宫格失败: {proc.stderr[-600:]}")
        return stamps
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _last_moving_action(journal: list[dict]) -> tuple[float | None, str | None]:
    """日志里最后一条**会改变画面**的指令什么时候结束的。

    区分"末尾静止"与"疑似冻帧"要的就是这个数：末尾一段画面不动，只有在
    这段时间里确实下过会让画面动的指令时才是异常。纯 pause / sleep 收尾，
    或者 reset 之后停几秒再停录，画面本来就该是静止的——那是完全正常的
    收尾镜头，报成 warn 是误判，与今天撤掉的 ui_ready 门禁同类。
    """
    last_at, last_op = None, None
    for e in journal:
        op = e.get("op")
        if op in STILL_OPS:
            continue
        until = e.get("until")
        if isinstance(until, (int, float)) and (last_at is None or until > last_at):
            last_at, last_op = float(until), op
    return last_at, last_op


# 不会改变画面的指令。其余一律算"会动"——判错的两个方向代价不对称：
# 把静止指令误算成会动，只是多一条 warn；把会动的误算成静止，就是把真冻帧
# 放过去，而那正是这套自检存在的理由。
STILL_OPS = {"sleep", "elements", "record.start", "record.stop",
             "camera.up", "camera.down"}


def _inspect_clip(mp4: Path, contact_png: Path,
                  journal: list[dict] | None = None) -> dict:
    """成片自检：宫格 + 冻帧指标。恒不抛异常。

    自检失败不得让停录失败——片子已经录好了，把它连同一句"自检没做成"
    交出去，远好过因为诊断环节出错而让人以为录制本身失败。
    """
    out: dict = {}
    duration = 0.0
    try:
        duration = _ffprobe_duration(mp4)
        total = _count_frames(mp4)
        unique = _count_unique_frames(mp4)
        frozen = _frozen_tail_sec(mp4, duration)
        out.update({
            "total_frames": total,
            "unique_frames": unique,
            "unique_ratio": (round(unique / total, 3) if total else None),
            "effective_fps": (round(unique / duration, 2) if duration else None),
            "frozen_tail_sec": frozen,
        })
        if frozen > FROZEN_TAIL_WARN_SEC:
            # 末尾静止 ≠ 冻帧。判据是这段静止里有没有下过会让画面动的指令：
            # 静止**开始**得比最后一条会动的指令还晚，说明那条指令的效果已经
            # 走完，之后就是一段有意的收尾静态镜头。
            frozen_from = round(duration - frozen, 2)
            last_at, last_op = _last_moving_action(journal or [])
            if last_at is None or frozen_from >= last_at - 0.5:
                out["static_tail_sec"] = frozen
                out["static_tail_note"] = (
                    f"末尾静止 {frozen}s（从 {frozen_from}s 起）"
                    + (f"，而最后一条会改变画面的指令（{last_op}）在 {last_at}s "
                       "就结束了" if last_at is not None else
                       "，录制期间没有发过任何会改变画面的指令")
                    + "——这是收尾静态镜头，不是冻帧。"
                )
            else:
                out["warn"] = (
                    f"画面末尾冻结 {frozen}s（阈值 {FROZEN_TAIL_WARN_SEC}s）——"
                    "静止期间仍有会改变画面的指令在跑"
                    + (f"（最后一条 {last_op} 到 {last_at}s）" if last_at else "")
                    + "，指令可能全部生效而画面停在某一帧，"
                    "先看宫格最后两格再决定是否重录"
                )
    except Exception as exc:  # noqa: BLE001 诊断出错只降级
        out["metrics_error"] = f"{type(exc).__name__}: {exc}"
    try:
        if not duration:
            duration = _ffprobe_duration(mp4)
        out["contact_sheet_at_sec"] = _contact_sheet(mp4, duration, contact_png)
        out["contact_sheet"] = str(contact_png)
    except Exception as exc:  # noqa: BLE001
        out.pop("contact_sheet", None)
        out["contact_sheet_error"] = f"{type(exc).__name__}: {exc}"
    return out


# ─────────────────────────── 舞台状态 ───────────────────────────


@dataclass
class Stage:
    desktop: dict
    layout: dict = field(default_factory=dict)
    cursor: tuple[float, float] = (960.0, 540.0)
    # 当前在最前面的程序。可以是 None——桌面上一个程序都没开着时就是这个状态，
    # 那时没有窗口能接收键盘输入，op_type / op_key 会明说而不是往空处送。
    focus: str | None = "term"
    # 每个程序在不在桌面上。这是"关掉"这件事的唯一真值，与最小化无关：
    # 收起的程序还在跑（dock 亮着灯），关掉的程序不在了。图片浏览器开机不在
    # 桌面上——它是被 image open 叫起来的。
    open: dict = field(default_factory=lambda: {"term": True, "browser": True,
                                                "image": False})
    clients: set = field(default_factory=set)
    # 最近一次的画面与地址栏状态。纯事件驱动没有快照，新连上的客户端会
    # 错过此前所有消息，桌面一片空白——而 UI 断线是会自动重连的，
    # 等于录制中一次抖动就永久黑屏。这几个字段就是补发用的。
    last_frame: str | None = None
    # 终端不在这儿留档：它的现状是 StageTerminal 手上那份缓冲区，
    # 补发时现取（term.snapshot()）。在这里再存一份只会多出一个会漂的副本。
    last_chrome: dict = field(default_factory=dict)
    # 图片浏览器窗口当前开的图。也要留档并补发：断线重连的客户端如果收不到这条，
    # 会把一扇没有内容的空窗口当成实时画面。
    last_image: dict | None = None
    # 演员标签的存活状态。也要留档并补发：断线重连的客户端如果收不到这条，
    # 会把上一帧当成实时画面，而那正是这条消息要消灭的误会。
    last_actor: dict | None = None
    # 窗口几何也必须留档。漏了它的后果很隐蔽：录制中的客户端位置是对的，
    # 而任何后连上的客户端（比如截图用的）按默认位置渲染，
    # 于是截图和实际录到的画面不是同一个东西，拿它做判断会一路错下去。
    win_geom: dict = field(default_factory=dict)
    # 当前悬停绑定：cursor 带 ref 时记下解析结果，随后的 click 按这个 ref 的
    # 语义执行而非纯坐标命中——一两像素的误差不该让点击落空。
    # 纯坐标 cursor 会把它清空，退回坐标命中。
    hover: dict | None = None
    # UI 每上报一次 layout 就 +1。窗口动作的"生效"信号就是它——几何由 UI 算，
    # broker 等它把新几何报回来，才算这次布局变更真的落在了画面上。
    layout_seq: int = 0
    # 报过旧版本 layout 的标签页版本号。ui_ready 自检据此点名，
    # 别让人对着一个被悄悄忽略的标签页调半天。
    stale_clients: set = field(default_factory=set)
    # ws → 这个客户端自报的身份和它的 layout 有没有被采纳。
    # 不属于本实例的荧幕由这张表现算，不另记一份累积账：自检的补救动作是
    # "去关掉那个标签"，而一个已经关掉的标签没什么可关的——历史账会让
    # WARN 在问题解决之后继续挂着，报久了就没人看了。
    # 也刻意不和 stale_clients 混在一起：一个是资产版本旧、一个是实例不对，
    # 病因不同、补救动作不同，混成一处会让自检说不清该关哪个标签。
    # clients 只是个数字时，查"到底是谁连着"得跳出 aos 去翻浏览器标签列表。
    client_meta: dict = field(default_factory=dict)
    # 连接计数器。判"最新连上的那条"需要先后次序，而 clients 是个 set，
    # 天生没有次序——靠遍历顺序猜先后是碰运气。每条连接进来时领一个号，
    # 号最大的那条就是最新的。
    conn_seq: int = 0
    # 上一次点过名的荧幕格局 (数量, 主荧幕身份)。荧幕数不变就不重复刷屏：
    # layout 每秒都在报，不去重的话这条日志会把 broker.log 淹掉。
    screen_note: tuple | None = None
    # 虚拟浏览器窗口的内容区矩形，由 broker 自己算出来（形状来自演员视口的
    # 宽高比）。这是权威反转之后的新事实：几何的作者是 broker，UI 只是执行。
    # 坐标换算一律用这一份，不再用 UI 报回来的那份——自己写的数字不必再问别人。
    browser_rect: dict | None = None
    # 算几何要用、而只有 UI 量得到的两个数字：桌面可用区（扣掉菜单栏与 dock）
    # 与浏览器窗口的装饰高度（标题栏 + 虚拟标签条）。
    ui_metrics: dict = field(default_factory=dict)
    # 终端视口停在缓冲区的第几行，以及是不是贴着底。
    #
    # **这两个数的作者是 broker，不是荧幕**，与虚拟浏览器窗口的几何同源：
    # 荧幕是执行者。曾经反过来——broker 读主荧幕上报的 scrollTop 反推行号，
    # 而每块荧幕收到滚动指令后各自拿自己的缓冲区和窗口高度去夹、去判贴底。
    # 刚连上的那一块（录制机位每次 rec start 都是新开的一页）此刻缓冲区还是空的，
    # 夹出来就是 0、还把自己判成贴底，等快照到了又一路贴回底部——画面停在
    # 最后一屏，而 /status 报的是另一块荧幕的数字。两边都"正常"，只有成片是错的。
    term_top: int = 0
    term_stuck: bool = True
    # 缓冲区头部已经丢掉多少行。丢行会让同样的内容整体前移，视口要跟着挪，
    # 否则人正在看的那几行会自己往上走。
    term_base: int = 0
    # 终端字号（px）。作者同样是 broker，理由和视口那两个数一样：录制机位是
    # 每次 rec start 现开的一页，它按出厂样式渲染，而人那块荧幕上可能已经切到
    # 录制档——两块荧幕字号不同，画面上的列数行数就不同，成片和当时看到的
    # 不是同一个东西。所以它进补发清单，且排在几何之前：格子大小决定列数，
    # 顺序反了荧幕会先按旧格子算一遍网格报上来，tmux 白 resize 一轮。
    term_fs: int = 13

    @property
    def elements(self) -> dict:
        """UI 上报的桌面级可寻址元素快照：ref → 桌面坐标矩形。"""
        el = self.layout.get("elements")
        return el if isinstance(el, dict) else {}

    @property
    def term_grid(self) -> dict:
        g = self.layout.get("termGrid")
        return g if isinstance(g, dict) else {}

    def element_at(self, x: float, y: float, refs: list[str] | None = None) -> str | None:
        """桌面坐标落在哪个桌面级元素上。多个命中取面积最小的那个——
        它是嵌套里最深的，也就是人眼认为"点到"的那个。"""
        best, best_area = None, None
        for ref, r in self.elements.items():
            if refs is not None and ref not in refs:
                continue
            if not (r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]):
                continue
            area = r["w"] * r["h"]
            if best_area is None or area < best_area:
                best, best_area = ref, area
        return best

    def content_rect(self, win: str) -> dict | None:
        """取窗口内容区矩形，两种上报形状都认。

        UI 可以报 {"content":{...},"frame":{...}}，也可以直接把内容区矩形平铺上来。
        平铺形式没有歧义，不值得为了对齐文档去改一份已经正确的前端。

        browser 例外：它的几何由 broker 自己算并下发，直接用自己那一份。
        绕一圈问 UI 要回来只会引入延迟与两份数字漂移的可能。

        关掉的程序恒返回 None。这一条必须在 browser 那条例外**之前**：
        browser_rect 是 broker 自己写的，程序关掉之后它还留着最后一次的值，
        照着它算坐标就会把点击送进一扇根本不在桌面上的窗口，而回执一切正常。
        """
        if not self.open.get(win, False):
            return None
        if win == "browser" and self.browser_rect:
            return self.browser_rect
        node = self.layout.get("windows", {}).get(win) or {}
        rect = node.get("content") if "content" in node else node
        if isinstance(rect, dict) and {"x", "y", "w", "h"} <= rect.keys():
            return rect
        return None

    def window_at(self, x: float, y: float) -> str | None:
        """桌面坐标落在哪扇窗口的内容区里。前台窗口优先——它压在上面。

        关掉的程序自然出局：content_rect 对它们返回 None。焦点为 None
        （桌面上没有开着的程序）时这个列表就只剩下按固定顺序的那几个，
        照样能答，只是没有谁享有前台优先。
        """
        order = list(dict.fromkeys(
            ([self.focus] if self.focus else []) + ["browser", "image", "term"]
        ))
        for win in order:
            r = self.content_rect(win)
            if r and r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]:
                return win
        return None

    def to_page(self, win: str, x: float, y: float, vw: int, vh: int) -> tuple[float, float]:
        """桌面坐标 → 舞台视口坐标。

        虚拟窗口在桌面里的显示尺寸未必等于舞台视口的真实像素尺寸（UI 会缩放画面），
        所以必须按比例换算，不能直接相减。
        """
        r = self.content_rect(win)
        if not r:
            raise RuntimeError(f"{win} 尚未上报 layout，无法换算坐标")
        return ((x - r["x"]) * vw / r["w"], (y - r["y"]) * vh / r["h"])

    def to_desktop(self, win: str, px: float, py: float,
                   vw: int, vh: int) -> tuple[float, float]:
        """舞台视口坐标 → 桌面坐标，to_page 的逆运算。

        这段换算 MUST 由 broker 做：窗口一动内容矩形就变，交给调用方算
        等于让它拿着随时会过期的矩形做除法，实测出现过用旧坐标点空。
        """
        r = self.content_rect(win)
        if not r:
            raise RuntimeError(f"{win} 尚未上报 layout，无法换算坐标")
        return (r["x"] + px * r["w"] / vw, r["y"] + py * r["h"] / vh)


# ─────────────────────── 页面内元素定位（JS） ───────────────────────
#
# 页面元素数量成千上万，无法像桌面级那样全量上报，只能按需查询。
# 返回的是页面坐标，换算成桌面坐标一律在 broker 内做。

_PAGE_BY_SELECTOR = """
(() => {
  const out = [];
  document.querySelectorAll(__SEL__).forEach(e => {
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    const reachable = !!top && (e.contains(top) || top.contains(e));
    out.push({x: cx, y: cy, w: r.width, h: r.height,
              tag: e.tagName.toLowerCase(), reachable: reachable,
              covered_by: reachable ? null
                : (top ? top.tagName.toLowerCase() + '.' + (top.className || '') : 'none'),
              text: (e.innerText || e.value || '').trim().slice(0, 120)});
  });
  return out;
})()
"""

# 文字匹配分三步，每一步都是被实测逼出来的：
#
# 1. 取最深的那个节点——容器的 innerText 也含目标文字，但人认为点中的是那个
#    按钮，不是包着它的三层 div。
# 2. 从它爬到最近的可交互祖先。实测 frago 首页的导航项里，文字在一个 span 上，
#    真正响应点击的是外层 button；对着 span 点毫无反应。
# 3. 用 elementFromPoint 验证中心点真的能被点到。同一个页面里那个 span 恰好被
#    内容区盖住，rect 明明在那儿，点下去命中的却是底下的 div——只看矩形是看不
#    出来的，必须做一次命中测试。够不到的候选排到后面，并如实标出来。
_PAGE_BY_TEXT = """
(() => {
  const t = __TXT__.toLowerCase();
  if (!t) return [];
  const CLICKABLE = 'a,button,[role=button],[role=link],[role=tab],[onclick],' +
                    'input,select,textarea,label,summary';
  const out = [];
  const seen = new Set();
  document.querySelectorAll('body *').forEach(e => {
    const tag = e.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') return;
    const s = e.innerText || e.value || e.getAttribute('aria-label') || '';
    if (!s.toLowerCase().includes(t)) return;
    for (const c of e.children) {
      const cs = c.innerText || c.getAttribute('aria-label') || '';
      if (cs.toLowerCase().includes(t)) return;
    }
    const target = e.closest(CLICKABLE) || e;
    if (seen.has(target)) return;
    seen.add(target);
    const r = target.getBoundingClientRect();
    if (!r.width || !r.height) return;
    if (r.bottom < 0 || r.right < 0 ||
        r.top > innerHeight || r.left > innerWidth) return;
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    const reachable = !!top && (target.contains(top) || top.contains(target));
    out.push({x: cx, y: cy, w: r.width, h: r.height,
              tag: target.tagName.toLowerCase(), reachable: reachable,
              covered_by: reachable ? null
                : (top ? top.tagName.toLowerCase() + '.' + (top.className || '') : 'none'),
              text: (target.innerText || s).trim().slice(0, 120)});
  });
  // 点得到的排前面：ref 解析取第一个，不该把一个够不到的元素交出去
  out.sort((a, b) => (b.reachable ? 1 : 0) - (a.reachable ? 1 : 0));
  return out;
})()
"""


# 取景专用的元素定位。和 _PAGE_BY_TEXT 是两件事，不合并：
#
# 点击要的是"哪个元素**响应**这一下"，所以那边爬到最近的可交互祖先、做命中测试、
# 按点得到排序。取景要的是"该把镜头对准**哪块矩形**"，可交互与否毫不相干——
# 一段纯文字标题不可点，却完全可能就是这一镜要拍的东西。
#
# 回执里带全矩形、tag 和**这块矩形里的文本摘要**，是为了让 agent 能自查命中了什么。
# `page:"IP 设计全案"` 命中的可能是那行标题文字，也可能是整张卡片，取决于 DOM
# 结构——agent 事前分不清，而这两者在画面上完全不同。要拍整张技能卡时，摘要里
# 应该同时出现标题、版本号、安装量、描述；如果只回来一个「IP 设计全案」，
# 立刻就知道命中的是标题而不是卡片。这个判据不需要眼睛，靠文本覆盖就能自查。
_PAGE_FRAME_TARGET = """
(() => {
  const t = __TXT__, sel = __SEL__, expand = __EXP__;
  let list = [];
  if (sel) {
    list = [...document.querySelectorAll(sel)];
  } else {
    const needle = (t || '').toLowerCase();
    if (!needle) return [];
    document.querySelectorAll('body *').forEach(e => {
      const tag = e.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') return;
      const s = e.innerText || e.value || e.getAttribute('aria-label') || '';
      if (!s.toLowerCase().includes(needle)) return;
      // 取最深的那个：容器的 innerText 也含目标文字，但人认为"就是这块"的是
      // 最里面那个。要整张卡片请用 --expand-to 显式说，不靠猜。
      for (const c of e.children) {
        const cs = c.innerText || c.getAttribute('aria-label') || '';
        if (cs.toLowerCase().includes(needle)) return;
      }
      list.push(e);
    });
  }
  const out = [], done = new Set();
  list.forEach(e => {
    const target = expand ? (e.closest(expand) || e) : e;
    if (done.has(target)) return;
    done.add(target);
    const r = target.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const txt = (target.innerText || target.value || '')
                  .replace(/\\s+/g, ' ').trim();
    out.push({x: r.x, y: r.y, w: r.width, h: r.height,
              tag: target.tagName.toLowerCase(),
              id: target.id || null,
              expanded: target !== e,
              text: txt.slice(0, 600), text_len: txt.length});
  });
  return out;
})()
"""


# 这一截是不是合法的 CSS 选择器。**零命中有两种来路**，补救动作完全不同：
# 选择器合法但页面上确实没有（该等、该换页面），或者它压根不是合法选择器
# （该换写法）。querySelectorAll 撞上非法选择器会抛异常，探针于是返回空——
# 与"合法但没有"长得一模一样。不分开问这一句，回执就只能说一句"未命中"，
# 而那句话读起来像"页面上没这个元素"，把排查方向从第一步就带偏。
_SELECTOR_VALID = """
(() => { try { document.querySelector(__SEL__); return true }
         catch (e) { return false } })()
"""


async def page_query(evaluate, text: str | None = None,
                     selector: str | None = None, *, frame: bool = False,
                     expand_to: str | None = None) -> list[dict]:
    """在舞台页面里找元素，返回页面坐标（尚未换算）。

    ``frame`` 分的是两件事，不是一个开关的两档：False 给点击用（爬到最近的
    可交互祖先、做命中测试、按点得到排序），True 给取景用（要的是一块矩形，
    可交互与否毫不相干）。见 _PAGE_BY_TEXT 与 _PAGE_FRAME_TARGET 各自的说明。

    ``evaluate`` 由调用方传进来（正常是 StageBrowser.evaluate）：这条路要能
    在没有浏览器的情况下单测，判型是这次修的东西，它必须验得动。
    """
    if frame:
        js = (_PAGE_FRAME_TARGET
              .replace("__TXT__", json.dumps(text, ensure_ascii=False))
              .replace("__SEL__", json.dumps(selector, ensure_ascii=False))
              .replace("__EXP__", json.dumps(expand_to, ensure_ascii=False)))
    elif selector:
        js = _PAGE_BY_SELECTOR.replace("__SEL__", json.dumps(selector))
    else:
        js = _PAGE_BY_TEXT.replace("__TXT__", json.dumps(text or ""))
    return await evaluate(js) or []


async def selector_is_valid(evaluate, selector: str) -> bool:
    try:
        return bool(await evaluate(
            _SELECTOR_VALID.replace("__SEL__", json.dumps(selector))))
    except Exception:  # noqa: BLE001 探针不通不该把寻址整个掀翻
        return False


async def page_locate(evaluate, arg: str, *, frame: bool = False,
                      expand_to: str | None = None) -> dict:
    """把 `page:` 后面那一截解析成命中列表。**判型只有这一处。**

    形态判定归 refs.parse_page_ref（纯函数、无依赖、可单测），这里只负责按
    它给的顺序去问页面。回执里带 ``tried``：每一跳试了什么、结果如何——
    判型这一层从此不是黑盒，"未命中"不再是一句没有信息量的话。
    """
    plan = refs.parse_page_ref(arg)
    tried: list[dict] = []
    for how, needle in plan["attempts"]:
        hits = await page_query(
            evaluate,
            text=needle if how == "text" else None,
            selector=needle if how == "selector" else None,
            frame=frame, expand_to=expand_to)
        tried.append({"how": how, "needle": needle, "hits": len(hits)})
        if hits:
            return {"hits": hits, "matched_by": how, "needle": needle,
                    "form": plan["form"], "tried": tried,
                    "note": refs.matched_note(plan["form"], how, needle)}
    # 合法性只在**整条都没命中**时才问。它唯一的用处是把错误消息说准
    # （"不是合法选择器" vs "合法但页面上没有"），而回退成功的那条路上多问一次
    # 就是多一次 CDP 往返——录制期间每一次往返都在啃动线的节奏。
    for note in tried:
        if note["how"] == "selector":
            note["valid_selector"] = await selector_is_valid(
                evaluate, note["needle"])
    return {"hits": [], "matched_by": None, "needle": None,
            "form": plan["form"], "tried": tried, "note": None}


# ─────────────────────── 世界状态探针与差异 ───────────────────────
#
# 反馈分三级：L1 受理（指令已收到）、L2 命中（动作打在哪个目标上）、
# L3 生效（世界真的变了）。v1 只有 L1，`clicked: true` 仅表示事件已发出，
# 点空时回执照样是 true——实测中文字寻址点到被遮挡元素、矩形正确、
# 命中别的东西，回执毫无察觉。下面这组探针就是 L3 的事实来源：
# 动作前后各取一次同形状的指纹，差异即"世界变了什么"。

# 一次 JS 往返取回页面的可比较指纹。取哈希而非全文：全量 DOM 会淹没信号，
# 而判断"该不该往下走"只需要知道变没变、往哪个方向变。全文经 detail 显式索取。
_PAGE_PROBE = """
(() => {
  const b = document.body;
  const t = b ? (b.innerText || '') : '';
  let h = 0;
  for (let i = 0; i < t.length; i++) h = (Math.imul(h, 31) + t.charCodeAt(i)) | 0;
  const a = document.activeElement;
  return {
    url: location.href,
    title: document.title,
    len: t.length,
    hash: h,
    nodes: document.getElementsByTagName('*').length,
    active: a ? a.tagName.toLowerCase() : null,
    value: (a && 'value' in a) ? String(a.value) : null,
    scrollY: Math.round(window.scrollY),
    head: t.slice(0, 160),
  };
})()
"""

# 客户端被拒的原因文本之一。/status 靠它现算 foreign_clients，
# 所以这句话是有语义的常量，不是随手写的日志措辞——散在几处各写一遍，
# 改动一处就会让那份现算悄悄漏掉一类客户端。
FOREIGN_REASON = "contentId 不属于本实例"

# ui_ready 的判定窗口。它问的是"现在画面是不是活的"，不是"历史上有没有过首帧"：
# 后者是一次性信号，主荧幕中途接位后新主荧幕若早就画过帧就不会再发，ui_ready
# 于是卡在 false 而画面其实是好的——真假两种情况分不出来，自检那条 WARN 就成了
# 狼来了。开录前真正要问的是前者。
UI_LIVE_WINDOW_SEC = 3.0

# 同一实例被开了不止一块荧幕时，非主荧幕的拒绝原因。/status 靠它现算
# duplicate_clients。刻意不与 FOREIGN_REASON 合并：外来荧幕要人去关**别的
# 实例**的标签，重复荧幕要人去关**本实例多开**的标签，两个补救动作指向的是
# 不同的标签页，合成一类就等于让人对着错误的那个使劲。
DUPLICATE_REASON = "同实例已有更新的荧幕，本连接不是主荧幕"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _plain(text: str) -> str:
    """去掉 SGR 转义。capture-pane -e 带颜色码，比对与摘要都要看纯文本。"""
    return _ANSI.sub("", text)


def _diff_page(a: dict | None, b: dict | None) -> dict:
    """页面指纹前后差异 → L3 摘要。

    探针取不到时如实说取不到，绝不默认成"没变"——把"没观察到"说成
    "没发生"正是本轮要修的病。
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return {"observed": False,
                "reason": "页面探针无回应（连接断开或页面不可执行 JS）"}
    out: dict = {"observed": True}
    out["url_changed"] = a.get("url") != b.get("url")
    if out["url_changed"]:
        out["url_from"], out["url_to"] = a.get("url"), b.get("url")
    out["title_changed"] = a.get("title") != b.get("title")
    if out["title_changed"]:
        out["title_from"], out["title_to"] = a.get("title"), b.get("title")
    out["dom_changed"] = (a.get("hash") != b.get("hash")
                          or a.get("nodes") != b.get("nodes"))
    if out["dom_changed"]:
        out["text_len"] = {"before": a.get("len"), "after": b.get("len"),
                           "delta": (b.get("len") or 0) - (a.get("len") or 0)}
        out["nodes"] = {"before": a.get("nodes"), "after": b.get("nodes"),
                        "delta": (b.get("nodes") or 0) - (a.get("nodes") or 0)}
        out["text_head"] = b.get("head")
    if a.get("scrollY") != b.get("scrollY"):
        out["scrolled"] = {"from": a.get("scrollY"), "to": b.get("scrollY")}
    if a.get("value") != b.get("value") or a.get("active") != b.get("active"):
        out["focused_field"] = {
            "tag_before": a.get("active"), "tag_after": b.get("active"),
            "value_before": a.get("value"), "value_after": b.get("value"),
        }
    return out


# 回执里最多带回多少行新增输出。缓冲区有几千行，而 `cat 一个大文件` 这种
# 命令一条就能推进去两千行——整段带回会把回执撑成几百 KB，真正的信号
# （命令跑没跑、报没报错）反而被埋掉。超出部分不是丢了，它就在缓冲区里，
# 回执点名 `term read --lines <n>` 去取，并如实说明这里只带了多少。
TERM_ADDED_MAX = 200


def _diff_term(a: list[str] | None, b: list[str] | None) -> dict:
    """终端缓冲区前后差异 → L3 摘要。

    比的是**整个缓冲区**（历史 + 当前屏），不是只比当前屏。只比当前屏时，
    输出超过一屏的命令一跑完，前面那些行已经滚进历史，公共前缀直接对不上，
    回执只能报一句 scrolled=true——真正新增了什么反而说不出来。

    末尾空行先削掉：capture-pane 恒把可见屏补齐到网格高度，那串空行不是内容。
    按公共前缀切出新增部分：输出是追加式的，前缀一致、尾部长出来的就是这条
    命令带来的。
    """
    if b is None:
        return {"observed": False, "reason": "终端尚未上报任何画面"}

    def trimmed(rows: list[str] | None) -> list[str]:
        rows = list(rows or [])
        while rows and not rows[-1].strip():
            rows.pop()
        return rows

    la, lb = trimmed(a), trimmed(b)
    if la == lb:
        return {"observed": True, "changed": False,
                "lines_before": len(la), "lines_after": len(lb),
                "lines_added": 0}
    common = 0
    while common < len(la) and common < len(lb) and la[common] == lb[common]:
        common += 1
    added = lb[common:]
    out = {
        "observed": True, "changed": True,
        "lines_before": len(la), "lines_after": len(lb),
        "lines_added": len(added),
        "added": added[-TERM_ADDED_MAX:],
    }
    if len(added) > TERM_ADDED_MAX:
        # 留的是末尾那一段：报错、退出码、跑完的提示都在输出的最后。
        out["added_truncated"] = {
            "kept": TERM_ADDED_MAX, "of": len(added), "kept_from": "tail",
            "how_to_read_all": "frago desktop term read --lines <n>",
        }
    if common == 0 and la:
        # 缓冲区被整段换掉了（会话重开、clear-history、改过窗口尺寸后重取）。
        out["resynced"] = True
    return out


def _diff_rect(a: dict | None, b: dict | None) -> dict:
    """窗口几何前后差异。UI 是几何的唯一真值，broker 只做比对。"""
    if not isinstance(b, dict):
        return {"observed": False, "reason": "UI 尚未上报窗口几何"}
    if a == b:
        return {"observed": True, "changed": False, "rect": b}
    return {"observed": True, "changed": True, "before": a, "after": b}


# ─────────────────────────── 服务 ───────────────────────────


def build_app(cfg: dict) -> FastAPI:
    stage = Stage(desktop=cfg["desktop"])
    browser = StageBrowser(
        int(cfg.get("stage_port", 9222)),
        cfg["browser"]["w"], cfg["browser"]["h"], cfg["start_url"],
        headless=bool(cfg.get("actor_headless", True)),
    )
    term = StageTerminal(cfg["tmux_session"], cfg["term"]["cols"], cfg["term"]["rows"])
    ready = asyncio.Event()

    async def broadcast(msg: dict) -> None:
        if not stage.clients:
            return
        payload = json.dumps(msg)
        dead = []
        for ws in list(stage.clients):
            try:
                # 单个客户端最多拖 2 秒。没有超时的话，一个卡住的连接
                # 会把整条下发链路无限期挂起。
                await asyncio.wait_for(ws.send_text(payload), timeout=2.0)
            except Exception:
                dead.append(ws)
        for ws in dead:
            stage.clients.discard(ws)
            stage.client_meta.pop(ws, None)
            _log("剔除无响应客户端")

    async def on_frame(data: str) -> None:
        stage.last_frame = data
        await broadcast({"t": "frame", "data": data})

    async def push_chrome(**fields) -> None:
        """改虚拟浏览器窗口的地址栏 / 标签条，并把这份现状记在自己名下。

        记账这一步不能漏，也不能只在某几条路上做：录制机位是**现拉的、必然后连**
        的客户端，它拿到的是补发的快照，不是历史广播。哪条路广播了却没记账，
        成片里那一栏就停在更早的状态上——2026-08-10 实测：`tab switch` 之后地址栏
        仍写着上一个标签的 URL、标签条退回出厂的单个"New Tab"，而画面里的网页
        确实已经换了。回执与日志全程正常。
        """
        msg = {"t": "chrome", **fields}
        stage.last_chrome.update(msg)
        await broadcast(msg)

    async def on_nav(url: str | None, loading: bool) -> None:
        await push_chrome(**({"loading": loading} if not url
                             else {"loading": loading, "url": url}))

    async def on_term(payload: dict) -> None:
        """把缓冲区的增量推给荧幕。

        缓冲区从头部丢过行时，视口跟着往上挪同样多——同一段内容整体前移了，
        不挪的话人正在回看的那几行会自己往上走。

        推增量不推整段：缓冲区有几千行，而绝大多数轮次变的只是最后那几行。
        整段推的话每秒八次、每次几百 KB，画面还得整块重画一遍，正在回看的
        人脚下的行会跟着抖。荧幕那边照 base/from 拼，拼出来的与这边一模一样。
        """
        base = int(payload.get("base") or 0)
        if base > stage.term_base:
            stage.term_top = max(0, stage.term_top - (base - stage.term_base))
        stage.term_base = base
        await broadcast({"t": "term", **payload})

    async def on_actor_state(alive: bool, reason: str) -> None:
        """演员标签没了/回来了，桌面页那扇虚拟浏览器窗口要跟着变。

        不告诉它的话，画面会停在最后一帧，看上去和"页面正好没动"完全一样，
        而人会对着一张两小时前的截图以为自己在看实时画面。
        """
        msg = {"t": "actor", "alive": alive, "reason": reason}
        stage.last_actor = msg
        await broadcast(msg)

    browser.on_frame = on_frame
    browser.on_nav = on_nav
    browser.on_actor_state = on_actor_state
    term.on_text = on_term

    # ── 虚拟浏览器窗口的几何：broker 是作者 ──
    #
    # 尺寸真值来自演员标签天然的视口，broker 只读它的宽高比 r=w/h，据此决定这扇
    # 虚拟窗口画多大。宽卡在桌面宽的 75%–85%（1440–1632），视口高 H=W/r，
    # 两边比例相同、尺寸不等，帧画进 canvas 是纯等比缩放：不变形也不留白。
    # 高度装不下时反过来由高定宽，此时宽允许跌破 75%，并在回执里注明。
    BROWSER_W_MIN_FRAC = 0.75
    BROWSER_W_MAX_FRAC = 0.85
    WIN_PAD = 10
    # UI 还没连上时的兜底度量：菜单栏 26、dock 66+两侧 10 留白、
    # 浏览器窗口装饰（标题栏 + 虚拟标签条）76。UI 一上报就以它量到的为准。
    FALLBACK_METRICS = {"menubar": 26, "dockArea": 86, "browserHeader": 76}

    def desktop_area() -> dict:
        """桌面可用区：整块桌面扣掉菜单栏与 dock。与 UI 的 desktopArea 同义。"""
        m = stage.ui_metrics or {}
        area = m.get("area")
        if isinstance(area, dict) and area.get("h"):
            return area
        mb = int(m.get("menubar") or FALLBACK_METRICS["menubar"])
        dock = int(m.get("dockArea") or FALLBACK_METRICS["dockArea"])
        return {"x": 0, "y": mb, "w": int(stage.desktop["w"]),
                "h": int(stage.desktop["h"]) - mb - dock}

    def browser_header_h() -> int:
        return int((stage.ui_metrics or {}).get("browserHeader")
                   or FALLBACK_METRICS["browserHeader"])

    def browser_geometry(target_w: int | None = None,
                         pin_x: int | None = None, pin_y: int | None = None,
                         allow_narrow: bool = False) -> dict:
        """按演员视口的宽高比算出虚拟浏览器窗口该有的几何。

        返回窗口框 frame（含装饰）、内容区 content（就是虚拟视口）、
        以及所有被夹紧/被高度限制的说明——回执里说不清为什么是这个数字，
        下次有人看到 1400 就会以为是 bug。
        """
        notes: list[str] = []
        dw = int(stage.desktop["w"])
        w_lo = int(dw * BROWSER_W_MIN_FRAC) & ~1
        w_hi = int(dw * BROWSER_W_MAX_FRAC) & ~1
        ratio = (browser.width / browser.height) if browser.height else 16 / 9
        # 默认取上界：同样的比例下画面越大越好看，也最省得每次去指定。
        want = int(target_w) if target_w else w_hi
        w = want
        if w > w_hi:
            w = w_hi
            notes.append(f"请求宽 {want} 超过上界 {w_hi}（桌面宽的 "
                         f"{BROWSER_W_MAX_FRAC:.0%}），已夹到上界")
        elif w < w_lo:
            if allow_narrow:
                notes.append(f"请求宽 {want} 低于下界 {w_lo}（桌面宽的 "
                             f"{BROWSER_W_MIN_FRAC:.0%}），但调用方连 --x 一起"
                             f"给了，那是对开布局的显式意图，放行；等比不变")
            else:
                w = w_lo
                notes.append(f"请求宽 {want} 低于下界 {w_lo}（桌面宽的 "
                             f"{BROWSER_W_MIN_FRAC:.0%}），已夹到下界")
        area = desktop_area()
        header = browser_header_h()
        h_avail = int(area["h"]) - WIN_PAD * 2 - header
        h = w / ratio
        height_limited = False
        if h > h_avail:
            height_limited = True
            notes.append(
                f"按宽定高得到视口高 {int(h)}，装不进可用高度 {h_avail}，"
                f"改由高度定宽：宽 = {h_avail} × {ratio:.4f} = "
                f"{int(h_avail * ratio)}，此时宽允许跌破下界 {w_lo}")
            h = h_avail
            w = h * ratio
        # 高取**最近**的偶数，不是向下截断。向下截断最多丢近 4px 的高，而 fitCanvas
        # 的缩放系数取 min(W/fw, H/fh)——高一旦偏小就由它说了算，缺掉的那点高会原封
        # 不动变成横向留白（实测 1440×742 对演员 1444×746，两边各留 1.87px）。
        # 取最近偶数把误差挤到"多出不到 1px 高"这一侧，对任意 r 都成立。
        # 宽仍向下截断：它是 75%–85% 区间里的取值，不能因为取整跑出上界。
        #
        # 例外是由高定宽那条路：此时 h 已经**等于**可用高度 h_avail，再取最近
        # 偶数就可能变成 h_avail + 1，窗口比桌面可用区高出 1px（实测 869 → 870）。
        # 那一侧没有余量可借，只能向下取偶；代价是最多 1px 的横向留白，
        # 远小于"窗口超出桌面"这个真错。
        w = max(320, int(w)) & ~1
        h = max(240, (int(h) if height_limited else int(h + 1)) & ~1)
        frame_h = h + header
        x = (int(pin_x) if pin_x is not None
             else int(area["x"] + (int(area["w"]) - w) / 2))
        y = (int(pin_y) if pin_y is not None
             else int(area["y"] + (int(area["h"]) - frame_h) / 2))
        if pin_x is not None or pin_y is not None:
            notes.append(f"位置由调用方钉住（x={x} y={y}），本次不做水平居中")
        return {
            "frame": {"x": x, "y": y, "w": w, "h": frame_h},
            "content": {"x": x, "y": y + header, "w": w, "h": h},
            "aspect_ratio": round(ratio, 4),
            "actor_viewport": {"w": browser.width, "h": browser.height},
            "width_bounds": {"min": w_lo, "max": w_hi},
            "width_frac": round(w / dw, 4),
            "height_limited": height_limited,
            "desktop_area": area, "header_h": header,
            "notes": notes,
        }

    # 最近一次显式指定过的宽度（max/restore 给的）。度量变化后重摆窗口时要
    # 沿用它，否则 restore 到下界之后随便一次重摆又跳回上界。
    browser_target_w: dict = {"w": None, "x": None, "y": None,
                              "narrow": False}

    async def push_browser_window(target_w: int | None = None, ms: int = 400,
                                  reason: str = "", pin_x: int | None = None,
                                  pin_y: int | None = None,
                                  allow_narrow: bool | None = None,
                                  clear_pin: bool = False) -> dict:
        """算好几何、记在自己名下、下发给虚拟桌面页照着摆。

        钉住的位置和"允许更窄"这两件事跟宽度一样要**记在自己名下**：度量一变
        （UI 重连、dock 高度变化）就会重摆一次窗口，不记就会悄悄弹回居中，
        而画面上那一下没有任何回执解释得了。
        """
        if target_w:
            browser_target_w["w"] = int(target_w)
        if clear_pin:
            browser_target_w["x"] = browser_target_w["y"] = None
            browser_target_w["narrow"] = False
        if pin_x is not None:
            browser_target_w["x"] = int(pin_x)
        if pin_y is not None:
            browser_target_w["y"] = int(pin_y)
        if allow_narrow is not None:
            browser_target_w["narrow"] = bool(allow_narrow)
        geo = browser_geometry(target_w or browser_target_w["w"],
                               pin_x=browser_target_w["x"],
                               pin_y=browser_target_w["y"],
                               allow_narrow=browser_target_w["narrow"])
        f = geo["frame"]
        stage.browser_rect = geo["content"]
        msg = {"t": "win", "win": "browser", "ms": int(ms), **f}
        stage.win_geom["browser"] = {**msg}
        await broadcast(msg)
        _log(f"虚拟浏览器窗口 → {f['w']}x{f['h']}（视口 {geo['content']['w']}x"
             f"{geo['content']['h']}，比例 {geo['aspect_ratio']}，{reason}）")
        return geo

    # ── 图片浏览器窗口的几何：broker 也是作者 ──
    #
    # 图片窗口没有演员视口可读，它自己的长宽比就是内容的比例。图片可能很大
    # （截图、长图），按原始尺寸摆会撑出桌面；这里把内容区钳进桌面可用区，
    # 宽上限 60%——浏览器窗口已经占了 75–85%，图片窗口再大就和它打架。
    # 高按宽的比例推出来，与浏览器窗口同一套思路：等比、不拉伸、不留白。
    IMAGE_W_MAX_FRAC = 0.60

    def image_geometry(img_w: int, img_h: int) -> dict:
        """按图片长宽比算出图片浏览器窗口该有的几何。

        返回窗口框 frame（含标题栏）与内容区 content，以及被夹在哪里的说明。
        """
        notes: list[str] = []
        area = desktop_area()
        header = 30  # 图片窗口只有一条标题栏，无地址栏
        max_w = int(area["w"] * IMAGE_W_MAX_FRAC) & ~1
        max_h = int(area["h"]) - WIN_PAD * 2 - header
        ratio = (img_w / img_h) if img_h else 16 / 9
        w = max_w
        h = w / ratio
        if h > max_h:
            height_limited = True
            notes.append(
                f"按宽定高得到内容高 {int(h)}，装不进可用高度 {max_h}，"
                f"改由高度定宽：宽 = {max_h} × {ratio:.4f} = {int(max_h * ratio)}"
            )
            h = max_h
            w = h * ratio
        else:
            height_limited = False
        w = max(320, int(w)) & ~1
        h = max(240, int(h)) & ~1
        frame_h = h + header
        x = int(area["x"] + (int(area["w"]) - w) / 2)
        y = int(area["y"] + (int(area["h"]) - frame_h) / 2)
        return {
            "frame": {"x": x, "y": y, "w": w, "h": frame_h},
            "content": {"x": x, "y": y + header, "w": w, "h": h},
            "aspect_ratio": round(ratio, 4),
            "image_size": {"w": img_w, "h": img_h},
            "height_limited": height_limited,
            "desktop_area": area, "header_h": header,
            "notes": notes,
        }

    async def push_image_window(geo: dict, ms: int = 0) -> dict:
        """把图片窗口几何下发给虚拟桌面页。

        图片窗口与浏览器窗口不同：它没有演员视口要跟随，开图后位置尺寸由人
        （window move）决定，几何的作者是 UI——这里只下发"按图片比例算好的
        初始几何"，之后的增改走通用 win 消息，不做 broker 侧对账。
        """
        f = geo["frame"]
        msg = {"t": "win", "win": "image", "ms": ms, **f}
        stage.win_geom["image"] = {**msg}
        await broadcast(msg)
        return geo

    async def on_viewport(w: int, h: int, reason: str) -> None:
        """演员视口变了，窗口形状跟着改。跟随的方向只有这一个。"""
        await push_browser_window(reason=f"演员视口变为 {w}x{h}（{reason}）")

    browser.on_viewport = on_viewport

    recorder = StageRecorder(
        url=cfg["desktop_url"],
        width=cfg["desktop"]["w"],
        height=cfg["desktop"]["h"],
        port=int(cfg.get("record_port", 9223)),
        fps=int(cfg.get("fps", 30)),
        # 落点由 main() 校验过必然在，这里直接取。NEVER 在这儿留一个默认路径：
        # 录屏片段会安静地落进另一个目录，而回执照常报成功。
        out_dir=Path(cfg["clips_dir"]).expanduser(),
    )

    instance_id = cfg.get("id") or registry.DEFAULT_ID
    last_beat = 0.0

    async def heartbeat() -> None:
        """每 10 秒落一次心跳时间戳。

        心跳只是"这一刻它还活着"的旁证，真正判定 stale 靠 read_instance 的
        pid + 端口探活——时间戳过期不等于死，进程也可能只是卡住。
        """
        # 演员标签的核对搭这趟车。它自己按 VERIFY_INTERVAL 节流，
        # 放在心跳的 10 秒闸门之前，免得核对被心跳的节奏拖慢。
        await browser.verify_actor()
        nonlocal last_beat
        now = time.time()
        if now - last_beat < 10:
            return
        last_beat = now
        await asyncio.to_thread(registry.touch_heartbeat, instance_id)

    async def confirm_running() -> None:
        """等到自己真的能应答了，再把"在跑"落一次盘。

        lifespan 跑完之前端口只是绑上了、还没开始 accept，而这段启动要十几秒
        （建 tmux 会话、拉演员浏览器、开帧流）。这期间任何一条 frago desktop
        指令都会走 registry.read_instance 探活，它的判据是"pid 活着**且**端口
        可达"——此刻端口不可达，于是它按规矩把记录纠正成 stopped 并清掉 pid。
        几秒后这台 broker 好端端地在服务，却再没人把记录改回来，之后每条指令
        都被一句"实例存在但没在运行"挡掉，而画面其实一直在推。

        2026-08-20 在自测里连撞两次。补救不能放进 read_instance——它那条
        "两个信号同时成立才算在跑"是对的，专治卡死的 broker；该补的是这一侧：
        我确实开始服务了，就再说一次。
        """
        for _ in range(240):
            await asyncio.sleep(0.5)
            if await asyncio.to_thread(_broker_alive, int(cfg["port"])):
                await asyncio.to_thread(
                    registry.mark_running, instance_id, os.getpid(),
                    int(cfg["port"]))
                return

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # 运行态先落盘：身份层由 recipe.py 建好，这里一个字段都不碰，
        # 只覆写 pid/port/status/started_at/heartbeat_at。
        registry.mark_running(instance_id, os.getpid(), int(cfg["port"]))
        confirmer = asyncio.create_task(confirm_running())
        await term.launch()
        await browser.launch()
        browser.min_interval = 1 / max(1, cfg.get("fps", 30))
        browser.on_tick = heartbeat
        await browser.start_stream(cfg.get("fps", 30))
        poller = asyncio.create_task(term.poll_forever())
        framer = asyncio.create_task(browser.pump_frames_forever())
        # 机位不预热、不常驻：摄像机只在录制时存在（record.start 拉起，
        # record.stop 收走）。代价是每段第一秒的启动延迟，换的是桌面上
        # 平时只有一个浏览器实例。
        yield
        confirmer.cancel()
        poller.cancel()
        framer.cancel()
        await recorder.close()
        await browser.close()
        if cfg.get("keep_tmux"):
            _log("按配置保留 tmux 会话")
        else:
            await term.close()
        # 只改运行态，绝不删文件：身份的载体（人那个标签页、viewer 目录、
        # clips）一样没少，"没在跑"和"不存在"是两种状态。
        # 带上自己的 pid：抢端口失败的那个 broker 也会走到这里，不许它把
        # 活着的那个注销掉（见 registry.mark_stopped）。
        registry.mark_stopped(instance_id, owner_pid=os.getpid())
        _log(f"实例 {instance_id} 已标记 stopped")

    app = FastAPI(lifespan=lifespan)

    def note_identity(meta: dict, msg: dict) -> bool:
        """记下客户端自报的身份，返回这块荧幕是否属于本实例。

        broker 此前把"连上来的桌面页都是我的荧幕"当成前提，从不核对。而端口
        不属于身份——所有实例默认都是 8770，旧实例遗留的标签每秒重连一次，
        连上后来的 broker 是必然事件，不是意外。

        自报里没有 contentId 的是更旧的资产（那时还没有这个字段），不当作
        外来荧幕——它归 uiVersion 那条防线管，两种病因不能互相顶替。
        """
        for key in ("contentId", "instanceId", "uiVersion"):
            if msg.get(key) is not None:
                meta[key] = msg[key]
        want = cfg.get("content_id")
        got = meta.get("contentId")
        return not want or not got or got == want

    def own_screens() -> list[dict]:
        """属于本实例、且有资格当主荧幕的连接，按连上的先后排序。

        认死"自报过 contentId 且正是本实例的"这一种，不认"暂时还看不出是谁的"。
        差别很实在：旧资产的标签不带 contentId，而它每秒重连一次，每次都会有
        一小段还没自报身份的空窗；把这段空窗算成本实例的荧幕，它就会每秒
        从真正那块手里抢一次主位，几何跟着一秒一跳。

        资产过旧的标签同样排除——它的 layout 本来就被版本那条防线丢弃，
        若还让它因为"最新"而占住主荧幕的位子，正常那块反倒被判成重复，
        两边都不报，舞台从此拿不到任何几何。
        """
        want = cfg.get("content_id")
        return sorted(
            (m for m in stage.client_meta.values()
             if not m.get("stale")
             and (m.get("contentId") == want if want
                  else m.get("reason") != FOREIGN_REASON)),
            key=lambda m: m.get("seq", 0),
        )

    def primary_meta() -> dict | None:
        """主荧幕 = 最新连上的那块。

        取最新而不是取最早：人刚打开或刚刷新的那个标签才是他正在看的那块，
        旧标签往往是忘了关的。而且这条规则让"主荧幕断了"不需要任何补救
        动作——它是现算的，最新的那条自动顶上，不存在没有主荧幕的空窗。
        """
        own = own_screens()
        return own[-1] if own else None

    def note_screens() -> None:
        """荧幕格局变化时点名。数量没变就不重复说。"""
        own = own_screens()
        top = primary_meta()
        # 让位要在新连接进来的那一刻就落到旧连接头上，不能等它下一次报 layout：
        # layout 只在几何变化时才报，一个安静的旧标签可能几分钟不出声，
        # 那段时间 /status 上它仍写着 accepted=true——名单说的和 broker 实际
        # 采信的对不上，比没有这张名单更坏。
        for m in own[:-1]:
            if m.get("accepted") or m.get("reason") == "尚未上报 layout":
                m["accepted"] = False
                m["reason"] = DUPLICATE_REASON
        key = (len(own), top.get("seq") if top else -1)
        if key == stage.screen_note:
            return
        stage.screen_note = key
        if len(own) > 1:
            _log(f"实例 {instance_id} 有 {len(own)} 块荧幕，认最新连上的那块"
                 f"（seq={top.get('seq') if top else '无'}）为主，"
                 f"其余 {len(own) - 1} 块只看不报")

    def reject_log(meta: dict) -> None:
        _log(f"拒绝实例 {meta.get('instanceId') or '未知'} 的荧幕"
             f"（contentId={meta.get('contentId')}），本 broker 是 "
             f"{instance_id}（contentId={cfg.get('content_id')}）"
             "——那是别的实例的桌面页标签，关掉它")

    @app.websocket("/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        stage.clients.add(ws)
        stage.conn_seq += 1
        meta: dict = {"contentId": None, "instanceId": None, "uiVersion": None,
                      "accepted": False, "reason": "尚未上报 layout",
                      "seq": stage.conn_seq, "stale": False}
        stage.client_meta[ws] = meta
        note_screens()
        await ws.send_text(json.dumps({
            "t": "hello",
            "desktop": stage.desktop,
            "term": cfg["term"],
            "browser": cfg["browser"],
        }))
        # 补发快照，让新客户端立刻拿到完整现状而不是从此刻开始的增量。
        # 几何先于其余状态补发，让窗口一上来就在正确位置，不出现回弹。
        # 补发的依据是 UI 报回来的**实际矩形**，不是 broker 记过的指令。
        # 记指令这条路只覆盖 win，漏掉 split/max/restore——症状是录制机位
        # （现拉的、必然后连）录到的窗口还停在默认位置，而桌面上明明是对开的，
        # 于是成片和当时看到的不是同一个画面，回看才发现。
        replay = [
            {"t": "win", "win": w, "ms": 0, **{k: r[k] for k in "xywh"}}
            for w, r in ((w, stage.elements.get("win:" + w))
                         for w in ("term", "browser", "image"))
            if r
        ] or [{**g, "ms": 0} for g in stage.win_geom.values()]
        # 谁开着谁关着必须补发，且排在几何之前。桌面页刚加载时是"终端和浏览器
        # 开着、图片浏览器没开"这个出厂状态，它自己无从知道此刻终端其实是被
        # 关掉的——不补这一段，录制机位（现拉的、必然后连）会拍到一扇本该不在
        # 的窗口，而成片和当时看到的不是同一个画面，回看才发现。
        power_state = [
            {"t": "win", "win": w, "ms": 0,
             "action": "open" if stage.open.get(w) else "close"}
            for w in ("term", "browser", "image")
        ]
        snapshot: list[dict] = [
            *power_state,
            # 字号排在几何之前：列数行数是"窗口内容区 ÷ 字符格子"，格子由字号定。
            # 反过来的话，荧幕会先拿出厂字号算一遍网格报上来，broker 照它
            # resize 一次 tmux，等字号到了再 resize 回去——一来一回两次
            # SIGWINCH，zsh 每次重印提示符，缓冲区里就多堆一行。
            {"t": "term.fontsize", "px": stage.term_fs},
            *replay,
            {"t": "focus", "win": stage.focus},
            {"t": "cursor", "x": stage.cursor[0], "y": stage.cursor[1], "ms": 0},
        ]
        if stage.last_chrome:
            snapshot.append({**stage.last_chrome, "t": "chrome"})
        if stage.last_image is not None:
            snapshot.append({"t": "image", **stage.last_image})
        term_snapshot = term.snapshot()
        if term_snapshot is not None:
            # 补发整段缓冲区，不是最后一屏：新连上的荧幕（机位就是这种，
            # 现拉的、必然后连）手上一行都没有，只给它当前屏的话，
            # 成片里的终端就没有可回看的历史，而人在自己那块荧幕上明明滚得动。
            snapshot.append({"t": "term", **term_snapshot})
            # 视口停在哪一行也要补发，紧跟在缓冲区后面。
            # 不补的话，新连上的荧幕按出厂状态贴底画——人明明正回看着第 20 行，
            # 一开机位（rec start 每次都是新开的一页）录下来的却是最后一屏，
            # 而 /status 报的是 broker 自己记的那一行，两边说的不是一回事。
            # ms=0：补发是对齐现状，不是演一遍滚动。
            snapshot.append({"t": "term.scroll", "top": stage.term_top,
                             "stuck": stage.term_stuck, "ms": 0})
        if stage.last_frame is not None:
            snapshot.append({"t": "frame", "data": stage.last_frame})
        elif not browser.actor_gone:
            # 一帧都还没有：静止页面不重绘就永远不发帧。给它一脚，
            # 新客户端才不会盯着一扇空窗口。
            # 演员标签已经没了的话不必踢——那一脚不会有任何结果，
            # 而下面那条状态会让页面显示成空标签页。
            asyncio.create_task(browser.start_stream(cfg["fps"]))
        # 补发的最后一帧可能是演员标签消失前那一张。这条跟在它后面，
        # 让新客户端立刻把它换成空标签页，而不是把旧帧当成实时画面。
        if stage.last_actor is not None:
            snapshot.append(stage.last_actor)
        # 补发完毕的信号。荧幕**收到这条之前不许上报几何**——它刚加载时手上是
        # 出厂几何（终端 900x560），那份几何一旦被当真，broker 就照它 resize
        # tmux，然后补发的真几何到了再 resize 回去。一来一回两次 SIGWINCH，
        # zsh 每次都把提示符重印一遍，旧的那行留在历史里。
        #
        # 2026-08-20 实测：`tmux resize-window` 来回改一对，缓冲区里就多一行
        # 一模一样的提示符（7→8→8→9）。而录制机位每次 rec start 都是新开的一页，
        # 于是每录一段就多堆一行——在只显示最后一屏的年代这些行滚出去就看不见了，
        # 有了可回看的缓冲区之后它们全都留在画面上。
        snapshot.append({"t": "synced"})
        for msg in snapshot:
            await ws.send_text(json.dumps(msg))
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                if msg.get("t") == "layout":
                    # 没有 elements 字段的 layout 来自旧版资产的标签页。
                    # 人已经开着的标签不会自动换版本，而它一上报就会把
                    # 元素快照连同几何一起抹掉——症状是 ref 时灵时不灵，
                    # 且完全看不出跟"忘了刷新"有关。整条丢弃，并说出来。
                    if "elements" not in msg:
                        _log("忽略旧版 UI 的 layout 上报——请刷新桌面页标签")
                        meta["accepted"] = False
                        meta["reason"] = "layout 不带 elements（资产过旧）"
                        continue
                    # 归属先于版本：两个实例的资产版本完全可能相同（同一份
                    # 资产复制过去的），那时版本这条防线一个字都拦不住，
                    # 双方轮流覆盖 stage.layout，视口被设成不属于它的那块荧幕
                    # 的尺寸——画面只贴在窗口左上角，而 stale_clients 仍是空的。
                    if not note_identity(meta, msg):
                        reject_log(meta)
                        meta["accepted"] = False
                        meta["reason"] = FOREIGN_REASON
                        continue
                    # 版本对不上同样整条丢弃。人手里可能同时开着好几个桌面页
                    # 标签，旧的那个几何算法不一样，两边轮流覆盖 stage.layout，
                    # 视口就跟着来回改，画面被拉伸变形。认版本，不认先来后到。
                    want = cfg.get("ui_version")
                    got = msg.get("uiVersion")
                    if want and got != want:
                        _log(f"忽略 uiVersion={got} 的 layout（当前 {want}）"
                             "——旧资产的桌面页，已叫它自己刷新")
                        # 叫它刷新，别让人去关。
                        #
                        # 这块荧幕是纯显示器，刷新一次什么都不丢——所有状态
                        # 重连后由 broker 补发。而它留在那儿的代价是真的：
                        # 旧资产算几何的方式不一样，它一上报就跟新的轮流覆盖；
                        # 自检为此长期挂一条 WARN，补救动作是"人去关掉那个标签"，
                        # 而人往往根本不知道哪个标签是旧的（地址一模一样）。
                        # 能自己好的事情不该写进文档让人记。
                        #
                        # 每条连接只叫一次：刷新会重连，重连若还是旧版本
                        # （比如中间层缓存），第二次叫就成了死循环。叫过一次
                        # 仍是旧的，就退回原来那条路——自检点名，人来处理。
                        if not meta.get("reload_sent"):
                            meta["reload_sent"] = True
                            with suppress(Exception):
                                await ws.send_text(json.dumps({"t": "reload"}))
                        # 没有 uiVersion 字段的更旧资产记成 0，否则它被
                        # 当成"无版本"过滤掉，自检就永远不会点它的名。
                        stage.stale_clients = stage.stale_clients | {got or 0}
                        meta["accepted"] = False
                        meta["stale"] = True
                        meta["reason"] = f"uiVersion={got} 与当前 {want} 不符"
                        note_screens()
                        continue
                    # 归属对、版本也对，仍可能是同一实例被开了两块荧幕：
                    # 实例身份永久，桌面页地址永久稳定，历史上开过的每个标签
                    # 只要还在就都会连回来。两块荧幕各有各的窗口几何、轮流上报，
                    # broker 每收一份就 resize 一次舞台视口——视口在两个尺寸之间
                    # 来回跳，而画帧走 letterbox，比例对不上就四周留白，
                    # 看起来像"网页没填满窗口"。只认主荧幕的几何，其余整条丢弃。
                    # 注意帧仍然照发给所有连接（broadcast 不看主不主）：
                    # 它们只是不能上报几何，不是不能看画面——人可能真的想在
                    # 两块屏幕上同时看。这不是漏了，是有意的。
                    if primary_meta() is not meta:
                        meta["accepted"] = False
                        meta["reason"] = DUPLICATE_REASON
                        note_screens()
                        continue
                    meta["accepted"] = True
                    meta["reason"] = None
                    stage.layout = msg
                    stage.layout_seq += 1
                    grid = msg.get("termGrid") or {}
                    if grid.get("cols") and grid.get("rows"):
                        with suppress(Exception):
                            await term.resize(int(grid["cols"]), int(grid["rows"]))
                    # layout 里唯一还影响舞台的东西是这两个度量：桌面可用区
                    # 与浏览器窗口的装饰高度。它们是"这块荧幕长什么样"，
                    # 只有 UI 量得到；几何本身由 broker 算，不再由这里决定。
                    # 演员视口更是一个字都不动——那是演员自己的事。
                    metrics = msg.get("metrics")
                    if isinstance(metrics, dict):
                        changed = metrics != stage.ui_metrics
                        stage.ui_metrics = metrics
                        # 头一次拿到度量、或桌面长相变了，就照新度量重摆一次。
                        if changed:
                            with suppress(Exception):
                                await push_browser_window(
                                    ms=0, reason="收到荧幕度量")
                elif msg.get("t") == "identify":
                    # 握手第一条。收下身份但不改任何舞台状态——身份只决定
                    # 后续 layout 收不收，它自己不是几何。
                    if not note_identity(meta, msg):
                        reject_log(meta)
                        meta["accepted"] = False
                        meta["reason"] = FOREIGN_REASON
                    # 自报身份之后才算数得清有几块荧幕：连接刚建立时还看不出
                    # 它是谁，那一刻数出来的数字会把外来标签也算进去。
                    note_screens()
                elif msg.get("t") == "ready":
                    # 外来荧幕画出首帧不算本实例就绪：它画的是自己那套几何，
                    # 拿它点亮 ui_ready 等于用别人的画面给自己发合格证。
                    # 非主荧幕同理——它画的是一份已被丢弃的几何。
                    if meta.get("reason") == FOREIGN_REASON:
                        continue
                    if primary_meta() is not meta:
                        continue
                    ready.set()
        except WebSocketDisconnect:
            pass
        finally:
            was_primary = primary_meta() is meta
            stage.clients.discard(ws)
            stage.client_meta.pop(ws, None)
            # 主荧幕断开时，剩下的那些里最新的一条立刻接位——primary_meta()
            # 是现算的，接位本身不需要动作，这里只是把它说出来，
            # 免得日志里只看到"少了一块"而不知道几何改跟谁了。
            if was_primary and (top := primary_meta()) is not None:
                _log(f"主荧幕断开，提升 seq={top.get('seq')} 的荧幕为主，"
                     "其 layout 即刻起被采信")
                top["reason"] = "尚未上报 layout"
                # 光是"允许它上报"还不够：layout 只在几何变化时才发，接位的
                # 那块荧幕可能安静很久，这段时间舞台视口还停在已经关掉的那块
                # 的尺寸上——空窗只是从"没有主荧幕"换成了"主荧幕的几何是别人的"。
                # 补一条 hello 逼它立刻重报（UI 收到 hello 就 sendLayout），
                # 不改任何资产，走的是它本来就认识的那条路。
                for other, m in stage.client_meta.items():
                    if m is top:
                        asyncio.create_task(other.send_text(json.dumps({
                            "t": "hello", "desktop": stage.desktop,
                            "term": cfg["term"], "browser": cfg["browser"],
                        })))
                        break
            stage.screen_note = None
            note_screens()

    # ── ref 解析 ──
    #
    # 前缀即域，域决定解析路径。这个 OS 的每个像素都是自己渲染的，位置全是
    # 一手数据：桌面级元素由 UI 全量上报，页面元素在舞台 DOM 里，终端是字符
    # 网格。所以不需要截图加视觉模型——那是把已知信息渲染成像素再猜回来。

    def _available() -> dict:
        return {
            "active": stage.focus,
            "desktop": stage.elements,
            "term_grid": stage.term_grid,
            "hint": "页面内元素四种写法——" + refs.FORMS_HINT + "；"
                    "终端有三档粒度——单个字符格 term:r<行>c<列>（行列均 0 基，"
                    "指哪儿点哪儿用它）、一段输出 term:rows 5-12 / term:rows -8 / "
                    'term:match "文字"（只能取景，是终端镜头最常用的一档）、'
                    "整扇窗口 win:term；桌面级 ref 见 desktop 字段",
        }

    async def page_find(text: str | None = None,
                        selector: str | None = None) -> list[dict]:
        """在舞台浏览器里定位元素，返回页面坐标（尚未换算）。

        text / selector 二选一这条老路留着：op_elements 的 --text / --selector
        是调用方**已经说明了按哪种找**，没有判型这回事。要判型的走 page_locate。
        """
        return await page_query(browser.evaluate, text=text, selector=selector)

    # ── 效果落定（settle） ──
    #
    # navigate 早就在做这件事：发出导航后等 load 事件、再等一帧新画面到达，
    # 确认渲染结果真的传过来了才返回。下面把这套抽成所有"会改变世界"的 op
    # 通用的能力。这条立住之后，指令不再需要靠外挂 sleep 去猜效果什么时候到——
    # 那些猜出来的等待时间本质上是在补偿反馈来得太早。
    #
    # 超时不是失败：如实报告"在这段时间里没有观察到变化"，让调用方自己判断
    # 该不该往下走。绝不因为观察不到就把回执写成成功。

    probe_cache: dict = {"at": 0.0, "value": None}

    async def page_probe(reuse_within: float = 0.0) -> dict | None:
        """取页面指纹。连接断了或页面拒绝执行 JS 就返回 None，不编造。

        reuse_within 允许复用刚取过的那一次。录制时观察快照会在每条指令
        发出前取一次指纹，而 click / type / key 紧接着还要取一次同样的
        "动作前"指纹——两次之间只隔着一次函数调用，让它们共用一次往返，
        录制不必为此多付一趟 JS 的钱。窗口取得很短（毫秒级的相邻调用），
        跨指令的旧值一律取不到复用。settle 循环用默认 0，永远取新鲜的。
        """
        if reuse_within and (time.time() - probe_cache["at"]) <= reuse_within:
            return probe_cache["value"]
        try:
            value = await browser.evaluate(_PAGE_PROBE)
        except Exception as exc:
            _log(f"页面探针失败: {type(exc).__name__}: {exc}")
            value = None
        probe_cache["at"] = time.time()
        probe_cache["value"] = value
        return value

    # ── 观察快照 ──
    #
    # 训练样本的另一半。日志里有动作、有结果，唯独缺"动作发生之前世界是什么样"——
    # 缺了它模型只能模仿动作序列，学不到为什么在这一步选这个动作。而观察是当时
    # 的现场，录制结束后页面早已变化，**事后无法重建**，所以它必须在动作发出前
    # 采集，且只能在录制期间付这份成本。

    def _term_tail(lines: int = 8) -> list[str] | None:
        """终端缓冲区末尾若干行纯文本。整份内容就在内存里，零往返。

        取的是缓冲区而不是可见屏：末尾那几行本来就是最新的，而人正回看历史时
        可见屏里根本没有它们——观察记的是"世界是什么样"，不是"荧幕在看哪儿"。
        """
        rows = term.plain_lines()
        if not rows:
            return None
        while rows and not rows[-1].strip():
            rows.pop()
        return rows[-lines:]

    async def observe() -> dict:
        """动作发出**之前**的世界快照。

        桌面级元素、焦点、鼠标、终端画面都是 broker 内存里的现成数据，零成本；
        只有 url / title 需要一次 JS 往返，且随后的 click / type / key 会复用
        这同一次探针结果，实际并不额外增加往返。
        取不到的项如实记进 unavailable，绝不省略、绝不填假值。
        """
        unavailable: dict[str, str] = {}
        probe = await page_probe()
        if not isinstance(probe, dict):
            for k in ("url", "title", "page_text_len", "scroll_y"):
                unavailable[k] = "页面探针无回应（连接断开或页面不可执行 JS）"
            probe = {}
        tail = _term_tail()
        if tail is None:
            unavailable["term_tail"] = "终端尚未上报任何画面"
        refs = sorted(stage.elements.keys())
        if not refs:
            unavailable["refs"] = "桌面页尚未上报 elements（标签页未连接或资产过旧）"
        return {
            "refs": refs,
            "url": probe.get("url"),
            "title": probe.get("title"),
            "page_text_len": probe.get("len"),
            "scroll_y": probe.get("scrollY"),
            "focus": stage.focus,
            "cursor": {"x": round(stage.cursor[0], 1),
                       "y": round(stage.cursor[1], 1)},
            "hover": (stage.hover or {}).get("ref"),
            "term_tail": tail,
            "unavailable": unavailable,
        }

    def _page_moved(a: dict | None, b: dict | None) -> bool:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        return any(a.get(k) != b.get(k) for k in
                   ("url", "title", "hash", "nodes", "scrollY", "value"))

    async def settle_page(before: dict | None, frame_before: str | None,
                          timeout_ms: int) -> tuple[dict, dict]:
        """等页面效果落定，返回（最后一次探针, 变化摘要）。

        判定顺序有讲究：DOM / URL 变化是确定性信号，一出现立刻返回，这就是
        "落定即返回"；只有帧变（悬停高亮之类的纯视觉反应）不足以断定动作生效，
        继续等满窗口再如实汇报。窗口耗尽也照样返回摘要，不抛错。
        """
        t0 = time.time()
        deadline = t0 + timeout_ms / 1000
        after = before
        moved = False
        while time.time() < deadline:
            await asyncio.sleep(0.06)
            after = await page_probe()
            if _page_moved(before, after):
                moved = True
                break
        effect = _diff_page(before, after)
        effect["frame_changed"] = (browser.latest_frame is not frame_before
                                   and browser.latest_frame is not None)
        effect["waited_ms"] = int((time.time() - t0) * 1000)
        # 说清楚是"等到了"还是"等满了也没等到"。后者不是失败，是一条事实。
        effect["settled"] = moved
        if not moved and effect.get("observed"):
            effect["note"] = "等待窗口内未观察到页面变化"
        return (after if isinstance(after, dict) else {}), effect

    async def settle_term(before: list[str] | None, timeout_ms: int,
                          quiet_ms: int = 260) -> dict:
        """等终端落定：先等它开始变，再等它不再变。

        只等"开始变"是不够的——命令刚回显第一行就返回，读到的是半截输出。
        追加一段静默期，连续 quiet_ms 没有新变化才算这条命令跑完了。

        判"变了没有"看的是轮询的序号而不是画面文本：输出一直往下滚时，可见屏
        的文本可能两轮之间碰巧一样（比如满屏同样的进度点），而缓冲区确实在长。
        """
        deadline = time.time() + timeout_ms / 1000
        changed_at = None
        last = term._seq
        while time.time() < deadline:
            await asyncio.sleep(0.06)
            cur = term._seq
            if cur != last:
                last = cur
                changed_at = time.time()
                continue
            if changed_at is not None and (time.time() - changed_at) * 1000 >= quiet_ms:
                break
        return _diff_term(before, term.plain_lines())

    async def settle_layout(seq_before: int, timeout_ms: int) -> bool:
        """等 UI 把新几何报回来。窗口动作的效果由 UI 计算，它报到才算落定。"""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if stage.layout_seq != seq_before:
                return True
            await asyncio.sleep(0.04)
        return False

    async def with_detail(step: dict, out: dict) -> dict:
        """细节显式索取：默认只回变化摘要，detail=true 才带上全文。

        默认不返回全量 DOM 快照——判断"该不该往下走"用不到它，而它会把
        真正的信号淹掉。
        """
        if not step.get("detail"):
            return out
        det: dict = {}
        with suppress(Exception):
            det["page_text"] = await browser.evaluate(
                "document.body ? document.body.innerText : ''")
        if term._last is not None:
            # 画面上看得见的那一段，与 term_text 这个名字的原意一致。
            # 整个缓冲区不从这儿走：它有几千行，而 detail 是"顺手多给一点"，
            # 不是"把仓库倒出来"。要全量走 term read --lines。
            det["term_text"] = "\n".join(term_screen_lines())
            det["term_view"] = term_view_state()
        out["detail"] = det
        return out

    async def resolve_ref(ref: str) -> dict:
        if not isinstance(ref, str) or not ref.strip():
            raise RefError("ref 必须是非空字符串", _available())
        ref = ref.strip()

        if refs.is_page_ref(ref):
            found = await page_locate(browser.evaluate, refs.page_body(ref))
            hits = found["hits"]
            if not hits:
                raise RefError(
                    refs.miss_message(ref, found["tried"]),
                    {**_available(), "ref_tried": found["tried"],
                     "ref_form": found["form"]})
            h = hits[0]
            what = f"按{'文字' if found['matched_by'] == 'text' else '选择器'} " \
                   f"{found['needle']!r}"
            # 候选已按"点得到"排序，第一个都够不到就说明整批都被盖住了。
            # 照样把鼠标挪过去再点，只会点到压在上面的那个元素——
            # 一次寻址失败伪装成一次成功的点击，故障延后到画面上才暴露。
            if h.get("reachable") is False:
                raise RefError(
                    f"page ref 命中 {len(hits)} 个元素但都点不到（{what}），"
                    f"中心点被 {h.get('covered_by')} 盖住",
                    {**_available(), "page_hits": hits,
                     "ref_tried": found["tried"]},
                )
            x, y = stage.to_desktop("browser", h["x"], h["y"],
                                    browser.width, browser.height)
            out = {"ref": ref, "kind": "page", "x": x, "y": y,
                   "page": {"x": h["x"], "y": h["y"]},
                   "text": h.get("text"), "tag": h.get("tag"),
                   "reachable": h.get("reachable"), "matches": len(hits),
                   # 按哪种解释命中的，恒在回执里：同一个字符串当选择器与当
                   # 文字命中的完全可能是两个元素，不说破就又是一次"看着正常"。
                   "matched_by": found["matched_by"], "ref_form": found["form"]}
            if found["note"]:
                out["ref_note"] = found["note"]
            return out

        if ref.startswith("term:"):
            m = re.fullmatch(r"r(\d+)c(\d+)", ref[5:].strip())
            if not m:
                # 区域形态（rows / match）拿到的是一片矩形，不是一个点，
                # 所以只有 camera 认它。这里说清楚，免得当成拼写错误去改。
                raise RefError(
                    f"这条路要的是一个点，ref 形如 term:r12c40，收到 {ref}"
                    + ("（term:rows / term:match 是区域形态，只能给 camera 用）"
                       if ref[5:].strip().split(" ")[0] in ("rows", "match")
                       else ""),
                    _available())
            g = stage.term_grid
            if any(g.get(k) is None for k in ("x", "y", "cellW", "cellH")):
                raise RefError("终端网格尚未上报，无法换算 term ref", _available())
            row, col = int(m.group(1)), int(m.group(2))
            return {"ref": ref, "kind": "term", "row": row, "col": col,
                    "x": g["x"] + (col + 0.5) * g["cellW"],
                    "y": g["y"] + (row + 0.5) * g["cellH"]}

        rect = stage.elements.get(ref)
        if rect is None:
            raise RefError(f"未知 ref: {ref}", _available())
        return {"ref": ref, "kind": "desktop", "rect": rect,
                "x": rect["x"] + rect["w"] / 2,
                "y": rect["y"] + rect["h"] / 2}

    # ── 操控 ──

    async def op_cursor(step: dict) -> Any:
        act = None
        if "ref" in step:
            info = await resolve_ref(step["ref"])
            x, y = float(info["x"]), float(info["y"])
            stage.hover = info
            # 带 ref 的移动已经说明目标是谁，先把那扇窗口提到最上层再动鼠标。
            #
            # 漏掉这一步的后果不是"少了个动画"。下面判断鼠标落在哪扇窗口用的是
            # 层级顺序（window_at 从 active 那扇开始找），浏览器被终端压着时会
            # 判成 term，于是悬停不转发给真实浏览器——菜单不展开、按钮不高亮，
            # 而回执里只写着 win=term，看不出哪里错了。
            #
            # 靠后面那一步 click 补激活是不够的：`browser click` 恒是
            # cursor + click 两步，那样鼠标会先当着镜头从错误的窗口上划过去，
            # 窗口在按下的瞬间才跳到前面。与 camera 那条同理——凡是"漏了一步
            # 就静默拍错"的东西都不该留给调用方记性。
            #
            # 焦点只改层级不改几何，所以 x/y 在激活前后是同一个值，先算后激活
            # 没有先后问题。
            act = await ensure_active(target_window(info))
            if act and act["focus_changed"]:
                # 层级要先落到画面上再开始补间，否则鼠标出发的头几帧拍到的
                # 还是旧层级。与 activate_for_camera 用同一个量。
                await asyncio.sleep(0.12)
        else:
            x, y = float(step["x"]), float(step["y"])
            stage.hover = None      # 纯坐标移动解除绑定，退回坐标命中
        ms = int(step.get("ms", 600))
        stage.cursor = (x, y)
        await broadcast({"t": "cursor", "x": x, "y": y, "ms": ms,
                         "ease": step.get("ease", "cubic-bezier(.4,0,.2,1)")})
        # 等补间走完再返回，否则下一条指令会在鼠标还在半路时就生效。
        await asyncio.sleep(ms / 1000)
        # 悬停也要真实发生：很多界面靠 hover 出效果，画面里手停在按钮上
        # 而按钮没亮，观众一眼就觉得假。
        win = stage.window_at(x, y)
        if win == "browser":
            px, py = stage.to_page(win, x, y, browser.width, browser.height)
            await browser.mouse("mouseMoved", px, py)
        out: dict = {"win": win, "x": round(x, 1), "y": round(y, 1)}
        if stage.hover:
            out["ref"] = stage.hover["ref"]
            out["kind"] = stage.hover["kind"]
            if stage.hover.get("text"):
                out["text"] = stage.hover["text"]
        # 顺带提前的窗口如实并进回执，别静默改状态——调用方要能看出
        # "我这条移动指令把一扇窗口提到了前面"。
        if act is not None:
            out["effect"] = _with_focus({"observed": True}, act)
        return out

    async def desktop_action(ref: str) -> dict:
        """桌面级元素的点击由窗口管理器执行，不转发给任何应用。

        与真实 OS 一致：点 dock 是窗口管理器的事，不是应用的事。
        """
        if ref.startswith("dock:"):
            win = ref.split(":", 1)[1]
            if win in ("term", "browser", "image"):
                was = stage.focus
                was_open = stage.open.get(win, False)
                # 点关着的程序就是启动它，与真实 dock 一致；op_focus 自己会开。
                # 这里曾经对图片浏览器单独判"没有打开的图片就拒绝"——那是它
                # 用"有没有图"冒充"窗口在不在"留下的疤，现在开关是独立状态，
                # 三个程序在这条路上没有差别。
                out = await op_focus({"win": win})
                # 点一个已经在前台的程序，世界并没有变。如实说出来，
                # 别拿"成功"糊过去——L2 命中了不等于 L3 生效。
                noop = was == win and was_open
                return {"acted": True,
                        "action": "launch" if not was_open else "focus",
                        "win": win,
                        "focus_changed": was != win,
                        "launched": None if was_open else win,
                        "noop": noop,
                        "note": None if not noop
                                else f"{win} 本来就是 active，这一下是多余动作",
                        "effect": out["effect"]}
        if ref.startswith("tab:"):
            idx = ref.split(":", 1)[1]
            if idx.isdigit():
                out = await op_tab({"action": "switch", "index": int(idx)})
                return {"acted": True, "action": "tab.switch",
                        "index": int(idx), **out}
        return {"acted": False, "reason": f"{ref} 无点击语义"}

    async def op_click(step: dict) -> Any:
        x, y = stage.cursor
        dwell = int(step.get("dwell", 120))
        settle_ms = int(step.get("settle_ms", 1500))
        # 动作之前先把世界的样子记下来，否则事后无从判断它变没变。
        # 录制时观察快照刚刚取过同一份指纹，复用它，不重复往返。
        page_before = await page_probe(reuse_within=0.3)
        frame_before = browser.latest_frame
        term_before = term.plain_lines()
        focus_before = stage.focus
        await broadcast({"t": "click", "phase": "down"})
        try:
            # 悬停绑定优先。ref 已经说明了目标是谁，就按它的语义走——
            # 一两像素的补间误差不该让点击落空。
            target = stage.hover
            if target is None:
                # 无绑定时先问窗口管理器：dock 与标签压在窗口之上，
                # 它们的命中优先于窗口内容区。
                ref = stage.element_at(x, y, refs=[
                    r for r in stage.elements if r.startswith(("dock:", "tab:"))
                ])
                if ref:
                    target = {"ref": ref, "kind": "desktop"}
            if target and target["kind"] == "desktop":
                seq = stage.layout_seq
                out = await desktop_action(target["ref"])
                await settle_layout(seq, 600)
                return await with_detail(step, {
                    "hit": target["ref"], "win": None, "clicked": False, **out,
                    "effect": {"observed": True,
                               "focus": {"before": focus_before,
                                         "after": stage.focus},
                               "focus_changed": focus_before != stage.focus,
                               "layout_reported": stage.layout_seq != seq},
                })

            win = "browser" if (target and target["kind"] == "page") else \
                  "term" if (target and target["kind"] == "term") else \
                  stage.window_at(x, y)
            if win == "browser":
                px, py = stage.to_page(win, x, y, browser.width, browser.height)
                await browser.mouse("mousePressed", px, py,
                                    step.get("button", "left"))
                await asyncio.sleep(dwell / 1000)
                await browser.mouse("mouseReleased", px, py,
                                    step.get("button", "left"))
            elif win in ("term", "image"):
                # 图片窗口不是可交互页面：点击只做焦点切换，没有输入事件可发。
                await asyncio.sleep(dwell / 1000)
            else:
                # 不在任何窗口内容区：看看是不是别的桌面级元素（标题栏、地址栏）。
                ref = stage.element_at(x, y)
                if ref:
                    seq = stage.layout_seq
                    out = await desktop_action(ref)
                    await settle_layout(seq, 600)
                    return await with_detail(step, {
                        "hit": ref, "win": None, "clicked": False, **out,
                        "effect": {"observed": True,
                                   "focus": {"before": focus_before,
                                             "after": stage.focus},
                                   "focus_changed": focus_before != stage.focus},
                    })
                return await with_detail(step, {
                    "hit": None, "win": None, "clicked": False, "acted": False,
                    "reason": "点击落空：不在任何窗口或桌面元素上",
                    "effect": {"observed": True, "settled": False,
                               "dom_changed": False, "url_changed": False,
                               "note": "未命中任何目标，未发出任何输入事件"},
                })
            act = await ensure_active(win)
            # 效果落定即返回：页面动了就立刻走，没动就等满窗口如实说没观察到变化。
            if win == "browser":
                _, effect = await settle_page(page_before, frame_before, settle_ms)
            else:
                # 点终端只改焦点，不送输入，没有值得久等的效果；短窗口够了。
                effect = await settle_term(term_before, min(settle_ms, 500))
            effect = _with_focus(effect, act)
            return await with_detail(step, {
                "hit": (target or {}).get("ref"), "win": win,
                "clicked": win == "browser", "acted": True,
                "target": {"kind": (target or {}).get("kind"),
                           "text": (target or {}).get("text"),
                           "tag": (target or {}).get("tag")} if target else None,
                "at": {"x": round(x, 1), "y": round(y, 1)},
                "effect": effect,
            })
        finally:
            await broadcast({"t": "click", "phase": "up"})

    async def op_elements(step: dict) -> Any:
        """列出当前可寻址元素。agent 的"眼睛"——没有它只能猜 ref。"""
        if step.get("in") == "browser":
            text, selector = step.get("text"), step.get("selector")
            # ref 这条路是给"要判型"的调用方走的（aos 的 wait --for page:...）：
            # 它手上只有一个 ref 字符串，凭什么判成文字还是选择器不该由它决定，
            # 否则判型又多出第三份。text / selector 那条老路留着——那是调用方
            # 已经说明了按哪种找，没有判型这回事。
            probe = step.get("ref")
            if not text and not selector and not probe:
                raise ValueError('elements --in browser 需要 ref、text 或 selector')
            # 在浏览器里找元素是指向浏览器的动作。observe=true 同 op_exec：
            # frago desktop wait 拿它当探针，那条路只看不做。
            act = None if step.get("observe") else await ensure_active("browser")
            found: dict | None = None
            if probe:
                if not refs.is_page_ref(probe):
                    raise ValueError(
                        f"elements --in browser 的 ref 要以 page: 开头，收到 {probe}")
                found = await page_locate(browser.evaluate, refs.page_body(probe))
                hits, ref = found["hits"], probe
            else:
                hits = await page_find(text=text, selector=selector)
                ref = f'page:"{text}"' if text else f"page:{selector}"
            items = []
            for i, h in enumerate(hits):
                dx, dy = stage.to_desktop("browser", h["x"], h["y"],
                                          browser.width, browser.height)
                items.append({
                    "ref": ref, "index": i,
                    "tag": h.get("tag"), "text": h.get("text"),
                    "reachable": h.get("reachable"),
                    "covered_by": h.get("covered_by"),
                    "desktop": {"x": round(dx, 1), "y": round(dy, 1)},
                    "page": {"x": round(h["x"], 1), "y": round(h["y"], 1),
                             "w": round(h["w"], 1), "h": round(h["h"], 1)},
                })
            out: dict = {"in": "browser",
                         "query": {"text": text, "selector": selector,
                                   "ref": probe},
                         "count": len(items), "matches": items,
                         "note": "ref 解析取第一个命中" if len(items) > 1 else None}
            if found is not None:
                # 探针也要说清判型走到了哪一跳：`wait --for` 超时时，
                # "选择器不合法"与"元素还没出现"是两件事，回执里分得开才查得动。
                out["ref_form"] = found["form"]
                out["matched_by"] = found["matched_by"]
                out["ref_tried"] = found["tried"]
                if found["note"]:
                    out["ref_note"] = found["note"]
            if act is not None:
                out["effect"] = _with_focus({"observed": True}, act)
            return out
        # active/active_ref 与 focus 是同一件事的两种说法：focus 是原有键，
        # 保留不动；active_ref 直接给出"这个程序对应哪个 dock ref"，
        # agent 拿它和自己想点的 ref 一比就知道该不该点，不用自己拼字符串。
        return {"in": "desktop", "count": len(stage.elements),
                "active": stage.focus,
                "active_ref": ("dock:" + stage.focus) if stage.focus else None,
                # 哪些程序开着，一眼可见。没有它的话，agent 只能从 desktop 里
                # 有没有 win:<w> 反推，而"没这个 ref"同时也可能是窗口收起来了。
                "windows_open": dict(stage.open),
                "desktop": stage.elements, "term_grid": stage.term_grid,
                "focus": stage.focus,
                "hover": (stage.hover or {}).get("ref")}

    # ── 程序的开与关 ──
    #
    # 三个程序（term / browser / image）共用这一条路。此前只有图片浏览器关得掉，
    # 而且走的是它自己那条 image.close——终端和浏览器根本没有"关掉"这个动作，
    # 最接近的 window min 只是收进 dock（灯还亮着）。想录一段"演示完把终端关掉、
    # 只留浏览器"的镜头就演不出来。
    #
    # **关掉不动载体。** tmux 会话、演员标签、已经装进图片浏览器的那张图全部留着，
    # 所以 open 回来的是原样。杀掉它们在画面上看不出任何区别（观众只看到窗口没了），
    # 代价却是真的：跑了一半的会话没了、登录态没了、重新拉起要几十秒。

    WINDOWS = ("term", "browser", "image")
    # 关掉当前前台程序之后，焦点让给谁。终端排第一是因为它是这个 OS 的默认落点，
    # 原先 image.close 也是还给它。三个都关着就交出 None，不硬找一个。
    FOCUS_ORDER = ("term", "browser", "image")

    def next_focus(closing: str) -> str | None:
        for w in FOCUS_ORDER:
            if w != closing and stage.open.get(w):
                return w
        return None

    async def set_focus(win: str | None) -> dict:
        """只改层级，不管开关。开关是 power 的事，两者分开才不会互相递归。"""
        before = stage.focus
        if before == win:
            return {"before": before, "after": win, "focus_changed": False}
        stage.focus = win
        await broadcast({"t": "focus", "win": win})
        return {"before": before, "after": win, "focus_changed": True}

    async def power(win: str, want_open: bool, ms: int = 260) -> dict:
        """开或关一个程序。程序在不在桌面上，只由这个函数改。"""
        if stage.open.get(win, False) == want_open:
            return {"changed": False, "open": want_open}
        stage.open[win] = want_open
        await broadcast({"t": "win", "win": win,
                         "action": "open" if want_open else "close",
                         "ms": int(ms)})
        if want_open:
            # 几何要在窗口重新出现时一并交代清楚。浏览器那份由 broker 算
            # （演员视口的宽高比可能在关着的这段时间变过），图片窗口沿用它
            # 上一次按图片比例算好的那份。不补这一下，重新打开的窗口会停在
            # UI 侧的默认位置上，而 broker 手里记的还是旧值，两边对不上。
            if win == "browser":
                with suppress(Exception):
                    await push_browser_window(ms=0, reason="浏览器重新打开")
            elif win == "image" and stage.win_geom.get("image"):
                await broadcast({**stage.win_geom["image"], "ms": 0})
            # 启动即置前台：现实里打开一个程序，它的窗口就在最上面。
            await set_focus(win)
        elif stage.focus == win:
            await set_focus(next_focus(win))
        return {"changed": True, "open": want_open}

    async def op_focus(step: dict) -> Any:
        win = step["win"]
        if win not in WINDOWS:
            raise ValueError(f"未知窗口: {win}")
        before = stage.focus
        # 点名一个关掉的程序 = 把它打开，与点 dock 图标一致。报错更"严格"，
        # 但那只是把一条本该自动的动作推给调用方记性，而这个 OS 里凡是
        # "漏一步就静默出错"的东西都由代码兜住。
        launched = await power(win, True, int(step.get("ms", 260)))
        await set_focus(win)
        out = {"focus": win, "noop": before == win and not launched["changed"],
               "effect": {"observed": True,
                          "focus": {"before": before, "after": win},
                          "focus_changed": before != win}}
        if launched["changed"]:
            out["launched"] = win
            out["effect"]["launched"] = win
            out["note"] = f"{win} 原本没开着，这一下把它打开了"
        return out

    # ── 自动激活 ──
    #
    # 规则：任何指向某扇窗口的动作，先把那扇窗口置为 active；active 窗口恒在
    # 最上层（UI 的 .stage-window.focused 压住 :not(.focused)）。
    #
    # 为什么必须自动、不能靠调用方记得先发 focus：2026-07-24 录 twitter 时
    # `camera focus --ref page:"Explore" --zoom 1.8` 回执全绿——ok、
    # target_in_frame、clamped 全部正确——而画面里推近框住的是压在上面的终端窗口。
    # camera 对准的是"元素在桌面坐标系里应该在的位置"，它没有、也不可能有
    # "那个位置现在显示着什么"这个信息，所以这类错误在回执里一个字都看不出来，
    # 只有录完抽帧才发现，那时现场早没了。凡是"漏发一条指令就静默拍错"的东西，
    # 都不该留给纪律，要么代码替它做掉，要么根本不该存在。
    #
    # op_focus 保留为显式动词（人明确要换焦点时用），这里是它的幂等封装：
    # 已经是 active 就 no-op，不广播、不产生多余的 layout 上报。
    async def ensure_active(win: str | None) -> dict | None:
        """把目标程序弄成"开着且在最前面"。关着就顺手打开——同 op_focus 的理由：
        `term run` 打在一个关掉的终端上，正确的结果是终端回来并执行，
        不是报一句"你得先打开它"。真要拍空桌面，别发这条指令就是了。"""
        if win not in WINDOWS:
            return None
        before = stage.focus
        launched = await power(win, True)
        if before == win and not launched["changed"]:
            return {"before": before, "after": before, "focus_changed": False}
        await set_focus(win)
        act = {"before": before, "after": win, "focus_changed": before != win}
        if launched["changed"]:
            act["launched"] = win
        return act

    def _with_focus(effect: dict, act: dict | None) -> dict:
        """把激活结果如实并进 effect。绝不静默改状态——调用方要能从回执看出
        "我这条指令顺带把窗口提到了前面"。形状照抄 op_click 原有的那份。"""
        if act is not None:
            effect["focus"] = {"before": act["before"], "after": act["after"]}
            effect["focus_changed"] = act["focus_changed"]
            if act.get("launched"):
                # 顺手启动一个程序比顺手换焦点动静大得多（画面上多一扇窗），
                # 混在 focus_changed 里说不清，单列一项。
                effect["launched"] = act["launched"]
        return effect

    def _with_term_view(effect: dict) -> dict:
        """人正回看历史时，新输出**不在画面上**——这件事必须说出来。

        终端有了可回看的缓冲区之后就多了一种状态：命令照跑、缓冲区照长，
        而窗口停在几百行之前，观众什么都看不到。回执里没有这一句的话，
        它和"一切正常"长得一模一样，只有回看成片才发现那一段白录了。
        """
        v = term_view_state()
        if not v["stuck"]:
            effect["view_detached"] = {
                **v,
                "note": "终端窗口停在历史里，新输出不在画面上（缓冲区照常在长）",
                "how_to_fix": "frago desktop term scroll --to-end",
            }
        return effect

    def require_focus(what: str) -> str:
        """键盘要有接收方。三个程序全关掉时没有，这时必须明说而不是往空处送。

        现实里也没有"对着空桌面打字"这回事。不拦的话 target_win 是 None，
        代码会走进浏览器分支，把字送给一扇不在桌面上的窗口——命令看着成功，
        画面上什么都没发生。
        """
        if stage.focus is None:
            raise ValueError(
                f"桌面上没有开着的程序，{what}没有接收方——"
                "先 `frago desktop window open --target term|browser|image`"
            )
        return stage.focus

    async def op_type(step: dict) -> Any:
        """输入回报：目标窗口是谁、实际送入了什么、目标区域内容有无变化。"""
        text = step["text"]
        settle_ms = int(step.get("settle_ms", 1200))
        # 打字送给**当前 active 的窗口**，这是键盘本来的语义（现实里也没有
        # "对着后台窗口打字"这回事）。所以目标窗口就是 stage.focus，
        # ensure_active 在这里恒为 no-op——留着是为了回执形状统一，
        # 也为了将来真出现"指定窗口输入"时只需改这一行。
        target_win = require_focus("输入文字")
        act = await ensure_active(target_win)
        if target_win == "term":
            before = term.plain_lines()
            await term.send_text(text)
            effect = await settle_term(before, settle_ms)
        else:
            page_before = await page_probe(reuse_within=0.3)
            frame_before = browser.latest_frame
            await browser.insert_text(text)
            _, effect = await settle_page(page_before, frame_before, settle_ms)
        if target_win == "term":
            effect = _with_term_view(effect)
        return await with_detail(step, {
            "typed": len(text), "win": target_win, "sent": text,
            "effect": _with_focus(effect, act),
        })

    async def op_key(step: dict) -> Any:
        name = step["key"]
        settle_ms = int(step.get("settle_ms", 1500))
        # 与 op_type 同理：按键送给当前 active 的窗口，往浏览器里按 Enter 走的
        # 就是这条路（target_win == "browser" 时进 browser.key 分支）。
        # 这里从来不是"写死 term"——写死 term 的是 op_shell，那条是对的：
        # 执行命令本来就只可能发生在终端里。
        target_win = require_focus(f"按 {name}")
        act = await ensure_active(target_win)
        if target_win == "term":
            before = term.plain_lines()
            await term.send_key(name)
            effect = await settle_term(before, settle_ms)
        else:
            page_before = await page_probe(reuse_within=0.3)
            frame_before = browser.latest_frame
            await browser.key(name)
            _, effect = await settle_page(page_before, frame_before, settle_ms)
        if target_win == "term":
            effect = _with_term_view(effect)
        return await with_detail(step, {
            "key": name, "win": target_win, "sent": name,
            "effect": _with_focus(effect, act),
        })

    async def op_shell(step: dict) -> Any:
        """执行命令，等它真的跑完再返回，回报终端新增了什么。

        v1 回的是命令原文——那只证明字符送进去了，不证明命令跑过、更不证明
        跑出了什么。这里等终端画面先变、再静默下来，把新增行如实带回。
        """
        settle_ms = int(step.get("settle_ms", 8000))
        act = await ensure_active("term")
        before = term.plain_lines()
        await term.send_text(step["cmd"])
        await asyncio.sleep(step.get("pause", 0.25))
        await term.send_key("Enter")
        effect = await settle_term(before, settle_ms)
        return await with_detail(step, {
            "cmd": step["cmd"], "win": "term",
            "effect": _with_focus(_with_term_view(effect), act),
        })

    async def op_term_fontsize(step: dict) -> Any:
        """改终端字号——录制构图的第一变量。

        画面上的字有多大只由这一个数决定。想靠别的路子把字弄大都是白费：
        窗口做大只会换来更多列（列数 = 窗口内容区 ÷ 字符格子），手动
        `tmux resize-window` 撑不过下一次窗口变动（荧幕按自己的字号重算网格
        再上报，broker 照它把 tmux 改回去）。2026-08-20 实测过两次都是这样。

        代价是列数行数跟着变少，长命令会折行——这是字大的必然结果，
        不是故障。改完拿回执里的 grid 对一眼够不够放要拍的那几行。
        """
        px = int(step.get("px", 13))
        if not 8 <= px <= 64:
            raise ValueError(
                f"字号 {px} 不在 8-64 内。录制档实测 24-28px 在 1080p 上手机可读，"
                f"13px 是人自己看这块荧幕的默认值")
        before = dict(stage.term_grid)
        stage.term_fs = px
        seq = stage.layout_seq
        await broadcast({"t": "term.fontsize", "px": px})
        # 等荧幕把按新格子算出来的网格报回来。它报到 broker 才会 resize tmux，
        # 所以这一步不等的话，回执里的 grid 还是旧的那份。
        reported = await settle_layout(seq, 1500)
        after = stage.term_grid
        return {
            "win": "term", "font_size": px,
            "layout_reported": reported,
            "grid": {k: after.get(k) for k in ("cols", "rows", "cellW", "cellH")},
            "before": {k: before.get(k) for k in ("cols", "rows", "cellW", "cellH")},
            "effect": {"observed": reported, "changed": after != before},
            "note": ("tmux 已按新网格 resize。列数变少是字变大的必然结果——"
                     "要放得下长命令就把终端窗口摆宽一点，别回头调字号"),
        }

    async def op_term_scroll(step: dict) -> Any:
        """把终端窗口的视口挪到缓冲区的某一段——回看。

        缓冲区是完整的，窗口只有几十行高；这条指令决定那几十行取自哪儿。
        它不碰 tmux 一个字节：滚的是荧幕上那扇窗口的视口，跑着的会话、
        当前屏的内容全都不受影响。

        滚动是**画面上看得见的动作**，所以走补间而不是瞬移，时长由 --ms 定：
        录进片子里的回看，观众要跟得上眼睛。
        """
        act = await ensure_active("term")
        # 收起或关掉时明确报错（复用取景那条路的判词），不往一扇不在桌面上的
        # 窗口发滚动指令——那样回执一切正常，画面什么都没发生。
        term_geometry()
        view = term_view_state()
        rows, total = view["rows"], view["buffer_lines"]
        max_top = view["max_first_row"]
        before = view["first_row"]
        hit: dict = {}

        if step.get("to_end"):
            target, how = max_top, "to-end"
        elif "to" in step:
            text = str(step["to"])
            buf = term.plain_lines()
            hits = [i for i, ln in enumerate(buf) if text in ln]
            if not hits:
                raise RefError(
                    f"缓冲区里没有 {text!r}（共 {total} 行）",
                    {**_available(), "term_view": view})
            # 取最后一处：终端往下滚，同样的文字出现多次时最新那次才是刚发生的。
            # 命中行摆在窗口中间，不摆在第一行——上下文比命中行本身更能说明
            # 那是什么，而报错那一行单独顶在最上面往往读不懂。
            row = hits[-1]
            target = max(0, min(row - rows // 2, max_top))
            how = "to-text"
            # 命中在哪一行必须回报。没有它，"命中行摆在窗口中间"这句承诺在回执里
            # 无从验证——调用方只看得到一个 first_row，没法判断那到底是不是它要的
            # 那一行，而这正是要拿去对镜头的数字。
            hit = {"matched": text, "matched_row": row, "matches": len(hits),
                   "matched_text": buf[row],
                   "matched_screen_row": row - target}
        elif "lines" in step:
            target = max(0, min(before + int(step["lines"]), max_top))
            how = "lines"
        else:
            raise ValueError("term scroll 需要 --lines <n> | --to <文字> | --to-end")

        # 位置在这里定下，荧幕只是执行。贴不贴底也由这里说了算：滚到底就是
        # 贴底（新输出跟着走），没到底就是松开（回看不该被新输出拽回去）。
        stage.term_top = target
        stage.term_stuck = target >= max_top
        ms = int(step.get("ms", 400))
        seq = stage.layout_seq
        await broadcast({"t": "term.scroll", "top": target,
                         "stuck": stage.term_stuck, "ms": ms})
        # 等补间走完，再等荧幕把 layout 报回来——它不再决定行号，但它报回来的
        # scrollTop 是对账用的：对不上就说明那块荧幕没执行到位。
        await asyncio.sleep(ms / 1000)
        reported = await settle_layout(seq, 800)
        after = term_view_state()
        lines = term.plain_lines()[after["first_row"]:
                                   after["first_row"] + after["rows"]]
        out = {
            "win": "term", "how": how,
            "requested_first_row": target,
            **hit, **after,
            "moved_rows": after["first_row"] - before,
            "text": "\n".join(lines),
            "effect": _with_focus({
                "observed": reported, "changed": after["first_row"] != before,
                "first_row": {"before": before, "after": after["first_row"]},
                **({} if reported else {
                    "note": "荧幕没在时限内报回 layout，无法与画面对账"}),
            }, act),
        }
        if target != after["first_row"]:
            out["clamped"] = (
                f"要滚到第 {target} 行，实际停在第 {after['first_row']} 行"
                f"（可滚范围 0–{max_top}）")
        return out

    async def op_navigate(step: dict) -> Any:
        act = await ensure_active("browser")
        await push_chrome(url=step["url"], loading=True)
        info = await browser.navigate(
            step["url"], wait=step.get("wait", True),
            timeout=float(step.get("timeout", 30)),
        )
        await push_chrome(url=step["url"], loading=False)
        await push_tabs()
        # 请求的地址和最终落地的地址未必是同一个：重定向、尾斜杠补全、
        # 登录墙跳转都会改写它。只回请求地址等于把这些情况全藏起来。
        probe = await page_probe()
        effect: dict = {"observed": isinstance(probe, dict)}
        if isinstance(probe, dict):
            final = probe.get("url")
            effect.update({
                "final_url": final,
                "title": probe.get("title"),
                "redirected": final != step["url"],
                "text_len": probe.get("len"),
                "loaded": info.get("loaded"),
                "frame_changed": info.get("repainted"),
            })
        else:
            effect["reason"] = "页面探针无回应，无法确认最终地址"
        return await with_detail(step, {"url": step["url"], **info,
                                        "effect": _with_focus(effect, act)})

    async def op_exec(step: dict) -> Any:
        # exec 是 browser scroll / browser read 的载体，都是指向浏览器的动作。
        # 例外是纯观察：frago desktop wait 也用 exec 探条件，而等待是"看"不是"做"，
        # 它一路探到条件成立期间不该把窗口层级翻来覆去改。调用方用
        # observe=true 声明这一次只是看（aos 的 wait 会带上）。
        act = None if step.get("observe") else await ensure_active("browser")
        out: dict = {"value": await browser.evaluate(step["js"])}
        if act is not None:
            out["effect"] = _with_focus({"observed": True}, act)
        return out

    async def op_win(step: dict) -> Any:
        win = step["win"]
        if win not in WINDOWS:
            raise ValueError(f"未知窗口: {win}（只有 {'/'.join(WINDOWS)}）")

        if step.get("action") in ("open", "close"):
            want_open = step["action"] == "open"
            ms = int(step.get("ms", 260))
            before_focus = stage.focus
            seq = stage.layout_seq
            res = await power(win, want_open, ms)
            if not res["changed"]:
                return {"win": win, "action": step["action"], "noop": True,
                        "open": stage.open[win], "focus": stage.focus,
                        "note": f"{win} 本来就"
                                + ("开着" if want_open else "关着")
                                + "，这一下没有改变任何东西",
                        "effect": {"observed": True, "changed": False}}
            await asyncio.sleep(ms / 1000)
            reported = await settle_layout(seq, 800)
            out = {
                "win": win, "action": step["action"], "noop": False,
                "open": stage.open[win],
                "focus": stage.focus,
                "windows_open": dict(stage.open),
                "effect": {
                    "observed": True, "changed": True,
                    "focus": {"before": before_focus, "after": stage.focus},
                    "focus_changed": before_focus != stage.focus,
                    "layout_reported": reported,
                },
            }
            if not want_open:
                # 关掉不等于销毁。这句话必须在回执里，否则下一个人会以为
                # tmux 会话被杀了，去查一个根本没发生的事。
                out["carrier_kept"] = {
                    "term": "tmux 会话照常在跑",
                    "browser": "演员标签照常在，画面仍在收",
                    "image": "已装载的图片留着，重新打开还是那张",
                }[win]
                if stage.focus is None:
                    out["note"] = ("桌面上已经没有开着的程序了，焦点为空；"
                                   "这时键盘输入没有接收方，"
                                   "指向某个程序的动作会把它重新打开。")
            return out

        if not stage.open.get(win):
            raise ValueError(
                f"{win} 没开着，"
                f"{step.get('action') or 'move'} 无处可施——"
                f"先 `frago desktop window open --target {win}`"
            )

        # 浏览器窗口的几何由 broker 算，不把意图转给 UI——UI 那套 max 会摊满
        # 整个桌面，直接破坏 75–85% 这条约束，也破坏与演员视口同比例这件事。
        # max 取宽度上界、restore 取下界，高度都按当前宽高比推出来；
        # min 只是收进 dock，与几何无关，照旧转给 UI。终端不受此约束。
        if step["win"] == "browser" and step.get("action") in ("max", "restore",
                                                               None):
            action = step.get("action")
            ms = int(step.get("ms", 400))
            dw = int(stage.desktop["w"])
            pin_x = pin_y = None
            allow_narrow = None
            clear_pin = False
            if action == "max":
                target = int(dw * BROWSER_W_MAX_FRAC) & ~1
                clear_pin = True
            elif action == "restore":
                target = int(dw * BROWSER_W_MIN_FRAC) & ~1
                clear_pin = True
            else:
                # window move --target browser：高永远由宽高比推出，不接受
                # 调用方自定的 h——给了高就等于给了另一个比例，画面要么变形
                # 要么留白，那是这套设计要消灭的东西，这条不放开。
                #
                # 放开的是另外两条：给了 --x 就钉住位置、并允许宽跌破 75%
                # 下界。理由是"恒占 75%"与"和终端一左一右不叠放"在 1920 的
                # 桌面上无法共存（居中 1440 宽两侧各只剩 240），而 75% 是个
                # 审美下界，等比才是不变量——牺牲前者保后者。不给 --x 时
                # 一切照旧，居中、夹进 75%–85%。
                target = int(step["w"]) if step.get("w") else None
                if step.get("x") is not None:
                    pin_x = int(step["x"])
                    allow_narrow = True
                if step.get("y") is not None:
                    pin_y = int(step["y"])
            before = stage.content_rect("browser")
            seq = stage.layout_seq
            geo = await push_browser_window(
                target_w=target, ms=ms, reason=f"window {action or 'move'}",
                pin_x=pin_x, pin_y=pin_y, allow_narrow=allow_narrow,
                clear_pin=clear_pin)
            await asyncio.sleep(ms / 1000)
            reported = await settle_layout(seq, 800)
            effect = _diff_rect(before, stage.content_rect("browser"))
            effect["layout_reported"] = reported
            return {"win": "browser", "action": action, "geometry": geo,
                    "effect": effect}
        msg = {"t": "win", "win": step["win"], "ms": step.get("ms", 400)}
        # action: min / max / restore —— 几何由 UI 计算（菜单栏高度、
        # 浏览器等比约束都只有 UI 知道），broker 只传意图。
        for k in ("x", "y", "w", "h", "action"):
            if k in step:
                msg[k] = step[k]
        stage.win_geom[step["win"]] = {**msg}
        # 几何由 UI 算，所以"变没变"也只能问 UI：记下动作前的矩形，
        # 等补间走完并等它把新几何报回来，再比对。
        before = stage.content_rect(step["win"])
        seq = stage.layout_seq
        await broadcast(msg)
        await asyncio.sleep(msg["ms"] / 1000)
        reported = await settle_layout(seq, 800)
        effect = _diff_rect(before, stage.content_rect(step["win"]))
        effect["layout_reported"] = reported
        if not reported:
            effect["note"] = "补间已结束，但 UI 未上报新几何（桌面页可能未连接）"
        return {"win": step["win"], "effect": effect}

    # split 已退场：它把终端和浏览器各摆一半宽，与"浏览器恒占桌面宽的
    # 75–85%"直接冲突，两者无法共存。半宽的浏览器窗口要么违反下界，
    # 要么就得放弃与演员视口同比例——而同比例正是这套设计的全部意义。

    # ── 运镜 ──
    #
    # camera 与 window 的边界要清楚：window 管**被摄物**（虚拟窗口在桌面里多大、
    # 摆在哪），camera 管**摄像机**（取景框对着桌面的哪一块）。两者都会改变
    # "元素在成片里有多大"，但改的是完全不同的东西，不要混。

    # 终端的三档取景粒度里，中间这一档（行范围）是这里实现的。
    #
    # 为什么需要它：`term:r12c40` 框住的是**一个字符格**——十几像素见方，
    # 推到 2.5 倍也只是一小块，没有任何镜头用途；`win:term` 框住的是整扇窗口，
    # 等于没推近。而教学视频里终端的镜头几乎全是"刚跑出来的那几行输出"这个
    # 粒度：一条命令的结果、一段报错、一个进度条。中间这一档缺席时，只能拿
    # 整窗口凑合，或者退回后期裁切——2026-07-24 就是这么翻的车：目测填 crop
    # 参数，摄像机根本没对准要说的位置。
    #
    # 数据全是一手的：终端画面本就是 broker 从 tmux capture-pane 取纯文本再
    # 渲染的，行列坐标现成；termGrid 给了字符格尺寸与网格原点。行号换算成
    # 桌面矩形是纯算术，没有一处目测。

    # 行号一律 **0 基**，与同前缀的 `term:r<行>c<列>` 保持同一套坐标系。
    # 同一个 `term:` 域里混用两套基准是最容易踩空的那种设计——`term:r3c0`
    # 指第 4 行、`term:rows 3` 指第 3 行，这种差一位的错误在画面上完全看不出来。
    _TERM_TAIL = re.compile(r"-\s*(\d+)")
    _TERM_SPAN = re.compile(r"(\d+)\s*-\s*(\d+)")
    _TERM_ONE = re.compile(r"(\d+)")

    def term_view_state() -> dict:
        """终端窗口现在看得见缓冲区的哪一段。

        缓冲区可以有几千行，窗口只有几十行高，两者之间隔着一个视口。视口的
        位置真值在荧幕那边（它才知道自己滚到哪儿了），随 termGrid 一起上报，
        这里只做换算。

        为什么必须有这个换算：摄像机拍的是桌面上那块矩形，而矩形里显示什么
        取决于视口滚到哪儿。拿缓冲区行号直接当画面行号去取景，人一回看历史，
        镜头就对着别处——而回执里每个字段都正常。
        """
        g = stage.term_grid
        total = len(term.buffer_lines())
        cell_h = float(g.get("cellH") or 0)
        # 窗口有多高是荧幕的属性（它也决定 tmux 的行数），这一项照旧读它的；
        # 视口停在哪一行是 broker 自己的账，不问荧幕。
        rows = int(g.get("rows") or 0) or total or 1
        max_top = max(0, total - rows)
        stuck = stage.term_stuck
        top = max_top if stuck else max(0, min(stage.term_top, max_top))
        out = {"first_row": top, "rows": rows, "buffer_lines": total,
               "max_first_row": max_top, "stuck": stuck}
        # 荧幕报回来的位置只当对账用：两边对不上说明那块荧幕没执行到位
        # （被浏览器冻住、或者资产是旧的），此时画面与这里说的不是一回事。
        # 不说破的话，它和"一切正常"长得一模一样——这正是这套系统反复栽的那种错。
        #
        # 但只在两边看的是**同一份缓冲区**时才比。layout 是事件驱动的（几何变了、
        # 滚动了才报），而缓冲区每 0.12 秒就可能长一截；缓冲区一变，上一次报上来
        # 的 scrollTop 就成了旧数字，拿它比必然对不上——而画面其实好好地贴着底。
        # 这种误报报几次就没人看了，比不报更坏。行数相等即"看的是同一份"。
        same_buffer = g.get("bufferLines") == total
        if cell_h and "scrollTop" in g and same_buffer:
            seen = max(0, round(float(g.get("scrollTop") or 0) / cell_h))
            if abs(seen - top) > 1:
                out["view_mismatch"] = {
                    "broker_first_row": top, "screen_first_row": seen,
                    "note": "主荧幕画的位置与这里记的不一致，画面可能没跟上",
                }
        return out

    def term_screen_lines() -> list[str]:
        """终端窗口里**看得见**的那些行，纯文本。行下标 = 网格行号。

        寻址与取景一律以这一段为准：`term:rows 5` 指的是画面上第 5 行，
        不是缓冲区第 5 行。摄像机只拍得到窗口里的东西。
        """
        v = term_view_state()
        return term.plain_lines()[v["first_row"]:v["first_row"] + v["rows"]]

    def term_geometry() -> tuple[dict, dict]:
        """取景要用的终端几何：字符网格 + 内容区矩形。窗口收起时明确报错。

        收起的窗口在 UI 那边上报的是"不占桌面"的形状——contentRect 报
        {x:-9999,w:0}，termGrid 的原点报 null。对着这样一个矩形取景，
        摄像机会飞到桌面外的虚空，而回执里 target_in_frame 之类的字段
        全都还是"正常"的。这类错误必须在这里就断掉。
        """
        if not stage.open.get("term"):
            raise RefError(
                "终端已经关掉了（不在桌面上），没有东西可以取景——"
                "先 `frago desktop window open --target term` 把它打开。"
                "注意这和收起不是一回事：收起用 window restore，关掉用 window open。",
                {**_available(), "windows_open": dict(stage.open)},
            )
        g = stage.term_grid
        r = stage.content_rect("term")
        minimized = (
            g.get("x") is None or g.get("y") is None
            or not r or r.get("w", 0) <= 0 or r.get("x", 0) <= -9999
        )
        if minimized:
            raise RefError(
                "终端窗口已收起（不在桌面上），无法对它取景——"
                "先 `window restore --target term` 把它放回桌面再取景。",
                {**_available(), "term_window": r, "term_grid": g},
            )
        if any(g.get(k) is None for k in ("cellW", "cellH", "rows", "cols")):
            raise RefError("终端网格尚未上报，无法换算 term ref", _available())
        return g, r

    def term_rows_target(ref: str, r0: int, r1: int,
                         extra: dict) -> dict:
        """把 0 基闭区间行号 [r0, r1] 换算成桌面矩形 + 自查回执。"""
        g, _ = term_geometry()
        lines = term_screen_lines()
        # 可见行数取网格行数与实际画面行数的交集：capture-pane 恒按网格高度
        # 补齐，两者通常相等，但窗口刚 resize 完的那一两帧会不一致。
        visible = max(1, min(int(g["rows"]), len(lines)))
        clamped = []
        if r0 < 0:
            clamped.append(f"起始行 {r0} → 0")
            r0 = 0
        if r1 > visible - 1:
            clamped.append(f"结束行 {r1} → {visible - 1}（可见行数 {visible}）")
            r1 = visible - 1
        r1 = max(r1, r0)
        cw, ch = float(g["cellW"]), float(g["cellH"])
        # x 取网格左边界、w 取整行宽，不按最长行去裁：一段输出天然是整行宽的，
        # 按内容宽裁会让画面左右随行长抖动——一行长一行短，镜头就在晃。
        pad_x, pad_y = cw, ch * 0.4      # 别让文字贴着取景框边缘
        rect = {
            "x": float(g["x"]) - pad_x,
            "y": float(g["y"]) + r0 * ch - pad_y,
            "w": int(g["cols"]) * cw + pad_x * 2,
            "h": (r1 - r0 + 1) * ch + pad_y * 2,
        }
        picked = lines[r0:r1 + 1]
        out = {
            "ref": ref, "kind": "term", "rect": rect,
            "rows": [r0, r1], "row_base": 0,
            "visible_rows": visible,
            # 完整原文，不截断：判"框住的是不是我要的那段"靠的就是它。
            # 可见画面最多几十行，带回来淹不了信号。
            "text": "\n".join(picked),
            "lines": picked,
            "tag": None,
        }
        if clamped:
            out["clamped"] = clamped
        return {**out, **extra}

    def term_last_content_row(lines: list[str], visible: int) -> int:
        """最后一个非空行的行号；整屏皆空时退回 0。

        尾部空行**默认**就跳过，不做成 --trim-empty 开关。理由是两边的错法
        代价完全不对称：capture-pane 恒把画面补齐到网格高度，所以终端里只要
        没写满，末尾永远挂着一串空行——`term:rows -8` 不跳过的话，绝大多数
        情况框到的是一片黑，而"我就是要拍那几行空白"这个需求不存在。
        真要拍固定位置的空白区，绝对行号形态 `term:rows 20-27` 原样照做，
        没有被这条默认挡住的用法。
        """
        for i in range(min(visible, len(lines)) - 1, -1, -1):
            if lines[i].strip():
                return i
        return 0

    def term_region(ref: str, context: int | None) -> dict:
        """`term:rows <spec>` / `term:match <文字>` → 取景目标。"""
        body = ref[len("term:"):].strip()
        verb, _, arg = body.partition(" ")
        arg = arg.strip()

        if verb == "rows":
            g, _ = term_geometry()
            lines = term_screen_lines()
            visible = max(1, min(int(g["rows"]), len(lines)))
            m = _TERM_TAIL.fullmatch(arg)
            if m:
                # 末尾 N 行，从最后一个非空行往上数。录制时最典型的动作就是
                # "跑一条命令，把刚出来的输出推近给观众看"，而那段输出永远在
                # 末尾；绝对行号会随着命令继续跑而漂移，负数形态才稳定。
                n = max(1, int(m.group(1)))
                end = term_last_content_row(lines, visible)
                return term_rows_target(ref, end - n + 1, end,
                                        {"form": "tail", "tail": n})
            m = _TERM_SPAN.fullmatch(arg)
            if m:
                return term_rows_target(ref, int(m.group(1)), int(m.group(2)),
                                        {"form": "span"})
            m = _TERM_ONE.fullmatch(arg)
            if m:
                row = int(m.group(1))
                return term_rows_target(ref, row, row, {"form": "single"})
            raise RefError(
                f"行范围形如 `term:rows 5-12`（第 5 到 12 行，含两端）、"
                f"`term:rows 5`（单行）或 `term:rows -8`（末尾 8 行），"
                f"收到 {arg!r}", _available())

        if verb == "match":
            text = arg
            if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
                text = text[1:-1]
            if not text:
                raise RefError("term:match 需要要找的文字", _available())
            g, _ = term_geometry()
            lines = term_screen_lines()
            visible = max(1, min(int(g["rows"]), len(lines)))
            hits = [i for i in range(visible) if text in lines[i]]
            if not hits:
                # 找不到有两种可能，补救动作完全不同：画面上真没有这段文字，
                # 或者它在缓冲区里、只是被滚出了窗口。后者不点破的话，人会
                # 反复改 match 的写法去找一段其实已经找到了的文字。
                buf = term.plain_lines()
                view = term_view_state()
                elsewhere = [i for i, ln in enumerate(buf) if text in ln]
                if elsewhere:
                    row = elsewhere[-1]
                    raise RefError(
                        f"{text!r} 在缓冲区第 {row} 行，但终端窗口现在看不见它"
                        f"（画面上是第 {view['first_row']}–"
                        f"{view['first_row'] + view['rows'] - 1} 行）。"
                        f"摄像机只拍得到窗口里的东西，先把它滚进画面："
                        f'`frago desktop term scroll --to "{text}"`',
                        {**_available(), "term_buffer_row": row,
                         "term_view": view,
                         "matches_in_buffer": len(elsewhere)})
                raise RefError(
                    f"终端画面里没有 {text!r}",
                    {**_available(), "term_visible_rows": visible,
                     "term_view": view,
                     "term_text": "\n".join(lines[:visible])})
            # 取最后一处：终端是往下滚的，同样的文字出现多次时，最新的那次
            # 才是"刚刚发生的事"，也就是镜头该对准的那一处。
            row = hits[-1]
            ctx = max(0, int(context or 0))
            return term_rows_target(
                ref, row - ctx, row + ctx,
                {"form": "match", "matched": text, "match_row": row,
                 "matches": len(hits), "match_rows": hits,
                 "context": ctx})

        raise RefError(
            f"终端区域 ref 形如 `term:rows <行范围>` 或 `term:match <文字>`，"
            f"收到 {ref}", _available())

    async def camera_target(ref: str, expand_to: str | None = None,
                            context: int | None = None) -> dict:
        """把一个 ref 变成取景要用的**桌面矩形**，外加一份自查用的回执。

        坐标全程一手数据：页面矩形来自 DOM，换算成桌面坐标用的是 broker 自己
        写的那份虚拟窗口几何。整条链上没有一处目测。
        """
        ref = (ref or "").strip()
        # 终端区域取景（行范围 / 内容匹配）在这里截胡：它返回的是一片矩形，
        # 而 resolve_ref 的契约是"一个点"，两者形状不同，不该硬塞进同一条路。
        if ref.startswith("term:") and not re.fullmatch(
                r"r\d+c\d+", ref[len("term:"):].strip()):
            return term_region(ref, context)
        if refs.is_page_ref(ref):
            # 判型与 resolve_ref 走同一处（page_locate）。这两条路曾各抄一份，
            # 两份判据必然漂移——漂移的表现是 `mouse to` 找得到而 `camera focus`
            # 找不到，看上去像页面问题，实际是同一个字符串被解释成了两个东西。
            found = await page_locate(browser.evaluate, refs.page_body(ref),
                                      frame=True, expand_to=expand_to)
            hits = found["hits"]
            if not hits:
                raise RefError(
                    "camera " + refs.miss_message(ref, found["tried"]),
                    {**_available(), "ref_tried": found["tried"],
                     "ref_form": found["form"]})
            h = hits[0]
            r = stage.content_rect("browser")
            if not r:
                raise RuntimeError(
                    "虚拟浏览器窗口尚无几何，无法把页面坐标换算成桌面坐标")
            kx = r["w"] / browser.width
            ky = r["h"] / browser.height
            rect = {"x": r["x"] + h["x"] * kx, "y": r["y"] + h["y"] * ky,
                    "w": h["w"] * kx, "h": h["h"] * ky}
            return {
                "ref": ref, "kind": "page", "rect": rect,
                "tag": h.get("tag"), "id": h.get("id"),
                "expanded_to": expand_to if h.get("expanded") else None,
                "page_rect": {k: round(h[k], 1) for k in "xywh"},
                "matches": len(hits),
                "matched_by": found["matched_by"], "ref_form": found["form"],
                **({"ref_note": found["note"]} if found["note"] else {}),
                # 摘要是给 agent 自查用的，不截到几十字：判"命中的是标题还是
                # 整张卡"靠的正是这段文本覆盖了多少东西，截短了就判不出来。
                "text": h.get("text"), "text_len": h.get("text_len"),
            }
        info = await resolve_ref(ref)
        if info["kind"] == "desktop":
            rect = {k: float(info["rect"][k]) for k in "xywh"}
        elif info["kind"] == "term":
            g = stage.term_grid
            rect = {"x": info["x"] - g["cellW"] / 2, "y": info["y"] - g["cellH"] / 2,
                    "w": float(g["cellW"]), "h": float(g["cellH"])}
        else:
            raise RuntimeError(f"ref {ref} 没有可取景的矩形")
        return {"ref": ref, "kind": info["kind"], "rect": rect,
                "tag": None, "text": None}

    def target_window(t: dict) -> str | None:
        """这个取景目标住在哪扇窗口里。

        取景对准的是"元素在桌面坐标系里应该在的位置"，而那个位置现在显示着
        什么，取决于窗口层级——所以取景前必须先把目标所在的窗口提到最上层。
        桌面级 ref（dock:term / win:browser 之类）按尾部认窗口；认不出来的
        （比如 tab:0）返回 None，不乱动焦点。
        """
        kind = t.get("kind")
        if kind == "page":
            return "browser"
        if kind == "term":
            return "term"
        tail = (t.get("ref") or "").split(":", 1)[-1]
        return tail if tail in ("term", "browser", "image") else None

    async def activate_for_camera(targets: list[dict]) -> tuple[dict | None, str | None]:
        """把取景目标所在的窗口置为 active，返回（激活结果, 说不通的原因）。

        多目标跨了两扇窗口时不猜：那种构图本来就是"同时拍两扇窗口"，
        没有哪一扇该被提到上面，如实说一句、不动焦点。
        """
        wins = {w for w in (target_window(t) for t in targets) if w}
        if len(wins) != 1:
            return None, ("多个目标分布在不同窗口，未自动激活任何一扇"
                          if len(wins) > 1 else None)
        act = await ensure_active(next(iter(wins)))
        if act and act["focus_changed"]:
            # 层级变化要先落到画面上，再开始插值。这一下人眼看得见（窗口跳到
            # 前面），这是对的——人操作电脑本来就是这样；但它必须发生在推拉
            # 镜头开始之前，否则镜头前几帧拍的还是旧的层级。
            await asyncio.sleep(0.12)
        return act, None

    def union_rect(targets: list[dict]) -> dict:
        """多目标的外接矩形。

        旁白说"装机量最高的这几个"时要的是好几张卡并排，按单个 ref 取景就是
        错的——镜头会怼在第一张上，而观众听到的是"这几个"。
        """
        x0 = min(t["rect"]["x"] for t in targets)
        y0 = min(t["rect"]["y"] for t in targets)
        x1 = max(t["rect"]["x"] + t["rect"]["w"] for t in targets)
        y1 = max(t["rect"]["y"] + t["rect"]["h"] for t in targets)
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}

    def check_zoom(zoom: float) -> None:
        cam = recorder.camera
        if zoom < ZOOM_MIN:
            raise CameraError(
                f"倍率 {zoom:g} 低于下限 {ZOOM_MIN:g}——这是几何约束："
                "1 倍就是原始镜头、拍的是整个虚拟桌面，再缩小意味着要拍桌面"
                "之外的区域，那里什么都没有，只有黑边。",
                {"zoom_requested": zoom, **cam.report()})
        if zoom > ZOOM_MAX:
            raise CameraError(
                f"倍率 {zoom:g} 超过上限 {ZOOM_MAX:g}——这是**清晰度**约束，"
                "不是几何约束。桌面页按 1920×1080 渲染，推近就是把中间那一块"
                f"拉满全屏：{zoom:g} 倍下只有 "
                f"{int(1920 / zoom)}×{int(1080 / zoom)} 的真实像素被拉到 1920×1080，"
                "信息量不增反减。想要真正清晰的特写，得让虚拟浏览器窗口本身更大"
                "让页面重排（window max --target browser），那是录制前的事，"
                "不是镜头的事。",
                {"zoom_requested": zoom, **cam.report()})

    def camera_result(verb: str, framing: dict, targets: list[dict],
                      ms: int, extra: dict | None = None) -> dict:
        out = {
            "verb": verb, "ms": ms,
            "framing": framing,
            "targets": [{k: v for k, v in t.items() if k != "rect"} for t in targets],
            # 不在录制期间时说清楚：状态改了，但没有任何一帧会因此不同。
            # 这条正是"录制前发现构图不对"的用法——几何完全可算，不必先录再看。
            "recording": recorder.recording,
            "note": None if recorder.recording else
                    "当前没有在录，本次只更新取景状态并给出构图预判；"
                    "取景只作用于录制落盘的帧，桌面页上人看到的画面不变。",
        }
        return {**out, **(extra or {})}

    async def op_camera_focus(step: dict) -> Any:
        """对准一个（或几个）元素推近。倍率 1 → k，中心 桌面正中 → 元素中心。"""
        cam = recorder.camera
        refs = step.get("refs") or ([step["ref"]] if step.get("ref") else [])
        if not refs:
            raise ValueError("camera.focus 需要至少一个 --ref")
        zoom = float(step.get("zoom", 1.8))
        ms = int(step.get("ms", FOCUS_DEFAULT_MS))
        check_zoom(zoom)
        targets = [await camera_target(r, step.get("expand_to"),
                                       step.get("context")) for r in refs]
        box = union_rect(targets)
        extra: dict = {"zoom_requested": zoom}
        if len(targets) > 1:
            # 多目标时 --zoom 是**上限**而不是定值：装不下所有目标的倍率没有意义。
            fit = cam.fit_zoom(box)
            zoom = max(ZOOM_MIN, min(zoom, fit, ZOOM_MAX))
            extra["zoom_fit"] = round(fit, 4)
            extra["bounding_rect"] = {k: round(box[k], 1) for k in "xywh"}
            extra["zoom_note"] = (
                f"多目标取景：--zoom 作上限用，按外接矩形（含 {FRAME_MARGIN}px "
                f"安全边距）能装下的最大倍率是 {fit:.3f}，最终取 {zoom:.3f}")
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        # 预判在真正移动**之前**：坐标全是一手数据，几何上完全可算，所以
        # "这个元素在 2 倍下没法居中"应该在录制前就知道，而不是录完才发现。
        framing = cam.framing(cx, cy, zoom, rect=box)
        if not framing["target_in_frame"]:
            raise CameraError(
                f"目标不在 {zoom:g} 倍的取景范围内：{framing['why_out']}",
                {"framing": framing, "targets": targets,
                 "how_to_fix": "降低 --zoom，或用 --expand-to 换一个更小的目标，"
                               "或先把元素滚到视口中部再取景"})
        act, why = await activate_for_camera(targets)
        cam.animate((cx, cy), zoom, ms)
        await asyncio.sleep(ms / 1000)
        if act is not None:
            extra["effect"] = _with_focus({"observed": True}, act)
        elif why:
            extra["focus_note"] = why
        return camera_result("focus", framing, targets, ms, extra)

    async def op_camera_pan(step: dict) -> Any:
        """摇镜：倍率不变，中心从当前位置移到目标元素。

        pan 的价值是**建立空间关系**——旁白说"装机量最高的这几个"时镜头从第一
        张卡摇到第三张，观众自然理解这是并列的一排；硬切三次看起来像三个不相干
        的东西。所以它不是"带动画的 focus"，是另一件事。
        """
        cam = recorder.camera
        ref = step.get("to")
        if not ref:
            raise ValueError("camera.pan 需要 --to <ref>")
        ms = int(step.get("ms", PAN_DEFAULT_MS))
        tgt = await camera_target(ref, step.get("expand_to"),
                                  step.get("context"))
        rect = tgt["rect"]
        cx, cy = rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2
        zoom = cam.state()[2]
        framing = cam.framing(cx, cy, zoom, rect=rect)
        if not framing["target_in_frame"]:
            raise CameraError(
                f"摇过去之后目标仍不在取景范围内：{framing['why_out']}",
                {"framing": framing, "targets": [tgt],
                 "how_to_fix": "先 camera reset 或降低倍率，再 pan"})
        act, _why = await activate_for_camera([tgt])
        cam.animate((cx, cy), zoom, ms)
        await asyncio.sleep(ms / 1000)
        extra: dict = {"zoom_held": round(zoom, 4)}
        if act is not None:
            extra["effect"] = _with_focus({"observed": True}, act)
        return camera_result("pan", framing, [tgt], ms, extra)

    async def op_camera_reset(step: dict) -> Any:
        """拉回全桌面。倍率 → 1，中心 → 桌面正中，与 focus 共用同一套插值，
        所以 reset 与 focus 之间的过渡就是一次平滑推拉，不是硬切。

        **不改焦点**：它回的是整个桌面，不指向任何一扇窗口，没有哪一扇
        该因此被提到最上层。
        """
        cam = recorder.camera
        ms = int(step.get("ms", RESET_DEFAULT_MS))
        cx, cy = cam.dw / 2, cam.dh / 2
        framing = cam.framing(cx, cy, ZOOM_MIN)
        before = cam.state()
        cam.animate((cx, cy), ZOOM_MIN, ms)
        await asyncio.sleep(ms / 1000)
        return camera_result("reset", framing, [], ms,
                             {"zoom_from": round(before[2], 4)})

    async def op_viewport(step: dict) -> Any:
        """主动重读一次演员视口，并按新比例重摆虚拟浏览器窗口。

        平时不需要：启动读一次、导航后读一次已经覆盖了会变的时机。
        它存在是为了人手动改了那扇真实浏览器窗口之后有一条路能立刻跟上。
        """
        info = await browser.refresh_viewport(step.get("reason") or "主动刷新")
        geo = await push_browser_window(ms=int(step.get("ms", 300)),
                                        reason="主动刷新视口")
        return {"viewport": info, "geometry": geo}

    async def push_tabs() -> list[dict]:
        """把舞台浏览器的真实标签列表推给 UI 的虚拟标签条。"""
        tabs = await browser.list_tabs()
        summary = [
            {
                "title": t.get("title") or "New Tab",
                "url": t.get("url", ""),
                "active": t.get("id") == browser.target_id,
            }
            for t in tabs
        ]
        await push_chrome(tabs=summary)
        return tabs

    async def op_tab(step: dict) -> Any:
        """真实标签页操作：open 新开并切过去 / switch 按序号切 / close 关掉。

        标签是舞台 Chrome 里的真实 tab，不是 UI 画的道具——
        切换即机位重新对准，画面、输入、导航全部跟着走。
        """
        action = step.get("action", "switch")
        # 开标签、切标签、关标签都是对着浏览器窗口做的事，先把它提到最上层。
        act = await ensure_active("browser")
        if action == "open":
            # 开完不 switch_to：切过去会把采集对准新标签，而"开一个后台标签
            # 给人稍后自己切"不该抢走当前画面。要切就用 tab switch。
            await browser.open_tab(step.get("url", "about:blank"))
        elif action == "switch":
            tabs = await browser.list_tabs()
            idx = int(step["index"])
            if not 0 <= idx < len(tabs):
                raise ValueError(f"标签序号越界: {idx}（共 {len(tabs)} 个）")
            await browser.switch_to(tabs[idx]["id"])
        elif action == "close":
            tabs = await browser.list_tabs()
            idx = int(step["index"])
            if not 0 <= idx < len(tabs):
                raise ValueError(f"标签序号越界: {idx}（共 {len(tabs)} 个）")
            tid = tabs[idx]["id"]
            if tid == browser.target_id:
                raise ValueError("不能关掉正在采集的标签，先 switch 走")
            await browser.close_tab(tid)
            await asyncio.sleep(0.3)
        else:
            raise ValueError(f"未知 tab 动作: {action}")
        tabs = await push_tabs()
        active = next(
            (t for t in tabs if t.get("id") == browser.target_id), {}
        )
        await push_chrome(url=active.get("url", ""),
                          title=active.get("title", ""), loading=False)
        return {"action": action, "tabs": len(tabs),
                "effect": _with_focus({"observed": True}, act)}

    async def op_say(step: dict) -> Any:
        await broadcast({"t": "say", "text": step["text"], "ms": step.get("ms", 2500)})
        return {"said": step["text"]}

    # ── 图片浏览器 ──
    #
    # 舞台上第三扇窗：给 agent 一个"打开一张本地图片给人看"的落点。图片是静态
    # 内容，没有演员视口可跟随，几何由 broker 按图片长宽比算（同浏览器窗口，
    # 见 image_geometry），画面内容经 broker 的 HTTP 路由投喂给桌面页。

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
    IMAGE_MIME = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }
    _served_image: dict = {"bytes": None, "mime": None, "name": None}

    async def op_image_open(step: dict) -> Any:
        path = Path(step["path"]).expanduser()
        if not path.is_file():
            raise ValueError(f"图片不存在: {path}")
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            raise ValueError(
                f"不支持的图片格式: {ext}（允许: {'/'.join(sorted(IMAGE_EXTENSIONS))}）"
            )
        data = path.read_bytes()
        try:
            from PIL import Image
            with Image.open(path) as im:
                img_w, img_h = im.size
        except Exception:
            img_w, img_h = 1600, 900
        geo = image_geometry(img_w, img_h)
        _served_image.update({"bytes": data, "mime": IMAGE_MIME[ext], "name": path.name})
        # 几何先落、内容再落、最后才把程序打开：顺序反过来的话，窗口会先按
        # 上一张图的尺寸出现一瞬再跳到新尺寸，录进片子就是一次没人下过的抖动。
        await push_image_window(geo)
        await broadcast({"t": "image", "url": f"http://127.0.0.1:{cfg['port']}/image",
                         "name": path.name})
        stage.last_image = {"url": f"http://127.0.0.1:{cfg['port']}/image",
                            "name": path.name}
        before = stage.focus
        was_open = stage.open.get("image", False)
        # 打开一份文件顺带把程序拉起来，这是文件与程序的正常关系；
        # 关窗口则一律走 window close，三个程序同一条路。
        await op_focus({"win": "image"})
        out = {
            "image": path.name, "win": "image",
            "size_bytes": len(data), "geometry": geo,
            "effect": _with_focus({"observed": True},
                                  {"before": before, "after": "image",
                                   "focus_changed": before != "image",
                                   **({} if was_open else {"launched": "image"})}),
        }
        if not was_open:
            out["launched"] = "image"
        return out

    @app.get("/image")
    async def serve_image() -> Response:
        if not _served_image["bytes"]:
            return Response(content=b"no image", status_code=404,
                            media_type="text/plain")
        # Cache-Control: no-store 是这里的刚需：桌面页的 <img> 地址恒为
        # 固定 URL（/image），不带任何版本参数。不禁止缓存的话，浏览器
        # 第一次加载后就把图片缓存下来，之后每次开新图 src 仍是同一个地址，
        # 浏览器直接读缓存——画面永远停在第一张图（实测：换图后仍是红框）。
        # 页面本身由 frago server 的校验头管，这条只负责图片。
        return Response(content=_served_image["bytes"],
                        media_type=_served_image["mime"],
                        headers={"Cache-Control": "no-store"})

    # ── overlay ──
    # 和 say 是两码事：say 是屏幕下方的字幕行，overlay 是压在桌面上的浮层标注。
    # 分开是因为它们的生命周期互不相干——讲解一句话的同时可能挂着一张结构图，
    # 谁先到期谁先撤，合流会让两者互相顶掉。
    OVERLAY_KINDS = ("card", "title", "highlight", "image")

    async def op_overlay(step: dict) -> Any:
        kind = step.get("kind")
        if kind not in OVERLAY_KINDS:
            raise ValueError(
                f"未知 overlay kind: {kind!r}（允许: {'/'.join(OVERLAY_KINDS)}）"
            )
        content = step.get("content")
        # highlight 是纯圈选框，靠 at 定位，本来就没有内容可放；其余三种
        # 缺了 content 就是一个空盒子飘在画面上，宁可报错也别让它进片子。
        if kind != "highlight" and not content:
            raise ValueError(f"overlay kind={kind} 需要 content（highlight 才可省略）")

        enter = step.get("enter", "fade")
        if enter not in ("fade", "slam", "slide"):
            raise ValueError(f"未知 overlay enter: {enter!r}（允许: fade/slam/slide）")

        msg = {
            "t": "overlay",
            "kind": kind,
            "content": content or "",
            "enter": enter,
            "ms": int(step.get("ms", 3000)),
        }
        if step.get("at"):
            msg["at"] = step["at"]
        if step.get("id"):
            msg["id"] = str(step["id"])
        await broadcast(msg)
        return {"overlay": kind, "id": msg.get("id"), "ms": msg["ms"]}

    async def op_overlay_clear(step: dict) -> Any:
        oid = step.get("id")
        await broadcast({"t": "overlay.clear", "id": oid})
        return {"cleared": oid or "all"}

    async def op_sleep(step: dict) -> Any:
        await asyncio.sleep(int(step.get("ms", 500)) / 1000)
        return {}

    # ── 开录门禁 ──
    #
    # 判据全部是"不成立就必然录废、且当场一声不吭"的那种。它们此前以
    # 散文形态写在 playbook 第三节里，靠自律执行——实测在同一次拍片会话里
    # 各被违反两次，代价是整个探索期对着一个只占左上角的画面做判断，
    # 以及一条从 76 秒起冻住的素材差点交付。文档负责提醒别做错，
    # 代码负责让错做不出来。
    #
    # 开过四条，现在实际生效的只有一条（见下面 record_gate）：
    # viewport_matches_window、ui_ready、single_primary_screen 各自撤掉的
    # 理由写在它们原地。
    #
    # 硬拒绝而不是警告：警告在这条链路上等于不存在——开录之后人不会回头看
    # 一条已经滚过去的 WARN，而录废要到回看成片时才发现，那时现场早没了。

    def ui_is_live() -> bool:
        """现在画面是不是活的。/status 与门禁共用这一处算式。

        两边各写一遍必然漂移，而漂移的表现是"status 说就绪、门禁说不行"，
        人会先怀疑门禁坏了而不是怀疑画面。
        """
        return (primary_meta() is not None
                and bool(browser.last_frame_at)
                and (time.time() - browser.last_frame_at) <= UI_LIVE_WINDOW_SEC)

    # viewport_matches_window 曾经是门禁的一项，随权威反转一并撤掉。它问的是
    # "演员视口跟不跟得上虚拟窗口"——那是覆写模型下的问题。现在虚拟窗口的形状
    # 由 broker 按演员视口的比例算出来，两者同比例是构造出来的，不是校验出来的，
    # 这条判据恒成立，留着就是一条永远为真的死判据。
    #
    # ui_ready 曾经是门禁的一项，2026-07-24 撤掉了。它问的是"最近 3 秒有没有新帧"，
    # 而静止的网页本来就不产帧——想拍一个不动的界面是完全正当的镜头，画布上挂着的
    # 是尺寸校验通过的那张帧（见 StageBrowser._on_frame：尺寸不符的帧根本不会更新
    # last_frame_at），画面没有骗人，只是没在动。用它当开录判据等于禁止静态镜头。
    # 冻帧那类真故障靠 rec stop 的 unique_ratio / frozen_tail_sec 事后抓，
    # 那两个数分得开"没在动"和"该动却没动"，开录前分不开。
    # ui_ready 仍留在 /status 和 health 自检里，那里它是信息不是闸门。

    # single_primary_screen 曾经是门禁的一项，2026-08-11 撤掉了。它数"此刻有几块
    # 荧幕连着"，要求恰好一块，两条分支现在都不成立：
    #
    # 数出多块——它防的是"几块荧幕轮流覆盖布局、视口来回跳、画面缩在窗口左上角"。
    # 那是覆写模型下的病：那时演员视口由桌面页报的尺寸决定。权威反转之后没人
    # 覆写演员视口，broker 又只采信主荧幕的几何（见 /stream 里那段），多开一块
    # 桌面页改不动成片。实测：2026-08-11 在两块荧幕连着的状态下录满 19 秒，
    # 成片构图正常。
    #
    # 数出零块——它写着"录下来是一段没有观众也没有画面的空片"，这句是错的。
    # 机位打开的是它自己那一份桌面页，人关不关标签与它无关。实测：把桌面页
    # 全部关掉后强录 18.6 秒（clips/probe-no-human.mp4），画面完整，终端输出
    # 与浏览器导航都录进去了。
    #
    # 而它误伤的恰恰是录制自己：门禁排在拉机位之前，机位一起来就是第二块荧幕，
    # 所以每一条成片全程都跑在这条判据判为不合格的状态里。代价是 camera up
    # 预热之后必被拒，开录只能现拉机位，片头恒带几秒静止画面。
    #
    # "人开了两块桌面页"这件事仍由 health 的 screen_duplicates 报，那里它是
    # 信息不是闸门。

    def gate_tmux() -> dict | None:
        ok, detail = term.alive()
        if ok:
            return None
        return {
            "item": "tmux_session",
            "detail": f"tmux 会话 {term.session} 取不到画面: {detail}",
            "means": "broker 从没建成这个会话，或它已经被杀掉。常见成因是"
                     "上一次 frago desktop down 没真停干净，这次 up 复用了一个半死的 broker。",
            "if_ignored": "终端窗口全程空白，/status 一切正常（ui_ready 只管"
                          "浏览器画面帧，不管终端），只有 broker.log 在刷 "
                          "capture-pane 失败。",
            "how_to_fix": f"frago desktop down --instance {instance_id} 之后确认 "
                          f"lsof -nP -iTCP:{cfg.get('port')} -sTCP:LISTEN 为空，"
                          f"再 frago desktop up --id {instance_id} 重起。",
            "session": term.session,
        }

    def record_gate() -> list[dict]:
        return [c for c in (gate_tmux(),) if c]

    async def op_record_start(step: dict) -> Any:
        name = step.get("name") or f"clip-{int(time.time())}"
        failed = record_gate()
        if failed and not step.get("force"):
            raise GateError(failed)
        out = await recorder.start(name)
        if failed:
            # 绕过要留痕，绝不静默：回执与 broker.log 各写一份，
            # 事后回看成片发现构图不对时，能查到当时是知情放行的。
            items = [c["item"] for c in failed]
            _log(f"⚠️ rec start --force 绕过开录门禁 {items}（clip={name}）: "
                 + json.dumps(failed, ensure_ascii=False))
            out["gate_bypassed"] = items
            out["gate_bypassed_detail"] = failed
            out["gate_note"] = ("本段是在门禁未通过的情况下强行开录的，"
                                "画面很可能不可用；绕过记录已写入 broker.log。")
        else:
            out["gate"] = "passed"
        return out

    async def op_record_stop(_step: dict) -> Any:
        return await recorder.stop()

    async def op_camera_up(_step: dict) -> Any:
        """把机位准备好，不开录。慢在这里，让开录那一下恒为毫秒级。"""
        return await recorder.prepare()

    async def op_camera_down(_step: dict) -> Any:
        """收走机位，**核对过再报**。正在录的时候不许收——那会留下一段没有结尾的片子。

        这里从前是 `await recorder.close()` 之后无条件 `return {"ok": True,
        "closed": True}`——不管杀没杀到都说收走了。而 `close()` 自己把那条
        `frago browser -b cdp stop` 整段包在 suppress(Exception) 里，既不看返回码
        也不看端口。两下一凑，"机位还活着"这件事三层都不报错：回执说收走了，
        状态里那块荧幕还在，自检的 screen_duplicates 永远消不掉，而它给的补救
        办法会把人引去人肉翻浏览器窗口——多出来的那块其实是舞台自己的机位。

        所以现在的规矩是：收完之后亲自看两样——端口上还有没有浏览器主进程、
        CDP 还应不应答。没收干净就报失败，绝不包装成成功。

        回执里 closed 与 killed 是两件事，刻意分开：closed 说"现在端口上确实
        没有机位了"，killed 说"这一次真的杀掉了东西"。两者分不开的话，
        "调用方以为架着的机位其实早就不在了"这种状态就永远看不出来。
        """
        if recorder.recording:
            raise RuntimeError(f"正在录 {recorder.name}，先 `frago desktop rec stop`")
        port = recorder.port
        was_open = recorder.alive          # broker 这边原本以为机位连着
        procs_before = await asyncio.to_thread(_actor_processes, port)
        cdp_before = await asyncio.to_thread(_cdp_answering, port)
        await recorder.close()
        # 判据是进程不是端口，理由同 _wait_browser_gone：端口先静默、进程后
        # 消失，中间那段老进程还占着 profile 的 Singleton 锁。机位恒为无头，
        # 退得快（一两秒），15 秒给足了还不退就是真没退。
        await _wait_browser_gone(port, 15.0)
        procs_after = await asyncio.to_thread(_actor_processes, port)
        cdp_after = await asyncio.to_thread(_cdp_answering, port)
        detail = {
            "port": port,
            "was_open": was_open,
            "browser_processes": {"before": procs_before, "after": procs_after},
            "cdp_answering": {"before": cdp_before, "after": cdp_after},
        }
        if procs_after or cdp_after:
            # 只说成立的那几条。两条恒列的话，进程数为 0 时会读出
            # "还有 0 个浏览器主进程"这种自相矛盾的话。
            why = []
            if procs_after:
                why.append(f"{port} 上还有 {procs_after} 个浏览器主进程")
            if cdp_after:
                why.append(f"{port} 的 CDP 仍在应答")
            raise CameraError(
                "机位没收掉：" + "、".join(why),
                {**detail,
                 "how_to_fix": f"frago browser -b cdp stop --port {port}；"
                               f"仍不退就 lsof -nP -iTCP:{port} -sTCP:LISTEN "
                               "看是谁占着"},
            )
        return {
            "closed": True,
            "killed": bool(procs_before or cdp_before),
            **detail,
            **({} if procs_before or cdp_before else
               {"note": f"{port} 上本来就没有机位，这一次什么都没杀"}),
        }

    OPS = {
        "cursor": op_cursor, "click": op_click, "focus": op_focus,
        "type": op_type, "key": op_key, "shell": op_shell,
        "term.scroll": op_term_scroll, "term.fontsize": op_term_fontsize,
        "navigate": op_navigate, "exec": op_exec, "win": op_win,
        "viewport": op_viewport, "tab": op_tab, "elements": op_elements,
        "say": op_say, "sleep": op_sleep,
        "camera.focus": op_camera_focus, "camera.pan": op_camera_pan,
        "camera.reset": op_camera_reset,
        "camera.up": op_camera_up, "camera.down": op_camera_down,
        "overlay": op_overlay, "overlay.clear": op_overlay_clear,
        # image.close 已撤销：关窗口是窗口管理器的事，三个程序走同一条
        # win/action=close。它曾是唯一一个自带关闭动作的程序，那条路让
        # "关掉程序"在这个 OS 里有两套语义，而终端和浏览器只有其中不存在的那套。
        "image.open": op_image_open,
        "record.start": op_record_start, "record.stop": op_record_stop,
    }

    # ── 批量下发的失败语义 ──
    #
    # 一条动线一次下发几十步（必须批量：逐条命令行调用每条约 3.6 秒，几乎全是
    # CLI 启动开销，实测把设计 52 秒的动线录成过 235 秒）。所以"第 N 步失败了，
    # 后面那些怎么办"是这条链路上一个真问题，不是边角。
    #
    # **默认整批停，不硬着头皮跑完。** 判据不是"哪种更省"，是哪种错更响：
    #
    #   停下来   这一镜作废，而它当场就作废得明明白白——回执 ok:false、
    #            results 里点名从第几步起没轮到。人立刻知道要重录。
    #   跑完     后面那些步骤跑在一个"世界已经不在动线假设的位置上"的现场里。
    #            最典型的是 cursor 失败紧跟一个 click：click 不接受坐标，它打在
    #            **上一次**悬停绑定的位置上——于是点在别的东西上，而回执一路
    #            正常。这正是这套系统反复栽的那种错：一次寻址失败伪装成一次
    #            成功的点击，只有回看成片才发现。
    #
    # 两种都是重录，代价却不对称：停下来是一段**看得出废**的素材，跑完是一段
    # **看不出废**的素材。后者更贵——它会被当成好素材交出去。
    #
    # 步骤之间互不相干时（一串 say / overlay / sleep），停整批确实是浪费，
    # 那种批次显式写 on_error=continue 说明自己知道在做什么。默认不给。
    #
    # 但停不等于撒手：**收尾步骤照跑**。见 ALWAYS_OPS。
    ON_ERROR_MODES = ("stop", "continue")

    # 中途失败之后仍然要执行的 op。
    #
    # 开录—动线—停录是一个必须闭合的组：漏掉停录，留下的不是"少一段片子"，
    # 是三样具体的烂摊子——帧目录留在临时盘里不回收、recorder 卡在 recording
    # 状态导致下一次 rec start 直接被"已经在录"拒掉、以及最要命的，那批帧
    # 从来没进过 ffmpeg，磁盘上根本没有 mp4。跑一次停录，换来的是一段**短但
    # 能播**的素材，外加一份把失败那一步如实记下来的动作日志。
    #
    # 任何步骤也可以自己声明 always=true 加入这一档。
    ALWAYS_OPS = {"record.stop"}

    @app.post("/control")
    async def control(body: dict) -> JSONResponse:
        steps = body.get("steps") or [body]
        on_error = body.get("on_error", "stop")
        if on_error not in ON_ERROR_MODES:
            return JSONResponse(
                {"ok": False,
                 "error": f"未知 on_error: {on_error!r}（只有 "
                          + " | ".join(ON_ERROR_MODES) + "）"},
                status_code=400)

        # 动词先全查一遍再动手，与 aos 的"全部先解析再执行"同源：半批打进画面
        # 之后再报一句"未知指令"，留下的是个说不清做到哪一步的中间态。查得出来
        # 的错就别让它发生在半路上。
        unknown = [{"index": i, "op": s.get("op")}
                   for i, s in enumerate(steps) if s.get("op") not in OPS]
        if unknown:
            return JSONResponse(
                {"ok": False,
                 "error": "未知指令: "
                          + "、".join(f"第 {u['index']} 步 {u['op']!r}"
                                     for u in unknown),
                 "unknown_ops": unknown,
                 "known_ops": sorted(OPS),
                 "executed": 0,
                 "note": "整批一步都没执行——动词在下发之前全查一遍，"
                         "免得半批打进画面之后才报语法错",
                 "results": []},
                status_code=400)

        results: list[dict] = []
        failure: dict | None = None      # 第一条失败，决定回执的措辞与状态码
        aborted_at: int | None = None    # 从第几步起不再往下走

        for i, step in enumerate(steps):
            op = step["op"]
            if aborted_at is not None and not (step.get("always")
                                               or op in ALWAYS_OPS):
                # **"没轮到"必须与"跑了但没记"分得开。** 原来的回执在失败那条
                # 就断了，后面的步骤在数组里一条都没有——看不出是没执行、
                # 还是执行了而回执丢了。这一条就是把它说出来。
                results.append({
                    "index": i, "op": op, "status": "not_reached",
                    "why": f"第 {aborted_at} 步失败，同批余下步骤不再执行"
                           "（on_error=stop）",
                })
                continue
            # 观察 MUST 在 handler 之前采。这是本段唯一不能调换的顺序：
            # 挪到 handler 之后拿到的是结果不是观察，而两者长得一模一样，
            # 记反了从日志里完全看不出来。
            # 只在录制期间采（record.start 例外——它要留下开录那一刻的现场，
            # 而 recorder.recording 要等它自己跑完才为真）。
            observation = None
            if recorder.recording or op == "record.start":
                observation = await observe()
            t_start = time.time()
            try:
                outcome = await OPS[op](step) or {}
                recorder.note(op, step, outcome, t_start, observation=observation)
                entry = {"index": i, "op": op, "status": "ok", **outcome}
                if aborted_at is not None:
                    # 收尾步骤是在"整批已经作废"之后跑的，别让它看起来像
                    # 一切正常走到了这里。
                    entry["ran_as"] = "teardown"
                results.append(entry)
            except Exception as exc:
                recorder.note(op, step, None, t_start,
                              error=f"{type(exc).__name__}: {exc}",
                              observation=observation)
                # 带上异常类型：asyncio.TimeoutError 的 str() 是空字符串，
                # 只拼 {exc} 会报出「navigate 失败: 」这种毫无线索的错误。
                entry = {"index": i, "op": op, "status": "failed"}
                if isinstance(exc, GateError):
                    # 门禁不是"执行失败"，是"不让执行"，所以措辞与载荷都单列：
                    # 每条带 how_to_fix，照抄就能改对；照抄不了才需要 --force。
                    entry["error"] = ("开录门禁未通过，拒绝开录（"
                                      + "、".join(c["item"] for c in exc.checks)
                                      + "）")
                    entry["gate"] = exc.checks
                    entry["how_to_fix"] = [c["how_to_fix"] for c in exc.checks]
                    entry["bypass"] = (
                        "确实要录残缺画面（比如就是要拍故障现场）时，"
                        "用 frago desktop rec start --name <n> --force；"
                        "绕过会写进回执和 broker.log。")
                    entry["http_status"] = 409
                else:
                    detail = f"{type(exc).__name__}: {exc}".rstrip(": ")
                    entry["error"] = f"{op} 失败 — {detail}"
                    entry["http_status"] = 500
                    if isinstance(exc, RefError):
                        # 只说"没找到"是没法自救的，把现在能点什么一并带回去。
                        entry["available"] = exc.available
                    if isinstance(exc, CameraError):
                        # 同理：把算出来的构图摆出来，让调用方看得出是该降倍率
                        # 还是该先把元素挪到画面中间。
                        entry["camera"] = exc.detail
                results.append(entry)
                if failure is None:
                    failure = entry
                if on_error == "stop" and aborted_at is None:
                    aborted_at = i

        summary = {
            "total": len(steps),
            "executed": sum(1 for r in results if r["status"] == "ok"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "not_reached": sum(1 for r in results if r["status"] == "not_reached"),
            "failed_at": failure["index"] if failure else None,
            "on_error": on_error,
        }
        if failure is None:
            return JSONResponse({"ok": True, "steps": summary,
                                 "results": results})
        payload: dict = {
            "ok": False,
            "error": failure["error"],
            # 失败之后 results 恒是**整批**，不再截到失败那条为止：三类步骤
            # （跑了的 / 失败的那条 / 根本没轮到的）各带 status，一眼分得开。
            "steps": summary,
            "results": results,
        }
        for k in ("gate", "how_to_fix", "bypass", "available", "camera"):
            if k in failure:
                payload[k] = failure[k]
        teardown = [r["op"] for r in results if r.get("ran_as") == "teardown"]
        if teardown:
            payload["teardown_ran"] = teardown
        return JSONResponse(payload,
                            status_code=failure.get("http_status", 500))

    @app.get("/status")
    async def status() -> dict:
        return {
            "ok": True,
            "instance": instance_id,
            "content_id": cfg.get("content_id"),
            # clients 从一个数字改成一张名单：光看数字没法决定下一步，查真相
            # 得跳出 aos 去 `frago browser list-tabs` 翻标签。带上身份之后，
            # "谁连着、是不是我的、几何收没收"一眼可见。
            "clients": [
                {"contentId": m.get("contentId"),
                 "instanceId": m.get("instanceId"),
                 "uiVersion": m.get("uiVersion"),
                 "accepted": bool(m.get("accepted")),
                 # 同实例多块荧幕时，只有一条是主荧幕、它的几何算数。
                 # 光看 accepted 分不清"还没报过 layout"和"报了但不算数"。
                 "primary": m is primary_meta(),
                 "reason": m.get("reason")}
                for m in stage.client_meta.values()
            ],
            "clients_count": len(stage.clients),
            # 现算，只含此刻还连着的外来荧幕——自检据此叫人去关标签，
            # 关掉了就该立刻不再报。
            "foreign_clients": sorted(
                ({"contentId": m.get("contentId"),
                  "instanceId": m.get("instanceId"),
                  "uiVersion": m.get("uiVersion")}
                 for m in stage.client_meta.values()
                 if m.get("reason") == FOREIGN_REASON),
                key=lambda c: c["contentId"] or "",
            ),
            # 同样现算：本实例多开的那些荧幕。与 foreign_clients 分开列，
            # 补救动作不同——那边关的是别的实例的标签，这边关的是本实例
            # 多开的标签，而且它很可能在另一个浏览器里。
            "duplicate_clients": [
                {"contentId": m.get("contentId"),
                 "instanceId": m.get("instanceId"),
                 "uiVersion": m.get("uiVersion"),
                 "seq": m.get("seq")}
                for m in own_screens()[:-1]
            ],
            "focus": stage.focus,
            # 三个程序各自开着没有。与 content_rects 分开报：那边答的是
            # "窗口摆在哪"，关掉的程序在那儿是个 null，看不出是关了还是
            # 收起来了，而两者的补救动作不同（window open vs window restore）。
            "windows_open": dict(stage.open),
            "cursor": {"x": stage.cursor[0], "y": stage.cursor[1]},
            "layout_reported": bool(stage.layout),
            # 自己的 pid。注册表里那份可能被探活清掉过（启动那十几秒端口还没
            # 开始 accept，read_instance 会把记录纠正成 stopped 并清 pid），
            # 那之后 `frago desktop down` 手里就没有可以 kill 的东西了——它改完
            # 记录就走，老 broker 照跑，下一次 up 又把它当现成的复用，于是改完
            # 代码怎么重启都还是老进程在服务。能应答的这一位自己报出来，
            # down 就永远有兜底的抓手。
            "pid": os.getpid(),
            # 持续状态，不是一次性信号：有主荧幕在看，且最近 UI_LIVE_WINDOW_SEC
            # 秒内收到过尺寸正确的帧。
            "ui_ready": ui_is_live(),
            "ui_live_window_sec": UI_LIVE_WINDOW_SEC,
            # 历史上有没有画出过首帧。保留下来是因为它答的是另一个问题
            # （桌面页这套渲染链路通没通），与"现在画面活不活"不是一回事。
            "ui_first_frame": ready.is_set(),
            # 演员标签还在不在。没有这一项的话，"标签被关了"和"页面静止不产帧"
            # 在自检眼里长得一模一样——两者都表现为帧龄一直涨——而它们的
            # 补救动作完全不同：一个要重开标签，另一个只要逼一次重绘。
            "actor_alive": not browser.actor_gone,
            "actor_gone_reason": browser.actor_gone_reason,
            "stale_clients": sorted(stage.stale_clients),
            "content_rects": {
                w: stage.content_rect(w) for w in ("term", "browser", "image")
            },
            # 尺寸真值：演员标签天然的视口（没人覆写它），以及 broker 据它的
            # 宽高比算出来的虚拟浏览器几何。核对方法是手算 H = W / r。
            **browser.viewport_report(),
            "browser_window": browser_geometry(browser_target_w["w"]),
            # 启动自检要判端口是否越界，真值只有 broker 手里有：
            # 注册表存的是 broker 的 HTTP 端口，不是 CDP 端口。
            "cdp_ports": {"stage": cfg.get("stage_port"),
                          "record": cfg.get("record_port")},
            "actor_target_id": browser.target_id,
            "elements": stage.elements,
            "term_grid": stage.term_grid,
            # 终端缓冲区有多少行、窗口现在看得见哪一段、贴没贴底。
            # 与 term_grid 分开报：那边是"一个字符格多大"，这边是"画面在看哪儿"，
            # 而后者决定 term:rows / term:match 的行号基准。
            "term_view": term_view_state(),
            "hover": (stage.hover or {}).get("ref"),
            # 取景框现状。它只作用于录制落盘的帧，所以这里报的是"下一帧会
            # 留下桌面的哪一块"，不是人在桌面页上看到的东西。
            "camera": recorder.camera.report(),
            "recorder": {
                "ready": recorder.alive,
                "recording": recorder.recording,
                "clip": recorder.name,
                "frames": len(recorder.stamps),
                "clips_dir": str(recorder.out_dir),
            },
        }

    return app


def main() -> None:
    cfg = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    cfg.setdefault("id", registry.DEFAULT_ID)
    # 归属校验的基准。算式只有 registry.content_id_for 一处，两边各写一遍
    # 必然漂移，而漂移的表现是 broker 把自己的荧幕当外来的全部拒掉。
    cfg.setdefault("content_id", registry.content_id_for(cfg["id"]))
    cfg.setdefault("port", 8770)
    cfg.setdefault("tmux_session", "frago-stage")
    cfg.setdefault("desktop", {"w": 1920, "h": 1080})
    cfg.setdefault("browser", {"w": 1280, "h": 800})
    cfg.setdefault("term", {"cols": 120, "rows": 32})
    cfg.setdefault("start_url", "about:blank")
    cfg.setdefault("fps", 30)
    # 演员 9222（`-b cdp` 的默认端口，profile 是从人真实 Edge 播种来的
    # edge/9222，带着现成登录态）、机位 9223。两台各占一个端口，谁也不能停掉谁。
    cfg.setdefault("stage_port", 9222)
    cfg.setdefault("record_port", 9223)
    cfg.setdefault("desktop_url", "")
    # 落点不 setdefault：它由起本进程的那一方交代（recipe.py 用平台交代的
    # FRAGO_RECIPE_DATA_DIR 算出 <落点>/clips 塞进 cfg）。这里从前写着一个
    # ~/.frago/data/agent-os/clips 的默认值，而注册表里实际用的是别的目录——
    # 兜底一旦生效，录屏片段就落进第二个目录，没有任何一层会报错。
    if not str(cfg.get("clips_dir") or "").strip():
        raise SystemExit(
            "起 broker 的一方没有交代 clips 落点（cfg.clips_dir 为空）。"
            "本进程只写交代给它的目录，请通过 frago desktop / frago recipe run 启动。"
        )
    # 端口上已经有一台活着的 broker 就直接退，一个字都不改注册表、一个浏览器
    # 都不拉。`frago desktop up` 会被人和守护服务同时敲，而 uvicorn 要等
    # lifespan 跑完（建 tmux、拉演员浏览器，好几秒）才开始监听——这段空窗里
    # 双方都探到"没人在跑"，于是各起一个。后起的那个在这里安静退场；
    # 拦不住的残余情况由 mark_stopped 的 owner_pid 兜底。
    if _broker_alive(cfg["port"]):
        _log(f"{cfg['port']} 上已有活着的 broker，本进程退场，不重复拉起")
        return
    # 上面那句探活挡不住同时起两个：`frago desktop up` 与守护服务几乎同时看到
    # "没人在跑"，双方都探到端口是空的，于是各起一个。真正分出胜负的是绑定端口
    # 那一下，而 uvicorn 是**先跑 lifespan 再绑端口**——输的那个已经把 tmux 会话
    # 建好（顺带把赢家那个同名会话 kill 掉了）、把演员浏览器接上、把注册表改成
    # 自己的 pid，然后才在绑定时失败退场，退场时又按流程收走 tmux 会话。
    #
    # 结果：赢家还活着、端口照应答、/status 一切正常，而它的终端会话没了,
    # broker.log 每 0.12 秒刷一条 capture-pane 失败，画面上终端全程空白。
    # 2026-08-20 实测撞到，这正是第 9 节 tmux_session 自检当年要抓的那种故障，
    # 只是换了个来路。
    #
    # 所以端口在这里先抢：绑上了才建舞台，绑不上一个字节都不碰。
    # 拿到的是一个已绑定的 socket，交给 uvicorn 复用，不给它第二次绑定的机会。
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", int(cfg["port"])))
    except OSError as exc:
        sock.close()
        _log(f"{cfg['port']} 已被占住（{exc}），本进程退场，不碰 tmux 会话")
        return
    server = uvicorn.Server(uvicorn.Config(
        build_app(cfg), host="127.0.0.1", port=int(cfg["port"]),
        log_level="warning",
    ))
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
