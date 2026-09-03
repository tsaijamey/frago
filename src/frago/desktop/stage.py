"""agent_os —— 一块虚拟 macOS 桌面舞台：把它拉起来，或者问它现在什么样。

要拍一段「在电脑上做某件事」的画面，真录屏会拍进私人窗口、通知气泡、乱七八糟的
标签页，而且不可重来。本模块把一个真实 tmux 会话和一个真实浏览器标签页重构成一块
可脚本操控的桌面画面，全屏打开后被录屏：终端里跑的是真命令，浏览器里开的是真网页，
桌面、窗口、鼠标、字幕都是画出来的，所以每一帧都可复现、可重来。

采集与操控的全部逻辑在同包的 broker.py；启动自检在 health.py；实例台账在
registry.py。本文件只做两件事——把舞台拉起来（up），把舞台现在的样子说清楚（status）。

停舞台、发指令、录制那些动词在同包的 aos.py 里（frago desktop 转发到它），指令直接
POST 到 broker 的 /control，不经过这个文件。视频制作的工艺、分镜与闸门在
video_pipeline_studio 手里：本模块答得出「画面是不是活的」，答不出「这条片子能不能用」。

本文件此前是配方 ``agent_os`` 的 recipe.py，能力建在 ``Recipe`` 基类上。搬进本体
之后基类没有了，它的六项服务各自换成了包内的现成东西：落点问 registry 要、页面状态
走 ``app_state.publish``、资产版本号本地算、开页走 ``viewer.browser.open_url``、
致命抛 ``StageFailed``、进度与警告走 logging。语义一条没改。

up 接受的参数（原 recipe.md 的 ``inputs:``，每个参数唯一的正式说明）
-------------------------------------------------------------------
``id``
    【已退役】虚拟桌面在这台电脑上只有一个，传 default 之外的值会被拒绝。字段留着
    只为不让旧调用方直接报参数错误。
``open``
    要不要开桌面页。传 true 一定开一个新的，传 false 一定不开；不传才走探测——
    先等 2.5 秒看本实例有没有主荧幕已经连着，有就复用。不传是对的默认，标签越攒越多
    正是不探测造成的。
``actor_mode``
    演员那台浏览器起成 headless（默认）还是 head。传 head 的唯一理由是演员要演的
    内容需要 GPU：无头带着 --disable-gpu 起，WebGL 拿不到，三维场景根本渲不出来
    而且没有任何一层报错。代价是一扇真窗口开在人屏幕上，还会抢一次焦点。
``desktop_width`` / ``desktop_height``
    桌面逻辑宽高，默认 1920 / 1080。
``browser_width`` / ``browser_height``
    首次读到演员真实视口之前的占位宽高，默认 1280 / 800。它不覆写任何东西——
    视口真值读自演员标签。
``term_cols`` / ``term_rows``
    舞台终端列数行数，默认 120 / 32。
``tmux_session``
    舞台终端那个 tmux 会话的名字，默认 frago-stage。
``start_url``
    舞台浏览器初始地址，默认 about:blank。
``fps``
    浏览器画面推送帧率上限，默认 30。
``port``
    broker 端口，默认 8770。
``stage_port``
    舞台浏览器（演员）的 CDP 端口，默认 9222——那是 -b cdp 的默认端口，profile
    edge/9222 由 frago 从人真实的 Edge profile 播种，带着现成登录态。白名单只认
    9222 / 9223。
``record_port``
    录制机位的 CDP 端口，默认 9223，舞台专用。必须与演员（9222）分开——stop 收走的
    是整台浏览器，共用端口就是互相顶掉。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from frago.recipes import app_state

from . import (
    health,  # 启动自检，与 aos.py 共用同一份实现
    registry,  # 同包模块，与 broker.py 共用注册表语义
)

logger = logging.getLogger(__name__)

#: 页面状态发布到哪个名字底下。与 registry.DATA_NAME 同名不是巧合：桌面页地址
#: /app/agent_os、台账落点 recipe-data/agent_os 都挂在这个名字上，换掉它等于让
#: 人手里那个标签页失联、369 个片子失联。见 migration-plan C7。
APP_NAME = "agent_os"

#: 采集与操控那支进程。用 frago 自己的解释器按模块起（`-m frago.desktop.broker`）：
#: 它顶层 import fastapi / uvicorn / websockets / PIL，那几样是 frago 的依赖，
#: 本进程的解释器手里就有。此前走 `uv run broker.py` 靠文件头的 PEP 723 块现装，
#: 那个块随搬家去掉了。
BROKER_MODULE = "frago.desktop.broker"

#: 演员那台浏览器起成无头还是有头。
#:
#: 默认无头——舞台存在的理由就是不占人的屏幕。传 head 的只有一种情形：演员要演的
#: 内容需要 GPU（无头带着 --disable-gpu 起，WebGL 拿不到，三维场景在里面不是渲得慢
#: 是根本渲不出来，而且没有任何一层会报错）。代价说在前面：有头就是一扇真窗口开在
#: 人的屏幕上，演员被调成可采集状态时还会把自己提到最前，抢一次焦点。
#:
#: 中间那档（把窗口挪到屏幕外）2026-08-23 撤掉了：macOS 只认进程开的第一扇窗，
#: 之后新建的窗口照样落在屏幕上——它从来没兑现过「看不见」，只是让人以为兑现了。
#: 所以它现在是个会被拒绝的值，NEVER 悄悄当成默认值处理。
ACTOR_MODES = {"headless": True, "head": False}

#: 等 broker 就绪的上限。到点还没起来就是致命，错误里带上 broker.log 的位置。
BROKER_READY_TIMEOUT_S = 90

#: 不传 open 时，探一次「本实例已经有主荧幕连着」要等多久。
#: 必须等：broker 刚起来时客户端必然是 0，人那个标签每秒重连一次，大约 1 秒后才回来。
#: 不等就会每次 up 都判成「没人开着」，于是又开一个——标签越攒越多，
#: 而这正是这条探测要治的病。
EXISTING_SCREEN_PROBE_S = 2.5

#: 自检前多等一会儿的上限，只在客户端数为 0 时用，一有客户端立刻走。
#: 刚重启的 broker 必然一个客户端都没有，不等就会在每次重启时报一条「没有桌面页连着」，
#: 而它一秒后自行消失——这种狼来了的告警报几次就没人看了。
HANDSHAKE_GRACE_S = 1.5

#: 桌面页的前端资产就在本包里，跟本文件同级。
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


class StageFailed(RuntimeError):
    """一句站得住的失败。

    从前是基类的 ``self.fail(...)``：它同时决定回执里的 ``ok: false`` 与非零退出码，
    两者永远一起动。搬进本体之后没有信封了，把两件事绑在一起的是调用方——
    ``aos.main()`` 抓住它、印一行 JSON、返回非零。
    """


# ── 落点 ──────────────────────────────────────────────────────────────────

def data_dir() -> Path:
    """本模块写东西的地方。与 registry 的台账落点是同一个目录。

    从前是基类的 ``self.data_dir``，由平台通过环境变量交代。改成自己向 registry 要，
    删掉的正是那份进程间的口头约定——本机的保活守护就是漏掉它才 4005 次拉不起舞台。
    """
    d = registry._instances_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def clips_dir() -> Path:
    """录屏片段落在哪。从前写作 ``self.store.path("clips")``。"""
    return data_dir() / "clips"


# ── up ────────────────────────────────────────────────────────────────────

def up(params: dict | None = None) -> dict:
    """把舞台拉起来。顺序是有讲究的，逐条写在下面。

    下面这七步的顺序不是流程图，是判据：每一步都在前一步成立之后才有意义，顺序换了
    不会报错，只会留下一台半成品舞台，而下一次 up 会把它当现成的复用。

      1. ``require_tmux`` —— 先查本机有没有 tmux。没有就致命，一个字节都不往下走
         ——后面每一步都会留下痕迹。
      2. ``resolve_config`` —— 合并参数与默认值：端口、尺寸、初始地址、演员有头无头；
         id 只认 default，clips 落点由 registry 求出。
      3. ``publish_desktop_page`` —— 发布桌面页要渲染的五项，其中 uiVersion 本地按
         资产内容算；算不出就是致命。
      4. ``resolve_desktop_url`` —— 算桌面页地址。算式只有
         ``health.expected_desktop_url`` 一处。
      5. ``ensure_identity_and_launch_broker`` —— 登记实例身份（已存在就原样返回，
         不重算），再拉 broker：端口上已经活着就复用，最多等 90 秒，中间报进度。
      6. ``settle_desktop_page`` —— 开不开桌面页。显式传 open 的优先；不传才探
         2.5 秒，看本实例有没有主荧幕已经连着，有就复用不开新标签。
      7. ``health_report`` —— 跑一次启动自检。恒不抛异常，查不了的项标 unavailable，
         本函数照常返回成功——诊断工具把被诊断对象搞挂是荒谬的。
    """
    params = params or {}

    # 1. 先查 tmux。MUST 在任何别的事情之前：后面每一步都会留下痕迹（发布页面
    #    状态、建实例记录、起进程、开标签页），在一台没有终端的机器上一路铺到
    #    最后再失败，留下的是一台半成品舞台——而下一次 up 会把那半成品当现成的
    #    复用。
    if not shutil.which("tmux"):
        raise StageFailed("本机没有 tmux，舞台终端无法启动")

    cfg = _build_config(params)
    content_id = _publish_desktop_page(cfg)

    # 桌面页地址必须先算出来再拉 broker：录制机位打开的就是这个页面，broker
    # 启动时就要知道拍哪儿。算式只有 health.expected_desktop_url 一处——
    # app_state.publish() 也算得出一个地址（page_url），但那是
    # http://localhost:8093/…，与算式给的 http://127.0.0.1:8093/… 是同一张页面的
    # 两个字符串。拿它去登记身份，自检的 desktop_url 那一项从此每次都报
    # 「桌面页地址变了」，而世界什么都没变。
    url = health.expected_desktop_url(content_id)
    # 算出来的地址 MUST 随 cfg 交给 broker：录制机位打开的就是它
    # （broker 拿 cfg["desktop_url"] 建机位）。不交代的话 broker 那边
    # setdefault 成空串，机位 `Page.navigate {"url": ""}` 落在随便哪个标签上，
    # 而 `_list_pages` 的 startswith("") 又匹配一切——
    # 录出来的片子拍的不是舞台，record.stop 照常报成功。
    cfg["desktop_url"] = url

    # 身份已存在就原样返回，不重算、不覆盖——身份的全部价值就在于它不变。
    # 人浏览器里那个标签页的门牌号不能因为换了个 broker 端口就换。
    identity = registry.ensure_identity(
        cfg["id"],
        desktop_url=url,
        clips_dir=cfg["clips_dir"],
        tmux_session=cfg["tmux_session"],
    )
    _launch_broker(cfg)
    runtime = registry.read_instance(cfg["id"]) or identity

    opened, reused = _settle_desktop_page(params, cfg, content_id, url)

    broker_status = _await_handshake(cfg["port"])
    report = health.report(_for_health(runtime), status=broker_status)
    _warn_stale_clips(runtime)
    _warn_from(report)

    return {
        # 与从前信封的 ok 重复，故意保留：现有调用方读的是它。
        "success": True,
        "id": cfg["id"],
        "url": url,
        "instance": {k: identity.get(k) for k in registry.IDENTITY_FIELDS},
        "runtime": {k: runtime.get(k) for k in registry.RUNTIME_FIELDS},
        "control": f"http://127.0.0.1:{cfg['port']}/control",
        "status": f"http://127.0.0.1:{cfg['port']}/status",
        "content_id": content_id,
        "tmux_session": cfg["tmux_session"],
        "browser_opened": opened,
        # 已经有主荧幕连着，所以这次没开新标签。人要看画面就用上面的 url。
        "screen_reused": reused,
        "health": report,
        "hint": "全屏打开 url 即被录制的画面；指令 POST 到 control",
    }


# ── status ────────────────────────────────────────────────────────────────

def status() -> dict:
    """舞台现在什么状态。MUST 只读。

    凭什么算只读：它只做三件事——读本模块自己的注册表文件、向 127.0.0.1 上
    自己那个 broker 的 /status 发一次 GET、跑一遍自检（自检会 capture-pane
    一次、scandir 两个目录）。不触网、不重算、不改状态、不开浏览器，别人每
    5 分钟问一次也不会出事。

    唯一一处可能落笔的地方写在明面上：registry.read_instance 读到一条写着
    running 的记录时会现场探活（pid 还在**且**端口应答），不成立就把 status
    就地纠正为 stopped 落盘。这不是新增状态，是把一句已经不成立的话改成真话；
    幂等，纠正一次之后不再写。不走它的话得在这儿抄一份「怎么算在跑」的判据，
    两份判据必然漂移——而这正是平台的守护服务当初宁可按路径 import registry.py
    也不肯抄的那份判据。
    """
    record = registry.read_instance(registry.DEFAULT_ID) or {}
    _warn_stale_clips(record)
    port = record.get("port")
    st = _fetch_status(port) if port else None
    return {
        "instance": {k: record.get(k) for k in registry.IDENTITY_FIELDS},
        "runtime": {k: record.get(k) for k in registry.RUNTIME_FIELDS},
        "control": f"http://127.0.0.1:{port}/control" if port else None,
        "broker": _broker_view(st),
        "health": health.report(_for_health(record), status=st),
    }


# ── 配置 ──────────────────────────────────────────────────────────────────

def _build_config(params: dict) -> dict:
    """合并参数与默认值，算出交给 broker 的那份 cfg。"""
    # 这台电脑上只有一个虚拟桌面。早先可以传 id 开多个，代价是每条指令都要先
    # 回答「打给哪一台」，而打错了回执照样一切正常。收成唯一之后这个问题不存在。
    if params.get("id") and params["id"] != registry.DEFAULT_ID:
        raise StageFailed(
            f"虚拟桌面在这台电脑上只有一个，不接受 id={params['id']}"
        )
    instance_id = registry.DEFAULT_ID

    mode = params.get("actor_mode", "headless")
    if mode not in ACTOR_MODES:
        raise StageFailed(
            f"actor_mode 只认 {sorted(ACTOR_MODES)}，得到: {mode!r}。"
            f"offscreen（把窗口挪到屏幕外）2026-08-23 撤掉了，它从来没兑现过"
            f"「看不见」——macOS 只认进程开的第一扇窗。"
        )

    return {
        "id": instance_id,
        # 录屏片段落 registry 求出的落点底下，NEVER 自己拼路径。
        "clips_dir": str(clips_dir()),
        "port": int(params.get("port", 8770)),
        # CDP 端口两个：演员 9222、机位 9223，两台都是 Edge。
        # 演员在 9222 是因为那是 `-b cdp` 的默认端口，那份 profile 由 frago 从人
        # 真实的 Edge profile 播种，带着现成登录态，舞台起来就能用。
        # 机位必须与它分开：停录时机位要 `-b cdp stop` 收走自己，共用端口那一下
        # 会把演员一起带走。白名单之外的端口会留垃圾 profile 目录，禁止自创。
        "stage_port": int(params.get("stage_port", 9222)),
        "record_port": int(params.get("record_port", 9223)),
        "tmux_session": params.get("tmux_session", "frago-stage"),
        "desktop": {
            "w": int(params.get("desktop_width", 1920)),
            "h": int(params.get("desktop_height", 1080)),
        },
        "browser": {
            "w": int(params.get("browser_width", 1280)),
            "h": int(params.get("browser_height", 800)),
        },
        "term": {
            "cols": int(params.get("term_cols", 120)),
            "rows": int(params.get("term_rows", 32)),
        },
        "start_url": params.get("start_url", "about:blank"),
        "fps": int(params.get("fps", 30)),
        "actor_headless": ACTOR_MODES[mode],
    }


# ── 页面 ──────────────────────────────────────────────────────────────────

def _publish_desktop_page(cfg: dict) -> str:
    """发布桌面页要渲染的那五项，返回本实例的 content_id。

    发的只是渲染状态，一项路径都没有。理由不是洁癖：访客机器上没那个文件，能读
    任意路径的接口对访客一律关死，而落点一挪页面还在读老地方、每次刷新都显示成功。

    页面**文件**从前不在本模块手里（recipe.md 里写着 ui_from: agent_os_ui，服务端
    直接从对方目录发）。搬进本体之后那四个文件就在 ``assets/`` 里，但这里发的东西
    一个字都没变——路径仍然不进页面状态。
    """
    # content_id 由实例 id 算，与端口无关：桌面页地址是人手里那个标签页的门牌号，
    # 不能因为换了个 broker 端口就换门牌，逼人重开标签。
    content_id = registry.content_id_for(cfg["id"])
    cfg["content_id"] = content_id
    cfg["ui_version"] = ui_version()

    slot = "default" if content_id == health.DEFAULT_CONTENT_ID else content_id
    app_state.publish(
        APP_NAME,
        {
            "brokerWs": f"ws://127.0.0.1:{cfg['port']}/stream",
            "desktop": cfg["desktop"],
            "uiVersion": cfg["ui_version"],
            # 荧幕归属：桌面页必须知道自己属于哪个实例。端口不属于身份（所有
            # 实例默认都是 8770），旧实例遗留的标签每秒重连一次，连上后来的
            # broker 是必然事件；它一上报 layout 就会把自己那块荧幕的窗口几何
            # 按在新舞台上——症状是网页只占窗口左上角一小块，而日志一切正常。
            # contentId 是荧幕归属的依据，broker 拿它比对；instanceId 是人和
            # 日志读得懂的名字。两个都写，缺一不可。
            "contentId": content_id,
            "instanceId": cfg["id"],
        },
        slot,
    )
    return content_id


def asset_files() -> list[Path]:
    """assets/ 里的常规文件，按文件名升序。

    目录没了、或者一个文件都没有，都是**致命**的：空资源包发出去是一张打不开的
    页面，而且版本算不出来。分界线只有一条——这套资产还答不答得出来。
    """
    if not ASSETS_DIR.is_dir():
        raise StageFailed(
            f"assets 目录不存在：{ASSETS_DIR}。"
            f"它跟本文件同级，是桌面页的正身，不是可选的缓存"
        )
    files = sorted((p for p in ASSETS_DIR.iterdir() if p.is_file()),
                   key=lambda p: p.name)
    if not files:
        raise StageFailed(
            f"assets 目录在，但一个常规文件都没有：{ASSETS_DIR}。"
            f"空资源包发出去是一张打不开的页面"
        )
    return files


def ui_version() -> int:
    """页面资产的版本号：资产内容的哈希，取 48 位。

    这个数字本身没有意义，唯一的要求是**资产变了它就变**：桌面页每次上报 layout
    都带着它，broker 拿它做**相等**比对，对不上就整条丢弃并叫那个标签自己刷新。
    所以算不出来就是致命——发一个没有版本号的页面状态出去，等于把每个标签都标成
    旧的，画面变形，而没有一处报错。

    **口径换了，是被迫的，不是顺手改的。** 从前是「资产目录下全部常规文件 mtime 的
    最大值」，由 agent_os_ui 走总线算。那个口径在配方年代成立：文件躺在磁盘上，改它
    mtime 就动。进了 wheel 就不成立了——wheel 里每个条目的时间戳被归一化成固定值，
    装完之后 mtime 至多是安装时刻，**不是资产内容的函数**：两个内容不同的 frago 版本
    完全可能算出同一个数，而 broker 拿它做相等比对，一样就当成同一版资产。
    哈希满足「资产变了它就变」，mtime 不再满足。

    名字一并进哈希：少一个文件、改一个文件名，都是资产变了。

    48 位是为了 JavaScript：桌面页把这个数原样带回来比对，超过 2^53 就不再是精确
    整数，一个来回之后自己跟自己对不上。48 位远在安全区内。
    """
    digest = hashlib.sha256()
    for p in asset_files():
        digest.update(p.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(p.read_bytes())
        digest.update(b"\0")
    return int(digest.hexdigest()[:12], 16)


# ── broker ────────────────────────────────────────────────────────────────

def _launch_broker(cfg: dict) -> None:
    """端口上已经活着就复用，NEVER 再起一个。

    两个 broker 抢同一个 tmux 会话会互相 kill，画面会莫名其妙清空；而且后起的
    那个绑不上端口、当场收尾，它的收尾会把**活着的那个**注销成 stopped，之后
    每条指令都被「实例存在但没在运行」挡掉，而画面其实好端端地在推。
    """
    port = cfg["port"]
    if _port_alive(port):
        logger.info("broker 已在 %s 上跑着，复用它", port)
        return

    log_path = data_dir() / "broker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", BROKER_MODULE,
             json.dumps(cfg, ensure_ascii=False)],
            # cwd 仍然显式给成本包的目录：从前给的是配方目录，理由是 broker 要
            # import 同目录的 registry。那条理由随相对 import 消失了，但把 cwd
            # 钉在代码所在的目录这件事本身照旧——搬家不是重新决定 cwd 的时机。
            cwd=str(Path(__file__).resolve().parent),
            stdout=log,
            stderr=log,
            # 环境原样传下去。落点不再靠环境变量交接——registry 自己求。
            start_new_session=True,
        )

    deadline = time.time() + BROKER_READY_TIMEOUT_S
    waited = 0
    while time.time() < deadline:
        if _port_alive(port):
            logger.info("broker 就绪（等了 %s 秒）", waited)
            return
        # 不报进度的话，一个要等一分半的启动和一个卡死的启动在调用方眼里
        # 长得一模一样。
        logger.info("等 broker 在 %s 上就绪（%s/%s）",
                    port, waited, BROKER_READY_TIMEOUT_S)
        time.sleep(1)
        waited += 1
    # 已起的进程留在原地，不去猜着 kill。
    raise StageFailed(
        f"broker 未能在 {BROKER_READY_TIMEOUT_S} 秒内就绪，详见 {log_path}"
    )


def _port_alive(port) -> bool:
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/status", timeout=1
        ).read()
        return True
    except Exception:  # noqa: BLE001 探活只有活/不活两种答案
        return False


def _fetch_status(port):
    """取 broker /status。不可达返回 None，由自检标 unavailable。"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/status", timeout=2
        ) as resp:
            return json.loads(resp.read())
    except Exception:  # noqa: BLE001 探不到就是探不到，别把原因编成状态
        return None


