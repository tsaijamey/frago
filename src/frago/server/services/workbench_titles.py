"""会话页上给会话起的名字，存在服务端，盖在各家自己的标题上面。

**为什么不写回各家的档案。** 四家存标题的地方各不相同：Claude Code 往会话 jsonl 末尾追一行
``custom-title``，codex 根本不让改名，opencode 在自己的库里，CoreAgent 另有一套。往别人的
档案里写东西，那场会话此刻正开着时还会跟引擎抢同一个文件。这里只存一份「编号 → 名字」，
清单出门前盖上去，四家一个样，档案一个字不动。

**眼下只有「交接到新会话」在用它。** 交接之后左栏会并排两场说同一件事的会话，人分不清哪场
是哪场。所以交接那一刻给两场各起一个带序号的名字：原会话叫「甲 #1」，新会话叫「甲 #2」；
再从「甲 #2」交接，新的那场叫「甲 #3」，一条接力链上的序号一眼看得出先后。

分层：服务层。只碰 ``~/.frago`` 下的一个 JSON 文件，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

TITLES_FILE = Path.home() / ".frago" / "workbench_titles.json"

#: 名字最长多少字。清单标题本来就只露头一行，再长只是占盘。
MAX_TITLE_LEN = 120
#: 起序号名时，原标题最多留多少字。开口第一句当标题时常有一百字，后面再挂序号就看不见了。
BASE_LEN = 60

_NUMBERED = re.compile(r"^(?P<base>.*?)\s*#(?P<n>\d+)$")
_lock = threading.Lock()


def _read() -> dict[str, str]:
    """读不动一律当没有改过名。改名是盖在上面的一层，它坏了不该连累人看会话清单。"""
    if not TITLES_FILE.exists():
        return {}
    try:
        data = json.loads(TITLES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("会话改名表读不动，当作没改过：%s", e)
        return {}
    titles = data.get("titles") if isinstance(data, dict) else None
    if not isinstance(titles, dict):
        return {}
    return {k: v for k, v in titles.items() if isinstance(k, str) and isinstance(v, str) and v}


def _write(titles: dict[str, str]) -> None:
    """先写同目录临时文件再 ``replace``，写到一半断电不会留下半截 JSON。"""
    TITLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"titles": titles}, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=str(TITLES_FILE.parent), prefix=".workbench_titles-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, TITLES_FILE)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def load() -> dict[str, str]:
    """全部起过的名字，编号 → 名字。"""
    return _read()


def set_title(session_id: str, title: str) -> None:
    sid = session_id.strip()
    name = " ".join(title.split())[:MAX_TITLE_LEN]
    if not sid or not name:
        raise ValueError("会话编号和名字都不能是空的")
    with _lock:
        titles = _read()
        titles[sid] = name
        _write(titles)


def numbered_pair(current: str) -> tuple[str, str]:
    """交接时两场各叫什么：``(原会话的名字, 新会话的名字)``。

    原会话已经带序号（它本身就是某次交接出来的）就不动它，新会话接着往下数；没带序号就
    从 1 开始，原会话改叫 ``#1``，新会话叫 ``#2``。
    """
    text = " ".join(current.split())
    matched = _NUMBERED.match(text)
    if matched and matched.group("base").strip():
        base, n = matched.group("base").strip(), int(matched.group("n"))
        return text, f"{base} #{n + 1}"
    base = text[:BASE_LEN].rstrip() or "会话"
    if len(text) > BASE_LEN:
        base += "…"
    return f"{base} #1", f"{base} #2"
