"""vibe teaming 的那扇门：拿着连接码的机器从这里进来。

两台个人机器要隔着这台服务器互相传话，而它们手里**只有一个连接码**。没有这台机器
的 token——那是整台机器的钥匙，给了就等于把服务器交出去；也没有这台机器上的账号——
一个人装完 frago 不会为了跟朋友结对再去注册一个。所以连接码就是凭证，这扇门认的就
是它。

**这扇门不开页面。** 中继是两台机器之间的信箱，没有任何人要看它，所以它不出现在
任何人登录后的应用清单里，也没有可以打开的地址。这里只有一个接口。

三件事在这一层做完：

- **限流，在任何验证之前。** 连接码是唯一凭证，猜是唯一的攻击方式，而挡住猜的办法
  只有让猜的代价高。按来源地址一条、按连接码一条，两条叠着——只按地址算，一群机器
  分头试同一个码就漏了。跑在验证之后的计数器不叫限流。
- **把请求交给中继那张配方。** 连接码的登记、teaming 的记录、日志，全都在配方那边，
  这一层不留任何一份。这样它们才是配方的数据，别的配方声明一句就能读。
- **把拒绝统一成一个回答。** 码不存在、和「码是对的但你是第三台机器」，回的是逐字节
  相同的 404。分开就等于给猜码的人一盏指示灯：告诉他哪个码是活的。而一个已经 open
  、还没被 join 的码，是真能被抢走的。

分层：路由层。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

#: 中继那张配方叫什么。这一层不认识它的数据，只认识它的名字。
RELAY_RECIPE = "vibe_teaming_relay"

#: 这扇门收哪几个动作。封闭清单，不是转发一切——把 ``mode`` 原样递给配方，等于让
#: 外面的人挑这台机器上那张配方的任何一个入口。
#:
#: 本机那一侧（``frago/team/sync.py``）敲的每个动作都必须在这里。漏一个不会报错，只会
#: 得到上面那句「码不可用」——``send`` 就这样漏过一次：码和钥匙都对，消息一条也投不出去。
ACTIONS = frozenset({"open", "join", "push", "pull", "send", "peer", "status", "leave"})

#: 挂长连接的那扇门。与上面那扇 POST 门同一个凭证（连接码 + 指纹 + 钥匙），只是活着
#: 不走。它的路径要和安全层那张匿名白名单里的字符串一致——那里也是逐条登记的。
LIVE_PATH = "/api/teaming/ws"

#: 码不存在、和「码对但你是第三台机器」，共用这一个回答。**逐字节相同**是这条的全部
#: 意义，改动它之前先想清楚泄的是什么。
def _no_such_team() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "no_such_team",
                 "detail": "这个连接码在这台中继上不可用"},
    )


def _too_many() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "too_many", "detail": "敲得太频繁了，慢一点再来"},
    )


def _client_address(request: Request) -> str:
    """请求从哪儿来。反代后面取转发头里的第一跳。"""
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "?"


async def _live_side(code: str, fingerprint: str, secret: str) -> str | None:
    """这台机器是这个码的哪一侧；不是那两台机器之一就返回 None。

    问的还是配方：**这一层不留任何一份 team 的档案**，本机是 A 还是 B 只有配方知道。
    用的是 ``status`` 这个只读动作——它认得出指纹与钥匙，也认得出一侧已经退出。
    """
    from frago.server.services.recipe_service import RecipeService

    params = {
        "mode": "status",
        "code": code,
        "fingerprint": fingerprint,
        "secret": secret,
    }
    try:
        result = await asyncio.to_thread(
            RecipeService.run_recipe, RELAY_RECIPE, params, 60, None, False
        )
    except Exception:
        logger.warning("teaming: 验长连接时中继没跑起来", exc_info=True)
        return None
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict) or data.get("refused"):
        return None
    side = data.get("side")
    return str(side) if side in ("A", "B") else None


async def _nudge_peer(code: str, action: str, data: dict[str, Any]) -> None:
    """办完一次之后，敲一下对面那条长连接。

    敲的是「有人动了」这一句，不带内容——数据仍旧由对面自己来取，走的是同一个信箱。
    所以对面不在线、或者通知半路掉了，都不丢东西，只是慢回那十五秒。

    收件那一侧从配方这次的返回里认：``push`` 回的是发起这一侧（要通知它的对侧），
    ``send`` 回的是消息投进了谁的信箱（那就是要通知的那一侧）。
    """
    if action == "push":
        # push 回的是发起这一侧，要喊的是它对面。
        actor = str(data.get("side") or "")
        if actor not in ("A", "B"):
            return
        target = "B" if actor == "A" else "A"
    elif action == "send":
        # send 回的 delivered_to 就是消息进了谁的信箱，那正是要喊醒的那一侧。
        target = str(data.get("delivered_to") or "")
        if target not in ("A", "B"):
            return
    else:
        return

    from frago.server.services.team_presence import TeamPresence

    await TeamPresence.get_instance().notify(
        code, target, {"type": "peer_activity", "action": action}
    )


@router.post("/teaming")
async def teaming(request: Request):
    """两台机器之间的全部往来，都走这一个接口。"""
    from frago.server import identity as ident

    address = _client_address(request)
    if not ident.allow_teaming(address):
        return _too_many()

    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return _no_such_team()

    action = str(body.get("action") or "").strip()
    if action not in ACTIONS:
        # 不在清单上的动作，与「码不对」同一个回答：这扇门不向外面描述它内部有什么。
        return _no_such_team()

    code = str(body.get("code") or "").strip().upper()
    if code and not ident.allow_teaming_code(code):
        return _too_many()

    params: dict[str, Any] = {k: v for k, v in body.items() if k != "action"}
    params["mode"] = action
    params["code"] = code

    from frago.server.services.recipe_service import RecipeService

    try:
        # 挪出接单那条线。中继跑起来要读写文件、还可能被别的请求排在后面，留在这条
        # 线上会让整台服务端在这期间谁也不答——vibe teaming 的界面接口就这样卡死过。
        result = await asyncio.to_thread(
            RecipeService.run_recipe, RELAY_RECIPE, params, 60, None, False
        )
    except Exception:
        logger.warning("teaming: 中继跑不起来", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"error": "relay_down", "detail": "这台中继现在起不来"},
        )

    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(result, dict) and result.get("status") == "error":
        # 配方**跑失败了**，不是它拒绝了。「码不对 / 你是第三台机器」配方是用数据回答
        # 的（下面的 ``refused``），从不走这条路；走到这里的是参数不对、对方信箱满了、
        # 进程起不来这类事，它们都在验过码之后或者跟码无关，说出来不给猜码的人任何
        # 指示。从前这里也翻成那个 404，于是一侧的推送因为参数过大连续两个多小时起不来，
        # 两边看到的都只是「码不可用」。
        detail = str(result.get("error") or "中继处理这一下失败了")
        logger.warning("teaming: %s 失败：%s", action, detail)
        return JSONResponse(
            status_code=502,
            content={"error": "relay_failed", "detail": detail[:500]},
        )
    if not isinstance(data, dict):
        return _no_such_team()
    if data.get("refused"):
        return _no_such_team()

    # 办完这次，顺手喊一声对面。喊的是「有人动了」这一句，内容仍由对面自己来取。
    # 喊不出去不算错——对面不在线是常态，它下一趟轮询照样取得到。
    await _nudge_peer(code, action, data)

    return JSONResponse(status_code=200, content=data)


@router.websocket("/teaming/ws")
async def teaming_live(websocket: WebSocket) -> None:
    """挂着等对面动静的一条长连接。

    这条连接**不办业务**。推记录、取消息、投消息仍旧走上面那扇 POST 门，落在配方
    里；它只让中继在对面有动静时能当场喊一声，省掉「等下一趟」那最多十五秒。

    凭证与那扇门是同一套：连接码、这台机器的指纹、进场时领的那把钥匙。**都从查询
    串里来**——WebSocket 的握手没法自己设请求头，安全层也只在这一种请求上认
    ``?token=`` 这类查询串（见 ``security._presented_token``）。验不过就关掉，回的是
    与那扇门同样的沉默，不说明是码打错了、作废了、还是这一侧已经满了。

    限流照旧跑在任何验证之前：连接码是唯一凭证，猜是唯一的攻击方式，而这条连接
    挂上之后可以待很久——比一次 POST 更值得在门口拦一道。
    """
    from frago.server import identity as ident
    from frago.server.services.team_presence import TeamPresence

    address = _client_address(websocket)
    if not ident.allow_teaming(address):
        await websocket.close(code=4429)
        return

    query = websocket.query_params
    code = str(query.get("code") or "").strip().upper()
    if not code or not ident.allow_teaming_code(code):
        await websocket.close(code=4429)
        return

    side = await _live_side(
        code,
        str(query.get("fingerprint") or ""),
        str(query.get("secret") or ""),
    )
    if side is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    async def sink(payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    presence = TeamPresence.get_instance()
    presence.attach(code, side, sink)
    logger.debug("teaming：%s 的 %s 侧挂上了长连接", code, side)
    try:
        while True:
            # 上行这一版没有用途，收着只是为了察觉断开。对面发什么一律不回——
            # 这条连接没有请求-应答的语义，回了反而会让人以为它是个接口。
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 — 连接怎么断的都一样，摘掉就完了
        logger.debug("teaming：%s 的 %s 侧长连接断了", code, side, exc_info=True)
    finally:
        presence.detach(code, side, sink)
