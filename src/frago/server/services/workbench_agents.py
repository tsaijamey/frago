"""工作台新建会话时能挑哪几家 CLI —— 一份从注册表现算的清单。

## 为什么这份清单不是一张手写的名单

页面上的「新建会话」从前只会起 claude：那不是有意的选择，是那条路上根本没有"挑一家"
这个概念。补上它的第一诱惑是在前端写一张 `['claude', 'codex', 'opencode']`。那张表活不
过下一次接新家——接的人改完 driver、跑通 tmux，界面上却看不见它，而 driver 那侧一点异样
都没有。所以这里**从 driver 注册表现算**：注册了就在清单里，没注册就不在，只有一处判据。

## 一家能不能挑，要过两道门

**装没装。** 探测走 driver 自己的 ``locate``：claude 多半在 nvm/fnm/volta 某个目录下，
codebuddy 躺在 WorkBuddy.app 里，都不是 ``which`` 一句话能覆盖的，那份知识本就属于各家
自己。没装的**照样列出来**，只是不可选、并明说"本机没装"——把它整个藏掉，人只会觉得
"frago 不支持 codex"，而真相是装一下就能用。

**记录读不读得回来。** 工作台的清单、记录流、发送三条路都以「会话属于哪一家」为轴，而
那一层认得的只有 claude-code / opencode / codex 三家（``RecordFamily``）。codebuddy 有
driver、跑得起来，但它的 jsonl 落在 ``~/.codebuddy/projects``，工作台一个字都读不到——
让人从这里起一场 codebuddy 会话，结果是会话真的起来了、真的在干活，而页面上那一行永远
不出现。这比不给这个选项坏得多，所以它列出来但不可选，理由照实说。

## 编号谁来 mint，是两种交互而不是一个开关

claude 接受 ``--session-id``：页面先 mint 一个编号，会话编号当场就有，点完"创建"直接
跳进那一场。codex 与 opencode 的编号由它们自己分配，frago 只能在会话起来之后去认领
（见各 driver 的 ``_claim_once``），所以点完"创建"还有一段"正在起、等它报编号"的空窗。
判据出自 driver 的 ``accepts_session_id``，NEVER 在界面上按 agent 名字写死。

分层：服务层。可以 import ``agent_driver/`` 与 ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from frago.agent_driver.driver import registered_drivers
from frago.server.services.session_send import AGENT_TYPE_BY_FAMILY

logger = logging.getLogger(__name__)

#: agent_type → 工作台里的家族名。由 ``session_send`` 那份反过来算，NEVER 另写一份：
#: 两张表一分岔，就会出现"新建时能挑，建完读不回来"这种只有用户撞得上的错配。
FAMILY_BY_AGENT_TYPE: dict[str, str] = {
    agent_type: family for family, agent_type in AGENT_TYPE_BY_FAMILY.items()
}

#: 清单次序。摆在前面的是更可能被挑的那几家；表里没有的新家按名字排在后面——次序不对
#: 只是不好看，而漏掉一家是功能缺失，所以这里 NEVER 拿它当白名单用。
_PREFERRED_ORDER = ("claude", "codex", "opencode")

_NOT_INSTALLED = "本机没找到这个命令，装好之后它会自己出现在这里"
_NOT_READABLE = "frago 驱动得动它，但它的会话记录读不进工作台，起了也不会出现在左栏"
_UNKNOWN_INSTALL = "这一家没提供探测方式，判不出装没装"


class AgentUnavailable(ValueError):
    """这一家现在挑不了（没注册 / 没装 / 记录读不回工作台）。"""


@dataclass(frozen=True)
class WorkbenchAgent:
    """清单里的一行：某一家 CLI 在本机现在是什么状况。"""

    agent_type: str
    display_name: str
    #: 本机装没装。探测方式缺失时为 None——"判不出"与"没装"是两回事，合并会让一台
    #: 明明装了的机器被告知没装。
    installed: bool | None
    #: 可执行文件在哪。给人排查用（"我明明装了"时看得出 frago 找到的是哪一份）。
    path: str | None
    #: 工作台里的家族名；None = 这一家的记录读不回工作台。
    family: str | None
    #: 现在能不能挑。
    selectable: bool
    #: 摆在名字底下的那一句话：挑不了时是为什么挑不了，能挑但探测不出装没装时是那句
    #: 提醒。两种都值得说，没什么要说时为 None。
    reason: str | None
    #: 会话编号谁 mint："caller" = 页面先给（claude），"claimed" = 起来后认领
    #: （codex / opencode），后者新建时有一段等编号的空窗。
    id_origin: str


def _locate(agent_type: str, driver) -> tuple[bool | None, str | None]:  # noqa: ANN001
    """这一家装没装、装在哪。探测抛异常一律当"判不出"，NEVER 让它把整份清单打死。"""
    if driver.locate is None:
        return None, None
    try:
        path = driver.locate()
    except Exception:  # noqa: BLE001 — 一家探测失败不该让别家也列不出来
        logger.warning("探测 %s 装没装时出错，当作判不出", agent_type, exc_info=True)
        return None, None
    return path is not None, path


def _order_key(agent_type: str) -> tuple[int, str]:
    if agent_type in _PREFERRED_ORDER:
        return (_PREFERRED_ORDER.index(agent_type), "")
    return (len(_PREFERRED_ORDER), agent_type)


def list_agents() -> list[WorkbenchAgent]:
    """本机这几家 CLI 现在各是什么状况，能挑的排在前面。

    **不能挑的也在清单里。** 藏起来等于告诉人"frago 不支持它"，而真相往往只是没装。
    每一行都带着不能挑的理由，界面原样转述。
    """
    agents: list[WorkbenchAgent] = []
    for agent_type, driver in registered_drivers().items():
        installed, path = _locate(agent_type, driver)
        family = FAMILY_BY_AGENT_TYPE.get(agent_type)

        if family is None:
            selectable, reason = False, _NOT_READABLE
        elif installed is False:
            selectable, reason = False, _NOT_INSTALLED
        elif installed is None:
            # 判不出装没装时**放行**：拦下来的代价是一台装了的机器用不了，而放行的
            # 代价只是没装时启动那一刻报错，pane 上看得见。话得说在明处。
            selectable, reason = True, _UNKNOWN_INSTALL
        else:
            selectable, reason = True, None

        agents.append(
            WorkbenchAgent(
                agent_type=agent_type,
                display_name=driver.display_name or agent_type,
                installed=installed,
                path=path,
                family=family,
                selectable=selectable,
                reason=reason,
                id_origin="caller" if driver.accepts_session_id else "claimed",
            )
        )

    agents.sort(key=lambda a: (not a.selectable, _order_key(a.agent_type)))
    return agents


def default_agent(agents: list[WorkbenchAgent] | None = None) -> str | None:
    """默认挑哪一家：全局配好的那个内核优先，它挑不了就退到清单里第一个能挑的。

    读不到配置不算错——那只说明这台机器还没设过内核，退到清单第一个能挑的即可。
    一家能挑的都没有时返回 None，界面据此说"本机一家都没装"，NEVER 摆一个点了必错
    的默认值。
    """
    agents = list_agents() if agents is None else agents
    selectable = [a for a in agents if a.selectable]
    if not selectable:
        return None
    try:
        from frago.init.config_manager import get_agent_core

        configured = get_agent_core()
    except Exception:  # noqa: BLE001 — 没配过 / 读不动都只是没有偏好
        configured = None
    if configured and any(a.agent_type == configured for a in selectable):
        return configured
    return selectable[0].agent_type


def require_selectable(agent_type: str) -> WorkbenchAgent:
    """取这一家，挑不了就抛 :class:`AgentUnavailable`（带上为什么）。

    在**起会话之前**拦：拦不住的话，人点完创建看到的是一场起不来的会话，或者一场
    起来了却永远不出现在左栏的会话——两种都得等上一分钟才看得出不对。
    """
    for agent in list_agents():
        if agent.agent_type == agent_type:
            if not agent.selectable:
                raise AgentUnavailable(f"{agent.display_name} 现在挑不了：{agent.reason}")
            return agent
    known = ", ".join(a.agent_type for a in list_agents()) or "<无>"
    raise AgentUnavailable(f"没有叫 {agent_type!r} 的客户端（本机认得的：{known}）")
