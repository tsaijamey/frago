"""``frago desktop`` —— 虚拟桌面舞台的一等入口。

为什么要有这一层
----------------
舞台的能力一直都在（``frago.desktop`` 包里那个 ``aos``），缺的是**被看见**。
同样是驱动一块外部界面，``frago browser`` 在 PATH 上、``--help`` 一把列全动词、
book 里有常驻章节；而 ``aos`` 从前埋在配方目录里，agent 只有先知道"有这么个文件"
才谈得上用它。结果是 agent 知道"有虚拟桌面这回事"，却不知道 ``aos status``
和 ``aos up`` 存在——这两条本来就在那儿。

2026-08-04 实测过这个失败：让 agent 去桌面上演示一个动作，它翻注册表、探端口、
读源码，走了四五步才拼出"舞台没在跑"，然后反过来问人要不要启动。而正确动作只有
三步：查状态、拉起来、演示。信息全在，只是没落在它看得见的地方。

这一层只做转发
--------------
真正干活的仍是 ``aos``：动词、参数、回执格式一个字不改，这里不复制任何语义。
复制会立刻产生第二份真相——那边改了动词、这边不跟，agent 拿到的帮助就是错的，
而这种错比没有帮助更伤。

这条约束照旧成立，但它现在是**自动**成立的，不再靠人守：舞台 2026-09-02 从配方
搬进本体（``frago.desktop``），全机器只剩这一份实现，没有任何地方还需要抄一遍动词表。

于是"怎么转发"退化成一道纯粹的工程题，答案从子进程换成了进程内直调：

- 从前 ``[sys.executable, ~/.frago/recipes/workflows/agent_os/aos, *args]``，
  外加一段"把落点用环境变量交代给子进程"的前置。
- 现在 ``aos.main(list(args))``。省掉一次解释器启动，更要紧的是省掉那份环境变量
  约定——本机的保活守护正是漏掉它，连续 4005 次没能把舞台拉起来，而每次只留下
  一行 WARNING。落点改由 ``registry`` 自己求，调用方**没有机会**漏掉交代。

代价是 stdout 的干净得主动守，两条护栏配套：``aos.main()`` 兜住所有异常，无论如何
只打印一行 JSON、用返回值定退出码；本命令体自己一个字都不打印。
"""

from __future__ import annotations

import sys

import click

from .agent_friendly import AgentFriendlyCommand


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
      frago desktop camera focus --ref page:text:Explore --zoom 1.8
      frago desktop say "旁白一句"

    \b
    Addressing a page element (`page:` refs) — four spellings, one meaning each:
      page:text:某段文字   by visible text; safe on the command line
      page:css:.selector   by CSS selector; no fallback, a typo says so
      page:"某段文字"      by visible text; quote it as 'page:"..."' or the
                           shell eats the quotes and it reads as a selector
      page:裸串            selector first, visible text if that finds nothing

    \b
    Every verb, flag and receipt is the stage's own — this command forwards
    verbatim and returns its exit code unchanged. Run it bare to list the
    resources, or see `frago book desktop-usage` for the full path.
    """
    # 这里没有"舞台不在本机"这条分支，是刻意的。舞台跟着 frago 包分发，import 不到
    # 就是这个装置装坏了，Python 自己的 ImportError 是最诚实的报告。给一个不可能
    # 发生的状态编一段回执，等于给下一个人埋一条要去查的假线索。
    from frago.desktop import aos

    sys.exit(aos.main(list(args)))
