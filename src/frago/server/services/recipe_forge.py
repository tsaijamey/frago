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
from frago.skills.skill_prompt import embed_skills, load_skills

logger = logging.getLogger(__name__)

#: 驱动虚拟桌面边干活边解说演示的通用 skill。创建配方的任务书 = 这个 skill + 本场景特定要求。
AGENT_OS_SKILL_NAME = "how-frago-agent-runs-an-agent-os"

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


def build_recipe_task(
    requirement: str, *, page: bool, name: str | None, session_id: str
) -> str:
    """创建配方这一场景的特定要求（不含虚拟桌面通用导演教程）。

    虚拟桌面怎么拉起、语音队列怎么预合成与插播、指针怎么动、人类输入行怎么接，统一由
    ``how-frago-agent-runs-an-agent-os`` skill 规定；这里只交代「创建配方」独有的边界与步骤。
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
    task = f"""本场任务：按 `how-frago-agent-runs-an-agent-os` 的方法，在虚拟桌面上为用户创建并验证一个配方，全程在桌面上解说演示。本场工作目录：`{forge_dir}`（讲稿 `script.md`、幕脚本 `acts/`、幻灯 `slides/`、需求文件 `requirement.md`、进度板 `board.py` 均落在此目录下）。

## 需求（原话，一个字都不要改）

{requirement.strip()}

{ui_line}
{name_line}

## 本场景特定约束

1. **派 worker 写配方**：只用
   `frago recipe create <名字> --prompt-file {forge_dir}/requirement.md --tmux-target {STAGE_TMUX_SESSION}`
   且 MUST 用 Bash 工具 `run_in_background: true` 起。NEVER 用不带 `--tmux-target` 的 `plan`/`create`；NEVER 自己在桌面终端里手敲 `claude`。
2. **人中途追加需求时**：若后台 `create` 命令还在跑，按 skill 规定用 `frago desktop focus term` → `frago desktop type "<原话>"` → `sleep 2` → `frago desktop key Enter` 排进 worker 队列；若 worker 已经结束，把原话追加进 `{forge_dir}/requirement.md` 末尾，再用
   `frago recipe create <名字> --force --prompt-file {forge_dir}/requirement.md --tmux-target {STAGE_TMUX_SESSION}`
   重新起一轮。
3. **五个阶段，字条就按它报数**：`1/5 定名`、`2/5 写规格`、`3/5 写代码`、`4/5 验证`、`5/5 完成`。每到一处（起台、定名、写需求文件、开始写规格、规格写好、开始写代码、页面第一次出来、validate 跑过、run 起来、完成 / 失败）都要有话说。
4. **窗口存亡**：桌上永远至少两扇窗。「需要界面：是」时浏览器窗口 MUST 一直留着；只有「需要界面：否」才执行 `frago desktop window close --target browser`（`window close` 整场只允许用在这一处）。
5. **配方进度板**：一字不改地把下面这份脚本写进 `{forge_dir}/board.py`，摊三样（规格多少字节、现在有哪几个 mode、验收列了几条，全部从磁盘现读，NEVER 手填）。每个阶段固定三步：

       python3 {forge_dir}/board.py <配方目录> {forge_dir}/board.png
       frago desktop image open {forge_dir}/board.png
       frago desktop focus term

   第一次画完用 `frago desktop window move --target image --x 1320 --y 60 --w 560 --h 490` 停到终端右边。配方目录在 `~/.frago/recipes` 下、名字就是配方名。脚本：

```bash
__BOARD_SCRIPT__
```

## 本场景执行步骤

1. 按 skill 起舞台并完成**首帧**（`strap show "接活：<一句话>" --style chip` + 第一句 `say`）。
2. **定名**：`frago recipe list --format names` 查重；定下后 `frago desktop say` 报出配方名，字条换成 `"1/5 定名"`。
3. **写需求文件**：`mkdir -p {forge_dir}`，把「需求」那一段原样写进 `{forge_dir}/requirement.md`（含「需要界面」那一行）。
4. **桌面布局与第一版进度板**：设 `term fontsize 18`；按需处理浏览器窗口；画出第一版 `board.png` 并停到终端右边。
5. **写第一批话并整批排出去**：写 `{forge_dir}/script.md` → 切短句 → 逐句 `voice synth` 拿 `duration_ms` → 一条命令整批发。
6. **后台起 worker**（`run_in_background: true`）：
   `frago recipe create <名字> --prompt-file {forge_dir}/requirement.md --tmux-target {STAGE_TMUX_SESSION}`
   worker 一起来就换字条 `"2/5 写规格"` 并插播（`--interject`）一句；讲稿与幕脚本写到 `{forge_dir}/slides/` 与 `{forge_dir}/acts/`。
7. **轮询 worker 与续批**：每 5–10 秒 `frago desktop term read --lines 40`；变化来的话**插播**一句（`--interject`）、配一次指针动作、换字条；队列快空了就续下一批，NEVER 让它空。进入写代码换字条 `"3/5 写代码"`、插播一句并重画进度板。
8. **配方页面实时预览**（「需要界面：是」时）：另起一个后台 bash 循环（`run_in_background: true`），每 5 秒查一次 `~/.frago/recipes` 下 `<名字>/assets/index.html` 是否出现；出现后演幕三（`browser open http://127.0.0.1:8093/app/<名字>/`、`say`、`pause 4000`、`focus term`）；此后每 20 秒比较 `assets` 目录内文件的最新修改时间，变了就再演一次幕三；直到 `create` 结束后再刷最后一次。
9. **create 结束与终幕**：
   - 退出码 `0` → 换字条 `"4/5 验证"`、插播一句；跑 `frago recipe validate <配方目录>` 与 `frago recipe run <名字>`；重画进度板；演终幕（`slide open` 讲稿最后一页，`pause` 几秒，`slide close`）；插播 `"The recipe is ready — you can launch it from its page."`，字条换成 `"5/5 完成"`。
   - 退出码 `2` → `frago desktop say "需要你处理：<原因>"` 并在本会话写明。
   - 其它 → 插播 `"It failed: <one-line reason>"`，字条写明失败，并在本会话写明。
10. 最后在本会话里给一份 5 行以内的总结（配方名、目录、modes、下一步），继续留在本会话里等人追加需求或提问。
"""
    return task.replace("__BOARD_SCRIPT__", _BOARD_SCRIPT).strip()


def build_brief(requirement: str, *, page: bool, name: str | None, session_id: str) -> str:
    """写给导演的任务书：`how-frago-agent-runs-an-agent-os` skill + 创建配方场景特定要求。"""
    task = build_recipe_task(requirement, page=page, name=name, session_id=session_id)
    skills = load_skills([AGENT_OS_SKILL_NAME])
    return embed_skills(task, skills, user_text=task)


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
