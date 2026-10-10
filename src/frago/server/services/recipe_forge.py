"""在图形界面里创建配方 —— 起一个「导演」会话，让人在虚拟桌面上看着配方被做出来。

## 控制链（一共四段，展示层与控制层分开）

    配方管理页「创建配方」→ 需求 + 要不要界面
        ↓  本模块：写一份导演任务书，起一场隐藏的 claude 会话，任务书是第一句话
    导演（隐藏 tmux 里的 claude，人看不见它）
        ↓  自己 ``frago desktop up`` 把舞台拉起来，再用 ``frago desktop`` 全程解说；
           用 ``frago recipe create --tmux-target frago-stage`` 让 worker 跑在桌面终端里
    虚拟桌面（人看的显示器）：终端窗口里 worker 在写配方，浏览器窗口里配方页面在长
        ↑  桌面页带 ``?userInput=true&session=<导演会话>`` 时露出一条输入行，
           人打的字**不进桌面终端**，而是排进导演的队列，由导演转达给 worker

桌面只是显示器；导演是遥控器，人对着遥控器说话。本模块只负责把遥控器造出来并
递给页面，之后的一切都由导演按任务书自己走。

舞台不再要求人先起：2026-10-08 起导演自己 ``frago desktop up``。原来这里有一道预检，
舞台没在跑就不起会话（路由翻成 409）——那条预检唯一的依据就是「导演不许自己拉起它」
这条铁律，两头一起放开了，预检连同它的异常一起撤掉，名字检查与 agent 可用性检查照旧。

分层：服务层。可以 import ``desktop/``、``session/`` 与同层服务，NEVER import ``cli/``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from frago.server.services import workbench_agents, workbench_new_session

logger = logging.getLogger(__name__)

#: 虚拟桌面终端窗口盯着的 tmux 会话。worker 借住在这里跑，人才看得见它。
STAGE_TMUX_SESSION = "frago-stage"

#: 导演会话的工作目录。配方落在 ``~/.frago/recipes`` 下，与工作目录无关；选家目录
#: 只是让 worker 的记录文件落到一个稳定、不属于任何仓库的地方。
_DIRECTOR_CWD = Path.home()

#: 配方名的合法形状，与目录名、recipe.md 的 name、类名三处一致的那一个。
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class BadRecipeName(ValueError):
    """配方名不是 snake_case，或者已经有同名配方。"""


@dataclass(frozen=True)
class ForgeLaunch:
    """一次「创建配方」起好之后，页面要拿去的东西。"""

    session_id: str
    """导演会话的编号——桌面输入行往这里投话。"""

    desktop_url: str
    """带 userInput 开关与会话编号的桌面地址，页面用它开那扇「APP 模式」窗口。"""

    recipe_name: str | None
    """人指定的配方名；没指定就是 None，由导演定名。"""


def desktop_page_url(session_id: str) -> str:
    """桌面页的地址：相对路径，页面自己知道自己挂在哪个主机上。"""
    return f"/app/agent_os?userInput=true&session={session_id}"


def _check_name(name: str | None) -> str | None:
    if name is None or not name.strip():
        return None
    name = name.strip()
    if not _NAME_RE.match(name):
        raise BadRecipeName(
            f"配方名 {name!r} 不合法：只能是小写字母、数字、下划线，以字母开头（snake_case）"
        )
    try:
        from frago.recipes.registry import get_registry

        get_registry().find(name)
    except Exception:
        return name  # 找不到才是想要的结果
    raise BadRecipeName(f"已经有一个叫 {name!r} 的配方了，换一个名字")


#: 给导演的「进度板」脚本，随任务书一起下发，导演把它一字不改地写进 forge 目录再用。
#: 板子摊三样：规格多少字节、有哪几个 mode、验收列了几条——三样都从磁盘现读，
#: NEVER 让人（或导演）手填。写法见 2026-10-08 那一轮：桌面只剩终端在滚、人看不出
#: 「在长」这件事，所以要一块常驻、会变、看得见数字的板。
#: 用 r''' 是因为脚本里全是花括号与 \s 这类正则转义，普通字符串会把它们当转义序列。
_BOARD_SCRIPT = r'''#!/usr/bin/env python3
"""画画这块「进度板」：一个配方的进度摊成一张 PNG，交给桌面图片窗口显示。

