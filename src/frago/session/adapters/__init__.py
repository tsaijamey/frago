"""两家会话记录翻译层的注册表（spec 20260729-session-workbench-webui Phase 1）。

``record_reader`` 判出会话属于哪一家之后，到这里按家族取翻译层，不写死 if/else。
新增一家（比如以后再接第三个 CLI）只要实现 :class:`RecordAdapter` 的两个方法再登记
进来，统一入口一个字不用改。

几家的翻译层在**第一次取用**时登记好（见 :func:`_load_builtins`），调用方 ``import``
进来直接取即可用，不需要谁先调一次初始化。取不到的家族抛 :class:`AdapterNotRegistered`，
NEVER 静默返回 None 让调用方拿着 None 往下走。

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

#: 内置的四家导过了没有。取用之前一直是 False。
_BUILTINS_LOADED = False


def _load_builtins() -> None:
    """把内置那几家登记进来：没登记过的补上，已经有的一动不动。

    为什么不在本模块被导入时就登记（2026-10-06 改）：CoreAgent 那一家的翻译层不在
    ``adapters/`` 里，而在 :mod:`frago.session.coreagent_store`——它是 Claude Code 那一份
    换个根目录，所以那个模块要在自己的模块级 ``import`` 里取 :class:`ClaudeCodeRecordAdapter`，
    而那一句会先把本模块整个跑完。本模块若反过来在末尾导入它，就成了一条回边，谁先被
    import 决定成败：先 import 本模块没事（那时 coreagent_store 还没开始跑），先 import
    ``frago.session.coreagent_store`` 就撞上「模块只初始化了一半」，报 ImportError。

    放到第一次取用的时候再导，这条回边就没了：本模块跑完时不去碰它，等真要取某一家的
    翻译层，两边都已经落地，先 import 哪个都行。

    已经登记过的那一家不覆盖。测试的写法是先 ``register_adapter`` 打桩、再 ``get_adapter``
    取用，覆盖会把刚打好的桩打掉。
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return

    from frago.session.adapters.claude_code_records import ClaudeCodeRecordAdapter
    from frago.session.adapters.codex_records import CodexRecordAdapter
    from frago.session.adapters.opencode_records import OpencodeRecordAdapter
    from frago.session.coreagent_store import CoreAgentRecordAdapter

    builtin: dict[RecordFamily, RecordAdapter] = {
        "claude-code": ClaudeCodeRecordAdapter(),
        "opencode": OpencodeRecordAdapter(),
        "codex": CodexRecordAdapter(),
        # CoreAgent 的记录形状就是 Claude Code 的形状，只是落在别处，所以这一家的翻译层
        # 是上面那一份换了个根目录，不另写判据。
        "coreagent": CoreAgentRecordAdapter(),
    }
    for family, adapter in builtin.items():
        if family not in _ADAPTERS:
            _ADAPTERS[family] = adapter
    _BUILTINS_LOADED = True


def register_adapter(family: RecordFamily, adapter: RecordAdapter) -> None:
    """登记一家的翻译层。同一家重复登记按后来者覆盖，方便测试打桩。"""
    _ADAPTERS[family] = adapter


def get_adapter(family: RecordFamily) -> RecordAdapter:
    """取某一家的翻译层。没登记过就抛，不给 None。"""
    _load_builtins()
    adapter = _ADAPTERS.get(family)
    if adapter is None:
        raise AdapterNotRegistered(f"{family} 的记录翻译层尚未登记")
    return adapter


def list_adapters() -> dict[RecordFamily, RecordAdapter]:
    """当前登记了哪几家。返回副本，外部改不动注册表。"""
    _load_builtins()
    return dict(_ADAPTERS)
