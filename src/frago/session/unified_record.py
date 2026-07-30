"""跨两家会话记录的统一类型（spec 20260729-session-workbench-webui Phase 1）。

Claude Code 与 opencode 各自的原始记录形状差得远，但界面只该认一种形状。这个模块
就是那一种：一条 :class:`UnifiedRecord` 等于界面上的一张卡片，十五种 :data:`RecordKind`
穷尽了两家真实数据里跑出来的全部形态。

设计上有三条不能松的口子，全都写进类型而不是写进注释：

1. **不设发言人字段** — 两家的原始类型标记都不可信。Claude Code 的用户标记里 86%
   不是人说的话（59173 条里 51002 条是工具结果、2012 条是引擎注入的伪消息，真正人
   手打的只有 4360 条），opencode 也把注入内容塞在用户侧。身份一律由 ``kind`` 的形
   态直接表达，NEVER 留二次判断的机会。
2. **顺序取物理序，不取时间戳** — Claude Code 七成会话文件存在时间戳倒挂，共 3973
   处，根因是并行工具调用落盘时调用与结果交错。``seq`` 取文件物理行序（Claude Code）
   与会话内片段序号（opencode），NEVER 按 ``ts`` 排序。
3. **报错只留三个字段** — 报错原文的响应头里带 Cloudflare 登录凭据，连原文入口都不
   给挂，所以 ``kind == "error"`` 的记录 ``raw_available`` 恒为 False，由
   :meth:`UnifiedRecord.__post_init__` 硬拦。

时间的表示：``ts`` 是毫秒整数，本身不涉及时区。一旦要落成 Python 的 ``datetime`` 或
返回 ISO 字符串，按项目约定走 naive local time，NEVER 出现 ``datetime.now(timezone.utc)``
或 ``utcnow()``，NEVER 手动拼 ``Z`` 后缀。

分层：本模块属核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, get_args

# ── 十五种形态 ──────────────────────────────────────────────────────
RecordKind = Literal[
    "user.say",  # 用户发言
    "agent.say",  # agent 回复正文
    "agent.think",  # agent 思考
    "tool.call",  # 工具调用
    "tool.result",  # 工具结果
    "subagent.dispatch",  # 子 agent 派发
    "context.inject",  # 注入内容
    "media.attach",  # 附件
    "todo.snapshot",  # 待办清单
    "permission.outcome",  # 权限结果
    "error",  # 报错
    "interrupt",  # 用户打断
    "context.compact",  # 上下文压缩
    "session.state",  # 会话状态变更
    # 第十五种是实现期补的。撤掉轮次显示时只撤了显示，两家各有一批「一次模型调用的
    # 边界标记」无处可归（opencode 的步骤开始与结束 936 条、Claude Code 的轮次耗时
    # 5324 条），照兜底塞进注入内容会把那一格淹掉，故单开一格。
    "call.envelope",  # 一次模型调用的边界
]

RECORD_KINDS: frozenset[str] = frozenset(get_args(RecordKind))
"""十五种形态的运行时集合。翻译层拿它做归类兜底的校验。"""


# ── 两家 ────────────────────────────────────────────────────────────
RecordFamily = Literal["claude-code", "opencode"]
"""会话属于哪一家。``record_reader.detect_family()`` 按会话编号的形状判定。"""

RECORD_FAMILIES: frozenset[str] = frozenset(get_args(RecordFamily))


# ── 三条纪律 ────────────────────────────────────────────────────────
ErrorScope = Literal["api", "engine", "model", "tool"]
"""报错出自哪一层。单独成名是因为本模块开了 ``from __future__ import annotations``，
   注解在运行时是字符串，取不出字面量集合。"""

ERROR_SCOPES: frozenset[str] = frozenset(get_args(ErrorScope))


@dataclass(frozen=True)
class ErrorPayload:
    """报错只留三个字段。响应头里带登录凭据，连原文入口都不给挂。"""

    scope: ErrorScope
    code: str
    message: str

TruncationState = Literal["none", "clipped", "offloaded"]
"""三值枚举不是布尔。两家都有「看着完整其实不完整」的情况：
   Claude Code 溢出转存时正文毫无提示，opencode 溢出时截断标记写的是 false。"""

TRUNCATION_STATES: frozenset[str] = frozenset(get_args(TruncationState))

ToolFamily = Literal[
    "shell",
    "file-read",
    "file-write",
    "search",
    "web",
    "agent",
    "todo",
    "ask",
    "schedule",
    "mcp",
    "other",
]
"""按大类分支，不按工具名穷举。工具名不是封闭集合，随用户配置变化。"""

TOOL_FAMILIES: frozenset[str] = frozenset(get_args(ToolFamily))


# ── 统一记录 ────────────────────────────────────────────────────────
@dataclass
class UnifiedRecord:
    """一条统一记录 = 界面上的一张卡片。

    字段名与 spec 的 Core Concepts 一节逐字对齐，NEVER 私自增删改名——服务层的
    序列化与界面的渲染都按这套名字取值。
    """

    id: str
    """全局唯一。Claude Code 取记录自带编号，opencode 取片段编号。"""

    session_id: str
    """所属会话编号。两家格式互不重叠（UUID vs ``ses_`` 前缀），已全量核对过。"""

    group_id: str | None
    """同一次模型回复的分组键。用户输入类为 None。"""

    seq: int
    """会话内权威顺序，从 0 递增。取物理序，NEVER 按 ``ts`` 排。"""

    ts: int
    """毫秒时间戳。只用于显示，不参与排序。"""

    kind: RecordKind
    """十五种形态之一。身份由它表达，不另设发言人字段。"""

    agent_path: list[str] = field(default_factory=list)
    """归属轨迹。主会话为 ``[]``，子 agent 为 ``["<子agent标识>"]``。"""

    payload: dict[str, Any] = field(default_factory=dict)
    """按 ``kind`` 而定的内容。"""

    raw_available: bool = True
    """原文能否按需取回。``error`` 类恒为 False。"""

    def __post_init__(self) -> None:
        """把三条纪律落成运行时约束。翻译层写错时当场炸，NEVER 放到界面上才发现。"""
        if self.kind not in RECORD_KINDS:
            raise ValueError(f"未知的记录形态: {self.kind!r}；十五种之外的一律不许出现")
        if self.seq < 0:
            raise ValueError(f"seq 必须从 0 起递增，收到 {self.seq}")
        if self.kind == "error" and self.raw_available:
            raise ValueError("报错类记录的原文入口恒不可用（响应头带登录凭据）")

    def is_raw_readable(self) -> bool:
        """这条记录能不能取原文。服务层据此决定放行还是 403。"""
        return self.raw_available and self.kind != "error"
