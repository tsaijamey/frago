#!/usr/bin/env python3
"""agent_os 启动自检：只报会静默出错的项。

"静默出错"是选检查项的唯一标准。这八项全部真实出过事（screen_ownership 与
screen_duplicates 是 2026-07-23 实测暴露的，tmux_session 是 2026-07-24，
其余在 v1 阶段），共同点是
出事的时候系统一声不吭——桌面页空白但没有报错、指令打在孤儿实例上但回执正常、
磁盘被 clips 吃掉但录制照常成功。会自己抛错的事情不需要自检，它们已经在喊了。

三条设计约束：

  **自检不是门禁。** 任何一项检查自己出错（目录不可读、注册表损坏、broker 不可达）
  都不得影响配方启动，该项如实标 unavailable。诊断工具把被诊断对象搞挂是荒谬的。

  **判定必须带阈值。** 没有阈值的检查项等于每次都报，报多了等于没报。
  够格才标 WARN。

  **提问必须可行动。** 不写"是否有风险"这类开放式提问——开放式问题换来的
  永远是敷衍的"无风险"。每条 WARN 自带 means / if_ignored / how_to_fix 三段，
  报告整体带一个要求 agent 逐条回应的指令性字段。约束长在动作上，不长在措辞上。

recipe.py（启动时）与 frago desktop status（随时）共用本模块，两处输出的是同一份报告。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

FRAGO_HOME = Path.home() / ".frago"
# 舞台两台都是 Edge，profile 落在 profiles/edge/<port>/。
BROWSER_PROFILES_DIR = FRAGO_HOME / "profiles" / "edge"

# CDP 端口白名单，两个，都是 Edge：
#   9222 演员（常驻。`-b cdp` 的默认端口，profile edge/9222 由 frago 从人真实的
#        Edge profile 播种，带着现成登录态）
#   9223 机位（只在录制期间存在，不需要任何登录态）
# 两者必须分开：停录时机位要 `-b cdp stop` 收走自己，共用端口那一下会把演员
# 一起带走。
# 除这两个之外的每个自创端口都会留一个 profile 目录，而且指令仍然"成功"
# ——打在一个没人看的浏览器上。
CDP_WHITELIST = (9222, 9223)

# clips 阈值。当前稳态是 43 个文件 / 57MB（跨会话累积的正常产物），
# 阈值取到它的一个数量级之上：到这个量级时才真正开始有代价——占盘、
# 目录列举变慢、找片子靠翻。低于此只是"攒了些东西"，不该占用注意力。
CLIPS_MAX_BYTES = 500 * 1024 * 1024
CLIPS_MAX_FILES = 200

DESKTOP_BASE = "http://127.0.0.1:8093/app/agent_os"

# 默认实例的 content_id。算式在 registry.content_id_for，这里只固化结果，
# 为的是自检不必依赖 registry 也能判断"这个 content_id 是不是默认实例"。
# 两处若漂移，check_desktop_url 会立刻报出来——它比的就是这个算式。
DEFAULT_CONTENT_ID = "bc98c2f8114b"


def expected_desktop_url(content_id: str) -> str:
    """桌面页地址的唯一算式。

    recipe.py 与自检各写一遍必然漂移，而漂移的表现是"自检天天报 URL 变了"
    或者更糟——真变了却报不出来。

    页面文件不再被复制到任何地方，服务端直接从 frago 包里的 desktop/assets/ 发
    （2026-09-02 之前是从 agent_os_ui 配方的目录），所以地址里不再有哈希目录。
    默认实例就是光秃秃的 /app/agent_os，人记得住；具名实例把自己的 content_id
    挂在查询参数上，各占一块互不覆盖。

    这个地址被写死在每个实例的台账里、也被人浏览器里那个标签页记着，**一个字符
    都不能改**：身份层按设计永不重算，改了它等于让那个标签页永远连不回来。
    """
    if content_id == DEFAULT_CONTENT_ID:
        return DESKTOP_BASE
    return f"{DESKTOP_BASE}?key={content_id}"


def _ok(item: str, detail: str, **extra) -> dict:
    return {"item": item, "level": "ok", "detail": detail, **extra}


def _warn(item: str, detail: str, *, means: str, if_ignored: str,
          how_to_fix: str, **extra) -> dict:
    return {
        "item": item, "level": "warn", "detail": detail,
        "means": means, "if_ignored": if_ignored, "how_to_fix": how_to_fix,
        **extra,
    }


def _unavailable(item: str, exc: BaseException | str) -> dict:
    return {
        "item": item, "level": "unavailable",
        "detail": f"该项检查不可用: {exc}",
        "means": "这一项这次没查成，不代表它没问题，也不代表它有问题。",
        "if_ignored": "该项的故障若真的存在，本次不会被发现。",
        "how_to_fix": "若本次任务依赖该项，手工确认一次；否则记录后继续。",
    }


def _guard(fn, item: str) -> dict:
    """检查项自身出错时降级为 unavailable，绝不向上抛。

    自检是诊断不是门禁——让配方因为"查不了 clips 目录"而启动失败，
    是把诊断工具变成新的故障源。
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 任何异常都只降级
        return _unavailable(item, f"{type(exc).__name__}: {exc}")