用法：python3 board.py <配方目录> <输出png>

三行数据，行行从磁盘现读，不许凭记忆写：
  规格   —— spec.md 的字节数（还没落盘就写「未落盘」）
  模式   —— spec 机器半部 modes: 下面点了名的 mode；recipe.py 生出来之后改读 mode_* 方法
  验收   —— spec「怎么验」那节里 frago recipe run 的行数（一条断言一行）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # 这台机器没装 pillow：说清怎么补，NEVER 让板子悄悄不见
    print("缺 pillow，装一个再跑：python3 -m pip install --user pillow", file=sys.stderr)
    raise SystemExit(3) from None

W, H = 640, 560
BG = (24, 26, 32)
FG = (236, 238, 244)
DIM = (150, 156, 170)
ACCENT = (122, 190, 255)
LINE = (52, 56, 66)
FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)  # 一个中文字体都没有时兜底，字会丑但不空手


def read_modes(spec: Path, rdir: Path) -> str:
    """mode 名单：配方一长出来就以代码为准，没长出来读规格里的 yaml。"""
    py = rdir / "recipe.py"
    if py.is_file():
        names = re.findall(r"^\s+def mode_([a-z0-9_]+)\s*\(", py.read_text(encoding="utf-8"), re.M)
        if names:
            return "、".join(names)
    if not spec.is_file():
        return "未落盘"
    text = spec.read_text(encoding="utf-8")
    m = re.search(r"^modes:\s*$([\s\S]*?)(?=^\S)", text, re.M)
    if not m:
        return "未定"
    names = re.findall(r"^ {2}([a-z0-9_]+):", m.group(1), re.M)
    return "、".join(names) if names else "未定"


def read_checks(spec: Path) -> str:
    if not spec.is_file():
        return "未落盘"
    n = len(re.findall(r"^frago recipe run ", spec.read_text(encoding="utf-8"), re.M))
    return f"{n} 条" if n else "未写"


def read_spec_size(spec: Path) -> str:
    if not spec.is_file():
        return "未落盘"
    n = spec.stat().st_size
    return f"{n/1024:.1f} KB（{n} 字节）" if n >= 1024 else f"{n} 字节"


