"""aos —— agent_os 的短指令入口。

只做三件事：把短语解析成 broker 现有的 op、按注册表找到目标实例、POST 到它的
/control。**broker 协议一条不改**——这里没有任何 broker 不认识的 op，凡是 broker
没有的能力（term read / browser read / wait）都由现有 op 组合出来，组合逻辑留在
本文件内。

为什么要有这一层：手拼 JSON POST 又长又易错，但那只是次要理由。真正的理由是这些
指令将来是训练特定小模型的语料，形状必须干净、统一、可学。所以语法遵守三条硬约束：

  同一语义只有一种写法。不做别名、不做简写、不做分号串联——那些是给人的便利，
  对模型是噪声，等价形式泛滥会让训练样本形状不一致。

  复用模型预训练见过的语法家族：`资源 动词 --具名参数`（kubectl / docker / gh 同族）。
  禁止用裸位置参数携带多个不同含义的值——`cursor 1300 420 700` 靠位置携带语义，
  模型得记住"第三位是毫秒"这种脆弱约定，且新增参数会让历史样本全部作废。
  单个自然宾语可以是位置参数（`browser open <url>`），那不需要记约定。

  动词自带意图。有目标的移动（mouse to）与无目标的闲晃（mouse drift）是两个动词，
  不是同一动词的两种参数——两类样本分布因此天然分离。

输出恒为单行 JSON，成功失败都是；失败 exit 非 0，且原样透出 broker 的错误。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

from . import (
    health,  # 启动自检，与 stage.py 共用同一份实现
    refs,  # page: 的判型，与 broker 共用同一份
    registry,  # 与 broker / stage 共用注册表语义
)

HERE = Path(__file__).parent


class Fail(Exception):
    """带结构化载荷的失败。载荷原样进 stdout，不重新措辞。"""

    def __init__(self, payload: dict):
        super().__init__(payload.get("error", "failed"))
        self.payload = payload


def die(error: str, **extra) -> Fail:
    return Fail({"ok": False, "error": error, **extra})


# ── 实例寻址：这台电脑上只有一个虚拟桌面 ──
#
# 早先支持多实例，代价是每条指令都要先回答"打给哪一台"：显式参数、环境变量、
# 单实例隐式绑定、多实例拒绝猜测，四条分支。猜错的后果是指令打在另一块画面上
# 而回执一切正常，事后极难发现。
#
# 虚拟桌面是台单数的东西——这台电脑上一个虚拟机器、一个看它的地址。收成唯一
# 之后，寻址这件事连同那类事故一起消失了。

def pick_instance(_explicit: str | None = None) -> dict:
    """这台电脑上只有一个虚拟桌面，所以没有"打给哪一台"这个问题。"""
    rec = registry.read_instance(registry.DEFAULT_ID)
    if not rec:
        raise die("虚拟桌面还没建起来", hint="用 `frago desktop up` 创建")
    return require_running(rec)


def require_running(rec: dict) -> dict:
    """"没在跑"与"不存在"是两种状态，不得都报成找不到。

    身份固定，所以 stopped 的实例拉起来还是同一个 content_id，人那个标签页每秒
    重连一次会自行恢复——这句提示能省掉一次"为什么画面没了"的排查。
    """
    if rec.get("status") != "running":
        raise die(
            f"实例 {rec['id']} 存在但没在运行",
            hint=f"用 `frago desktop up --id {rec['id']}` 拉起（身份不变，桌面页会自行重连）",
            instance={"id": rec["id"], "status": rec.get("status"),
                      "desktop_url": rec.get("desktop_url")},
        )
    return rec


def control_url(rec: dict) -> str:
    return f"http://127.0.0.1:{rec['port']}/control"


# ── 读超时：停录单列一档 ──
#
# 其余动词全是毫秒到秒级，180 秒绰绰有余。停录不是——它在 broker 那边要跑完
# 编码、抽帧、冻帧检测三样，耗时跟片长走：实测一条 10 分半的片子约 4 分钟。
# 于是"读超时 180 秒"这个定数对停录恒为假，长镜头必踩。
#
# 踩上去之后的形态才是真正的缺陷：读超时抛的是 TimeoutError，它**不是**
# urllib.error.URLError 的子类，下面那个 except 分支盖不住它。于是这一层
# "恒为单行 JSON"的承诺在这里破了——调用方拿不到片子路径、拿不到自检指标，
# 也无从判断片子到底成没成。等这个信号的脚本会一直等下去。
DEFAULT_POST_TIMEOUT = 180.0
# 停录给到 30 分钟。**刻意不设成无限等**：broker 真卡死时无限等会把调用方
# 一起挂住，而挂住的调用方连"我在等什么"都说不出来。
RECORD_STOP_TIMEOUT = 1800.0


def _is_record_stop(steps: list[dict]) -> bool:
    return any(s.get("op") == "record.stop" for s in steps)


def _stopping_clip(rec: dict) -> dict:
    """停录之前先问一句它在录哪一段。

    超时回执要说得出片子叫什么、会落在哪，而 broker 一进编码就把 name 清了
    （`StageRecorder.stop` 里 `self.name = None` 排在编码之前），事后问不出来。
    问不到就留白——编不出来的路径比没有路径更坏。
    """
    try:
        st = get_status(rec, timeout=5.0)
    except Exception:  # noqa: BLE001 —— 问不到就留白，不许让它掀翻停录
        return {}
    r = st.get("recorder") or {}
    name, clips_dir = r.get("clip"), r.get("clips_dir")
    if not name:
        return {}
    out = {"clip": name}
    if clips_dir:
        out["output"] = str(Path(clips_dir) / f"{name}.mp4")
        out["journal"] = str(Path(clips_dir) / f"{name}.jsonl")
        out["contact_sheet"] = str(Path(clips_dir) / f"{name}-contact.png")
        # broker 的日志与 clips 同一个落点、高一层（stage.py 写死的
        # data_dir()/broker.log）。超时之后唯一能看见"编码走到哪了"的地方
        # 就是它，所以路径要算出来给人，不能让人自己去猜。
        out["broker_log"] = str(Path(clips_dir).parent / "broker.log")
    return out


def post(rec: dict, steps: list[dict], timeout: float | None = None) -> dict:
    """把整批 steps 一次 POST 过去。

    一次而非逐条：/control 的 steps 数组本就顺序执行，时序精度由 broker 内部保证，
    与调用进程次数无关。逐条发反而在每两条之间塞进一次进程启动与 HTTP 往返，
    演示节奏会被这些抖动啃掉。

    timeout 留空时按批次内容选档：带停录的走 RECORD_STOP_TIMEOUT，其余走默认。
    """
    stopping = _is_record_stop(steps)
    if timeout is None:
        timeout = RECORD_STOP_TIMEOUT if stopping else DEFAULT_POST_TIMEOUT
    # 问在发之前：发完再问就晚了，那时 name 已经被清掉。
    clip = _stopping_clip(rec) if stopping else {}
    body = json.dumps({"steps": steps}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        control_url(rec), data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # broker 报错原样透出，一个字不改、不吞。它的错误里带着可寻址元素列表
        # 这类自救线索，重新措辞会把线索丢掉。
        raw = exc.read().decode(errors="replace")
        try:
            raise Fail(json.loads(raw))
        except json.JSONDecodeError:
            raise die(f"broker HTTP {exc.code}: {raw}") from None
    except TimeoutError:
        # 读超时。**必须单独接**：TimeoutError 不是 URLError 的子类，下面那个
        # 分支盖不住它，漏下去就是一段 Python 堆栈。
        #
        # 超时 ≠ 失败。停录超时时片子多半正在编码，几分钟后会自己落地——所以
        # 这里报的是"还没完"而不是"没成"，并且把接下来去哪儿看写清楚。
        raise Fail(_timeout_payload(rec, stopping, timeout, clip)) from None
    except urllib.error.URLError as exc:
        raise die(f"连不上 broker（{control_url(rec)}）: {exc.reason}") from None


def _timeout_payload(rec: dict, stopping: bool, waited: float,
                     clip: dict) -> dict:
    if not stopping:
        return {"ok": False,
                "error": f"broker {waited:.0f} 秒内没有回应（读超时）",
                "timed_out": True, "waited_sec": waited,
                "control": control_url(rec),
                "hint": "broker 还活着但这一批没跑完；"
                        "`frago desktop status` 看它现在在做什么"}
    return {
        "ok": False,
        "error": f"停录等了 {waited:.0f} 秒还没等到回执（读超时）",
        "timed_out": True,
        "still_encoding": True,
        "waited_sec": waited,
        **clip,
        "note": "帧已经收完了，broker 这时在编码与自检——超时的是等回执这件事，"
                "不是录制本身。片子多半会自己落地。",
        "hint": ("轮询上面那个 output 的大小直到不再变化；"
                 "或看 broker_log 里「停录」与「成片自检」两行——"
                 "那两行出来了就是全部产出都好了"
                 if clip else
                 "问不到正在录的片名（broker 可能已经进编码）；"
                 "去 clips 落点看最新的 mp4，或翻 broker 日志里的「停录」一行"),
    }


def get_status(rec: dict, timeout: float = 10.0) -> dict:
    url = f"http://127.0.0.1:{rec['port']}/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        raise die(f"读不到 broker 状态（{url}）: {exc}") from None


# ── 参数解析 ──
#
# 只认 `--name value`。不认 `-n`、不认 `--name=value`——同一语义一种写法。

def take_flags(tokens: list[str], allowed: set[str],
               multi: set[str] | None = None) -> dict:
    """解析 --name value。

    multi 里的参数允许重复出现并收成列表（目前只有 camera 的 --ref：一镜要框
    住并排的三张卡时，"多个目标"是这条指令的正常形态，不是异常）。其余参数
    重复出现照旧后者覆盖前者——形状恒定，不因为写法不同而变。
    """
    multi = multi or set()
    flags: dict = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("--"):
            raise die(f"多余的位置参数: {tok}",
                      hint="除自然宾语外一律用 --具名参数")
        name = tok[2:]
        if name not in allowed:
            raise die(f"未知参数: --{name}",
                      allowed=sorted(allowed))
        if i + 1 >= len(tokens):
            raise die(f"--{name} 缺少取值")
        if name in multi:
            flags.setdefault(name, []).append(tokens[i + 1])
        else:
            flags[name] = tokens[i + 1]
        i += 2
    return flags


def as_int(flags: dict, name: str, default: int | None = None) -> int | None:
    if name not in flags:
        return default
    try:
        return int(flags[name])
    except ValueError:
        raise die(f"--{name} 需要整数，得到: {flags[name]}") from None


def as_float(flags: dict, name: str, default: float | None = None) -> float | None:
    if name not in flags:
        return default
    try:
        return float(flags[name])
    except ValueError:
        raise die(f"--{name} 需要数字，得到: {flags[name]}") from None


def one_positional(tokens: list[str], what: str) -> tuple[str, list[str]]:
    if not tokens or tokens[0].startswith("--"):
        raise die(f"缺少 {what}")
    return tokens[0], tokens[1:]


def need_exactly_one(flags: dict, names: list[str], verb: str) -> str:
    got = [n for n in names if n in flags]
    if len(got) != 1:
        raise die(
            f"{verb} 需要且只需要一个: " + " | ".join("--" + n for n in names),
            got=[f"--{n}" for n in got],
        )
    return got[0]


# ── 短语 → op ──
#
# 返回 ("steps", [...]) 表示可以并进同一次 POST；返回 ("local", callable) 表示
# 得在客户端跑（轮询、读 tmux、进程生命周期），这类会先把已攒的 steps 冲掉再执行。

def js_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def parse(tokens: list[str]) -> tuple[str, object]:
    if not tokens:
        raise die("空指令")
    res, rest = tokens[0], tokens[1:]

    if res == "status":
        take_flags(rest, set())
        return "local", cmd_status
    if res == "up":
        # 不收 --id：这台电脑上的虚拟桌面只有一个。
        f = take_flags(rest, {"start-url", "actor-mode"})
        # "boot"：唯一不要求实例已存在的指令——它自己就是来创建实例的。
        return "boot", lambda _rec: cmd_up(f)
    if res == "down":
        take_flags(rest, set())
        # "any"：不要求实例正在运行。停一台**还在应答**的 broker 不该被一句
        # "记录里说它没在跑"挡住——记录会因为启动期探活而被清成 stopped，
        # 那之后 down 进不了门，老进程就永远停不掉，下一次 up 又把它复用。
        return "any", cmd_down

    if res == "elements":
        f = take_flags(rest, {"in", "text", "selector"})
        step: dict = {"op": "elements"}
        if "in" in f:
            if f["in"] != "browser":
                raise die(f"--in 只支持 browser，得到: {f['in']}")
            step["in"] = "browser"
            if "text" not in f and "selector" not in f:
                raise die("elements --in browser 需要 --text 或 --selector")
        for k in ("text", "selector"):
            if k in f:
                step[k] = f[k]
        return "steps", [step]

    if res == "mouse":
        verb, rest = one_positional(rest, "mouse 的动词（to / drift / click）")
        if verb == "to":
            ref, rest = one_positional(rest, "目标 ref")
            f = take_flags(rest, {"ms"})
            return "steps", [{"op": "cursor", "ref": ref,
                              "ms": as_int(f, "ms", 700)}]
        if verb == "drift":
            f = take_flags(rest, {"x", "y", "ms"})
            for k in ("x", "y"):
                if k not in f:
                    raise die(f"mouse drift 需要 --{k}")
            return "steps", [{"op": "cursor", "x": as_int(f, "x"),
                              "y": as_int(f, "y"), "ms": as_int(f, "ms", 700)}]
        if verb == "click":
            # 刻意不接受坐标：点的是"当前位置"，而当前位置由上一条 mouse to
            # 用语义定下。允许 click 带坐标就等于给了绕开语义寻址的后门。
            take_flags(rest, set())
            return "steps", [{"op": "click"}]
        raise die(f"未知 mouse 动词: {verb}", allowed=["to", "drift", "click"])

    if res == "window":
        verb, rest = one_positional(rest, "window 的动词")
        # split 已退场：对开要把浏览器压到半个桌面宽，与"浏览器恒占桌面宽的
        # 75–85%、且与演员视口同比例"冲突，两条规则无法共存。
        if verb in ("open", "close"):
            # 开关程序。三扇窗共用这一条，图片浏览器不再有自己的 image close——
            # 同一语义只有一种写法，而"关掉一个程序"就是这一种。
            # 与 min/restore 是两件事：min 收进 dock（还在跑），close 让它
            # 离开桌面（dock 的灯灭掉）。
            f = take_flags(rest, {"target", "ms"})
            win = need_target(f)
            return "steps", [{"op": "win", "win": win, "action": verb,
                              "ms": as_int(f, "ms", 260)}]
        if verb in ("min", "max", "restore"):
            f = take_flags(rest, {"target", "ms"})
            win = need_target(f)
            return "steps", [{"op": "win", "win": win, "action": verb,
                              "ms": as_int(f, "ms", 400)}]
        if verb == "move":
            f = take_flags(rest, {"target", "x", "y", "w", "h", "ms"})
            win = need_target(f)
            step = {"op": "win", "win": win, "ms": as_int(f, "ms", 400)}
            for k in ("x", "y", "w", "h"):
                if k not in f:
                    raise die(f"window move 需要 --{k}")
                step[k] = as_int(f, k)
            return "steps", [step]
        raise die(f"未知 window 动词: {verb}",
                  allowed=["open", "close", "min", "max", "restore", "move"])

    if res == "focus":
        win, rest = one_positional(rest, "窗口（term / browser / image）")
        take_flags(rest, set())
        if win not in ("term", "browser", "image"):
            raise die(f"未知窗口: {win}", allowed=["term", "browser", "image"])
        return "steps", [{"op": "focus", "win": win}]

    if res == "term":
        verb, rest = one_positional(
            rest, "term 的动词（run / read / scroll / fontsize）")
        if verb == "run":
            cmd, rest = one_positional(rest, "要执行的命令")
            take_flags(rest, set())
            return "steps", [{"op": "shell", "cmd": cmd}]
        if verb == "read":
            f = take_flags(rest, {"lines"})
            n = as_int(f, "lines", 20)
            return "local", lambda rec: cmd_term_read(rec, n)
        if verb == "scroll":
            # 回看。滚的是终端窗口的视口，不是 tmux——会话照常跑，当前屏一个
            # 字节都不动。三种给法各自对应一种真实意图，形状与 browser scroll
            # 同族（--to 是"滚到那段文字"，--lines 对应它的 --pixels）：
            #   --lines -20   往回二十行（正数往下）
            #   --to "报错"    滚到最后一处匹配，命中行摆在窗口中间
            #   --to-end      回到底部，并恢复"新输出跟着走"
            to_end = "--to-end" in rest
            rest = [t for t in rest if t != "--to-end"]
            f = take_flags(rest, {"lines", "to", "ms"})
            step: dict = {"op": "term.scroll", "ms": as_int(f, "ms", 400)}
            if to_end:
                if "lines" in f or "to" in f:
                    raise die("term scroll --to-end 不接受 --lines / --to",
                              hint="回到底部就是回到底部，没有第二个目标")
                step["to_end"] = True
            elif "lines" in f or "to" in f:
                which = need_exactly_one(f, ["lines", "to"], "term scroll")
                if which == "lines":
                    step["lines"] = as_int(f, "lines")
                else:
                    step["to"] = f["to"]
            else:
                raise die('term scroll 需要一个目标：--lines <n> | '
                          '--to "<文字>" | --to-end')
            return "steps", [step]
        if verb == "fontsize":
            # 录制构图的第一变量。画面上的字多大只由它决定：窗口做大只换来
            # 更多列，手动 tmux resize 撑不过下一次窗口变动。列数行数跟着
            # 重算，回执里带新旧网格对照。
            px, rest = one_positional(rest, "字号（px，8-64；录制档 24-28）")
            take_flags(rest, set())
            return "steps", [{"op": "term.fontsize", "px": int(px)}]
        raise die(f"未知 term 动词: {verb}",
                  allowed=["run", "read", "scroll", "fontsize"])

    if res == "image":
        verb, rest = one_positional(rest, "image 的动词（open）")
        if verb == "open":
            # 只剩"装一张图进来"这一件事。它顺带把图片浏览器打开，
            # 与"打开一份文件顺带拉起对应程序"是同一件事。
            path, rest = one_positional(rest, "图片路径")
            take_flags(rest, set())
            return "steps", [{"op": "image.open", "path": path}]
        if verb == "close":
            # 明确指路，不是一句"未知动词"。这条曾经是全场唯一能关掉程序的
            # 动作，写过它的剧本和文档都还在，撞上来的人需要知道去哪儿。
            raise die(
                "image close 已撤销：关掉一个程序是窗口管理器的事，"
                "三扇窗走同一条路 —— `window close --target image`",
                allowed=["open"],
                use_instead="window close --target image",
            )
        raise die(f"未知 image 动词: {verb}", allowed=["open"])

    if res == "browser":
        verb, rest = one_positional(rest, "browser 的动词")
        if verb == "open":
            url, rest = one_positional(rest, "URL")
            take_flags(rest, set())
            return "steps", [{"op": "navigate", "url": url}]
        if verb == "click":
            f = take_flags(rest, {"text", "selector", "ms"})
            which = need_exactly_one(f, ["text", "selector"], "browser click")
            ref = (f'page:"{f["text"]}"' if which == "text"
                   else f"page:{f['selector']}")
            # 走真实鼠标：先移过去（同时建立悬停绑定），再点。不直接派发 DOM
            # click——那样画面里鼠标没动过，录出来的片子对不上，而且 hover 效果
            # 不会触发。
            return "steps", [{"op": "cursor", "ref": ref,
                              "ms": as_int(f, "ms", 700)},
                             {"op": "click"}]
        if verb == "scroll":
            f = take_flags(rest, {"to", "pixels"})
            which = need_exactly_one(f, ["to", "pixels"], "browser scroll")
            if which == "pixels":
                js = ("(()=>{window.scrollBy(0,"
                      + str(as_int(f, "pixels")) + ");"
                      "return{scrollY:Math.round(window.scrollY)};})()")
            else:
                js = (
                    "(()=>{const t=" + js_literal(f["to"]) + ";"
                    "const w=document.createTreeWalker(document.body,"
                    "NodeFilter.SHOW_TEXT);let n;"
                    "while((n=w.nextNode())){if(n.textContent.includes(t)){"
                    "const e=n.parentElement;"
                    "e.scrollIntoView({block:'center'});"
                    "return{found:true,scrollY:Math.round(window.scrollY)};}}"
                    "return{found:false,scrollY:Math.round(window.scrollY)};})()"
                )
            return "steps", [{"op": "exec", "js": js}]
        if verb == "read":
            f = take_flags(rest, {"selector"})
            if "selector" in f:
                js = ("(()=>{const e=document.querySelector("
                      + js_literal(f["selector"]) + ");"
                      "return e?{found:true,text:e.innerText}:"
                      "{found:false,text:null};})()")
            else:
                js = ("(()=>({found:true,url:location.href,"
                      "title:document.title,"
                      "text:document.body?document.body.innerText:''}))()")
            return "steps", [{"op": "exec", "js": js}]
        raise die(f"未知 browser 动词: {verb}",
                  allowed=["open", "click", "scroll", "read"])

    if res == "tab":
        verb, rest = one_positional(rest, "tab 的动词（open / switch / close）")
        if verb == "open":
            url, rest = one_positional(rest, "URL")
            take_flags(rest, set())
            return "steps", [{"op": "tab", "action": "open", "url": url}]
        if verb in ("switch", "close"):
            idx, rest = one_positional(rest, "标签序号")
            take_flags(rest, set())
            if not idx.isdigit():
                raise die(f"标签序号需要非负整数，得到: {idx}")
            return "steps", [{"op": "tab", "action": verb, "index": int(idx)}]
        raise die(f"未知 tab 动词: {verb}", allowed=["open", "switch", "close"])

    if res == "camera":
        verb, rest = one_positional(rest, "camera 的动词（up / down / focus / pan / reset）")
        # camera 管的是**摄像机**（在不在、取景框对着桌面的哪一块），window 管的是
        # **被摄物**（虚拟窗口在桌面里多大、摆在哪）。两个资源不重叠，
        # 别把取景写进 window。
        if verb == "up":
            # 架机位：拉起、连上、等桌面页画出首帧。首次要几十秒，之后是空操作。
            # 单独成一个动词，是为了让 rec start 恒为毫秒级——一条时快时慢的
            # 指令，agent 没法据它安排动作。
            take_flags(rest, set())
            return "steps", [{"op": "camera.up"}]
        if verb == "down":
            take_flags(rest, set())
            return "steps", [{"op": "camera.down"}]
        if verb == "focus":
            # --context 只对 term:match 有意义：命中行往上下各扩几行。
            # 报错那一行单独框住往往读不懂，得看见它前面那条命令。
            f = take_flags(rest, {"ref", "zoom", "ms", "expand-to", "context"},
                           multi={"ref"})
            if "ref" not in f:
                raise die("camera focus 需要 --ref <ref>（可给多个，取外接矩形）")
            step = {"op": "camera.focus", "refs": f["ref"],
                    "ms": as_int(f, "ms", 1200)}
            if "zoom" in f:
                step["zoom"] = as_float(f, "zoom")
            if "expand-to" in f:
                step["expand_to"] = f["expand-to"]
            if "context" in f:
                step["context"] = as_int(f, "context")
            return "steps", [step]
        if verb == "pan":
            f = take_flags(rest, {"to", "ms", "expand-to", "context"})
            if "to" not in f:
                raise die("camera pan 需要 --to <ref>")
            step = {"op": "camera.pan", "to": f["to"],
                    "ms": as_int(f, "ms", 2000)}
            if "expand-to" in f:
                step["expand_to"] = f["expand-to"]
            if "context" in f:
                step["context"] = as_int(f, "context")
            return "steps", [step]
        if verb == "reset":
            f = take_flags(rest, {"ms"})
            return "steps", [{"op": "camera.reset", "ms": as_int(f, "ms", 1200)}]
        raise die(f"未知 camera 动词: {verb}",
                  allowed=["up", "down", "focus", "pan", "reset"])

    if res == "viewport":
        verb, rest = one_positional(rest, "viewport 的动词（refresh）")
        if verb == "refresh":
            f = take_flags(rest, {"ms"})
            # 尺寸真值在演员标签那边，平时由启动与导航两个时机自动读。
            # 人手动改过那扇真实浏览器窗口之后，用这条立刻跟上。
            return "steps", [{"op": "viewport", "ms": as_int(f, "ms", 300)}]
        raise die(f"未知 viewport 动词: {verb}", allowed=["refresh"])

    if res == "wait":
        f = take_flags(rest, {"for", "url", "text", "timeout"})
        which = need_exactly_one(f, ["for", "url", "text"], "wait")
        timeout = as_int(f, "timeout", 30)
        return "local", lambda rec: cmd_wait(rec, which, f[which], timeout)

    if res == "pause":
        f = take_flags(rest, {"ms"})
        if "ms" not in f:
            raise die("pause 需要 --ms")
        return "steps", [{"op": "sleep", "ms": as_int(f, "ms")}]

    if res == "rec":
        verb, rest = one_positional(rest, "rec 的动词（start / stop）")
        if verb == "start":
            # --force 是无值 flag（另一个是 term scroll 的 --to-end），
            # 在进 take_flags 之前先摘掉。不给解析器开一个通用的无值分支：
            # 那样 `--name --force` 里的 --name 会静默吃掉后面的 flag 当取值，
            # 是一条走错了也看不出来的路。
            force = "--force" in rest
            rest = [t for t in rest if t != "--force"]
            f = take_flags(rest, {"name"})
            if "name" not in f:
                raise die("rec start 需要 --name")
            step = {"op": "record.start", "name": f["name"]}
            if force:
                step["force"] = True
            return "steps", [step]
        if verb == "stop":
            take_flags(rest, set())
            return "steps", [{"op": "record.stop"}]
        raise die(f"未知 rec 动词: {verb}", allowed=["start", "stop"])

    if res == "say":
        text, rest = one_positional(rest, "字幕文字")
        f = take_flags(rest, {"ms"})
        return "steps", [{"op": "say", "text": text,
                          "ms": as_int(f, "ms", 2600)}]

    raise die(f"未知指令: {res}", allowed=sorted(RESOURCES))


def need_target(f: dict) -> str:
    if "target" not in f:
        raise die("需要 --target term|browser|image")
    if f["target"] not in ("term", "browser", "image"):
        raise die(f"--target 只支持 term|browser|image，得到: {f['target']}")
    return f["target"]


RESOURCES = {"up", "down", "status", "elements", "mouse", "window", "focus",
             "term", "image", "browser", "tab", "camera", "viewport", "wait",
             "pause", "rec", "say"}


# ── 客户端侧组合（broker 协议不动） ──

def cmd_status(rec: dict) -> dict:
    st = get_status(rec)
    return {
        "ok": True,
        "instance": {k: rec.get(k) for k in registry.IDENTITY_FIELDS},
        "runtime": {k: rec.get(k) for k in registry.RUNTIME_FIELDS},
        "control": control_url(rec),
        # 自检报告与配方启动时输出的是同一份实现（health.report），不写两遍：
        # 两份实现必然漂移，届时"启动时没报、status 报了"这种差异会被当成
        # 状态变化去排查，而根本没变的是世界，是代码。
        # runtime_state 是原有的即时快照，保留——它答的是"现在是什么样"，
        # checks 答的是"哪里不对劲"，两个问题不同。
        "health": {
            **health.report(rec, status=st),
            "runtime_state": {
                # ui_ready 是"现在画面活不活"，判据是最近一帧多久之前收到的。
                "ui_ready": st.get("ui_ready"),
                "frame_age_sec": st.get("frame_age_sec"),
                # 尺寸真值：演员标签天然的视口（没人覆写它）、它的宽高比，
                # 以及 broker 据此算出的虚拟浏览器几何。
                "actor_viewport": st.get("actor_viewport"),
                "aspect_ratio": st.get("aspect_ratio"),
                "viewport_source": st.get("viewport_source"),
                "browser_window": st.get("browser_window"),
                # clients 是一张带身份的名单（谁连着、是不是我的荧幕、
                # 几何收没收），不是数字——数字答不出该关哪个标签。
                "clients": st.get("clients"),
                "clients_count": st.get("clients_count"),
                "layout_reported": st.get("layout_reported"),
                "focus": st.get("focus"),
                "hover": st.get("hover"),
                "recording": st.get("recorder", {}).get("recording"),
            },
        },
        # 当前 active 的程序提到顶层：它埋在 health.runtime_state 里时，
        # agent 扫一眼 status 是看不见的，于是"先点一下 dock 保险"成了习惯动作——
        # 而终端本来就在前台，那一下白点，还录进了片子。
        "active": st.get("focus"),
        "elements": sorted(st.get("elements", {}).keys()),
    }


ACTOR_MODES = ("headless", "head")


def cmd_up(flags: dict) -> dict:
    """拉舞台就是本进程里调一次 `stage.up()`。

    从前这里绕一圈平台（`frago recipe run agent_os`），理由是配方建在基类上：落点
    （FRAGO_RECIPE_DATA_DIR）、总线地址、基类的 PYTHONPATH，三样必须由平台交代，
    直接起脚本一样都拿不到。舞台 2026-09-02 搬进本体之后这三样一样都不需要了——
    落点由 registry 自己求，页面状态直接落盘，基类没有了。

    那一圈从此只剩坏处：多起两个进程；而且旧配方一退役这条路就断，断的表现是
    up 回一句「配方没能把舞台拉起来」——一句把"这条路本身作废了"说成"舞台起不来"
    的误导性诊断。

    回执形状一个键都没变：从前读的是 `frago recipe run` 打在 stdout 的那块 data，
    而那块 data 就是配方 up 的返回值；现在 stage.up() 直接返回同一个 dict
    （success / id / url / instance / runtime / control / status / content_id / …）。
    `success: true` 照旧在里面——现有调用方读的是它。
    """
    params = {}
    if "start-url" in flags:
        params["start_url"] = flags["start-url"]
    if "actor-mode" in flags:
        mode = flags["actor-mode"]
        if mode not in ACTOR_MODES:
            raise die(f"--actor-mode 只认 {list(ACTOR_MODES)}，得到: {mode!r}",
                      allowed=list(ACTOR_MODES))
        params["actor_mode"] = mode

    # stage 顶层 import fastapi 那一族用不着，但它会拉起 app_state / viewer，
    # 而 `frago desktop status` 这类指令一条都不需要——只在真要起舞台时才付这笔钱。
    from . import stage

    try:
        return {"ok": True, **stage.up(params)}
    except stage.StageFailed as exc:
        # 舞台自己说得出的失败（没有 tmux、id 不是 default、broker 90 秒没就绪……），
        # 措辞一字不改地透出去。它从前经由基类信封变成 ok:false，现在由这里绑定。
        raise die(str(exc)) from None


def cmd_down(rec: dict) -> dict:
    """停运行态，保留身份。

    只发 SIGTERM 再把注册表标 stopped——身份层一个字段都不碰。载体（桌面页标签、
    viewer 目录、clips、tmux 会话）全都还在，删掉身份等于把"存在但没跑"错报成
    "不存在"。
    """
    # 先落意愿再动手：这句话是说给守护听的——它看到进程没了会拉起，除非人
    # 明说过不想让它跑。顺序反过来的话，中间那一瞬守护正好巡检到，就会把
    # 刚杀掉的进程原样拉回来，而人以为自己关掉了。
    registry.set_desired(rec["id"], registry.DESIRED_STOPPED)
    pid = rec.get("pid")
    if not pid:
        # 注册表里的 pid 可能被探活清掉过（启动那十几秒端口还没开始 accept，
        # read_instance 就把记录纠正成 stopped 并清了 pid）。这时不问一句就走，
        # 等于什么都没停：老 broker 照跑，下一次 up 探到端口活着直接复用它，
        # 改完的代码永远上不了台。能应答的那一位自己报得出 pid，问它。
        with suppress(Exception):
            pid = get_status(rec).get("pid")
    signalled = False
    if pid:
        try:
            os.kill(int(pid), 15)
            signalled = True
        except ProcessLookupError:
            signalled = False
        except PermissionError as exc:
            raise die(f"无权停止 pid {pid}: {exc}") from None
    deadline = time.time() + 15
    while time.time() < deadline:
        if not registry._port_alive(rec.get("port")):
            break
        time.sleep(0.3)
    registry.mark_stopped(rec["id"])
    after = registry.read_instance(rec["id"]) or {}
    return {"ok": True, "id": rec["id"], "signalled": signalled,
            "status": after.get("status"),
            "desired": after.get(registry.DESIRED_FIELD),
            "note": "已记下人不想让它跑，守护不会把它拉起来；要重新用就 `frago desktop up`。",
            "identity_kept": {k: after.get(k) for k in registry.IDENTITY_FIELDS}}


def cmd_term_read(rec: dict, lines: int) -> dict:
    """直接读 tmux 会话，不经 broker。

    broker 没有"读终端"的 op，而能用来凑出一个的只有 shell——那会往终端里真打
    一条命令，读一眼就污染画面与后续 diff，代价比收益大。tmux 会话名是注册表里
    的身份字段，capture-pane 读的就是 broker 自己在轮询的同一份真值，绕开的只是
    一次转发，不是绕开权威。

    读的范围含历史（`-S -<n>`），不是只有可见屏：pane 有多高是虚拟终端窗口
    说了算，输出一长前面就滚进历史了。只读可见屏的话，`--lines 200` 要来的
    两百行永远只回得来三十行，而回执看不出被截过。
    """
    session = rec.get("tmux_session")
    if not session:
        raise die("注册表里没有 tmux_session", instance=rec.get("id"))
    # --lines 0（及负数）历来的语义是"全给"，那就从历史最开头取（-S -）。
    # 写成 -S -0 的话 0 是可见屏第一行，"全给"会静默退化成"只给这一屏"。
    start = "-" if lines <= 0 else f"-{lines}"
    proc = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", session, "-S", start],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        raise die(f"tmux capture-pane 失败: {proc.stderr.strip()}",
                  session=session)
    rows = proc.stdout.split("\n")
    while rows and not rows[-1].strip():
        rows.pop()
    tail = rows[-lines:] if lines > 0 else rows
    return {"ok": True, "win": "term", "session": session,
            "lines": len(tail), "total_lines": len(rows), "text": tail}


def _ref_probe_step(ref: str) -> dict:
    """把一个 ref 变成一次只读的存在性查询。

    域由前缀决定，与 broker 的解析路径同构：page: 走页面按需查询，其余走桌面
    全量快照。两条路都只是"看"，不碰世界。

    **判型不在这里做**：page: 后面那一截是文字还是选择器，由 broker 的
    page_locate 一处判定（它与 mouse to / camera focus 走的是同一份）。这里
    曾经自己抄过一遍那段判据，于是 `wait --for` 与真正动手的那条指令对同一个
    ref 可能给出不同解释——等到了却点不着，或者反过来，而两边回执都正常。
    """
    if refs.is_page_ref(ref):
        # observe：这一步只看不做，broker 据此**不**自动激活浏览器窗口。
        # 动作会自动把目标窗口提到最上层（见 broker 的 ensure_active），
        # 而等待是观察——盯一个还没出现的元素时反复翻窗口层级，
        # 录进片子里就是一段没人下过的指令，与本函数下面那条注释同源。
        return {"op": "elements", "in": "browser", "observe": True, "ref": ref}
    return {"op": "elements"}


def cmd_wait(rec: dict, mode: str, needle: str, timeout: int) -> dict:
    """语义等待：条件成立立刻返回并报告实际耗时。

    这是 sleep 的替代品而不是包装：sleep 是猜一个时长，wait 是盯一个可观测条件。
    两者的区别在超时那一刻最明显——sleep 到点就当成功，wait 会如实说"没等到"。
    演示节拍要慢下来时用 pause，语义等待用这个，两者刻意分成不同动词。
    """
    t0 = time.time()
    deadline = t0 + timeout
    if mode == "for":
        # 用 elements 探，不用 cursor 探。cursor 会真的把鼠标挪过去——等待是
        # 观察，不该改变世界；拿移动当探针，等一个还没出现的元素时鼠标会在
        # 画面上乱跳，录进片子里就是一段没人下过的指令。
        step = _ref_probe_step(needle)
    elif mode == "url":
        step = {"op": "exec", "js": "location.href", "observe": True}
    else:
        step = {"op": "exec", "observe": True,
                "js": ("(()=>{const b=document.body;"
                       "return b?(b.innerText||''):'';})()")}

    attempts = 0
    last: object = None
    while True:
        attempts += 1
        try:
            res = post(rec, [step], timeout=30)
            hit = False
            if mode == "for":
                r = res["results"][0]
                if r.get("in") == "browser":
                    hit = r.get("count", 0) > 0
                    last = r.get("count")
                else:
                    hit = needle in (r.get("desktop") or {})
                    last = sorted((r.get("desktop") or {}).keys())
            else:
                last = res["results"][0].get("value")
                hit = isinstance(last, str) and needle in last
            if hit:
                return {"ok": True, "waited_sec": round(time.time() - t0, 3),
                        "attempts": attempts, "mode": mode, "matched": needle,
                        **({"ref": needle, "found": last} if mode == "for"
                           else {"url": last} if mode == "url"
                           else {"text_len": len(last or "")})}
        except Fail:
            # ref 解析不到 / 页面还没执行 JS，都是"条件尚未成立"的正常形态。
            # 只有等到超时都不成立才算失败——那时把最后一次的原始错误带出去。
            pass
        if time.time() >= deadline:
            break
        time.sleep(0.25)
    raise die(f"wait 超时（{timeout}s）未等到 --{mode} {needle}",
              waited_sec=round(time.time() - t0, 3), attempts=attempts,
              last_seen=(last if not isinstance(last, str) else last[:400]))


# ── 执行 ──
#
# steps 攒着，遇到客户端侧指令（或读完输入）才冲。这样纯 broker 指令的批次是
# 一次 POST，时序交给 broker 保证；而 wait 这类必须往返轮询的，本来就不可能
# 塞进一次 POST。

def run(phrases: list[list[str]], to: str | None) -> dict:
    # 全部先解析再执行：一批里有任何一条语法错，就一条都不发。半批打进画面
    # 之后再报语法错，留下的是个说不清做到哪一步的中间态。
    plans = [parse(p) for p in phrases]

    # up 之外的任何指令都要先定位实例；up 自己负责创建，不能反过来要求它先存在。
    # "any" 那一档（目前只有 down）只要求实例**存在**，不要求它在跑。
    rec: dict | None = None
    kinds = {kind for kind, _ in plans}
    if kinds - {"boot", "any"}:
        rec = pick_instance(to)
    elif "any" in kinds:
        rec = registry.read_instance(registry.DEFAULT_ID)
        if not rec:
            raise die("虚拟桌面还没建起来", hint="用 `frago desktop up` 创建")

    buffer: list[dict] = []
    results: list[object] = []
    posts = 0

    def carry_earlier(exc: Fail) -> Fail:
        """把"这一批之前已经做完的事"挂到失败回执上。

        一次调用可能拆成好几批（中间夹着 wait 这类必须往返轮询的指令）。只抛
        失败那一批的回执，等于把前面几批已经打进画面的动作一起丢掉——而那正是
        broker 那一层刚修掉的病：回执看不出做到哪一步。这一层同病同治。
        """
        if results:
            exc.payload = {**exc.payload,
                           "earlier_results": list(results),
                           "earlier_note": f"本批之前已经执行过 {len(results)} 步，"
                                           "见 earlier_results"}
        return exc

    def flush() -> None:
        nonlocal posts
        if not buffer:
            return
        try:
            res = post(rec, list(buffer))
        except Fail as exc:
            raise carry_earlier(exc) from None
        posts += 1
        results.extend(res.get("results", []))
        buffer.clear()

    for kind, obj in plans:
        if kind == "steps":
            buffer.extend(obj)  # type: ignore[arg-type]
        else:
            # 客户端侧指令（轮询、读 tmux、进程生命周期）无法并进 POST，
            # 执行前先把攒下的 steps 冲掉，保住书写顺序即执行顺序。
            flush()
            try:
                results.append(obj(rec))  # type: ignore[operator]
            except Fail as exc:
                raise carry_earlier(exc) from None
    flush()
    return {"ok": True, "posts": posts, "results": results}


def main(argv: list[str] | None = None) -> int:
    """一条（或一批）指令的全程。恒打印一行 JSON，退出码由返回值定。

    argv 是 `frago desktop` 后面那些词，不含程序名。留空时退回读 sys.argv[1:]，
    这样 `python -m frago.desktop.aos …` 手工探查照旧能用。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(json.dumps({"ok": False, "error": "需要指令",
                          "resources": sorted(RESOURCES),
                          "batch": "aos - 从标准输入按行读"},
                         ensure_ascii=False))
        return 2

    # 实例选择器叫 --instance 而不是 --to：spec 两处各写了一个 --to，一处指实例、
    # 一处指 browser scroll 的目标文字。同一个 flag 承载两种语义，正是"同一语义
    # 只有一种写法"要挡的那种噪声，而且它会真的解析错——全局 flag 先被剥掉，
    # `browser scroll --to "配方"` 的目标就凭空消失了。全局修饰符改名，
    # 各命令自己的参数保持 spec 原样。
    to = None
    if "--instance" in argv:
        i = argv.index("--instance")
        if i + 1 >= len(argv):
            print(json.dumps({"ok": False, "error": "--instance 缺少取值"},
                             ensure_ascii=False))
            return 2
        to = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    if argv == ["-"]:
        phrases = [shlex.split(line) for line in sys.stdin.read().splitlines()
                   if line.strip() and not line.lstrip().startswith("#")]
        if not phrases:
            print(json.dumps({"ok": False, "error": "标准输入没有任何指令"},
                             ensure_ascii=False))
            return 2
    else:
        phrases = [argv]

    try:
        out = run(phrases, to)
    except Fail as exc:
        print(json.dumps(exc.payload, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001 —— 见下
        # 兜住一切，因为这一层的全部承诺就是"恒为单行 JSON"。
        #
        # 从前 `frago desktop` 是条子进程管道，舞台代码怎么崩都崩在子进程里，CLI 这边
        # 拿到的仍是退出码。搬进本体之后 aos.main() 与 CLI 同一个进程：一个漏网的异常
        # 会直接变成 Python 堆栈打在 stderr、stdout 一个字都没有——而调用方多半是
        # 拿 json.loads 读 stdout 的 agent，它看到的是"命令没有输出"。
        #
        # 堆栈本身照旧带在回执里：诊断信息一个字节都不该丢，只是它得先是合法 JSON。
        # json.dumps 会把换行转义成 \n，所以带上堆栈也仍然是一行。
        import traceback
        print(json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "unexpected": True,
            "traceback": traceback.format_exc(),
        }, ensure_ascii=False))
        return 1
    # 单条模式把唯一结果摊平，省掉一层 results 包装；批量模式保留数组。
    if len(phrases) == 1 and len(out["results"]) == 1 \
            and isinstance(out["results"][0], dict):
        merged = {"ok": True, **out["results"][0]}
        print(json.dumps(merged, ensure_ascii=False))
        return 0
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