# ── 六项检查 ──

def check_clips(clips_dir: str | None) -> dict:
    item = "clips"
    if not clips_dir:
        return _unavailable(item, "实例记录里没有 clips_dir")
    d = Path(clips_dir).expanduser()
    if not d.exists():
        return _ok(item, f"{d} 尚未创建（还没录过）", files=0, bytes=0)
    total = 0
    files = 0
    # 一层 scandir，不递归：clips 是平铺的 <name>.mp4 / <name>.jsonl，
    # 递归只会去踩 ffmpeg 的临时帧目录，慢且没有意义。
    with os.scandir(d) as it:
        for entry in it:
            if entry.is_file(follow_symlinks=False):
                files += 1
                total += entry.stat().st_size
    mb = total / 1024 / 1024
    shape = f"{files} 个文件 / {mb:.0f}MB"
    if total <= CLIPS_MAX_BYTES and files <= CLIPS_MAX_FILES:
        return _ok(item, f"{shape}（阈值 {CLIPS_MAX_FILES} 个 / "
                         f"{CLIPS_MAX_BYTES // 1024 // 1024}MB）",
                   files=files, bytes=total, path=str(d))
    return _warn(
        item,
        f"{shape}，超过阈值 {CLIPS_MAX_FILES} 个 / "
        f"{CLIPS_MAX_BYTES // 1024 // 1024}MB：{d}",
        means="录制产物跨会话累积到了值得看一眼的量级。这是提示，不是要求清理——"
              "这些文件本身没有损坏，录制功能也照常可用。",
        if_ignored="继续录制会继续占盘；找历史片子要在更长的列表里翻。"
                   "对本次任务通常没有影响。",
        how_to_fix=f"若确实要腾地方，人工挑选后删除 {d} 下不再需要的 "
                   f"<name>.mp4 / <name>.jsonl；jsonl 是训练语料，删前确认已归档。",
        files=files, bytes=total, path=str(d),
    )


def check_cdp_ports(ports: dict | None) -> dict:
    """配方实际使用的 CDP 端口是否落在白名单内。"""
    item = "cdp_ports"
    if not ports:
        return _unavailable(item, "拿不到 broker 的端口配置（broker 未运行？）")
    offending = {role: p for role, p in ports.items()
                 if int(p) not in CDP_WHITELIST}
    if not offending:
        return _ok(item, f"{ports} 全部落在白名单 {list(CDP_WHITELIST)} 内",
                   ports=ports)
    return _warn(
        item,
        f"越界端口 {offending}，白名单只有 {list(CDP_WHITELIST)}",
        means="配方正在用白名单之外的 CDP 端口。9222 是演员、9223 是机位，"
              "其余端口一律是自创的。",
        if_ignored="每个自创端口会在 ~/.frago/profiles/edge/<port>/ 留一个"
                   "永久 profile 目录；演员跑偏到别的端口还会丢掉 edge/9222 那份"
                   "播种来的登录态，撞上登录墙而毫无提示。更糟的是指令打在一个"
                   "没人看的浏览器上，回执一切正常而画面纹丝不动。",
        how_to_fix="把配方参数里的 stage_port 改回 9222、record_port 改回 9223，"
                   "重启 broker，再删掉越界端口留下的 profile 目录。",
        ports=ports,
    )


def _port_listening(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.05)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        s.close()


