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


def _refuse(err: Exception) -> HTTPException:
    """把本机这一侧的三类失败变成界面能照着说的一句话。

    都回 400 而不是 500：这些不是这台机器坏了，是中继那边不接受、或者本机还没配好。
    500 会让界面显示「服务器错误」，而人要看的是「对方还没加入」。
    """
    return HTTPException(status_code=400, detail=str(err))


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
