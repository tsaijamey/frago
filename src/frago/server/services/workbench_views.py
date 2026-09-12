"""每场会话你上次点开它的时刻。左栏据此判「这一场我还没回去看过」。

**判「没看过」要两个时刻。** 一个是这场会话最后一句回复的时刻（清单那条接口本来就给），
另一个是你上次点开它的时刻——只有这一个页面知道，所以记在这里。两者一比：回复比你上次
点开新，而且这场已经不在跑了，那就是"agent 说完了话、你还没回去看"。

**名单里没有的会话照样可能"没看过"。** 挡住那六百多场旧会话的是时间窗而不是这份名单：
界面只在"停下来那一刻在一小时之内"时才标（见 `useSessionViews`），旧会话停在几天前，
不会亮。所以从没点开过的新会话——比如在终端里刚谈完的那一场——也标得出来。

**存在服务端，不存浏览器本地。** 同一台机器上这个页面至少有两个壳——桌面客户端与浏览器，
两边的 localStorage 天生不通。在桌面客户端看过的那几场，换到浏览器又全成了"没看过"，
这个标记就开始说谎。置顶名单是同一个道理（见 :mod:`~frago.server.services.workbench_pins`）。

分层：服务层。只碰 ``~/.frago`` 下的一个 JSON 文件，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VIEWS_FILE = Path.home() / ".frago" / "workbench_views.json"

#: 单个会话编号最长多少字符，与置顶名单同一道线。
MAX_ID_LEN = 128

_LOCK = threading.Lock()


def _read() -> dict[str, int]:
    """盘上那份「编号 → 上次点开的毫秒时刻」。读不动一律当空名单。

    这个标记坏了只是少一个提示，NEVER 让它把整个左栏拖成报错。
    """
    if not VIEWS_FILE.exists():
        return {}
    try:
        data = json.loads(VIEWS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("会话查看记录读不动，当作一场都没看过：%s", e)
        return {}
    if not isinstance(data, dict):
        return {}
    viewed = data.get("viewed")
    if not isinstance(viewed, dict):
        return {}
    return {
        sid: int(ts)
        for sid, ts in viewed.items()
        if isinstance(sid, str) and sid.strip() and isinstance(ts, (int, float)) and ts > 0
    }


def _write(viewed: dict[str, int]) -> None:
    """整份落盘。先写同目录临时文件再 ``replace``，断电也不会留下半截 JSON。"""
    VIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"viewed": viewed}, indent=2, ensure_ascii=False, sort_keys=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(VIEWS_FILE.parent), prefix=".workbench_views-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, VIEWS_FILE)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def list_views() -> dict[str, int]:
    """每场会话你上次点开它的毫秒时刻。没点开过的不在里面。"""
    with _LOCK:
        return _read()


def mark_viewed(session_id: str, at: int | None = None) -> dict[str, Any]:
    """记下你此刻点开了这场会话，返回这一条。

    时刻由服务端取，不收页面给的：页面那边的钟可能不准，而这个时刻要和会话记录里的
    时刻相比，两边必须出自同一个钟。
    """
    sid = session_id.strip()
    if not sid:
        raise ValueError("会话编号不能是空的")
    if len(sid) > MAX_ID_LEN:
        raise ValueError(f"会话编号太长了（超过 {MAX_ID_LEN} 字符）")
    stamp = int(at if at is not None else time.time() * 1000)
    with _LOCK:
        viewed = _read()
        viewed[sid] = stamp
        _write(viewed)
    return {"session_id": sid, "viewed_at": stamp}