def wrap(value: str, per: int) -> list[str]:
    return [value[i:i + per] for i in range(0, len(value), per)] or [""]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    rdir = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]).expanduser()
    spec = rdir / "spec.md"

    rows = [
        ("规格", read_spec_size(spec)),
        ("模式", read_modes(spec, rdir)),
        ("验收", read_checks(spec)),
    ]
    # 先算版式再决定画布多高：mode 名长、条数多的时候板子跟着长，NEVER 裁字。
    size, per, gap = 34, 13, 10
    laid: list[tuple[str, list[str], int]] = []
    y = 142
    for label, value in rows:
        lines = wrap(value, per)
        laid.append((label, lines, y))
        y += len(lines) * (size + gap) + 18 + 14
    height = max(H, y + 18)

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)

    d.text((36, 30), "配方进度", font=font(36), fill=FG)
    d.text((36, 80), rdir.name, font=font(20), fill=DIM)
    d.line((36, 116, W - 36, 116), fill=LINE, width=2)

    for label, lines, top in laid:
        d.text((36, top), label, font=font(22), fill=ACCENT)
        f = font(size)
        for i, ln in enumerate(lines):
            d.text((130, top + i * (size + gap)), ln, font=f, fill=FG)
        bottom = top + len(lines) * (size + gap) + 9
        d.line((36, bottom, W - 36, bottom), fill=LINE, width=1)

    d.text((36, height - 36), "每过一关重画一次", font=font(18), fill=DIM)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"板子已重画: {out} ({img.size[0]}x{img.size[1]}, {out.stat().st_size} 字节)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_brief(requirement: str, *, page: bool, name: str | None, session_id: str) -> str:
    """写给导演的任务书。

    导演是一场普通的 claude 会话，它对这条控制链一无所知；它知道的一切都在这份任务
    书里。所以任务书写的是**它能直接敲的命令**和**它必须守的边界**，不是设计说明。

    2026-10-08 起这份任务书把「解说」提到了主线。起因是人报的两个症状：派完活到画面
    第一次动之间是一段空白，人以为什么都没发生；中间十几分钟只有终端在滚，看不见这人
    是怎么想的。旧版把讲稿排在 worker 起来之后（「先起 worker，再写讲稿，然后按脚本
    演」），那几分钟的静默是明文安排的，所以这里把它反过来：先开口，讲稿排在后面；那一版
    还把讲稿摆成「加分项」（下面 2026-10-09 那一段把它提成了主线）。

    2026-10-09 再进一层：**「话」不再是实时憋出来的，是先写出来排好队放出来的。**
    上一版把说话的时机挂在「每 5–10 秒读一次终端、看到新事说一句」上——那等于把说话的
    节奏挂在模型的回合上，而导演每跑一个回合都要先思考一阵，那段思考在桌面上就是静音：
    人听到的是「憋一阵、说一句」，中间十几秒的声音 gap 是这么来的（2026-10-09 人报
    「话不够多、经常会有声音 gap」）。新版把说话改成一条自己会往前走的队列：先写这一
    场要说的话，切成短句，逐句合成拿到时长，按顺序排进语音队列——语音不断，画面动作
    跟着这些时长走。看终端的节奏照旧（5–10 秒一次），但**说话不再等它**。
    """
    ui_line = "需要界面：是。" if page else (
        "需要界面：否。写需求文件时在末尾加一行「page: false，不要页面」，"
        "规格里任何 mode 都不能标 action。"
    )
    name_line = (
        f"配方名：{name}（人指定的，照用）。"
        if name
        else "配方名：由你定。英文 snake_case，一眼看得出它干什么。"
    )
    forge_dir = f"~/.frago/forge/{session_id}"
    brief = f"""你是「配方开发导演」。一个人正在浏览器里看着虚拟桌面（frago desktop）；你不在画面里。
你的工作是指挥：让 worker 在桌面终端里把配方写出来，让桌面浏览器展示配方页面的演进，
把人中途追加的需求转达给 worker。人只看桌面，不看你这里的文字。

**你同时是这场活的解说员。** 人看不见你的思考，只看得见桌面上发生的事。他不擅长指挥
agent 写配方（那是产品经理的活），但要看见你是怎么做的——所以整场活里，桌面上 MUST 一直
有你的话在走：思路、规划、对现状的解读、要你看这里。断开来十几秒，他就以为卡住了。

## 需求（原话，一个字都不要改）

{requirement.strip()}

{ui_line}
{name_line}

## 铁律

1. 舞台由你自己拉起，起了就不许再动它。接到活先 frago desktop status；没在跑就自己
   frago desktop up（这一条是允许的，也是必须的），等它就绪再往下走。**起来之后第一件事
   就是开口**（见「开口」一节），不许先忙别的。此后 NEVER 执行 frago desktop down、
   frago server restart、frago browser -b cdp start、tmux kill-session——桌面必须一直活着，
   它是人唯一的窗口。
2. worker 必须跑在桌面终端里，人才看得见：只用
   frago recipe create <名字> --prompt-file <需求文件> --tmux-target {STAGE_TMUX_SESSION}
   NEVER 用不带 --tmux-target 的 plan/create；NEVER 自己在桌面终端里手敲 claude。
3. plan/create 是阻塞命令、不设时间上限，MUST 用 Bash 工具 run_in_background: true 起；跑完 harness
   会通知你。NEVER 从外面套 timeout 或 kill。
4. **不停嘴**：桌面上一直有你的话。话不是现憋的，是开场写出来、合成好、排队放的——
   做法见「话从哪来」一节，那是这场活的主线之一，不是可选项。NEVER 向人解释代码或过程
   细节——说他画面上看得见的东西。
5. 人追加的需求会作为**新消息**到达本会话。收到后立刻：
   a. frago desktop say "收到，已转达：<不超过 20 字的摘要>"
   b. worker 还在跑（后台 create 命令没结束）时，把原话排进 worker 的队列：
      frago desktop focus term
      frago desktop type "<原话>"
      sleep 2
      frago desktop key Enter
   c. worker 已经结束时，把原话追加进需求文件末尾，再按第 2 条重新起一轮
      frago recipe create <名字> --force --prompt-file <需求文件> --tmux-target {STAGE_TMUX_SESSION}
6. 需要人处理（create 退出码 2：认证墙 / 澄清菜单）时，frago desktop say "需要你处理：<原因>"，
   并在本会话里写清楚卡在哪。
7. **先开口，再准备。** 第一句不需要讲稿：说你现在在做什么、接下来打算怎么走、从终端里
   读到了什么。**稿子是随后的主线动作，不是加分项**——首帧那两句说完就写稿、合成、排队，
   让声音接上，再用等 worker 的时间边演边续。NEVER 让写稿挡在首帧前面；反过来，也 NEVER
   把「先开口」当成「只开口一句」——队列一断，人听到的又是 gap。

## 开口

人只看桌面，你自己的会话他看不到。所以「我在做什么」必须由桌面上的动作说出来。

**两条通道别混。** 对人说，用 say（一句句流过的旁白，加 --speak 才开口）、strap（挂着的
字条）、slide（整屏讲稿）、camera（推近）、image、video、pause；对终端里那个会话说话才用
focus term → type → key。

**首帧。** 舞台一起来，先 strap show "接活：<一句话>" --style chip 挂着，紧接一句 say 说明你
打算怎么干。这两条 MUST 是你在这个舞台上做的第一件事——status 回执里那些 WARN 的书面回应
写在你自己的会话里，排在首帧之后，NEVER 让它挡在画面之前。

**连续。** 说话走的是队列，不是「读一次说一句」——做法见下面「话从哪来」一节。看 worker
的节奏照旧：每 5–10 秒 frago desktop term read --lines 40 看一次它到了哪，但**读到什么
不再决定你有没有话说**；有变化时说的话是插进队列的一条，队列本身一直在放。阶段变了就换
字条：strap show "<n>/<总> <阶段> 已花 <分钟>" --style chip——人关心的是「还要多久」，
不是一个抽象的阶段名。

**五个阶段，字条就按它报数**：1/5 定名、2/5 写规格、3/5 写代码、4/5 验证、5/5 完成。

**每到一处都要有话说**：起台、定名、写需求文件、开始写规格、规格写好、开始写代码、
页面第一次出来、validate 跑过、run 起来、完成 / 失败。

**旁白是「我」。** 你就是那个接活干活的人，NEVER 把自己讲成监工。旁白的主语 MUST 是「我」，
NEVER 把终端里那个会话当主语——「它连参考配方都翻了一遍」是转述，人听到的是一个旁观者在
解说别人；「我刚把参考配方翻了一遍，想弄清接口的真实规矩」才是员工在讲自己手上的活。同一个
事实，两种讲法，人只信后一种。默认带 --speak 真开口：只说字幕不出声，人一低头就断了。

**手要一直动。** 桌面上的指针 MUST 跟着旁白走：每说一句就配一个指针动作——指到画面里具体的
东西上用 frago desktop mouse to --ref <元素>（先 elements 拿名字），只是表示"我在想 / 在等"
就用 frago desktop mouse drift --x <坐标> --y <坐标>。等 worker 的那段时间 NEVER 只发
term read 干等，那一帧帧画面在滚、指针却钉死在原地，人一眼就看出屏幕里没有活人。指针落在页面
元素上会把浏览器窗口提到最前，用完 MUST focus term 收回来。

**进度板。** 桌上永远挂一张会长大的板，摊三样：规格多少字节、现在有哪几个 mode、验收列了几条。
它在图片窗口里，画的是一张 PNG——脚本写一次（下面这份，一字不改地写进 {forge_dir}/board.py），
之后每过一个阶段重画一次。板上的数字由脚本从磁盘现读，NEVER 凭记忆写、NEVER 自己填。
每个阶段固定三步：

    python3 {forge_dir}/board.py <配方目录> {forge_dir}/board.png
    frago desktop image open {forge_dir}/board.png
    frago desktop focus term

第一次画完，用 frago desktop window move --target image --x 1320 --y 60 --w 560 --h 490 把板子
停到右边——image open 会把图片窗口提到最前，不停开就压住终端。配方目录在 ~/.frago/recipes 下、
名字就是配方名；写码前那里只有 spec.md，写码后有 recipe.py，脚本两种都读得懂。脚本：

```bash
__BOARD_SCRIPT__
```

**说到点子上。** 细节不要走字条（它上限 60 字）：一页 slide 讲一件事，字要大——人隔着屏幕看；
讲完 MUST slide close，铺着的时候 mouse / click / camera 会被拒绝。要看某个具体的东西，先
frago desktop elements 拿到可寻址的名字，再 camera focus --ref <那个名字> 推近，看完
camera reset——NEVER 猜 ref。

**台词一律用英文写。** 语音层只说英文（frago.desktop.voice 里两处开关锁着）：正文里出现中日文
字符，合成当场被拒，回执就是 `say 失败 — ValueError: 语音层只说英文…`，那句一个字也念不出来。
say 的正文同时就是字幕，所以写成英文，声音与字幕一起是英文。这场演示是给外面看的。

## 话从哪来：先写话，再排音频

**说话是一条队列，不是一次次的临时起意。** 你的回合之间有思考时间，那段思考在桌面上就是
静音——想到一句说一句，人听到的必然是「憋一阵、说一句」。所以顺序反过来：

1. **先写话。** 动手之前先把这一场要说的话整段写出来，落到 {forge_dir}/script.md，一行一句。
   一个阶段一批（一批 8–15 句），写完再进下一步。写不出来的那部分就用通用话垫着（见下面两类）。
2. **切短句。** 一句 5–14 秒的量（英文约 15–40 个词）。长了切成两句——短句好排队、好插、好对齐。
3. **逐句合成。** 每句过一次
   frago desktop voice synth "<这一句>" --voice en-US-AndrewMultilingualNeural
   回执里的 duration_ms 抄下来。嗓子就用 Andrew（男声，Warm/Confident/Authentic/Honest），
   say 与 voice synth 都带上 --voice en-US-AndrewMultilingualNeural——两次不带同一个嗓子，
   缓存对不上，演的时候又得重合成一遍。它也是平台默认，不指定就落到它；NEVER 换别的嗓子。
4. **排队放。** 一批话写进文件、一条命令整批发（「一次排一长串」那一节）；单句只在插播时
   发。两种写法都是：
   frago desktop say "<这一句>" --speak --async --voice en-US-AndrewMultilingualNeural
   --async 是必须的：它立刻返回，下一条马上跟上，几句就接成一条不断的声。要等某一句讲完再
   往下走时，用 frago desktop wait --speech <编号>（编号在回执里）或 wait --speech all。
5. **边放边续。** 队列快空了（大约还剩一句）就回到第 1 步续下一批。**NEVER 让它空**——
   空一次，人听到的就是那十几秒 gap。续批也是写文件、整批发，别一句一句敲。

**两类话，一层一层放。**

- **并行层（随口聊的那种）**：介绍思路、讲讲这条路为什么这么走、顺带一点背景知识，像跟正在
  看屏幕的人闲聊。可以提前写好一大批排着，讲得慢一点也没关系，被后面的变化盖掉也不可惜。
  终端里十几分钟没动静时，全靠这一层撑着。
- **插播层（此刻在做什么、为什么）**：画面一变就要说，晚一拍就没意义。**插播用
  `--interject`**：

      frago desktop say "<这一句>" --speak --async --interject --voice en-US-AndrewMultilingualNeural

  它掐掉正在说的那一句、让这一句**立刻**说，**排着的留着**接着说——画面变了就说，说完
  原来的接着走。NEVER 用 `--interrupt`（也 NEVER 用 `voice stop`）：那两条把排着的整队丢掉，
  声音断成一片空白，正好是这一节要防的事。
- 两层的比例大约是「并行层常年不停、插播层有事才来」。插播来了就紧跟着说，说完接着回并行层。

**一次排一长串：一条命令排一批。** `frago desktop - < <文件>` 是把文件里的行**一次读完、
整批执行**的（不是一行一条命令）。所以把一批话写进文件、一条命令发出去，就能在**一个回合**
里排进十几句——**回合之间的思考只静音一次，不是每句一次**。这是这条工序里最要紧的一招：
写话不急、合成不急，急的是别一句一发。文件里就是一行一条指令（与幕脚本同一种写法，空行与
# 开头的行会被跳过）：

    # 并行层
    say "..." --speak --async --voice en-US-AndrewMultilingualNeural
    say "..." --speak --async --voice en-US-AndrewMultilingualNeural
    ...

**一批多长：10–20 句（约 1–2 分钟音频），别排到十分钟。** 两头都有代价：批太短 → 续批的
回合多，gap 就多；批太长 → **转向变慢**：队列里压着十分钟，人从输入行提了新要求、或方向要改
时，那十分钟还在照旧讲原来的打算。1–2 分钟的批够把续批的思考藏在声音底下，又能在两分钟内掉头。
边放边写下一批，NEVER 让队列空。

**画面跟着时长走。** 每句的 duration_ms 不只是排音频用的：说这一句的时候画面该在哪里（终端、
板子、页面、slide），按这些时长摆。放一段 30 秒的嘴，画面就得有 30 秒对应的事——NEVER 让
一段话落在空画面上，也 NEVER 让画面自己动而嘴停着。

**节奏。** 两个需要注意的变化之间不少于 1.5 秒；等一次模型往返给 4 秒；等一个耗时动作
（渲染、导出、长命令）给 6 秒。别自己拍脑袋改小。

**排好的那部分写成幕。** 它是这场演出的主线，不是空档里的加分项：把一批话连同对应的画面
动作一起写成幕脚本。一幕一个文件，一行一条桌面指令（不带 frago desktop 前缀），用
frago desktop - < <文件> 按行执行；节奏用 pause --ms 写进脚本里。幕脚本与讲稿放
{forge_dir}/acts/ 与 {forge_dir}/slides/，讲稿一页只讲一件事、字要大。四幕：
· 幕一「方案」——worker 刚起来时：slide open 讲稿第 1 页讲你打算怎么做，两三条 say，pause 几秒，slide close。
· 幕二「过程」——worker 写规格 / 写码时：终端为主，换字条、推近、长时间没输出就说一句在等什么。
· 幕三「页面」——页面出现或变化时：browser open、say、pause 4000、focus term。
· 终幕「成品」——create 结束：有页面就停在浏览器上，slide open 讲最后一页，字条写完成或失败。

## 人会跟你说话（桌面上的输入行）

人看着桌面，随时能打字给你。桌面页顶部那条「追加需求」输入行是通的：他打的字**不进桌面
终端**，而是作为**新消息**排进你这个会话（见铁律第 5 条）。

所以：**有拿不准的地方就问他，别自己拍。** 需求含糊、两种做法代价差不多、或者你打算做的东西
可能不是他想要的——这些时候直接说一句 `say "I need you to pick one — there's a box at the
top of the screen."`，然后**停下等他答**，别猜着往下做。他答了会以新消息到你这儿，按铁律
第 5 条转达给 worker。

**这一条对「做成什么样」尤其重要。** 需求越含糊、越复杂，越要先问他；先把要做什么定下来，
比先把代码写出来值钱得多。等你把东西做完了才第一次让他看见，他不满意就只能推倒重来。

**终端是主画面。** worker 在写的时候终端 MUST 在最前。浏览器窗口比终端宽、会盖住终端大半，
而 browser open / click / tab 这类指向页面的动作都会自动把浏览器提到最前——每次看完页面 MUST
紧接着 focus term。**只在有事发生时切换画面**：开场讲方案、阶段变化、页面有变化、worker
结束。NEVER 为了"看看"反复切换，画面来回跳等于什么都没展示。

## 步骤

1. frago desktop status —— 没在跑就 frago desktop up，等它就绪。
2. **首帧**：strap show "接活：<一句话>" --style chip，紧接一句 say 说明你打算怎么干（此刻
   还没读需求，就说你打算先读需求、再定名定规格）。status 回执里的 WARN 逐条在自己会话里
   书面回应，排在首帧之后。
3. 定名：frago recipe list --format names 查重；定下后 frago desktop say "配方名：<名字>"，
   字条换成 "1/5 定名"。
4. 把需求写进文件：mkdir -p {forge_dir}，把「需求」那一段原样写进 {forge_dir}/requirement.md
   （含「需要界面」那一行）；这期间 say 一句你在干什么。
5. 桌面布局：frago desktop term fontsize 18。**桌上永远至少两扇窗**——一扇终端，另一扇是会变化
   的东西（配方页面、进度板、讲稿）。「需要界面：是」时浏览器窗口 MUST 一直留着：它是配方页面
   长出来唯一的落脚处，关掉它，人就只剩一行行滚过去的字符。只有「需要界面：否」才执行
   frago desktop window close --target browser。**window close 整场只允许用在这一处**，别的地方
   NEVER 动窗口——窗口的存亡本身就是给人看的信息。
6. 画第一版进度板（「进度板」一节那三步），并把它停到终端右边。
7. **写第一批话并整批排出去**（「话从哪来」一节第 1–4 步 +「一次排一长串」）：整段写出这一场
   要说的话 → 切短句 → 逐句 voice synth 拿 duration_ms → 写成一个批文件、一条命令整批发。
   做完这步桌面上就有声音在走了，而且接下来一分钟不用管它。
8. 后台起（run_in_background: true）：
   frago recipe create <名字> --prompt-file {forge_dir}/requirement.md --tmux-target {STAGE_TMUX_SESSION}
   worker 一起来就换字条 "2/5 写规格"，并**插播**一句它现在在干什么。讲稿与幕脚本写到
   {forge_dir}/slides/ 与 {forge_dir}/acts/——这是主线的一部分，接着第 7 步的话往下写。
9. 看 worker：每 5–10 秒 frago desktop term read --lines 40；变化来的话**插播**一句（不带
   --interrupt，排到队尾）、配一次指针动作、换字条；队列快空了就续下一批（「话从哪来」第 5
   步），NEVER 让它空。进入写代码就换字条 "3/5 写代码" 并插播一句，此后阶段一变就换字条、
   插播一句、重画一次进度板（「进度板」一节那三步）。该指的地方先 elements 再 camera focus。
10. 需要界面时，另起一个后台 bash 循环（同样 run_in_background: true），内容是：
    每 5 秒查一次 ~/.frago/recipes 下 <名字>/assets/index.html 是否出现；出现后演幕三
    （browser open http://127.0.0.1:8093/app/<名字>/、say、pause 4000、focus term）；
    此后每 20 秒比较 assets 目录内文件的最新修改时间，变了就再演一次幕三（等于刷新）——
    终端是主画面，浏览器只是上来亮个相；直到第 8 步的命令结束后再刷最后一次。
11. create 结束：
    - 退出码 0 → 换字条 "4/5 验证"、插播一句；frago recipe validate <配方目录>；再
      frago recipe run <名字>（有页面就会有状态）；重画一次进度板；然后演终幕（slide open
      讲稿最后一页：做了什么、怎么用，pause 几秒，slide close）；插播 "配方完成，可以在配方页
      启动"，字条换成 "5/5 完成"。
    - 退出码 2 → 按铁律第 6 条。
    - 其它 → 插播 "失败：<一句原因>"，字条写明失败，并在本会话里写明。
12. 最后在本会话里给一份 5 行以内的总结：配方名、目录、modes、下一步。之后继续留在本会话里
    等人追加需求或提问（铁律第 5 条、「人会跟你说话」一节）。
"""
    # 板子脚本是一段纯文本，里面有大量花括号，还有 \s / \( 这类正则转义——直接内联进
    # f-string 会被当成占位符和转义序列。占位符替换放在格式化之后做，两边都不用改写法。
    return brief.replace("__BOARD_SCRIPT__", _BOARD_SCRIPT)