def _await_handshake(port):
    """自检前取一次 /status，只在客户端数为 0 时多等一会儿。

    不轮询等 ui_ready：那要等舞台浏览器吐出第一帧，静止页面可能一直不吐——
    那条 WARN 是真的，附带的补救动作就是逼一次重绘。
    """
    st = _fetch_status(port)

    def handshaken(s) -> bool:
        # 连上 + 报过几何 = 握手完成。
        return bool(s and s.get("clients_count") and s.get("layout_reported"))

    if st is None or handshaken(st):
        return st
    deadline = time.time() + HANDSHAKE_GRACE_S
    while time.time() < deadline:
        time.sleep(0.2)
        probe = _fetch_status(port)
        if probe is None or handshaken(probe):
            return probe or st
    return st


def _broker_view(st) -> dict:
    """broker 报的采集 / 客户端 / 几何上报。

    探不到就如实说不可达，NEVER 当成正常：其余字段一律 null，NEVER 拿 0 或
    false 顶上去——「没有客户端连着」和「问不到」是两件事，补救动作也不同
    （一个去开标签页，一个去看 broker 死没死），混成一个数就等于拿一个编出来的
    0 去骗自检。
    """
    fields = ("clients", "clients_count", "layout_reported", "ui_ready",
              "frame_age_sec", "actor_viewport", "focus", "windows_open",
              "cdp_ports", "pid")
    if st is None:
        return {"reachable": False, "recording": None,
                **{f: None for f in fields}}
    return {
        "reachable": True,
        **{f: st.get(f) for f in fields},
        "recording": (st.get("recorder") or {}).get("recording"),
    }


