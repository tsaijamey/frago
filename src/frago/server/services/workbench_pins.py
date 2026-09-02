"""置顶会话名单：左栏那几场"随时要回来"的会话，存在服务端。

**为什么不放浏览器本地。** 同一台机器上这个页面至少有两个壳——桌面客户端（Tauri 的
webview）与浏览器，两边的 localStorage 天生不通。置顶是人一条条挑出来的东西，在桌面
客户端里挑好的十几场，换到浏览器一场都不在，这不是"没同步"，是数据丢了。名单跟着
服务端走，两个壳看到的就是同一份。

**名单里存的是会话编号，不是会话。** 会话档案随时可能被删（``claude`` 自己会滚删），
名单不去核对那场还在不在：编号留着，那场会话哪天又出现在清单里，置顶自然还在；一直
不出现就一直不显示。反过来做——发现清单里没有就把编号踢掉——会让一次超时或一次滚删
悄悄清空人的名单。

**次序就是置顶的次序，最近置顶的排在最前。** 清单其余部分按最后活动时刻倒序，置顶区
不跟：那一区的意义正是"我说了算"，让它跟着活动时刻重排等于把人刚摆好的次序打乱。

**不设上限。** 上限是替人做决定：一个人愿意置顶两百场，那两百场对他就是有用的。左栏
的渲染本来就是窗口化的，多几行不额外花什么。

分层：服务层。只碰 ``~/.frago`` 下的一个 JSON 文件，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

PINS_FILE = Path.home() / ".frago" / "workbench_pins.json"

#: 单个会话编号最长多少字符。三家里最长的是 opencode 的 ``ses_`` + 26 位，留足余量后
#: 仍然卡一道——名单是照单写盘的，不设长度上限等于让任意长的字符串进文件。
MAX_ID_LEN = 128


def _read_raw() -> list[str]:
    """把盘上那份名单读成编号列表。读不动一律当空名单。

    文件坏了就当没有置顶，NEVER 让一份读不动的 JSON 把整个左栏拖成报错——置顶是锦上
    添花的一层，它坏了不该连累人看会话清单。
    """
    if not PINS_FILE.exists():
        return []
    try:
        data = json.loads(PINS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("置顶名单读不动，当作空名单：%s", e)
        return []
    if not isinstance(data, dict):
        logger.warning("置顶名单不是预期的形状（%s），当作空名单", type(data).__name__)
        return []
    pinned = data.get("pinned")
    if not isinstance(pinned, list):
        return []
    return [item for item in pinned if isinstance(item, str) and item.strip()]


def _dedup(ids: list[str]) -> list[str]:
    """去重但保序。同一场被写进去两次时，留最靠前那一次。"""
    seen: set[str] = set()
    out: list[str] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _write(pinned: list[str]) -> None:
    """整份名单落盘。

    先写同目录下的临时文件再 ``replace``：直接覆写的话，写到一半断电留下的是半截 JSON，
    下次读出来就是"一场都没置顶"。同目录是为了让 ``replace`` 落在同一个文件系统上，
    跨设备的 rename 不是原子的。
    """
    PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pinned": pinned}, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=str(PINS_FILE.parent), prefix=".workbench_pins-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, PINS_FILE)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def list_pins() -> list[str]:
    """当前置顶的会话编号，最近置顶的在最前。"""
    return _dedup(_read_raw())


def pin(session_id: str) -> list[str]:
    """把这场会话置顶，返回置顶后的完整名单。

    已经在名单里时**挪到最前**而不是原地不动：人再点一次置顶，要的就是"把它提到我眼
    皮底下"。重复置顶报错或静默无视都答不了这个诉求。
    """
    sid = session_id.strip()
    if not sid:
        raise ValueError("会话编号不能是空的")
    if len(sid) > MAX_ID_LEN:
        raise ValueError(f"会话编号太长了（超过 {MAX_ID_LEN} 字符）")
    pinned = [existing for existing in list_pins() if existing != sid]
    pinned.insert(0, sid)
    _write(pinned)
    return pinned


def unpin(session_id: str) -> list[str]:
    """取消置顶，返回剩下的名单。

    本来就不在名单里也算成功：取消置顶要的是"结束时它不在名单里"，这个结果已经成立。
    为此回一个 404 只会让界面在双击时弹出一句没有意义的报错。
    """
    sid = session_id.strip()
    before = list_pins()
    pinned = [existing for existing in before if existing != sid]
    if pinned != before:
        _write(pinned)
    return pinned
