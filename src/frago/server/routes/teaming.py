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

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

#: 中继那张配方叫什么。这一层不认识它的数据，只认识它的名字。
RELAY_RECIPE = "vibe_teaming_relay"

#: 这扇门收哪几个动作。封闭清单，不是转发一切——把 ``mode`` 原样递给配方，等于让
#: 外面的人挑这台机器上那张配方的任何一个入口。
ACTIONS = frozenset({"open", "join", "push", "pull", "peer", "status", "leave"})

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
        # 配方自己说不行。它对「码不对 / 你是第三台机器」回的就是那个统一的拒绝，
        # 这里照着翻成同一个 404。
        return _no_such_team()
    if not isinstance(data, dict):
        return _no_such_team()
    if data.get("refused"):
        return _no_such_team()

    return JSONResponse(status_code=200, content=data)
