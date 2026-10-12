"""实际用哪个内核跑这一轮 —— 偏好里那个装了就用它，没装退回自带内核。

## 为什么需要这一层

`agent_core` 是一个**偏好**，不是"这台机器上一定有的东西"。它可能指向一家这个用户压根
没装的 CLI：那样每一次不点名内核的会话都会在启动那一刻失败，报的还是驱动层的错（"没有
命令"这种），看不出根因是"你偏好了一个不存在的东西"。

页面那条路早就自愈了（`workbench_agents.default_agent()`：配的那家不可选就退到清单里
第一个能挑的）。**无界面那条一直没跟上** —— `frago agent` 和两个 HTTP 启动接口都是把
配置值原样拿去用。本模块补的就是这一句，给两条路同一份判据。

## 退回的是自带内核，不是另一家 CLI

`CoreAgent` 与 frago 同一个安装包（`~/.frago/bin/frago-core`，`frago init` 就装好），
是唯一一件**不需要用户另外装什么**的内核。退到它，最坏情况是"还没配模型连接"——那件事
有一句明确的报错，而不是一个用户看不懂的启动失败。

## 它也没装的时候不装作有

偏好和自带内核都没有时，照样把自带内核交出去，让内核后端自己去报"内核不在，跑一次
`frago init` 补上"。那句话比这里能编的任何一句都具体，NEVER 在这里替它编一个。

分层：`init/` 层。可以 import `compat` 与 `agent_driver`（后者按 `profile_manager` 的
既有做法延迟 import）。
"""

from __future__ import annotations


def built_in_core() -> str:
    """自带内核的 agent 名（与 `AgentType` 对齐，NEVER 另拼字符串）。"""
    from frago.session.models import AgentType

    return AgentType.COREAGENT.value


def kernel_installed() -> bool:
    """自带内核在这台机器上装了吗（`~/.frago/bin` 下那个二进制在不在）。"""
    try:
        from frago.init.hook_binary import get_binary_name, get_hook_deploy_dir

        return (get_hook_deploy_dir() / get_binary_name()).exists()
    except Exception:  # noqa: BLE001 — 探测不出来当作没装，退回自带内核那条路本就无副作用
        return False


def core_installed(agent_type: str) -> bool:
    """这一家内核本机装了吗。

    判据按"这一家是什么"分岔：自带内核看那个二进制；其余几家用 `compat.find_agent_cli`
    （claude 要翻 nvm/fnm/volta 那一堆目录，不是 `which` 一句话能覆盖的，那份知识住在
    `compat` 里）。**这一处是全系统"内核装没装"的唯一判据**——设置接口、CLI、启动接口
    都从这里取，NEVER 各写一份。
    """
    from frago.agent_driver.driver import runs_on_kernel

    if runs_on_kernel(agent_type):
        return kernel_installed()
    from frago.compat import find_agent_cli

    try:
        return find_agent_cli(agent_type) is not None
    except Exception:  # noqa: BLE001 — 一家探测失败不该让整轮会话起不来
        return False


def resolve_agent_core(preference: str) -> tuple[str, str | None]:
    """这一轮实际用哪个内核。返回 ``(内核, 给用户的一句说明或 None)``。

    偏好里那个装了就用它（说明为 None，无事发生）。没装退回自带内核，并给一句说明——
    "你以为在用 A、实际在用 B"这件事必须当场看得见，静默换掉和静默失败一样坏。
    """
    if core_installed(preference):
        return preference, None

    fallback = built_in_core()
    if preference == fallback:
        # 偏好就是自带内核而它也没装：照原样交给内核后端，让它报那句具体的"跑一次 frago init"。
        return fallback, None
    return fallback, f"偏好内核 {preference!r} 本机没装，这一轮改用自带内核 {fallback!r}。"
