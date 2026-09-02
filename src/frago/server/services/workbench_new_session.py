"""页面新建一场会话 —— 两条路，因为编号的来路本来就是两种。

## 现象先说

从前页面上的「新建会话」只会起 claude，人在本机装了 codex、装了 opencode，一个都挑不
到。补的就是这一条。补的时候撞上一件不能绕的事：**三家的会话编号来路不同。**

- claude 接受 ``--session-id``：页面先 mint 一个 uuid，会话编号在点"创建"那一刻就有，
  界面直接跳进那一场，跟从前一模一样。
- codex 与 opencode 的编号由它们自己分配。frago 只能在会话起来之后去认领（见各 driver
  的 ``_claim_once``）。也就是说点完"创建"到"知道这一场叫什么"之间有一段空窗——codex
  的记录文件在 TUI 起来那一刻就建好，几秒；opencode 要等首轮提交落库，久一些。

那段空窗必须如实呈现，不能假装编号已经有了。所以这里给出的是一个**把手**
（``handle``）：页面拿着把手来问"认到编号没有"，认到了再跳进去。

## 把手不是会话编号，形状上就不许像

把手一律带 ``webui-`` 前缀。三家的编号要么是 UUID 形状（claude/codex）、要么是 ``ses_``
开头（opencode），前缀一加就绝不会被 ``detect_family`` 当成某一家的会话去翻档案——翻出
空的，看起来像"会话没记录"，而真相是它压根不是个会话编号。

## 认到编号之后，池里那一场要认两个名字

新建时 tmux 那场是以把手为键起的，而认领到的原生编号才是页面之后用的名字。同一个 TUI
两个名字，池里 MUST 只有一份：不然页面认到编号后紧接着再发一句话，池里查不到，于是又起
一个 tmux 去 ``codex resume <同一个编号>``，撞上 codex 0.149 的单写者锁——第二次 resume
在 TUI bootstrap 阶段直接失败退出（20260902 实测），这一轮报废。这由
``WarmSessionPool.alias`` 登记。

首轮跑完就把这一场从池里驱逐掉，别名跟着清。别名只是进程内的一张表，服务一重启就没
了，而 tmux 是独立守护进程、一场都不会跟着死——那时页面拿原生编号来发话，池里查不到、
tmux 里也没有同名会话，就会在另一个窗口里 resume 同一场，回到上面那个坏结果。让首轮
结束即收摊，代价是下一句话付一次冷启动，换来的是"任何时刻至多一个 TUI 对着一场会话"。

分层：服务层。可以 import ``agent_driver/`` 与 ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from frago.server.services import workbench_agents

logger = logging.getLogger(__name__)

#: 把手的前缀。见模块头："形状上就不许像会话编号"。
HANDLE_PREFIX = "webui-"

#: 一条把手记录在内存里留多久（秒）。页面认到编号就不再问它，留着只为让"起失败了"
#: 这件事在人回头看的时候还答得上来。
_RETENTION_S = 30 * 60

#: 首轮的墙钟上限。给得比普通一轮宽：新建会话这一轮既要付冷启动，又常是最长的一轮
#: （人往往一上来就交代一整件事）。超了不代表会话没了，只代表这一轮不再等它。
_FIRST_TURN_TIMEOUT_S = 600.0


@dataclass
class PendingLaunch:
    """一次"新建会话"从点下去到认到编号之间的全部状态。"""

    handle: str
    agent_type: str
    display_name: str
    cwd: str
    #: 这一场会话的编号。``id_origin == "caller"`` 时点下去就有；否则等认领。
    session_id: str | None = None
    #: 起会话这条路上出的错（起不来 / 挑不了）。有值时页面停下来报它，NEVER 继续等。
    error: str | None = None
    #: 首轮跑完了没有。用来判"认领的机会窗口已经关了"——跑完还没认到就是真认不到了。
    finished: bool = False
    created_at: float = field(default_factory=time.time)


_launches: dict[str, PendingLaunch] = {}
_lock = threading.Lock()


def _prune_locked() -> None:
    cutoff = time.time() - _RETENTION_S
    for handle in [h for h, launch in _launches.items() if launch.created_at < cutoff]:
        del _launches[handle]


def _resolve_claimed(agent_type: str, handle: str) -> str | None:
    """这家 agent 认领到编号没有。查不动一律当"还没认到"，NEVER 因此报错。

    认领映射是 driver 在会话跑起来的过程中写的，键就是我们给的那个把手。
    """
    try:
        if agent_type == "codex":
            from frago.session import codex_store

            return codex_store.get_binding(handle)
        if agent_type == "opencode":
            from frago.session import opencode_store

            return opencode_store.get_binding(handle)
    except Exception:  # noqa: BLE001 — 读不到只是这一拍还没认到
        logger.debug("查 %s 的认领映射时出错（handle=%s）", agent_type, handle, exc_info=True)
    return None


def start(agent_type: str, cwd: str, prompt: str) -> PendingLaunch:
    """起一场新会话并投进第一句话，立刻返回（首轮在后台跑）。

    **不等首轮跑完。** 一轮少则十几秒、多则几分钟，让创建对话框挂在那儿等，人会以为
    卡死了。页面拿着返回的编号（或把手）自己去看记录流，那条路本来就会把"还在等 agent
    开口"显示出来。

    挑不了的那一家在这里就拦下（:class:`AgentUnavailable`）：拦不住的话人要等上一分钟
    才看得出这一场根本起不来。
    """
    agent = workbench_agents.require_selectable(agent_type)
    directory = str(Path(cwd).expanduser()) if cwd.strip() else str(Path.home())

    if agent.id_origin == "caller":
        # 编号页面这边定：claude 拿 ``--session-id`` 用它新建，记录自己落到该去的地方，
        # 下一次扫描它就是一行普通会话。
        launch_id = str(uuid.uuid4())
        session_id: str | None = launch_id
        native = True
    else:
        # 编号得等认领。把手带前缀，形状上就不会被当成某一家的会话编号。
        launch_id = f"{HANDLE_PREFIX}{uuid.uuid4()}"
        session_id = None
        native = False

    launch = PendingLaunch(
        handle=launch_id,
        agent_type=agent.agent_type,
        display_name=agent.display_name,
        cwd=directory,
        session_id=session_id,
    )
    with _lock:
        _prune_locked()
        _launches[launch_id] = launch

    if native:
        # 编号是页面自己 mint 的，claude 不会给它派 slug，扫描那一侧因此认不出"这场是
        # 人从网页开的"。与 ``session_send`` 里那一处是同一件事，登记一次。
        try:
            from frago.session import claude_sessions as claude_svc

            claude_svc.register_webui_session(launch_id)
        except Exception:  # noqa: BLE001 — 登记失败不该把一场会话拦下
            logger.warning("登记 webui 会话 %s 失败", launch_id, exc_info=True)

    thread = threading.Thread(
        target=_run_first_turn,
        args=(launch, prompt, native),
        name=f"webui-new-session-{launch_id[:12]}",
        daemon=True,
    )
    thread.start()
    return launch


def _run_first_turn(launch: PendingLaunch, prompt: str, native: bool) -> None:
    """后台跑首轮：起 tmux、投第一句话，中途把认领到的编号接上。

    认领在**首轮进行当中**就会发生，所以这里一边跑一边有一条并行的看守线程去问
    （``_watch_claim``）——等首轮结束再问，页面就要干等一整轮才知道自己开的是哪一场。
    """
    from frago.server.services.ui_session_runner import get_runner

    watcher: threading.Thread | None = None
    if not native:
        watcher = threading.Thread(
            target=_watch_claim,
            args=(launch,),
            name=f"webui-claim-{launch.handle[:12]}",
            daemon=True,
        )
        watcher.start()

    try:
        get_runner().send(
            launch.handle,
            prompt,
            agent_type=launch.agent_type,
            cwd=launch.cwd,
            timeout_s=_FIRST_TURN_TIMEOUT_S,
            native_session_id=native,
        )
    except Exception as e:  # noqa: BLE001 — 起不来照实记下，页面据此停下来报
        launch.error = f"{launch.display_name} 没起来：{e}"
        logger.warning("新建会话失败（handle=%s）", launch.handle, exc_info=True)
    finally:
        launch.finished = True
        if not native:
            # 首轮结束前最后再问一次：轮次很短时看守线程可能还没轮到。
            _adopt_claimed(launch)
            _retire(launch)


def _watch_claim(launch: PendingLaunch) -> None:
    """首轮跑着的时候盯着认领映射，认到就登记别名并记进 launch。

    盯到首轮结束为止。认不到不是错——那多半意味着这一轮压根没起来，错会由跑首轮那条
    路自己报，NEVER 在这里再编一个理由。
    """
    while not launch.finished and launch.session_id is None:
        if _adopt_claimed(launch):
            return
        time.sleep(0.5)


def _adopt_claimed(launch: PendingLaunch) -> bool:
    """认到编号就记下来，并让池里那一场也认这个名字。认到返回 True。"""
    if launch.session_id is not None:
        return True
    claimed = _resolve_claimed(launch.agent_type, launch.handle)
    if claimed is None:
        return False
    try:
        from frago.server.services.ui_session_runner import get_runner

        get_runner().alias(claimed, launch.handle)
    except Exception:  # noqa: BLE001 — 别名登记失败只影响下一句话要不要冷启动
        logger.debug("登记别名 %s → %s 失败", claimed, launch.handle, exc_info=True)
    launch.session_id = claimed
    logger.info(
        "webui 新建会话认到编号：handle=%s agent=%s session=%s",
        launch.handle,
        launch.agent_type,
        claimed,
    )
    return True


def _retire(launch: PendingLaunch) -> None:
    """首轮跑完就把以把手为键的那一场从池里收走（连同别名）。

    见模块头："别名只是进程内的一张表"。收摊的代价是下一句话付一次冷启动，换来的是
    任何时刻至多一个 TUI 对着一场会话。
    """
    try:
        from frago.server.services.ui_session_runner import get_runner

        get_runner().evict(launch.handle)
    except Exception:  # noqa: BLE001 — 收不掉最坏是多留一个 tmux，不该反过来炸
        logger.debug("收走 %s 的常驻会话失败", launch.handle, exc_info=True)


def status(handle: str) -> PendingLaunch | None:
    """这次新建现在到哪一步了。没有这个把手时返回 None。

    还没认到编号时顺手再问一次认领映射：看守线程可能已经退了（首轮结束），而映射是
    盘上的事实，问一次不花什么。
    """
    with _lock:
        launch = _launches.get(handle)
    if launch is None:
        return None
    if launch.session_id is None:
        _adopt_claimed(launch)
    return launch