def check_orphan_profiles() -> dict:
    """~/.frago/profiles/edge/ 下的越界目录，以及它们是否还活着。"""
    item = "orphan_profiles"
    if not BROWSER_PROFILES_DIR.exists():
        return _ok(item, f"{BROWSER_PROFILES_DIR} 不存在（还没起过浏览器）",
                   orphans=[])
    orphans = []
    with os.scandir(BROWSER_PROFILES_DIR) as it:
        for entry in it:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name.isdigit() and int(entry.name) in CDP_WHITELIST:
                continue
            orphans.append(entry.name)
    if not orphans:
        return _ok(item, f"{BROWSER_PROFILES_DIR} 下只有 "
                         f"{[str(p) for p in CDP_WHITELIST]}", orphans=[])
    # 只对越界目录探活——正常情况这个列表是空的，探活成本为零。
    alive = [n for n in orphans if n.isdigit() and _port_listening(int(n))]
    return _warn(
        item,
        f"{BROWSER_PROFILES_DIR} 下有白名单外的目录: {sorted(orphans)}"
        + (f"；其中 {sorted(alive)} 端口仍在监听，是活着的残留实例" if alive
           else "；均未在监听，是孤儿目录"),
        means="有人用过白名单外的 CDP 端口。目录是那次使用留下的 profile。"
              + ("其中一部分现在还有进程占着。" if alive else ""),
        if_ignored=("活着的残留实例会继续占内存，并且可能抢走本该发给 9222 / 9223 的"
                    "调试连接——指令打过去回执正常，桌面画面却不动。"
                    if alive else
                    "孤儿目录只占盘，不影响功能；但它是曾经跑偏过的证据，"
                    "留着会让下次自检继续报同一条。"),
        how_to_fix=(f"先 `frago browser -b cdp stop` 或按端口停掉 {sorted(alive)} "
                    f"的进程，再删除 " if alive else "直接删除 ")
                   + "、".join(str(BROWSER_PROFILES_DIR / n)
                               for n in sorted(orphans)),
        orphans=sorted(orphans), alive=sorted(alive),
    )


def check_desktop_url(instance: dict) -> dict:
    """注册表里的桌面页地址是否仍等于当前算式的结果。"""
    item = "desktop_url"
    recorded = instance.get("desktop_url")
    content_id = instance.get("content_id")
    if not recorded or not content_id:
        return _unavailable(item, "实例记录缺 desktop_url 或 content_id")
    expected = expected_desktop_url(content_id)
    if recorded == expected:
        return _ok(item, f"与上次一致: {recorded}", url=recorded)
    return _warn(
        item,
        f"桌面页地址变了：注册表记录 {recorded}，当前应为 {expected}",
        means="人浏览器里那个标签页的门牌号换了。身份层的 desktop_url 本该永久稳定，"
              "它变了说明 content_id 算法、viewer 路径或注册表被改动过。",
        if_ignored="人手里开着的还是旧地址那个标签页，它会一直重连一个不再有内容的"
                   "地址——画面永远空白，且没有任何报错。录制拍到的也是空白页。",
        how_to_fix=f"请人在浏览器里重开 {expected}；确认这次变更是有意的之后，"
                   f"再用新地址更新注册表 "
                   f"{FRAGO_HOME}/data/agent-os/instances/{instance.get('id')}.json。",
        recorded=recorded, expected=expected,
    )


def _client_count(status: dict) -> int:
    """clients 现在是一张带身份的名单，早先是个数字。两种形状都认。

    形状变过一次就会有别处还按旧形状读，而读错的表现是"客户端数永远是 0"
    或者报出一个列表当数字用，都不会抛错。这里认死两种形状，别处只调它。
    """
    clients = status.get("clients")
    if isinstance(clients, list):
        return len(clients)
    if isinstance(clients, int):
        return clients
    return int(status.get("clients_count") or 0)


