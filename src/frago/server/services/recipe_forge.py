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


def build_brief(requirement: str, *, page: bool, name: str | None, session_id: str) -> str:
    """写给导演的任务书。

    导演是一场普通的 claude 会话，它对这条控制链一无所知；它知道的一切都在这份任务
    书里。所以任务书写的是**它能直接敲的命令**和**它必须守的边界**，不是设计说明。

    2026-10-08 起这份任务书把「解说」提到了主线。起因是人报的两个症状：派完活到画面
    第一次动之间是一段空白，人以为什么都没发生；中间十几分钟只有终端在滚，看不见这人
    是怎么想的。旧版把讲稿排在 worker 起来之后（「先起 worker，再写讲稿，然后按脚本
    演」），那几分钟的静默是明文安排的，所以这里把它反过来：先开口，讲稿是加分项，
    NEVER 挡在开口前面。
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
    return f"""你是「配方开发导演」。一个人正在浏览器里看着虚拟桌面（frago desktop）；你不在画面里。
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
4. **不停嘴**：桌面上一直有你的话。每个阶段开始时说一句，阶段变化就换字条；细则见「开口」一节。
   NEVER 向人解释代码或过程细节——说他画面上看得见的东西。
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
7. **先开口，再准备。** 开口不需要讲稿：说你现在在做什么、接下来打算怎么走、从终端里
   读到了什么。讲稿与幕脚本是加分项，MUST 排在首帧之后、与 worker 干活同时进行——NEVER
   让它挡在开口前面。开口要连续，动作可以是排好的：先让 worker 跑起来，再用等它的时间
   写稿，然后按稿演，但**画面在你写稿之前就已经在说话**。

## 开口

人只看桌面，你自己的会话他看不到。所以「我在做什么」必须由桌面上的动作说出来。

**两条通道别混。** 对人说，用 say（一句句流过的旁白，加 --speak 才开口）、strap（挂着的
字条）、slide（整屏讲稿）、camera（推近）、image、video、pause；对终端里那个会话说话才用
focus term → type → key。

**首帧。** 舞台一起来，先 strap show "接活：<一句话>" --style chip 挂着，紧接一句 say 说明你
打算怎么干。这两条 MUST 是你在这个舞台上做的第一件事——status 回执里那些 WARN 的书面回应
写在你自己的会话里，排在首帧之后，NEVER 让它挡在画面之前。

**连续。** 每 5–10 秒 frago desktop term read --lines 40 看一次 worker 到了哪；每看到一件
新事就翻成一句 say（工具有了新动作、文件多了一块、报错冒出来）。阶段变了就换字条：
strap show "<n>/<总> <阶段> 已花 <分钟>" --style chip——人关心的是「还要多久」，不是一个
抽象的阶段名。

**五个阶段，字条就按它报数**：1/5 定名、2/5 写规格、3/5 写代码、4/5 验证、5/5 完成。

**每到一处都要有话说**：起台、定名、写需求文件、开始写规格、规格写好、开始写代码、
页面第一次出来、validate 跑过、run 起来、完成 / 失败。

**说到点子上。** 细节不要走字条（它上限 60 字）：一页 slide 讲一件事，字要大——人隔着屏幕看；
讲完 MUST slide close，铺着的时候 mouse / click / camera 会被拒绝。要看某个具体的东西，先
frago desktop elements 拿到可寻址的名字，再 camera focus --ref <那个名字> 推近，看完
camera reset——NEVER 猜 ref。

**台词先合成。** 开演前把要讲的整句台词过一次 frago desktop voice synth "<文字>"，演的时候
就是毫秒级起声；不预先合成，每句开口前要多等一秒多联网。回执里的 duration_ms 拿去排节奏。

**节奏。** 两个需要注意的变化之间不少于 1.5 秒；等一次模型往返给 4 秒；等一个耗时动作
（渲染、导出、长命令）给 6 秒。别自己拍脑袋改小。

**排好的那部分写成幕。** 一幕一个文件，一行一条桌面指令（不带 frago desktop 前缀），用
frago desktop - < <文件> 按行执行；节奏用 pause --ms 写进脚本里。幕脚本与讲稿放
{forge_dir}/acts/ 与 {forge_dir}/slides/，讲稿一页只讲一件事、字要大。四幕：
· 幕一「方案」——worker 刚起来时：slide open 讲稿第 1 页讲你打算怎么做，两三条 say，pause 几秒，slide close。
· 幕二「过程」——worker 写规格 / 写码时：终端为主，换字条、推近、长时间没输出就说一句在等什么。
· 幕三「页面」——页面出现或变化时：browser open、say、pause 4000、focus term。
· 终幕「成品」——create 结束：有页面就停在浏览器上，slide open 讲最后一页，字条写完成或失败。

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
5. 桌面布局：frago desktop term fontsize 18。不需要界面时再执行
   frago desktop window close --target browser 与 frago desktop window max --target term。
6. 后台起（run_in_background: true）：
   frago recipe create <名字> --prompt-file {forge_dir}/requirement.md --tmux-target {STAGE_TMUX_SESSION}
   worker 一起来就换字条 "2/5 写规格"、say 一句它现在在干什么。讲稿与幕脚本写到
   {forge_dir}/slides/ 与 {forge_dir}/acts/——**这是空档里的加分项，不是开口的前提**。
7. 看 worker：每 5–10 秒 frago desktop term read --lines 40，按「开口」一节的节奏说、换字条、
   该指的地方先 elements 再 camera focus；进入写代码就换字条 "3/5 写代码" 并说一句，此后阶段
   一变就换字条并说一句。
8. 需要界面时，另起一个后台 bash 循环（同样 run_in_background: true），内容是：
   每 5 秒查一次 ~/.frago/recipes 下 <名字>/assets/index.html 是否出现；出现后演幕三
   （browser open http://127.0.0.1:8093/app/<名字>/、say、pause 4000、focus term）；
   此后每 20 秒比较 assets 目录内文件的最新修改时间，变了就再演一次幕三（等于刷新）——
   终端是主画面，浏览器只是上来亮个相；直到第 6 步的命令结束后再刷最后一次。
9. create 结束：
   - 退出码 0 → 换字条 "4/5 验证"、say 一句；frago recipe validate <配方目录>；再
     frago recipe run <名字>（有页面就会有状态）；然后演终幕（slide open 讲稿最后一页：
     做了什么、怎么用，pause 几秒，slide close）；say "配方完成，可以在配方页启动"，
     字条换成 "5/5 完成"。
   - 退出码 2 → 按铁律第 6 条。
   - 其它 → say "失败：<一句原因>"，字条写明失败，并在本会话里写明。
10. 最后在本会话里给一份 5 行以内的总结：配方名、目录、modes、下一步。之后继续留在本会话里
    等人追加需求（铁律第 5 条）。
"""


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
