"""「今天捡回来用」名单：`timeline 里把旧会话 add to today`，左栏当天留着它。

左栏的口径是**今天有过真正回复的会话**。一场昨天晚上 23:59:59 说过话的会话，今天早上打开
页面就不该再占着位置——人今天要看的是今天动过的东西。可是有些旧会话今天还要接着用，人
从 timeline 里把它捡回来，它得在左栏待着。

**只记「哪天捡的」，不记「要不要留」。** 名单里一条 = 编号 + 捡起那天（本地日期）。取名单
时只认日期等于今天的那几条：第二天它自然就不在名单里了，不需要定时任务去清。人第二天真的
又在里面说了话，那它因为**今天有回复**进清单，与这份名单无关——这也正是要的效果：捡回来
只是给它一天的位置，留得住留不住看它当天有没有真动静。

**存服务端，不存浏览器本地。** 与置顶、查看记录同一个理由：页面在多个浏览器、多台设备上
打开，localStorage 天生不通。今天在这台机器上捡回来的会话，换一台打开就没了，这不叫临时，
叫丢数据。见 :mod:`~frago.server.services.workbench_pins`。

**过期的条目在写盘时顺手丢掉。** 读的一侧已经按日期筛过，盘上留几条旧记录不影响任何显示；
但一直不写的话旧记录会越积越多。每次 pick/unpick 落盘前只留今天的，文件大小始终是"今天
捡回来的那几场"。

分层：服务层。只碰 ``~/.frago`` 下的一个 JSON 文件，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TODAY_FILE = Path.home() / ".frago" / "workbench_today.json"

#: 单个会话编号最长多少字符，与置顶名单同一道线。
MAX_ID_LEN = 128

_LOCK = threading.Lock()


def _today(at: float | None = None) -> str:
    """本地日期 ``YYYY-MM-DD``。

    「今天」按跑服务这台机器的本地日历算，不按 UTC：人夜里 23:59 说的话，在他眼里就是今天
    说的，换算成 UTC 可能已经算到明天去了。这里取秒级时刻，测试可以传一个固定值进来。
    """
    moment = datetime.fromtimestamp(at if at is not None else time.time())
    return moment.date().isoformat()


def _read() -> dict[str, str]:
    """盘上那份「编号 → 捡起它的本地日期」。读不动一律当空名单。

    这份名单坏了，最坏的后果是今天捡回来的几场暂时不显示——NEVER 让它把左栏拖成报错。
    """
    if not TODAY_FILE.exists():
        return {}
    try:
        data = json.loads(TODAY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("今天名单读不动，当作一场都没捡：%s", e)
        return {}
    if not isinstance(data, dict):
        return {}
    picked = data.get("picked")
    if not isinstance(picked, dict):
        return {}
    out: dict[str, str] = {}
    for sid, day in picked.items():
        if not isinstance(sid, str) or not sid.strip() or not isinstance(day, str):
            continue
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            continue
        out[sid] = parsed.isoformat()
    return out


def _write(picked: dict[str, str]) -> None:
    """整份落盘。先写同目录临时文件再 ``replace``，断电也不会留下半截 JSON。"""
    TODAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"picked": picked}, indent=2, ensure_ascii=False, sort_keys=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(TODAY_FILE.parent), prefix=".workbench_today-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, TODAY_FILE)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _todays(picked: dict[str, str], today: str) -> dict[str, str]:
    """只留这一天捡的。其余日期的不删盘、也不返回。"""
    return {sid: day for sid, day in picked.items() if day == today}


def list_picked(today: str | None = None) -> dict[str, str]:
    """今天捡回来用的会话：编号 → 捡起日期。没捡过就是空表。

    日期由调用方给（接口层不传，取服务端本地今天）。给日期是为了让测试能把"昨天捡的"
    这一格直接摆出来，不用去改系统时钟。
    """
    stamp = today or _today()
    with _LOCK:
        return _todays(_read(), stamp)


def pick(session_id: str, today: str | None = None) -> dict[str, str]:
    """把这场会话捡到今天，返回今天的完整名单。

    已经在名单里时**不改它的日期**：它本来就是今天捡的；即便盘上那条是昨天留下的
    （读的时候被筛掉了），现在捡也是记今天。
    """
    sid = session_id.strip()
    if not sid:
        raise ValueError("会话编号不能是空的")
    if len(sid) > MAX_ID_LEN:
        raise ValueError(f"会话编号太长了（超过 {MAX_ID_LEN} 字符）")
    stamp = today or _today()
    with _LOCK:
        picked = _todays(_read(), stamp)
        picked[sid] = stamp
        _write(picked)
    return dict(picked)


def unpick(session_id: str, today: str | None = None) -> dict[str, str]:
    """把这场会话从今天的名单里去掉，返回剩下的。

    本来就不在名单里也算成功——与取消置顶同一个理由：这条接口承诺的是"结束时它不在这
    份今天的名单里"，那个结果已经成立。
    """
    sid = session_id.strip()
    stamp = today or _today()
    with _LOCK:
        picked = _todays(_read(), stamp)
        picked.pop(sid, None)
        # 没有改动也落一次盘：顺手把盘上过期的条目清掉。读的一侧本来就筛过，
        # 这里只是不让文件无限长下去。
        _write(picked)
    return dict(picked)


def snapshot(today: str | None = None) -> dict[str, object]:
    """接口的对外形状：今天是哪一天，外加今天捡回来的编号。

    界面拿编号去清单里对号入座——与置顶一样只回编号，不回会话本身。编号**不与清单核对**：
    会话档案可能刚被滚删，对不上就不显示，但人捡它的这个动作不该被悄悄撤销。
    """
    stamp = today or _today()
    picked = list_picked(stamp)
    return {"today": stamp, "picked": list(picked.keys())}