def check_screen_ownership(status: dict | None) -> dict:
    """连上来的桌面页里有没有不属于本实例的荧幕。

    与 ui_ready 里那条 stale 分开报：那条查的是**资产版本旧**，这条查的是
    **实例不对**。两个实例的资产版本完全可能相同（同一份资产复制过去的），
    那时版本这条防线一个字都拦不住，而症状——网页只占窗口左上角一小块——
    看上去和版本问题一模一样。合并成一条就等于让人对着错误的补救动作使劲。
    """
    item = "screen_ownership"
    if status is None:
        return _unavailable(item, "broker /status 不可达")
    foreign = status.get("foreign_clients")
    if foreign is None:
        return _unavailable(
            item, "broker /status 不带 foreign_clients（broker 是旧版本？）")
    mine = status.get("content_id")
    if not foreign:
        return _ok(item, f"连着的荧幕都属于本实例（contentId={mine}）",
                   content_id=mine, foreign=[])
    who = "、".join(
        f"{c.get('instanceId') or '未知实例'}（contentId={c.get('contentId')}）"
        for c in foreign
    )
    return _warn(
        item,
        f"有不属于本实例的桌面页连着：{who}；本实例 contentId={mine}",
        means="别的实例遗留的桌面页标签连上了这台 broker。端口不属于身份——"
              "所有实例默认都是 8770，那个标签每秒重连一次，撞上来是必然的。"
              "它的 layout 已被整条丢弃，但画面照推，所以它看起来一切正常。",
        if_ignored="拒绝之前它的窗口几何会覆盖真实布局，舞台视口被设成不属于"
                   "它的那块荧幕的尺寸，网页只贴在窗口左上角一小块；"
                   "而且盯着它看的人以为自己在看本实例的画面。",
        how_to_fix="关掉那个标签页——它的地址是 "
                   + "、".join(
                       expected_desktop_url(c.get("contentId"))
                       for c in foreign if c.get("contentId")
                   )
                   + "；只留本实例 instance.desktop_url 那一个。",
        content_id=mine, foreign=list(foreign),
    )


def check_screen_duplicates(status: dict | None) -> dict:
    """本实例自己有没有被开成好几块荧幕。

    与 screen_ownership 分成两项而不是合并：那条说的是**别的实例**的标签连过来了，
    这条说的是**本实例**的标签被开了不止一个。两条的补救动作指向的是不同的标签页，
    合并成一句"关掉多余的标签"，人会去关错的那个。
    """
    item = "screen_duplicates"
    if status is None:
        return _unavailable(item, "broker /status 不可达")
    dup = status.get("duplicate_clients")
    if dup is None:
        return _unavailable(
            item, "broker /status 不带 duplicate_clients（broker 是旧版本？）")
    if not dup:
        return _ok(item, "本实例只有一块荧幕", duplicates=[])
    mine = status.get("content_id")
    url = expected_desktop_url(mine) if mine else "实例的 desktop_url"
    return _warn(
        item,
        f"本实例有 {len(dup) + 1} 块荧幕连着（同一个 contentId={mine} 开了多次）",
        means=("实例身份是永久的，桌面页地址永久稳定，而桌面页每秒重连一次 broker，"
               "所以历史上开过的每一个标签只要还在就都会连回来。broker 已经只认"
               "最新连上的那块为主荧幕，其余几块的窗口几何整条丢弃、画面照推——"
               "它们看起来一切正常。"),
        if_ignored=("在没有这层过滤的旧 broker 上，几块荧幕的窗口几何会轮流覆盖"
                    "舞台视口，视口在两个尺寸之间来回跳；画帧走 letterbox，"
                    "比例一对不上就四周留白，看起来像网页没填满虚拟浏览器窗口。"
                    "现在几何不会跳了，但你在非主荧幕上看到的画面仍然不是"
                    "按它自己的窗口算的。"),
        how_to_fix=("关掉多余的那个标签页，只留一个 " + url + "。"
                    "注意它很可能开在**另一个浏览器**里——`frago desktop up` 默认用系统"
                    "默认浏览器打开桌面页，而 `frago browser list-tabs` 只看得见"
                    "扩展所在的那个浏览器，在那里找不到不等于它不存在，"
                    "得人自己到各个浏览器窗口里翻。"),
        content_id=mine, duplicates=list(dup),
    )