# ── 桌面页 ────────────────────────────────────────────────────────────────

def _settle_desktop_page(params: dict, cfg: dict, content_id: str, url: str):
    """开不开桌面页，返回 (browser_opened, screen_reused)。

    显式传 open 的照旧优先：人说不开就不开，人说要开就一定开一个新的。
    不传（默认）时才走探测——`frago desktop up` 会被反复拉起，每次都开一个新
    标签就是荧幕越攒越多的源头，而实例身份永久，老标签本来就还连着。
    """
    wants = params.get("open")
    if wants is False:
        return False, False
    if wants is True:
        return _open_desktop_page(url), False
    if _wait_for_existing_screen(cfg["port"], content_id):
        logger.info("本实例已经有主荧幕连着，不再开新标签")
        return False, True
    return _open_desktop_page(url), False


def _wait_for_existing_screen(port, content_id: str) -> bool:
    """探一次已经连着的**本实例**荧幕。

    必须核对 content_id：端口不属于身份，探到的很可能是别的实例的 broker。
    只看 primary 的话，别人那块荧幕会让这次 up 判成「已经有人开着」，于是自己
    的桌面页一个也不开——回执还写着 screen_reused: true，看上去一切正常，
    人却对着空白等画面。
    """
    deadline = time.time() + EXISTING_SCREEN_PROBE_S
    while True:
        st = _fetch_status(port)
        if st and st.get("content_id") == content_id:
            if any(c.get("primary") for c in (st.get("clients") or [])):
                return True
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def _open_desktop_page(url: str) -> bool:
    """走 viewer.browser.open_url：它用系统默认浏览器，是把页面给人看的唯一入口。

    NEVER 用 `frago browser navigate`——那会把页面塞进 agent 正在驱动的那个
    CDP 浏览器，既占着 agent 的浏览器，又让录制依赖那个浏览器活着。

    开不开得成不致命：人拿回执里的 url 自己开就是了。
    """
    from frago.viewer.browser import open_url

    if open_url(url):
        return True
    _warn(f"桌面页没能自动打开（系统里没有可用浏览器？），请自己打开 {url}")
    return False


