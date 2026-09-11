"""右栏读槽位的接口。

页面打开一场会话、或者切回来时读这一份——不靠离开期间收到的推送，推送只给正在看的人。
槽位怎么填出来的见 :mod:`frago.server.services.session_observer`。
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/workbench/sessions/{sid}/observer")
async def get_session_observer(sid: str) -> dict:
    """这场会话右栏此刻的五格，外加旁路 AI 绑没绑、上一次问得怎么样。"""
    from frago.server.services.session_observer import load_public_state
    from frago.session.record_reader import UnknownSessionFamily

    try:
        return load_public_state(sid)
    except UnknownSessionFamily as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