def check_tmux_session(instance: dict) -> dict:
    """舞台终端的 tmux 会话还在不在。

    2026-07-24 新加。此前没有任何一处会发现它不在：`frago desktop down` 在 broker 已经
    失联时返回 None 且没真停，下一次 `up` 复用了那个半死的 broker——它连着
    8770、能应答 /status，却从没走过建 tmux 会话那一步。表现是终端窗口全程
    空白，而 /status 一切正常，因为 ui_ready 只反映浏览器画面帧、不管终端。
    唯一的证据是 broker.log 里每 0.12 秒一条 `capture-pane 失败`。

    判据用 capture-pane 而不是 has-session：前者是终端画面这条链路的端到端
    检验，后者只答"有这么个名字"。不经 broker 直接问 tmux——broker 不可达时
    这一项仍然答得出来，而那恰好是最需要它的时候。
    """
    item = "tmux_session"
    session = instance.get("tmux_session")
    if not session:
        return _unavailable(item, "实例记录里没有 tmux_session")
    proc = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", session],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if proc.returncode == 0:
        return _ok(item, f"{session} 在，capture-pane 取到 "
                         f"{len(proc.stdout.splitlines())} 行",
                   session=session)
    return _warn(
        item,
        f"tmux 会话 {session} 取不到画面: "
        + ((proc.stderr or proc.stdout).strip() or "capture-pane 失败"),
        means="舞台终端的会话不存在。要么 broker 从没建成它（复用了一个半死的"
              "broker 实例），要么它已被杀掉。",
        if_ignored="终端窗口在桌面上全程空白，而所有指令回执与 /status 都正常——"
                   "`frago desktop term run` 送出去的命令没有任何地方在执行，"
                   "录进片子的是一扇空窗户。",
        how_to_fix=f"`frago desktop down --instance {instance.get('id')}` 之后确认端口"
                   f"{instance.get('port') or ''}已经没人监听，"
                   f"再 `frago desktop up --id {instance.get('id')}` 重起；"
                   f"重起后 `tmux has-session -t {session}` 应返回 0。",
        session=session,
    )


def check_ui_ready(status: dict | None) -> dict:
    """ui_ready 现在是持续状态：最近几秒有没有收到过尺寸正确的帧。

    早先它是"桌面页画出首帧时发一次"的一次性信号。那个语义有个盲区：主荧幕
    中途接位后，新主荧幕如果早就画过帧就不会再发，ui_ready 卡在 false 而画面
    其实是好的——真假两种情况分不出来，这条 WARN 就成了狼来了。
    开录前真正要问的是"现在画面是不是活的"，所以判据换成帧的新鲜度。

    它仍比"有没有客户端连着"和"有没有上报 layout"晚一步，三者形成三种不同的
    半死状态，补救动作各不相同——合并成一句"未就绪"就等于没说。
    """
    item = "ui_ready"
    if status is None:
        return _unavailable(item, "broker /status 不可达")
    clients = _client_count(status)
    layout = bool(status.get("layout_reported"))
    stale = status.get("stale_clients") or []
    # 旧标签的 layout 已被丢弃，画面却照样推给它——它自己画得好好的，
    # 人看不出它是个已经不算数的标签。这个状态优先报，因为它同时解释了
    # "改了资产却没生效"和"画面变形"两种表象。
    if stale:
        return _warn(
            item,
            f"{clients} 个客户端连着，其中有开着旧版资产的标签"
            f"（uiVersion={stale}）",
            means=("同一个桌面页被开了不止一次，旧的那个几何算法与当前版本"
                   "不一致。它的 layout 已被 broker 丢弃，但画面照推，"
                   "所以它看起来一切正常。"),
            if_ignored=("以旧标签为准看到的画面会与真实几何对不上——"
                        "浏览器窗口尺寸和舞台视口不同比，网页被拉伸变形。"),
            how_to_fix=("关掉旧的桌面页标签，只留 instance.desktop_url 那一个；"
                        "或对它硬刷新（Cmd+Shift+R）取到新版资产。"),
            clients=clients, layout_reported=layout, stale_versions=stale,
        )
    age = status.get("frame_age_sec")
    window = status.get("ui_live_window_sec")
    # 演员标签天然的视口。它就是帧的尺寸——没人覆写它，也就没有第二个数字
    # 可以跟它对账，此处只是把这个事实报出来。
    size = status.get("actor_viewport")
    if status.get("ui_ready"):
        return _ok(item,
                   f"画面是活的（{age}s 前收到一帧，演员视口 "
                   f"{(size or {}).get('w')}x{(size or {}).get('h')}），"
                   f"{clients} 个客户端连着",
                   clients=clients, layout_reported=layout,
                   frame_age_sec=age, actor_viewport=size)

    if clients == 0:
        detail = "没有任何桌面页连着 broker"
        means = ("人的浏览器里没有开着这个实例的桌面页，或标签页已关闭。"
                 "broker 在对着空气推画面。")
        if_ignored = ("指令照常执行、回执照常成功，但没有任何人看得见结果；"
                      "此刻录制会得到一段没有观众也没有画面的空片。")
        how_to_fix = "请人在浏览器里打开实例的 desktop_url（见本报告 instance 段）。"
    elif not layout:
        detail = f"{clients} 个客户端连着，但没有一个上报过 layout"
        means = ("桌面页连上了却没报几何。通常是标签页开着的资产是旧版——"
                 "旧版 layout 不带 elements 字段，broker 整条丢弃。")
        if_ignored = ("所有 ref 寻址会解析失败或解析到过期矩形，"
                      "点击落在错误的位置上而回执看不出异常。")
        how_to_fix = ("请人硬刷新桌面页标签（Cmd+Shift+R）取到新版资产，"
                      "再 `frago desktop status` 确认。")
    else:
        detail = (f"{clients} 个客户端连着、已上报 layout，"
                  + (f"但最近一帧是 {age}s 前收到的（活跃窗口 {window}s）"
                     if age is not None else "但一帧都还没收到"))
        means = ("几何真值已经有了，画面不在动。演员标签完全静止时 CDP 一帧不产，"
                 "这是 v1 实测过的零帧故障；画布会一直停在最后那张帧上。")
        if_ignored = ("ref 寻址可用，但没人能确认画面是当下的——"
                      "此刻开录，拍到的可能是一段一动不动的旧画面。")
        how_to_fix = (
            "让**演员标签**重绘一次：`frago desktop browser open <url>` 换一个地址，"
            "或 `frago desktop browser scroll --pixels 1`。注意 `frago desktop mouse drift` 没用——"
            "它只移动桌面页上画的那个虚拟鼠标，碰不到演员标签，逼不出任何重绘。"
            "然后 `frago desktop status` 确认 ui_ready 变 true。")
    return _warn(item, detail, means=means, if_ignored=if_ignored,
                 how_to_fix=how_to_fix,
                 clients=clients, layout_reported=layout,
                 frame_age_sec=age, actor_viewport=size)


