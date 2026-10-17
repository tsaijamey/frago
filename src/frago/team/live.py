"""朝中继挂一条长连接，等它喊「对面动了」。

**这条连接不传数据。** 会话记录怎么推、消息怎么投，仍旧走原来那扇门、落在中继的
信箱里；这条连接只做一件事——让对面有动静的时候这边能立刻知道，而不是等下一趟
十五秒的循环。所以它断了不丢任何东西：退回轮询，慢一点而已。

跑在自己的线程里（``websocket-client`` 是同步的，而调用方在事件循环里，不能让
它在那儿等读）。断了按退避重连，一直连到 ``stop()`` 被叫。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from collections.abc import Callable
from urllib.parse import urlencode

import websocket

logger = logging.getLogger(__name__)

#: 长连接挂在中继的哪一扇门上。要与中继那侧 ``routes/teaming.py`` 的 ``LIVE_PATH``
#: 和本机安全层的 ``_ANON_WS`` 逐字相同。
LIVE_DOOR = "/api/teaming/ws"

#: 一次读等多久算「这条连接没动静」。中继那边 uvicorn 每二十秒发一次 ping，正常
#: 连接不会静默这么久；超过就当它死在半路了，重连一次。
READ_TIMEOUT_SECONDS = 60.0

#: 断线之后隔多久再连，以及最长隔多久。从两秒起翻倍退到一分钟——中继在重启、或者
#: 本机网络刚断，等一等就好；退避是为了别在这段时间里每秒敲一次门。
RECONNECT_MIN_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 60.0

#: 中继发来什么才算「对面动了」。
ACTIVITY_TYPE = "peer_activity"


class TeamLiveLink:
    """一个连接码、这一侧，跟中继之间的一条长连接。

    ``on_activity`` 在**这条连接自己的线程里**被叫，别在它里面做重活——它只该把
    「该同步了」这件事转交给事件循环。
    """

    def __init__(
        self,
        base: str,
        code: str,
        fingerprint: str,
        secret: str,
        on_activity: Callable[[str], None],
    ) -> None:
        self._base = base
        self._code = code
        self._fingerprint = fingerprint
        self._secret = secret
        self._on_activity = on_activity
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._link: websocket.WebSocket | None = None

    # ── 起停 ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"team-live-{self._code}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """叫停。**不等线程收工**——它可能正卡在一次读里，而调用方在事件循环里，
        停一条连接不该把整个服务端拖住。

        光设标志位不够：线程多半正堵在 ``recv()`` 上，要等有人说话才醒。喊醒它的
        办法是把这条连接关掉，读当场返回。**关掉之后仍可能在路上的一条通知不能再
        投出去**——这一侧已经退团了，收到也不会去取，白跑一轮。
        """
        self._stop.set()
        link = self._link
        if link is not None:
            with contextlib.suppress(Exception):
                link.close()

    # ── 连接 ────────────────────────────────────────────────────────────

    def url(self) -> str:
        base = self._base.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        query = urlencode(
            {
                "code": self._code,
                "fingerprint": self._fingerprint,
                "secret": self._secret,
            }
        )
        return f"{base}{LIVE_DOOR}?{query}"

    def _run(self) -> None:
        delay = RECONNECT_MIN_SECONDS
        while not self._stop.is_set():
            try:
                link = websocket.create_connection(
                    self.url(), timeout=READ_TIMEOUT_SECONDS
                )
            except Exception as err:  # noqa: BLE001 — 连不上就退避重试
                logger.debug(
                    "team %s：长连接没连上（%s），%.0f 秒后再试",
                    self._code, err, delay,
                )
                if self._stop.wait(delay):
                    return
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)
                continue

            delay = RECONNECT_MIN_SECONDS
            logger.debug("team %s：长连接挂上了", self._code)
            self._link = link
            try:
                self._listen(link)
            except Exception as err:  # noqa: BLE001
                logger.debug("team %s：长连接断了（%s）", self._code, err)
            finally:
                self._link = None
                with contextlib.suppress(Exception):
                    link.close()
            # 断开之后先歇一下再重连，别在一个一直连不上的中继上空转。
            if self._stop.wait(RECONNECT_MIN_SECONDS):
                return

    def _listen(self, link: websocket.WebSocket) -> None:
        while not self._stop.is_set():
            try:
                raw = link.recv()
            except websocket.WebSocketTimeoutException:
                # 读超时不是断线，是这段时间没人说话。中继那边的 ping 会让这条
                # 连接保持活着；真断了下一次读会抛别的错。
                continue
            if not raw:
                return
            self._deliver(raw)

    def _deliver(self, raw: str) -> None:
        # 读是被 stop() 关掉连接叫醒的时候，手上这条已经在路上了。这一侧已经退团，
        # 转出去只会让它白跑一轮同步。
        if self._stop.is_set():
            return
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or payload.get("type") != ACTIVITY_TYPE:
            return
        try:
            self._on_activity(str(payload.get("action") or ""))
        except Exception:  # noqa: BLE001 — 一次转发失败不该把这条连接带走
            logger.warning("team %s：长连接收到动静但没转出去", self._code, exc_info=True)
