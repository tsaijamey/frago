"""``frago desktop`` —— 虚拟桌面舞台的一等入口。

为什么要有这一层
----------------
舞台的能力一直都在（配方 ``agent_os`` 里那个 ``aos`` 脚本），缺的是**被看见**。
同样是驱动一块外部界面，``frago browser`` 在 PATH 上、``--help`` 一把列全动词、
book 里有常驻章节；而 ``aos`` 埋在配方目录里，agent 只有先知道"有这么个文件"
才谈得上用它。结果是 agent 知道"有虚拟桌面这回事"，却不知道 ``aos status``
和 ``aos up`` 存在——这两条本来就在那儿。

2026-08-04 实测过这个失败：让 agent 去桌面上演示一个动作，它翻注册表、探端口、
读源码，走了四五步才拼出"舞台没在跑"，然后反过来问人要不要启动。而正确动作只有
三步：查状态、拉起来、演示。信息全在，只是没落在它看得见的地方。

这一层只做转发
--------------
真正干活的仍是配方里那份 ``aos``：动词、参数、回执格式一个字不改，这里不复制
任何语义。复制会立刻产生第二份真相——配方改了动词，CLI 这边不跟，agent 拿到的
帮助就是错的，而这种错比没有帮助更伤。

所以这里刻意做成**透明管道**：拿到什么原样递过去，stdout / stderr / 退出码
原样带回来。``frago desktop`` 与 ``aos`` 永远等价。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import click

from .agent_friendly import AgentFriendlyCommand

# 舞台脚本的位置。跟 virtual_os_lifecycle 用的是同一条路径约定：
# 配方装在用户目录下，不随 frago 包分发。
RECIPE_NAME = "agent_os"
AOS = Path.home() / ".frago" / "recipes" / "workflows" / RECIPE_NAME / "aos"


@click.command(
    name="desktop",
    cls=AgentFriendlyCommand,
    context_settings={
        # 舞台自己解析参数。这里不能让 click 插手：它会把 --zoom、--ref 这类
        # 它不认识的选项当成错误挡下来，而那些正是舞台的正常用法。
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def desktop_group(args: tuple[str, ...]) -> None:
    """Drive the virtual desktop stage (recording / demo).

    A fake macOS desktop whose windows show a real tmux session, a real browser
    tab, and a local image. Everything on it is scriptable, so a workflow can be
    replayed as a video take.

    \b
    Always start here:
      frago desktop status          # is the stage running? (like `browser status`)
      frago desktop up              # bring it up; the desktop page reconnects itself
      frago desktop down            # stop it — intent is remembered, it stays down

    \b
    Then drive it:
      frago desktop browser open <url>
      frago desktop browser click --text "Sign in"
      frago desktop term run "ls -la"
      frago desktop camera focus --ref page:"Explore" --zoom 1.8
      frago desktop say "旁白一句"

    \b
    Every verb, flag and receipt is the stage's own — this command forwards
    verbatim and returns its exit code unchanged. Run it bare to list the
    resources, or see `frago book desktop-usage` for the full path.
    """
    if not AOS.exists():
        # 这里曾经写着"用 frago init 装配方"，那是假的：包里只随分发
        # transcript_completion 与 openrouter_vision_classify 两个配方，
        # agent_os 不在其中。init 会正常跑完、报告成功，然后这条命令依然
        # 找不到舞台——一个会跑完、会报成功、却什么也没解决的指引，比没有
        # 指引更坏。所以这里只说实话：它不随包走，得从配方来源同步。
        # 回执用 json.dumps 生成，不手拼字符串：这段里有中文、有路径、有引号，
        # 手拼出非法 JSON 的话，调用方（多半是 agent）拿到的是解析异常，
        # 而真正的原因「配方不在」一个字都传不到。
        click.echo(json.dumps({
            "ok": False,
            "error": "本机没有虚拟桌面配方，frago desktop 无法工作",
            "expected": str(AOS),
            "note": "agent_os 与 agent_os_ui 两个配方不随 frago 包分发，"
                    "frago init 装不来它们",
            "hint": "从配方来源同步这两份到 ~/.frago/recipes/：",
            "need": ["workflows/agent_os", "atomic/system/agent_os_ui"],
        }, ensure_ascii=False))
        sys.exit(2)

    # 舞台把它的运行状态（实例台账、录屏片段、broker 日志）写在平台交代的落点里，
    # 而这条命令不走 `frago recipe run`——它直接起舞台脚本，所以那份交代得由这里补上。
    # 不补的话舞台起不来，报的是「平台没有交代落点」：一条对着人喊的错误，而人根本
    # 没做错什么，他只是敲了 frago desktop。
    env = dict(os.environ)
    try:
        from frago.recipes.context import for_owner

        ctx = for_owner(RECIPE_NAME)
        if ctx.data_dir is not None:
            env["FRAGO_RECIPE_DATA_DIR"] = str(ctx.data_dir)
            env["FRAGO_RECIPE_CALLER"] = "owner"
            if ctx.slot:
                env["FRAGO_RECIPE_SLOT"] = ctx.slot
    except Exception:  # noqa: BLE001 — 交代不出就让舞台自己报，别把这里变成第二个报错点
        pass

    # 直接把子进程的输出接到自己的 stdout/stderr 上，不做缓冲、不做转写：
    # 舞台的回执恒为单行 JSON，调用方（多半是 agent）要拿它原样解析。
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(AOS), *args],
        check=False,
        env=env,
    )
    sys.exit(proc.returncode)
