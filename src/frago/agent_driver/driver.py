"""Agent driver contract — 单个 cli-agent 的适配契约。

所有 agent 特异性集中于此（启动命令、就绪信号、提交键、完成信号、答案抽取、
异常处理），主路径不可见，NEVER 出现 ``if agent == "claude"``。

Phase 0 spike 阶段，driver 以裸字符串 agent key（"claude" / "opencode"）注册，
不引入共享的 ``session.models.AgentType`` 枚举（补 OPENCODE/CODEX 属 Phase 2，
会触碰会话子系统，违反本轮零侵入约束）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from frago.agent_driver.tmux_session import TmuxAgentSession
    from frago.agent_driver.transcript_source import TranscriptSource
    from frago.init.profile_manager import APIProfile


@dataclass(frozen=True)
class LaunchCtx:
    """生成启动命令时可见的上下文。"""

    cwd: str
    session_id: str
    # session_id 是否已是 agent 原生的真实会话 id（无需再派生）。
    # 默认 False：调用方给的是 frago 自己的标识（如 thread_id / conv-key），driver
    # 需把它确定性映射成合法的 agent 会话 id（claude 走 uuid5）。
    # True：调用方（如 WebUI 续接一个已存在的 claude 会话）给的就是真实 id，driver
    # 原样使用、跳过派生，否则会另起新会话、写进别的 jsonl，续不上原会话。
    native_session_id: bool = False


@dataclass(frozen=True)
class PaneMatcher:
    """判定一块 pane 文本是否命中某状态（就绪 / 完成）。

    ``pattern`` 是正则；``regex`` 预编译；调用 ``matches(text)`` 返回 bool。
    用正则而非固定行号/坐标，避免终端换行差异导致失配。
    """

    name: str
    pattern: str

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.MULTILINE)

    def matches(self, text: str) -> bool:
        return self.regex.search(text) is not None


@dataclass(frozen=True)
class CompletionVerdict:
    """权威完成探针的一次判定结果。

    ``done`` 为最新一轮是否答完；``text`` 是该轮最终文本（已知时），未知时为 None；
    ``marker`` 是这一轮的去重锚点（如终结记录 uuid），driver 据此判断「答完的是
    *本轮* 而非常驻会话里残留的上一轮」。

    ``status`` 是「这一轮虽然结束了，但结束得正不正常」。默认 ``ok``；探针发现本轮
    以异常方式终结（如答完却一个字都没产出——通常是鉴权失败或 provider 拒绝）时改
    成 ``needs_input`` / ``error``，上层据此把 TurnResult 标成同一档，NEVER 让一轮
    什么都没发生的对话以成功姿态返回。``done`` 为假时这个字段无意义。
    """

    done: bool
    text: str | None = None
    marker: str | None = None
    status: Literal["ok", "needs_input", "error"] = "ok"


@dataclass(frozen=True)
class ExceptionHandler:
    """启动/运行期异常的一次性处理（如更新模态 → Esc）。

    ``trigger`` 命中 pane 文本时，对 session 执行 ``action``。
    """

    name: str
    trigger: PaneMatcher
    action: Callable[[TmuxAgentSession], None]


@dataclass(frozen=True)
class AgentDriver:
    """单个 cli-agent 的适配契约。"""

    agent_type: str
    launch_command: Callable[[LaunchCtx], str]
    ready_signal: PaneMatcher
    submit: Callable[[TmuxAgentSession, str], None]
    done_signal: PaneMatcher
    extract: Callable[[str], str]
    # 给人看的名字（"Claude Code" / "Codex CLI"）。界面要列出"本机能用哪几家"时照抄
    # 这一份，NEVER 在前端再维护一张 agent_type → 显示名的表：那张表与这里的注册表
    # 一分岔，新接一家的人改完 driver 会发现界面上它仍然叫裸 key，或者干脆不出现。
    # 不填时上层退回 agent_type 本身。
    display_name: str | None = None
    # 本机装没装这一家：返回可执行文件的绝对路径，找不到返回 None。
    #
    # 探测规则是**这一家自己的知识**，故落在 driver 里：claude 要翻 nvm/fnm/volta 那
    # 一堆 Node 版本管理器的目录，codebuddy 要退回 WorkBuddy.app 里那份内嵌 CLI，
    # 都不是"PATH 里 which 一下"能覆盖的。不填时上层只能报"判不出装没装"。
    locate: Callable[[], str | None] | None = None
    # 起会话时能不能由调用方指定会话编号。
    #
    # True（claude / codebuddy）：launch 接受 ``--session-id`` 一类的开关，调用方可以
    # 先 mint 一个编号再新建，编号当场就有。
    # False（codex / opencode）：编号由 agent 自己分配，frago 只能在会话起来之后去
    # **认领**（见各 driver 的 ``_claim_once``），所以新建的那一刻拿不到编号。
    # 这两条路在"页面新建一场会话"上是两种交互，判据 MUST 出自 driver 自己。
    accepts_session_id: bool = False
    exception_handlers: list[ExceptionHandler] = field(default_factory=list)
    # 可选：直接从完成时的可见 pane 抽取本轮答案（pane, prompt）→ answer。
    # 给 claude 这类"固定底部输入框 + 答案在框上方渲染 + alt-screen 无 scrollback"
    # 的 TUI 用：通用的 pre/post delta 锚点模型对其失效。设置后 driver 跳过
    # delta+extract 路径，直接喂可见 pane。opencode/codex 不设，沿用 delta 路径。
    read_answer: Callable[[str, str], str] | None = None
    # 运行期遇到认证墙/权限门/澄清门时命中；driver 据此把本轮判为 needs_input。
    needs_input_signal: PaneMatcher | None = None
    # 可选：权威完成探针。给 claude 这类把结构化 transcript 写进 session JSONL 的
    # agent 用——从 JSONL 的 stop_reason 判「本轮是否真答完」+ 取最终文本，绕开读屏
    # 在多工具轮空窗帧的误判。入参是 session（探针自行定位/读取其 transcript），
    # 返回 CompletionVerdict；探针不可用（如 jsonl 尚未生成）时返回 None，driver
    # 当帧退回 pane done_signal。不设置时（opencode/codex）行为完全不变。
    completion_probe: Callable[[TmuxAgentSession], CompletionVerdict | None] | None = None
    # 可选：清空输入框残留文本的自愈动作，返回"确已清空"与否。给 claude 这类
    # 懒重绘 TUI 用——清行键（C-u）立即清空缓冲区，但 pane 不重绘、仍显示旧文本，
    # "发键后读屏等空输入框"的通用验证注定失败，必须由 driver 自己用结构手段
    # （探针字符强制重绘）确认缓冲区状态。不设置时上层退回通用行为（Escape +
    # 轮询 ready_signal）。
    clear_input: Callable[[TmuxAgentSession], bool] | None = None
    # 可选：该会话记录的增量读取来源。``TranscriptStreamer`` 据此 tail 出逐块的
    # 文本/工具事件喂给 attached 流式（spec 20260607 Phase 6）。
    #
    # 这里原先是 ``transcript_path``（一个返回 jsonl 路径的函数），换掉是因为那个
    # 签名把"记录 = 一个文件 + 字节偏移"写进了共用契约。它只对 claude 成立：
    # opencode 把记录存进 SQLite，既没有单一文件也没有字节偏移。改成来源对象后，
    # 记录怎么存完全是 driver 自己的事（spec 20260725 Phase 2）。
    # 返回 None 表示该 agent 没有可读的记录来源，此时 attached 不做增量流式，
    # 本轮照常跑完。
    transcript_source: (
        Callable[[TmuxAgentSession], TranscriptSource | None] | None
    ) = None
    # 可选：该 agent 起会话时自己需要的基线环境变量（与 profile 无关）。
    # ``TmuxAgentSession.open()`` 把它并进 ``new-session -e``，**调用方传入的 env
    # 优先级更高、可覆盖同名键**。给 opencode 这类"没有等价启动开关、只能靠会话级
    # 配置声明权限放行"的 agent 用：claude 靠 ``--dangerously-skip-permissions``
    # 跳过权限确认，opencode 只能经 ``OPENCODE_CONFIG_CONTENT`` 声明，不放行的话
    # 无人值守时会卡在权限询问上永不返回。不设置时行为完全不变。
    session_env: Callable[[LaunchCtx], dict[str, str]] | None = None
    # 可选：把一条 API profile 翻成该 agent 能消费的环境变量。
    # claude 产出 ``ANTHROPIC_*``，opencode 产出 ``OPENCODE_CONFIG_CONTENT``。
    # profile 语义只有一份（见 configurator.resolve_auth_style），翻译落在 driver。
    # 不设置时上层保持原有行为，NEVER 因缺这个字段报错。
    profile_env: Callable[[APIProfile], dict[str, str]] | None = None
    # 可选：把一条 profile 写进该 agent **自己的常驻配置**——也就是"激活"。
    #
    # 与 ``profile_env`` 的区别是作用域，不是内容：``profile_env`` 只影响 frago 起的
    # 那一个 tmux 会话，人手敲命令起的会话完全不受影响；``profile_apply`` 改的是这个
    # agent 下次启动就会读到的那份配置，人自己起的会话同样生效。同一条 profile 事实，
    # 两处翻译 MUST 一致，否则"激活了"和"worker 跑的"是两个模型。
    #
    # 权限放行这类**只对无人值守成立**的设置 NEVER 进这里：那是 frago 替 worker 做的
    # 取舍，写进用户全局配置等于替他把权限确认永久关掉。
    profile_apply: Callable[[APIProfile], None] | None = None
    # 可选：撤销 ``profile_apply``——把该 agent 的常驻配置还原成 frago 接管前的样子。
    # 与 apply 成对出现：只实现一半，用户就只能激活不能取消，或取消后留下半份配置。
    profile_revert: Callable[[], None] | None = None
    # 可选：说明这个 agent 为什么接不了 frago 的 profile（没有 ``profile_apply`` 时）。
    # 给人看的一句话，UI 与 CLI 原样转述。空着的话用户只会看到一个禁用的复选框而不知
    # 道为什么——那比不列出它更让人困惑。
    profile_unsupported_reason: str | None = None


_REGISTRY: dict[str, AgentDriver] = {}


def register_driver(driver: AgentDriver) -> None:
    """注册一个 driver；重复注册同 agent_type 覆盖旧值。"""
    _REGISTRY[driver.agent_type] = driver


def registered_drivers() -> dict[str, AgentDriver]:
    """已注册的全部 driver（agent_type → driver）的快照。

    "本机支持哪几家"只有这一份判据。上层要列客户端时照着它遍历，NEVER 另写一张
    名单——两张名单迟早各走各的，那时新接的一家在界面上根本不出现，而接它的人
    在 driver 侧看不出少了什么。
    """
    import frago.agent_driver.drivers  # noqa: F401 — 触发各 driver 自注册

    return dict(_REGISTRY)


def load_driver(agent_type: str) -> AgentDriver:
    """按 agent key 加载 driver；未注册抛 KeyError。"""
    # 延迟导入触发各 driver 模块自注册，避免循环依赖。
    import frago.agent_driver.drivers  # noqa: F401

    try:
        return _REGISTRY[agent_type]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(
            f"no driver registered for agent_type={agent_type!r} (known: {known})"
        ) from exc
