"""中继那台上，此刻谁挂着一条长连接。

一台机器接上中继之后挂上一条长连接。这条连接**不办业务**：推记录、取消息、投消息
仍旧走 ``POST /api/teaming`` 那扇门，落在配方里。它存在的唯一理由是让中继在对面有
动静的时候，能当场喊一声。

没有它的时候，结对的两个人各自跑一条每十五秒一趟的循环，谁有新东西都要等对面下一趟
来取——一句话从这里发出去，到对面落进会话，要等十几秒。有它之后，中继在办完一次
``push`` 或 ``send`` 时朝对面喊一声，对面立刻来取。

**通知只是「快一点」，不是「送达」。** 对面取的东西与轮询取的是同一份，都在配方
那个信箱里，所以这条连接断了、或者对面压根是旧版没连过，一条消息也不丢——只是慢回
那十五秒。这也是旧客户端不用改就能继续用的原因：它们在的时候，这一层等于不存在。

**在线表只住在这一层的内存里。** 它说的是「这台机器此刻有哪些连接」，不是 team 的
档案——谁跟谁结对、信箱里积了什么，仍旧只有配方那一份。因此服务端重启丢掉的只是
「谁在线」，下一次连上就补回来，没有任何东西需要落盘。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

#: 一条连接的投递口：给它一份 JSON，它送到对面那条 WebSocket 上。
Sink = Callable[[dict[str, Any]], Awaitable[None]]


class TeamPresence:
    """哪些 team 的哪一侧现在挂着长连接。

    一个连接码底下最多两条（A 一侧、B 一侧）。同一侧重复连上时后到的顶掉先到的：
    一台机器重启之后，旧的连接在服务端这边往往还要过一会儿才会被察觉已经断了，
    新连接必须立刻生效，否则通知会继续投给那个已经没人读的旧口子上，而那台机器
    正等着——看起来就是「连上了还是慢」。
    """

    _instance: TeamPresence | None = None

    def __init__(self) -> None:
        self._links: dict[str, dict[str, Sink]] = {}

    @classmethod
    def get_instance(cls) -> TeamPresence:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """丢掉这张表。测试之间要清干净，免得一个用例的残留影响下一个。"""
        cls._instance = None

    def attach(self, code: str, side: str, sink: Sink) -> None:
        self._links.setdefault(code, {})[side] = sink

    def detach(self, code: str, side: str, sink: Sink) -> None:
        """摘掉这一条。

        ``sink`` 必须比对：一条旧连接断开时，它可能已经被同侧的新连接顶掉了，
        这时候不能顺手把新那条也摘了——那台机器会一直挂着连接却收不到通知。
        """
        sides = self._links.get(code)
        if not sides:
            return
        if sides.get(side) is sink:
            sides.pop(side, None)
        if not sides:
            self._links.pop(code, None)

    def online_sides(self, code: str) -> list[str]:
        return sorted(self._links.get(code, {}))

    async def notify(self, code: str, side: str, payload: dict[str, Any]) -> bool:
        """给这一侧发一条通知。没人在线返回 False，**这不是失败**。

        对面不在线是常态：人关了机器、断了网、或者还在用没这条连接的旧版。通知本
        就是「快一点」，送不出去就当这一侧下一趟轮询自己取。
        """
        sink = self._links.get(code, {}).get(side)
        if sink is None:
            return False
        try:
            await sink(payload)
        except Exception:  # noqa: BLE001 — 一条连接发不出去，不该影响这次请求本身
            logger.debug("teaming：通知 %s 的 %s 侧没发出去", code, side, exc_info=True)
            return False
        return True