# ── 自检 ──────────────────────────────────────────────────────────────────

def _for_health(record: dict) -> dict:
    """交给自检的那份实例记录：clips_dir 换成本次运行算出来的落点。

    registry.ensure_identity 对已存在的记录一个字段都不重算（身份的价值就在于
    它不变），所以老记录里的 clips_dir 可能指着一个早就不存在的目录，而 broker
    实际把片子写在算出来的落点下。自检的 clips 那一项读注册表那条，就会在查
    一个空气目录，报「尚未创建（还没录过）」并标 ok——一句错话，而且是自检最不该
    说的那种错话。

    up 与 status 都走这条：自检两处共用同一份实现，一处修好另一处照旧，
    就等于没修。

    **注册表文件不动**：身份层永不重算是 registry 的设计，不在这一层推翻。
    回执里那份 instance 也照旧是台账原文的忠实回声——它回答的是「登记时是什么」，
    与「这次片子写在哪」是两个问题，混成一个字段两边都说不清。
    """
    return {**record, "clips_dir": str(clips_dir())}


def _warn_stale_clips(record: dict) -> None:
    """台账里登记的录屏落点跟本次运行的落点不是一个地方时，喊一声。

    不致命：片子照录，落点由本次运行的 cfg 交给 broker，一直是对的。
    但**回执里那份 instance 是台账原文的忠实回声**，它照旧报着登记那天的路径。
    人照它去找素材会扑空，而自检那一项报的是真落点、数得出真文件数——
    同一份回执里两个字段各说一个地方，是最难查的形状。

    2026-08-27 实测过：台账里写着 ~/.frago/data/agent_os/clips（2026-07-22 登记，
    那个目录如今根本不存在），真落点在算出来的落点底下，116 个文件。

    所以这儿不去改那份回声——身份层永不重算是 registry 的设计，不在这一层推翻——
    而是把「这两条对不上」这件事本身说出来。悄悄换成对的再假装没事，
    下一个人还会踩同一脚。

    病根记在这儿：**录屏落点根本不该待在身份层**。身份层装的是门牌号
    （桌面页地址、荧幕归属），价值就在于永不变；而落点是每次运行现算的。
    两者同层，就必然出现「登记时是对的、后来落点变了、而记录按设计不许重算」
    这个死结。搬它要动 registry.IDENTITY_FIELDS，得单独一轮，连着守护一起验。
    """
    registered = str(record.get("clips_dir") or "").strip()
    if not registered:
        return
    live = str(clips_dir())
    if registered == live:
        return
    gone = not Path(registered).expanduser().exists()
    _warn(
        f"台账里登记的录屏落点是 {registered}"
        f"{'（这个目录已经不存在）' if gone else ''}，"
        f"而本次运行的落点是 {live}。回执里 instance.clips_dir 报的是前者"
        f"——那是登记那天的值，身份层按设计不重算。**找素材去后者**，"
        f"自检的 clips 那一项数的也是后者。"
    )


def _warn_from(report: dict) -> None:
    """自检里那条「桌面页还没连上来」升一级说出来。

    不致命：舞台立得住，指令照常执行。但它值得一句 warn——那条 WARN 自带
    means / if_ignored / how_to_fix 三段，人读到才知道该去开标签页。
    自检本身恒不抛异常：它是诊断不是门禁，任何一项查不了都如实标 unavailable，
    本函数照常返回成功。诊断工具把被诊断对象搞挂是荒谬的。
    """
    for check in report.get("checks", []):
        if check.get("item") != "ui_ready" or check.get("level") != "warn":
            continue
        if not check.get("clients"):
            _warn(f"{check.get('detail')}；{check.get('how_to_fix')}")


def _warn(message: str) -> None:
    """出了点事，但答案还算数。

    从前是基类的 ``self.warn(...)``：它把这句话记进信封的 warnings 数组。
    信封没有了，而 up / status 的回执形状是对外承诺，不能为了塞警告改它——
    所以警告走日志。一个不可读的文件不该让另外二十五个从页面上消失，把警告
    和失败合成一件事，模块就失去了「部分坏掉」这个状态，而真实的模块大多在
    那个状态里。
    """
    logger.warning("%s", message)
