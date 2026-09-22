"""朝中继发请求。

中继是那台服务器上的 ``vibe_teaming_relay`` 配方，而两台机器都从**同一扇门**进去：
``POST /api/teaming``。那扇门不要求登录、也不要求那台服务器的 token——两个想结对的
人，手里只有一个连接码。

**连接码就是凭证。** 它不是门里的一个参数，它就是那把钥匙：发起方开一个 team，中继
记下这串码，对方拿着它就能接进来。除此之外不需要那台服务器上的任何东西。

进场之后每一侧另领一把只有自己知道的钥匙。连接码要转交给对方，转交途中可能被人看见
（贴在聊天窗口、念给人听）；钥匙不会。于是即使码泄露了，已经坐满的两个位置也顶不掉。

拒绝只有一种回答：码不对、码对但你是第三台机器、动作不在清单上——统统是同一个 404。
分开说等于给猜码的人一盏指示灯。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from frago.team.state import Relay

logger = logging.getLogger(__name__)

#: 中继那扇门在服务器上的地址。
DOOR = "/api/teaming"

#: 一次请求等多久。中继只做文件读写，正常在一秒内回来；20 秒是留给网络的。
TIMEOUT_SECONDS = 20

#: 被限流挡住时重试几次、每次退多久。
#:
#: 那扇门在任何验证之前先限流——连接码是唯一凭证，猜是唯一的攻击方式。正常的两侧
#: 每十五秒各敲一次，撞上限流通常是同一台机器上并排开了好几个 team，退一下就过去了。
BUSY_RETRIES = 4
BUSY_BACKOFF = 1.0


class RelayError(RuntimeError):
    """朝中继要东西没要到。

    话一律写成人能直接行动的样子。这条错误会出现在 agent 的屏幕上，而 agent 下一步
    做什么全看这句话说了什么。
    """


class RelayClient:
    """一个配好的中继，和一次同步里对它的全部调用。"""

    def __init__(self, relay: Relay) -> None:
        if not relay.configured():
            raise RelayError(
                "还没告诉 frago 中继在哪。跑一次："
                "frago team config --url https://中继服务器"
            )
        self._relay = relay
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": "frago-team"})

    def call(self, action: str, **params: Any) -> dict[str, Any]:
        """敲一次门，同步拿回结果。"""
        url = f"{self._relay.base()}{DOOR}"
        body = {"action": action, **params}
        for attempt in range(BUSY_RETRIES + 1):
            try:
                reply = self._http.post(url, json=body, timeout=TIMEOUT_SECONDS)
            except requests.RequestException as err:
                raise RelayError(f"连不上中继 {self._relay.base()}：{err}") from err
            if reply.status_code == 429 and attempt < BUSY_RETRIES:
                time.sleep(BUSY_BACKOFF)
                continue
            return self._unwrap(reply, action)
        raise RelayError(
            f"中继一直在限流，{action} 发不进去。"
            f"要么这台机器敲得太密，要么那边正在被人猛试连接码"
        )

    @staticmethod
    def _unwrap(reply: requests.Response, action: str) -> dict[str, Any]:
        try:
            payload = reply.json()
        except (ValueError, json.JSONDecodeError):
            payload = None

        if reply.status_code == 404:
            # 这一句要照着中继的口径说：它对「码不对」和「你是第三台机器」回的是
            # 同一个答案，本机这边也不许替它猜是哪一种——猜了就等于把那盏指示灯
            # 自己点上。
            raise RelayError(
                "这个连接码在中继上不可用。它可能打错了、已经作废了，"
                "或者两个位置已经被别的两台机器占着——中继不区分这几种，"
                "免得有人靠试错筛出活的连接码"
            )
        if reply.status_code == 429:
            raise RelayError("中继在限流，等一会儿再来")
        if reply.status_code >= 400:
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("error") or "")
            raise RelayError(
                f"中继拒绝了 {action}（HTTP {reply.status_code}）"
                + (f"：{detail}" if detail else "")
            )
        if not isinstance(payload, dict):
            raise RelayError(f"中继对 {action} 的回答看不懂：{payload!r}")
        if payload.get("refused"):
            raise RelayError(str(payload["refused"]))
        return payload
