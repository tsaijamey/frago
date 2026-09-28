"""会话页标注（引用、暂存）的读写接口。

页面打开或切回一场会话时读一次，之后每改一次就整份交回来覆盖。存在哪、坏文件怎么办
见 :mod:`frago.server.services.workbench_marks`。
"""

from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter()


@router.get("/workbench/sessions/{sid}/marks")
async def get_session_marks(sid: str) -> dict:
    """这场会话的全部标注。还没有就是空列表。"""
    from frago.server.services.workbench_marks import load_marks
    from frago.session.record_reader import UnknownSessionFamily

    try:
        return load_marks(sid)
    except (UnknownSessionFamily, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/workbench/sessions/{sid}/marks")
async def put_session_marks(sid: str, payload: Any = Body(...)) -> dict:
    """整份覆盖。不合规矩整份拒收（400），原因照抄给页面。"""
    from frago.server.services.workbench_marks import MarksError, save_marks
    from frago.session.record_reader import UnknownSessionFamily

    try:
        return save_marks(sid, payload)
    except (UnknownSessionFamily, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarksError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