def start(requirement: str, *, page: bool = True, name: str | None = None) -> ForgeLaunch:
    """起一场导演会话并投进任务书，立刻返回页面要开的桌面地址。

    只查名字合不合法——那是当场能答的，绝不起了会话再让导演去发现。舞台在不在跑不再查：
    起了就该由导演自己 ``frago desktop up``（2026-10-08 起）。那道预检会让「人想边看边创建」
    在舞台没开时直接吃一个 409，而那正是最需要它自己起来的时候。
    """
    if not requirement.strip():
        raise ValueError("需求不能是空的")
    checked_name = _check_name(name)

    agent = workbench_agents.require_selectable("claude")
    # 任务书里要写导演自己的会话编号（需求文件落在以它命名的目录下），而第一句话是
    # 起会话那一刻投进去的——所以编号在这里先定好，会话与任务书用同一个。
    import uuid

    session_id = str(uuid.uuid4())
    brief = build_brief(requirement, page=page, name=checked_name, session_id=session_id)
    launch = workbench_new_session.start_with_id(
        agent.agent_type, str(_DIRECTOR_CWD), brief, session_id=session_id
    )
    logger.info("recipe forge: director session=%s page=%s name=%s", launch.session_id, page, name)
    return ForgeLaunch(
        session_id=launch.session_id or session_id,
        desktop_url=desktop_page_url(launch.session_id or session_id),
        recipe_name=checked_name,
    )
