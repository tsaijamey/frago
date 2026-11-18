"""置顶会话名单：左栏那几场"随时要回来"的会话，存在服务端。

**为什么不放浏览器本地。** 这个页面不止在一个地方打开——换一个浏览器、局域网里换一台
设备，各自的 localStorage 天生不通。置顶是人一条条挑出来的东西，在一个浏览器里挑好的
十几场，换到另一个一场都不在，这不是"没同步"，是数据丢了。名单跟着服务端走，在哪儿
打开看到的都是同一份。

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
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PINS_FILE = Path.home() / ".frago" / "workbench_pins.json"

#: 单个会话编号最长多少字符。三家里最长的是 opencode 的 ``ses_`` + 26 位，留足余量后
#: 仍然卡一道——名单是照单写盘的，不设长度上限等于让任意长的字符串进文件。
MAX_ID_LEN = 128

#: 单个文件路径最长多少字符，防止异常超长字符串写盘。
MAX_FILE_PATH_LEN = 4096

_LOCK = threading.Lock()
_WIN_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_absolute_path(path: str) -> bool:
    """判断是否为明确的系统绝对路径（POSIX `/`、Windows 盘符或 UNC `\\\\`）。"""
    return path.startswith("/") or bool(_WIN_ABS_RE.match(path)) or path.startswith("\\\\")


def normalize_file_pin_path(raw_path: str) -> str:
    """规范化文件固定路径：去首尾空白与非根末尾斜杠，并严格校验绝对路径。"""
    if not isinstance(raw_path, str):
        raise ValueError("文件路径必须是字符串")
    trimmed = raw_path.strip()
    if not trimmed:
        raise ValueError("文件路径不能是空的")
    if len(trimmed) > MAX_FILE_PATH_LEN:
        raise ValueError(f"文件路径太长了（超过 {MAX_FILE_PATH_LEN} 字符）")
    if not _is_absolute_path(trimmed):
        raise ValueError(f"仅支持固定绝对路径：{trimmed}")
    if trimmed == "/":
        return "/"
    if _WIN_ABS_RE.match(trimmed) and len(trimmed) == 3:
        return trimmed
    cleaned = trimmed.rstrip("/")
    return cleaned or "/"


def _split_recipe_app_id(raw_id: str) -> tuple[str, str | None]:
    at = raw_id.find("/")
    if at < 0:
        return raw_id, None
    return raw_id[:at], raw_id[at + 1 :] or None


def normalize_recipe_app_id(raw_id: str) -> str:
    """规范化配方 UI 标识：`<配方名>` 或 `<配方名>/<槽位>`，默认槽位收拢为 `<配方名>`。"""
    if not isinstance(raw_id, str):
        raise ValueError("配方界面标识必须是字符串")
    trimmed = raw_id.strip()
    if not trimmed:
        raise ValueError("配方界面标识不能是空的")
    if len(trimmed) > MAX_ID_LEN:
        raise ValueError(f"配方界面标识太长了（超过 {MAX_ID_LEN} 字符）")
    name, slot = _split_recipe_app_id(trimmed)
    name = name.strip()
    if not name or any(ch.isspace() for ch in name):
        raise ValueError(f"无效的配方名称：{trimmed}")
    if slot is not None:
        slot = slot.strip()
        if any(ch.isspace() for ch in slot):
            raise ValueError(f"无效的配方槽位：{trimmed}")
    if not slot or slot == "default":
        return name
    return f"{name}/{slot}"


def _dedup_ids(ids: list[str]) -> list[str]:
    """去重但保序。同一场被写进去两次时，留最靠前那一次。"""
    seen: set[str] = set()
    out: list[str] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _dedup_file_pins(raw_items: Any) -> list[dict[str, Any]]:
    """清洗并按规范化路径去重保序。"""
    if not isinstance(raw_items, list):
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        try:
            clean_path = normalize_file_pin_path(raw_path)
        except ValueError:
            continue
        if clean_path in seen:
            continue
        seen.add(clean_path)
        out.append({"path": clean_path, "is_dir": bool(item.get("is_dir", False))})
    return out


def _dedup_recipe_app_pins(raw_items: Any) -> list[str]:
    """按配方名去重保序（一个配方只占一行）。"""
    if not isinstance(raw_items, list):
        return []
    seen_names: set[str] = set()
    out: list[str] = []
    for raw_id in raw_items:
        try:
            clean_id = normalize_recipe_app_id(raw_id)
        except ValueError:
            continue
        name, _ = _split_recipe_app_id(clean_id)
        if name in seen_names:
            continue
        seen_names.add(name)
        out.append(clean_id)
    return out


def _read_state() -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """读取盘上的会话置顶、文件固定项与配方 UI 固定项。读不动一律当空名单。

    文件坏了就当没有置顶，NEVER 让一份读不动的 JSON 把整个左栏拖成报错——置顶是锦上
    添花的一层，它坏了不该连累人看会话清单。
    """
    if not PINS_FILE.exists():
        return [], [], []
    try:
        data = json.loads(PINS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("置顶名单读不动，当作空名单：%s", e)
        return [], [], []
    if not isinstance(data, dict):
        logger.warning("置顶名单不是预期的形状（%s），当作空名单", type(data).__name__)
        return [], [], []
    raw_pinned = data.get("pinned")
    pinned = (
        _dedup_ids([item for item in raw_pinned if isinstance(item, str) and item.strip()])
        if isinstance(raw_pinned, list)
        else []
    )
    file_pins = _dedup_file_pins(data.get("file_pins"))
    recipe_app_pins = _dedup_recipe_app_pins(data.get("recipe_app_pins"))
    return pinned, file_pins, recipe_app_pins


def _write_state(
    pinned: list[str],
    file_pins: list[dict[str, Any]],
    recipe_app_pins: list[str],
) -> None:
    """整份名单原子落盘。

    先写同目录下的临时文件再 ``replace``：直接覆写的话，写到一半断电留下的是半截 JSON，
    下次读出来就是"一场都没置顶"。同目录是为了让 ``replace`` 落在同一个文件系统上，
    跨设备的 rename 不是原子的。

    当 ``file_pins`` 或 ``recipe_app_pins`` 为空时省略对应键，保持与既有 ``{"pinned": [...]}``
    落盘结构 100% 向后兼容。
    """
    PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {"pinned": pinned}
    if file_pins:
        doc["file_pins"] = file_pins
    if recipe_app_pins:
        doc["recipe_app_pins"] = recipe_app_pins
    payload = json.dumps(doc, indent=2, ensure_ascii=False)
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
    with _LOCK:
        pinned, _, _ = _read_state()
        return pinned


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
    with _LOCK:
        before, file_pins, recipe_app_pins = _read_state()
        pinned = [existing for existing in before if existing != sid]
        pinned.insert(0, sid)
        _write_state(pinned, file_pins, recipe_app_pins)
        return pinned


def unpin(session_id: str) -> list[str]:
    """取消置顶，返回剩下的名单。

    本来就不在名单里也算成功：取消置顶要的是"结束时它不在名单里"，这个结果已经成立。
    为此回一个 404 只会让界面在双击时弹出一句没有意义的报错。
    """
    sid = session_id.strip()
    with _LOCK:
        before, file_pins, recipe_app_pins = _read_state()
        pinned = [existing for existing in before if existing != sid]
        if pinned != before:
            _write_state(pinned, file_pins, recipe_app_pins)
        return pinned


# ── Files 固定项（~/.frago/workbench_pins.json -> file_pins） ─────────────────


def list_file_pins() -> list[dict[str, Any]]:
    """当前固定在 Files 菜单下的目录与文件清单。"""
    with _LOCK:
        _, file_pins, _ = _read_state()
        return file_pins


def pin_file(path: str, is_dir: bool = False) -> list[dict[str, Any]]:
    """将绝对路径固定到 Files 菜单下（已存在则幂等返回原清单）。"""
    clean_path = normalize_file_pin_path(path)
    with _LOCK:
        pinned, file_pins, recipe_app_pins = _read_state()
        if any(item["path"] == clean_path for item in file_pins):
            return file_pins
        updated = [*file_pins, {"path": clean_path, "is_dir": bool(is_dir)}]
        _write_state(pinned, updated, recipe_app_pins)
        return updated


def unpin_file(path: str) -> list[dict[str, Any]]:
    """从 Files 菜单下取消固定某路径（不存在时幂等返回原清单）。"""
    if not isinstance(path, str) or not path.strip():
        return list_file_pins()
    try:
        target = normalize_file_pin_path(path)
    except ValueError:
        target = path.strip().rstrip("/") or path.strip()
    with _LOCK:
        pinned, file_pins, recipe_app_pins = _read_state()
        updated = [item for item in file_pins if item["path"] != target]
        if updated != file_pins:
            _write_state(pinned, updated, recipe_app_pins)
        return updated


def merge_file_pins(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """幂等合并一组固定文件/目录（仅保留合法绝对路径并保序去重）。"""
    cleaned = _dedup_file_pins(items)
    if not cleaned:
        return list_file_pins()
    with _LOCK:
        pinned, file_pins, recipe_app_pins = _read_state()
        existing_paths = {item["path"] for item in file_pins}
        merged = list(file_pins)
        changed = False
        for item in cleaned:
            if item["path"] in existing_paths:
                continue
            existing_paths.add(item["path"])
            merged.append(item)
            changed = True
        if changed:
            _write_state(pinned, merged, recipe_app_pins)
        return merged


# ── Recipes 已打开界面（~/.frago/workbench_pins.json -> recipe_app_pins） ─────


def list_recipe_app_pins() -> list[str]:
    """当前固定在 Recipes 菜单下的已打开配方界面列表。"""
    with _LOCK:
        _, _, recipe_app_pins = _read_state()
        return recipe_app_pins


def pin_recipe_app(app_id: str) -> tuple[str, list[str]]:
    """固定某个配方 UI：同配方已存在时返回既有条目（不新增、不覆写槽位）。"""
    clean_id = normalize_recipe_app_id(app_id)
    name, _ = _split_recipe_app_id(clean_id)
    with _LOCK:
        pinned, file_pins, recipe_app_pins = _read_state()
        for existing in recipe_app_pins:
            existing_name, _ = _split_recipe_app_id(existing)
            if existing_name == name:
                return existing, recipe_app_pins
        updated = [*recipe_app_pins, clean_id]
        _write_state(pinned, file_pins, updated)
        return clean_id, updated


def unpin_recipe_app(app_id: str) -> list[str]:
    """从 Recipes 菜单下摘掉已打开配方 UI（不存在时幂等返回原清单）。"""
    if not isinstance(app_id, str) or not app_id.strip():
        return list_recipe_app_pins()
    raw_trimmed = app_id.strip()
    try:
        clean_id = normalize_recipe_app_id(raw_trimmed)
    except ValueError:
        clean_id = raw_trimmed
    with _LOCK:
        pinned, file_pins, recipe_app_pins = _read_state()
        updated = [
            existing
            for existing in recipe_app_pins
            if existing != clean_id and existing != raw_trimmed
        ]
        if updated != recipe_app_pins:
            _write_state(pinned, file_pins, updated)
        return updated


def merge_recipe_app_pins(ids: list[str]) -> list[str]:
    """幂等合并一组配方 UI 条目（按配方名保序去重）。"""
    cleaned = _dedup_recipe_app_pins(ids)
    if not cleaned:
        return list_recipe_app_pins()
    with _LOCK:
        pinned, file_pins, recipe_app_pins = _read_state()
        existing_names = {_split_recipe_app_id(item)[0] for item in recipe_app_pins}
        merged = list(recipe_app_pins)
        changed = False
        for item in cleaned:
            name, _ = _split_recipe_app_id(item)
            if name in existing_names:
                continue
            existing_names.add(name)
            merged.append(item)
            changed = True
        if changed:
            _write_state(pinned, file_pins, merged)
        return merged
