"""vibe teaming 的界面接口。

工作台的双列视图靠这几条：左边那列是本机这场会话的记录（走工作台原来那条
``/api/workbench/sessions/<编号>/records``，这里不重复一份），右边那列是对方的，
只能从中继取——所以右边这一半在这里。

**这些接口只服务本机的界面。** 它们落在 token 区（新接口的默认），也就是只有主人
够得着；对方那一侧的人从他自己那台机器上看他自己的界面，两边谁也不通过这台机器
去看对方，都通过中继。

**每一条都把活挪到接单那条线之外去做。**

这不是性能上的讲究，是能不能用的问题。本机这一侧要办的每件事，最后都要去敲中继一次，
而中继常常就住在同一个 frago 里（自己跟自己结 team，或者经 SSH 隧道把服务器那一端
映射到本地——``frago book remote-frago`` 推荐的正是后者）。活写在接单线上，这台服务端
就会在接下这一单之后去等自己回话，而它正忙着等，于是**整个服务端停止响应任何请求**，
直到二十秒后客户端先放弃。

实测过：页面上点一次「发起」，那二十秒里这台 frago 连最普通的接口都不答。命令行不会
这样，因为那是两次各自独立的请求，服务端一次只接一单——所以这个坏法只在界面上出现，
而且看起来像「中继连不上」，与真正的网络故障一个样子。

分层：路由层。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class OpenRequest(BaseModel):
    session_id: str


class JoinRequest(BaseModel):
    code: str
    session_id: str


class SendRequest(BaseModel):
    text: str
    note: str = ""


#: 一次失败属于哪一类。**界面照这个分支，NEVER 去猜那句话里的字眼。**
#:
#: 三类各自的下一步完全不同，所以必须分开：
#:
#: * ``bad_code`` —— 中继不认这个码。它对「打错了」「已作废」「位置被别的机器占了」
#:   回的是**逐字节相同**的一句话，分开说等于给猜码的人一盏指示灯，所以这一层也只给
#:   一个类别，不替它猜是哪一种。人该做的是改那串码。
#: * ``relay_down`` —— 够不着中继。跟码没关系，人该做的是等网络。
#: * ``busy`` —— 被限流挡住。人该做的是等一会儿再来。
#:
#: 从前这里只回一句话，界面要靠在中文里找「限流」「连不上中继」这几个词来分支——
#: 换个说法、翻成别的语言，判读当场失效，而且不报错，只会一律显示成同一种错。
TROUBLE_BAD_CODE = "bad_code"
TROUBLE_RELAY_DOWN = "relay_down"
TROUBLE_BUSY = "busy"


def _classify(err: Exception) -> str:
    """这次失败属于哪一类。

    判据取自本机同一份代码抛出来的那几句话（见 ``frago/team/relay.py``），不是外面
    来的文本。对不上的落到「够不着中继」——那一类的说法最不武断，给的也是「再试
    一次」，不会把人引到改码那条错路上。
    """
    said = str(err)
    if "限流" in said:
        return TROUBLE_BUSY
    if "连不上中继" in said or "看不懂" in said:
        return TROUBLE_RELAY_DOWN
    if "连接码" in said or "不可用" in said:
        return TROUBLE_BAD_CODE
    return TROUBLE_RELAY_DOWN


def _refuse(err: Exception) -> HTTPException:
    """把本机这一侧的失败变成界面能照着分支的一份答复。

    都回 400 而不是 500：这些不是这台机器坏了，是中继那边不接受、或者够不着它。
    500 会让界面显示「服务器错误」，而人要看的是「这个码用不了」。

    ``detail`` 仍然是那句话（命令行和日志照旧读它），``trouble`` 是给界面的类别。
    """
    return HTTPException(
        status_code=400,
        detail={"detail": str(err), "trouble": _classify(err)},
    )


@router.get("/team")
async def read_team_state() -> dict[str, Any]:
    """本机参加了哪些 team、中继配好了没有。不联网。

    界面第一屏就要它，所以它不能去敲中继——中继连不上时这一屏还得画得出来，
    不然人连「中继没配」这件事都看不见。
    """
    from frago.team.state import ensure_member

    state = ensure_member()
    return {
        "member": state.member,
        "configured": state.relay.configured(),
        "relay_url": state.relay.url,
        "prefix": state.prefix,
        "interval_seconds": state.interval_seconds,
        "teams": [
            {
                "code": one.code,
                "session_id": one.session_id,
                "side": one.side,
                "active": one.active,
                "pushed_seq": one.pushed_seq,
            }
            for one in state.teams.values()
        ],
    }


@router.post("/team/open")
async def open_team(request: OpenRequest) -> dict[str, Any]:
    """发起一个 team，返回连接码。"""
    from frago.team import sync as team_sync
    from frago.team.state import load_state

    state = load_state()
    try:
        binding = await asyncio.to_thread(team_sync.open_team, state, request.session_id)
    except Exception as err:  # noqa: BLE001
        raise _refuse(err) from err
    return {"code": binding.code, "side": binding.side}


@router.post("/team/join")
async def join_team(request: JoinRequest) -> dict[str, Any]:
    """用连接码加入。"""
    from frago.team import sync as team_sync
    from frago.team.state import load_state

    state = load_state()
    try:
        binding = await asyncio.to_thread(
            team_sync.join_team, state, request.code, request.session_id
        )
    except Exception as err:  # noqa: BLE001
        raise _refuse(err) from err
    return {"code": binding.code, "side": binding.side}


@router.post("/team/{code}/leave")
async def leave_team(code: str) -> dict[str, Any]:
    from frago.team import sync as team_sync
    from frago.team.state import load_state

    state = load_state()
    try:
        await asyncio.to_thread(team_sync.leave_team, state, code)
    except Exception as err:  # noqa: BLE001
        raise _refuse(err) from err
    return {"left": code}


@router.get("/team/{code}/status")
async def team_status(code: str) -> dict[str, Any]:
    from frago.team import sync as team_sync
    from frago.team.state import load_state

    state = load_state()
    try:
        return await asyncio.to_thread(team_sync.team_status, state, code)
    except Exception as err:  # noqa: BLE001
        raise _refuse(err) from err


@router.get("/team/{code}/records")
async def peer_records(code: str, limit: int = 80, after_seq: int | None = None) -> dict[str, Any]:
    """右边那一列：对方会话的记录。

    形状与工作台左边那列一样（同一种统一记录），所以界面能拿同一个卡片组件去画
    两边——这是双列视图成立的前提，不是巧合：两家会话的记录在进入界面之前就已经
    被翻译成同一种形状了。
    """
    from frago.team import sync as team_sync
    from frago.team.state import load_state

    state = load_state()
    try:
        records = await asyncio.to_thread(
            team_sync.peer_records, state, code, limit, after_seq
        )
    except Exception as err:  # noqa: BLE001
        raise _refuse(err) from err
    return {"records": records}


@router.post("/team/{code}/send")
async def send_to_peer(code: str, request: SendRequest) -> dict[str, Any]:
    """往对方的会话投一条消息。"""
    from frago.team import sync as team_sync
    from frago.team.state import load_state

    state = load_state()
    try:
        await asyncio.to_thread(
            team_sync.send_to_peer, state, code, request.text, request.note
        )
    except Exception as err:  # noqa: BLE001
        raise _refuse(err) from err
    return {"sent": True}
