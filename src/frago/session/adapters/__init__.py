"""两家会话记录翻译层的注册表（spec 20260729-session-workbench-webui Phase 1）。

``record_reader`` 判出会话属于哪一家之后，到这里按家族取翻译层，不写死 if/else。
新增一家（比如以后再接第三个 CLI）只要实现 :class:`RecordAdapter` 的两个方法再登记
进来，统一入口一个字不用改。

两家的翻译层在本模块被导入时就登记好（见文件末尾），调用方 ``import`` 进来即可用，
不需要谁先调一次初始化。取不到的家族抛 :class:`AdapterNotRegistered`，NEVER 静默返回
None 让调用方拿着 None 往下走。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from frago.session.unified_record import RecordFamily, UnifiedRecord

__all__ = [
    "AdapterNotRegistered",
    "RecordAdapter",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]


class AdapterNotRegistered(LookupError):
    """要的那一家还没有翻译层。"""


@runtime_checkable
class RecordAdapter(Protocol):
    """一家的翻译层要提供的能力。两家各实现一份，形状必须一致。"""

    def to_unified(
        self, session_id: str, after: int, limit: int, tail: bool = False
    ) -> list[UnifiedRecord]:
        """把这场会话从 ``after`` 起的原始记录翻成统一记录。

        ``after`` 是**本批第一条的 ``seq``，闭区间起点**：``after=0`` 从头取，第一条
        的 ``seq`` 就是 0；下一批传上一批末条的 ``seq`` 加一。NEVER 做成「上一批最后
        一条」那种排他游标——默认值 0 会把第 0 条吃掉，而会话的第 0 条通常正是用户
        开口那句。

        ``after`` 不是绝对下标：会话被重新解析后 ``seq`` 可能变，界面拿着过期的游标
        只会错位，过期时从 0 重拉。

        ``tail=True`` 时忽略 ``after``，取整场**最后** ``limit`` 条——中栏打开会话要
        直接落在最新内容上，从头一页页翻到尾会把大会话整个塞进浏览器。
        """
        ...

    def read_raw(self, session_id: str, record_id: str) -> dict[str, Any] | None:
        """取单条记录的原文。取不到返回 None，NEVER 抛。"""
        ...


_ADAPTERS: dict[RecordFamily, RecordAdapter] = {}


def register_adapter(family: RecordFamily, adapter: RecordAdapter) -> None:
    """登记一家的翻译层。同一家重复登记按后来者覆盖，方便测试打桩。"""
    _ADAPTERS[family] = adapter


def get_adapter(family: RecordFamily) -> RecordAdapter:
    """取某一家的翻译层。没登记过就抛，不给 None。"""
    adapter = _ADAPTERS.get(family)
    if adapter is None:
        raise AdapterNotRegistered(f"{family} 的记录翻译层尚未登记")
    return adapter


def list_adapters() -> dict[RecordFamily, RecordAdapter]:
    """当前登记了哪几家。返回副本，外部改不动注册表。"""
    return dict(_ADAPTERS)


# ── 两家就位 ────────────────────────────────────────────────────────
# 放在文件末尾是因为两家的翻译层要 import 上面的协议之外的东西时会绕回本模块；
# 定义全部落地之后再导入，循环引用就不可能发生。
from frago.session.adapters.claude_code_records import (  # noqa: E402
    ClaudeCodeRecordAdapter,
)
from frago.session.adapters.opencode_records import OpencodeRecordAdapter  # noqa: E402

register_adapter("claude-code", ClaudeCodeRecordAdapter())
register_adapter("opencode", OpencodeRecordAdapter())