# ── 汇总 ──

RESPOND_INSTRUCTION = (
    "以下每一条 WARN，你 MUST 在继续之前逐条书面回应，格式为："
    "「<item>：影响/不影响本次任务，因为<具体理由>；我选择 处理/接受，"
    "处理方式是<动作>」。理由 MUST 引用本次任务实际要做的事，"
    "不得只写「看起来没问题」或「应该不影响」。说不出理由的条目不得跳过——"
    "那说明你还没弄清它是什么，先去弄清。"
)


def report(instance: dict, status: dict | None = None,
           cdp_ports: dict | None = None) -> dict:
    """产出结构化健康报告。恒不抛异常。

    instance: 注册表记录；status: broker /status 的返回，不可达时传 None；
    cdp_ports: {"stage": 9222, "record": 9223}，缺省时从 status 里取。
    """
    if cdp_ports is None and isinstance(status, dict):
        cdp_ports = status.get("cdp_ports")
    checks = [
        _guard(lambda: check_clips(instance.get("clips_dir")), "clips"),
        _guard(lambda: check_cdp_ports(cdp_ports), "cdp_ports"),
        _guard(check_orphan_profiles, "orphan_profiles"),
        _guard(lambda: check_desktop_url(instance), "desktop_url"),
        _guard(lambda: check_screen_ownership(status), "screen_ownership"),
        _guard(lambda: check_screen_duplicates(status), "screen_duplicates"),
        _guard(lambda: check_tmux_session(instance), "tmux_session"),
        _guard(lambda: check_ui_ready(status), "ui_ready"),
    ]
    warns = [c for c in checks if c["level"] == "warn"]
    unavail = [c for c in checks if c["level"] == "unavailable"]
    out = {
        "checks": checks,
        "warn_count": len(warns),
        "unavailable_count": len(unavail),
    }
    if warns:
        out["agent_must_respond"] = RESPOND_INSTRUCTION
        out["warn_items"] = [c["item"] for c in warns]
    return out


if __name__ == "__main__":  # 手工探查用：python -m frago.desktop.health [实例 id]
    import sys

    from . import registry

    rec = registry.read_instance(
        sys.argv[1] if len(sys.argv) > 1 else registry.DEFAULT_ID) or {}
    print(json.dumps(report(rec), ensure_ascii=False, indent=2))
