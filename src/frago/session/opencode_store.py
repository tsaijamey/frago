"""opencode 会话库的只读访问层 + frago 侧身份映射。

opencode 把会话搬进了 SQLite（``~/.local/share/opencode/opencode.db``），
结构比 claude 的 JSONL 还整齐：一个用户轮次产生多条助手消息，中途每段工具
调用都带 ``finish=="tool-calls"``，末段带别的取值（``stop`` 居多，也有
``unknown`` 与干脆没有这个字段的），而同一轮的全部助手消息共享同一个指向那条
用户消息的 ``parentID``；每段写完那一刻都会补上 ``time.completed``。轮次边界与
完成时刻因此都是结构化可判的，NEVER 需要从屏幕上刮。

**这个库有两套表，本模块两套都认**（2026-10-09 补）：

- 1.18 及以前：会话在 ``session``，消息在 ``message``（``parentID`` 圈定轮次），
  片段在独立的 ``part`` 表，靠 ``part.message_id`` 挂回消息。
- 2.0 起：会话在 ``session_v2``，消息在 ``session_message``（``seq`` 定序，
  轮次边界改为「最后一条 user 之后的那批 assistant」），**片段不再单独成表**，
  而是嵌在消息 ``data.content`` 数组里；工具片段的字段也跟着改了名
  （``tool``→``name``、``state.output``→``state.content``）。

判断用哪一套只看**这场会话住在哪张表**，不看 opencode 版本号：升级当天库里两套
并存，旧会话仍在旧表里，混着读才是对的。缺哪张表就当哪套不存在。

两套表都读不出来时一律返回 None / 空——不许因为新版本多了一张表就让旧机器报错。

放在 ``session/`` 是分层要求（spec 20260725 Phase 1）：驱动层与会话子系统都
要读这个库，而 ``session/`` 禁止依赖 ``agent_driver/``，所以只能落在下层由
``agent_driver`` 正向依赖。

硬约束：
- 打开数据库 MUST 只读（``mode=ro``），NEVER 执行任何写语句。opencode 正在跑
  时持有该库，读失败当次返回 None / 空即可，NEVER 重试风暴。
- 库不存在 / 会话不存在 / 内容损坏一律返回 None，NEVER 向调用方抛。
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session.engine_cli import run_engine_command

logger = logging.getLogger(__name__)

# opencode 的会话库默认位置。测试经 ``FRAGO_OPENCODE_DB`` 指向临时库。
DEFAULT_DB_PATH = Path.home() / ".local/share/opencode/opencode.db"

# frago 侧的身份映射文件：frago 会话标识 → opencode 原生会话 id。
# 设备本地运行时产物（对端机器上的 opencode 会话 id 无意义），已列进
# ``frago-home-gitignore.template``，不跨设备同步。
BINDINGS_PATH = Path.home() / ".frago" / "opencode-sessions.json"

# 唯一表示"后面还有下一段"的结束标记。一条助手消息带 ``time.completed`` 就说明这
# 一段已经写完了，而这一段是不是**本轮的最后一段**，只看它是不是工具调用段。
#
# 判据 MUST 是黑名单而不是白名单。真实会话库里助手消息的结束标记分布：``stop`` 61
# 条、``tool-calls`` 172 条、无该字段 6 条、``unknown`` 1 条——后两类同样全部带完成
# 时刻，即同样已经结束。按白名单只认 ``stop`` 时它们被判成"没答完"，本轮一路空等到
# 超时（现场：一轮跑满 300 秒，而库里那条消息早就写完了）。结束标记随 provider 与
# 模型变，白名单永远追不完；``tool-calls`` 才是那个含义明确、必须排除的取值。
FINISH_CONTINUES = "tool-calls"

# 归档同步侧仍在用的"正常收尾"取值。NEVER 拿它当轮次完成判据（见上）。
FINISH_DONE = "stop"

# 助手消息下要保留的片段类型。``reasoning``（思考）与工具类片段一律丢弃。
_TEXT_PART_TYPE = "text"


@dataclass(frozen=True)
class OpencodeTurn:
    """从 opencode 会话库读出的一轮结果。"""

    parent_id: str
    """本轮那条 user 消息的 id；同轮助手消息全部指向它。"""

    final_message_id: str | None
    """本轮终结那条助手消息的 id；本轮未答完时为 None。"""

    done: bool
    """本轮存在"带完成时刻且不是工具调用段"的助手消息时为真。"""

    text: str
    """本轮全部助手消息的 text 片段按时间升序聚合。"""

    completed_at: int | None
    """终结那条消息的 ``time.completed``（毫秒）；未答完时为 None。"""


def db_path() -> Path:
    """会话库路径。``FRAGO_OPENCODE_DB`` 覆盖（单测据此指向临时库）。"""
    override = os.environ.get("FRAGO_OPENCODE_DB")
    return Path(override) if override else DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection | None:
    """只读打开会话库。库不存在 / 打不开返回 None，NEVER 抛。"""
    path = db_path()
    if not path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.debug("opencode db open failed: %s", exc)
        return None


def _loads(raw: Any) -> dict[str, Any]:
    """把 ``data`` 列的 JSON 文本解析成字典；损坏时当空字典。"""
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ── 两套表的探测与 v2 读取原语 ──────────────────────────────────────
# 1.18 的表名 / 2.0 的表名。两套并存于升级当天的库里，故按"这场会话住在哪张表"
# 分流，而不是按版本号一刀切。
_LEGACY_SESSION_TABLE = "session"
_LEGACY_MESSAGE_TABLE = "message"
_LEGACY_PART_TABLE = "part"
_V2_SESSION_TABLE = "session_v2"
_V2_MESSAGE_TABLE = "session_message"

# 会话分流结果。``None`` 表示两张表里都没有这场会话。
KIND_V2 = "v2"
KIND_LEGACY = "legacy"


def _table_names(conn: sqlite3.Connection) -> frozenset[str] | None:
    """库里现存的表名；读不动（打不开 / 文件损坏）时返回 None。

    返回 ``None`` 与返回空集合是两回事，调用方 MUST 分开处理：空集合是"读到了，
    这个库里一张表都没有"，``None`` 是"根本没读成"。存在性问句在后者上必须保守
    答"在"——一次读失败不等于会话被删了，混成同一个值就会把好绑定清掉。
    """
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode table listing failed: %s", exc)
        return None
    return frozenset(str(row[0]) for row in rows if row and row[0])


def _session_kind(conn: sqlite3.Connection, session_id: str) -> str | None:
    """这场会话住在哪套表里；两套都没有返回 None。

    先问 v2：新会话一律进 v2，先问它能把常见情形压到一次查询。库读不动时同样
    返回 None，由调用方按各自的语义兜底（存在性问句保守答"在"，内容问句答"没有"）。
    """
    names = _table_names(conn)
    if names is None:
        return None
    for table, kind in (
        (_V2_SESSION_TABLE, KIND_V2),
        (_LEGACY_SESSION_TABLE, KIND_LEGACY),
    ):
        if table not in names:
            continue
        try:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1",  # noqa: S608 - 表名是常量
                (session_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.debug("opencode session kind probe failed: %s", exc)
            return None
        if row:
            return kind
    return None


def _v2_rows(conn: sqlite3.Connection, session_id: str) -> list[tuple[str, str, dict]]:
    """该会话的 v2 消息，按 ``seq`` 升序：``(message_id, type, data)``。

    ``type`` 取 ``user`` / ``assistant`` / ``idle`` / ``synthetic`` / ``system``。
    2.0 的消息不带 ``parentID``，轮次边界由次序决定（见 :func:`_v2_latest_turn`）。
    """
    rows = conn.execute(
        "SELECT id, type, data FROM session_message WHERE session_id = ? "
        "ORDER BY seq ASC, time_created ASC, id ASC",
        (session_id,),
    ).fetchall()
    return [(str(mid), str(mtype or ""), _loads(raw)) for mid, mtype, raw in rows]


def _v2_is_synthetic(mtype: str, data: dict[str, Any]) -> bool:
    """这条消息是不是 opencode 自己注入的编辑器上下文（不是人打的字）。

    1.18 把这件事标在片段上（``part.synthetic``），2.0 提到消息层（``type``）。
    两处都要认，否则注入回显会被当成真人提问混进归档。
    """
    return mtype == "synthetic" or bool(data.get("synthetic"))


def _v2_content(data: dict[str, Any]) -> list[dict[str, Any]]:
    """消息里嵌的片段数组。空 / 形状不对当空数组。"""
    content = data.get("content")
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, dict)]


_V2_TOOL_TEXT_JOIN = "\n"


def _v2_normalize_part(part: dict[str, Any], mtype: str) -> dict[str, Any]:
    """把 v2 的片段字段名翻成 1.18 的那一套，下游规则因此只需一份。

    两处改名：工具名在 v2 叫 ``name``（1.18 叫 ``tool``）；工具产出在 v2 是
    ``state.content`` 的富文本数组（1.18 是 ``state.output`` 的字符串）。外加
    ``synthetic`` 的落点从片段搬到消息类型上，这里补回去——``part_payloads``
    只认片段上那个字段。
    """
    out = dict(part)
    if mtype == "synthetic":
        out["synthetic"] = True
    if out.get("type") == "tool":
        if "tool" not in out and isinstance(out.get("name"), str):
            out["tool"] = out["name"]
        if "callID" not in out and isinstance(out.get("id"), str):
            out["callID"] = out["id"]
        state = out.get("state")
        if isinstance(state, dict) and "output" not in state:
            state = dict(state)
            content = state.get("content")
            if isinstance(content, list):
                state["output"] = _V2_TOOL_TEXT_JOIN.join(
                    str(entry.get("text", ""))
                    for entry in content
                    if isinstance(entry, dict) and entry.get("type") == "text"
                )
            out["state"] = state
    return out


def _v2_user_text_part(mtype: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """用户消息的正文片段：2.0 把它挂在消息的 ``text`` 上，不在 ``content`` 里。

    只有 ``user`` 才有这一层；``system`` / ``idle`` 之类没有正文，返回空。注入的
    编辑器上下文同样从这里来，故 ``synthetic`` 要标上——下游据此整条丢弃。
    """
    if mtype != "user":
        return []
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return []
    part: dict[str, Any] = {"type": _TEXT_PART_TYPE, "text": text}
    if _v2_is_synthetic(mtype, data):
        part["synthetic"] = True
    return [part]


def _v2_part_items(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    order: str = "seq",
    since_updated: int | None = None,
) -> tuple[list[dict[str, Any]], PartCursor | None]:
    """把 v2 的嵌在消息里的片段摊成与 1.18 同形状的条目。

    ``order``：``"seq"`` 按会话次序（实时流要的），``"created"`` 按消息创建时刻
    （归档时间轴要的）。

    合成的片段 id 是 ``<消息 id>:<序号>``，序号补零到四位——归档侧按 ``(time_created,
    id)`` 排序，不补零会让第 10 段排到第 9 段前面。

    第二个返回值是**消息行**层面的最末位置（游标锚在消息上，不锚在片段上）：即使
    某条消息的片段数组是空的、一条条目都没产出，游标也照常推进，下一拍不会把同一批
    再扫一遍。
    """
    sort = (
        "time_created ASC, seq ASC, id ASC"
        if order == "created"
        else "time_updated ASC, seq ASC, id ASC"
    )
    sql = (
        "SELECT id, type, time_created, time_updated, data FROM session_message "
        "WHERE session_id = ? "
    )
    params: list[Any] = [session_id]
    if since_updated is not None:
        sql += "AND time_updated >= ? "
        params.append(since_updated)
    sql += f"ORDER BY {sort}"

    items: list[dict[str, Any]] = []
    trailing: PartCursor | None = None
    for mid, mtype, created, updated, raw in conn.execute(sql, tuple(params)).fetchall():
        data = _loads(raw)
        created_int = created if isinstance(created, int) else 0
        updated_int = updated if isinstance(updated, int) else created_int
        trailing = PartCursor(time_updated=updated_int, part_id=str(mid))
        role = "user" if mtype == "user" else "assistant"
        content = _v2_content(data)
        if not content:
            # 2.0 的**用户消息不装片段**，正文直接挂在消息的 ``text`` 上（助手消息才用
            # ``content`` 数组）。不把它补成一条 text 片段，用户说过的话在归档与搜索
            # 里一个字都不剩——会话详情页会只剩助手那半边。
            content = _v2_user_text_part(mtype, data)
        for index, part in enumerate(content):
            part_stamp = part.get("time")
            if isinstance(part_stamp, dict) and isinstance(part_stamp.get("created"), int):
                created_int_part = part_stamp["created"]
            else:
                created_int_part = created_int
            items.append(
                {
                    "part": _v2_normalize_part(part, str(mtype or "")),
                    "role": role,
                    "message_id": str(mid),
                    "time_created": created_int_part,
                    "time_updated": updated_int,
                    "part_id": f"{mid}:{index:04d}",
                }
            )
    return items, trailing


# ── 会话认领 ────────────────────────────────────────────────────────
def normalize_directory(directory: str) -> str:
    """把工作目录归一化到解析过软链接的真实路径。

    opencode 存进 ``session.directory`` 的是真实路径：macOS 上 ``/tmp`` 是指向
    ``/private/tmp`` 的软链接，tmux 会话以 ``-c /tmp/x`` 起来时 ``session.cwd``
    还是 ``/tmp/x``，而库里记的是 ``/private/tmp/x``。不归一化就精确匹配，认领
    永远落空，而且是静默落空——没有绑定 → 完成探针永远 None → 悄悄退回读屏。
    """
    try:
        return os.path.realpath(directory)
    except OSError:
        return directory


def claim_session(directory: str, since_ms: int) -> str | None:
    """认领会话：取 directory 匹配且 ``time_created >= since_ms`` 的最新一条。

    opencode 不接受"用我给的 id 建会话"，只接受"续接这个 id"，所以身份是认领
    来的而不是指定的。会话行在首轮提交那一刻才建，故时间窗从提交前一刻起算。

    目录先按真实路径查，未命中再按调用方给的原值查一次——库里理论上存的是真实
    路径，但两侧都试过才不会因为某个版本的行为差异又变成静默落空。

    两套表都问：升级当天新会话进 ``session_v2``、库里同时躺着 1.18 的旧会话，
    只问一套就会在另一套上静默落空（认不到 → 没有绑定 → 完成探针全程弃权 →
    本轮答案退回读屏）。两边各取最新一条，再比创建时刻取赢家。
    找不到返回 None（NEVER 抛）。
    """
    conn = _connect()
    if conn is None:
        return None
    candidates = [normalize_directory(directory)]
    if directory not in candidates:
        candidates.append(directory)
    names = _table_names(conn) or frozenset()
    best: tuple[int, str] | None = None
    try:
        for table in (_V2_SESSION_TABLE, _LEGACY_SESSION_TABLE):
            if table not in names:
                continue
            for candidate in candidates:
                row = conn.execute(
                    f"SELECT id, time_created FROM {table} "  # noqa: S608 - 表名是常量
                    "WHERE directory = ? AND time_created >= ? "
                    "ORDER BY time_created DESC, id DESC LIMIT 1",
                    (candidate, since_ms),
                ).fetchone()
                if not row:
                    continue
                created = row[1] if isinstance(row[1], int) else 0
                if best is None or created > best[0]:
                    best = (created, str(row[0]))
    except sqlite3.Error as exc:
        logger.debug("opencode claim_session failed: %s", exc)
        return None
    finally:
        conn.close()
    return best[1] if best else None


def session_exists(opencode_session_id: str) -> bool:
    """该会话在库里是否还在。

    库不可读时返回 True——不可读不等于不存在，NEVER 因为一次读失败就把一条好
    绑定清掉。两套表都问，任一处有就算在。
    """
    conn = _connect()
    if conn is None:
        return True
    names = _table_names(conn)
    if names is None or not names:
        # 读不动，或这个库里一张表都没有（不是一个 opencode 会话库）。两种情况都
        # 说不上"会话已被删"，保守答"在"。
        conn.close()
        return True
    try:
        for table in (_V2_SESSION_TABLE, _LEGACY_SESSION_TABLE):
            if table not in names:
                continue
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1",  # noqa: S608 - 表名是常量
                (opencode_session_id,),
            ).fetchone()
            if row:
                return True
    except sqlite3.Error as exc:
        logger.debug("opencode session_exists failed: %s", exc)
        return True
    finally:
        conn.close()
    return False


def delete_session(opencode_session_id: str) -> str:
    """叫 opencode 自己把这场会话删掉，回它吐出来的那句话。

    **这条命令是唯一一处从这个模块发起的写。** 它不由本模块的只读连接执行——那个
    连接照旧 ``mode=ro``，本模块照旧一条写语句都不发；动手的是 ``opencode session
    delete``，写它自己的库是它的事。

    不自己发 ``DELETE`` 的理由在 :mod:`frago.session.engine_cli`：这个库默认不强制
    外键，漏删的子表不报错，事件流水的序列号对不上时坏的是 opencode 自己的同步，
    而这些在界面上都表现为「删干净了」。

    "本机已经没有了"这条**不在这里判**，判据在上游的 ``session_exists``；走到这儿
    还失败就是真失败，如实抛。
    """
    return run_engine_command("opencode", ["session", "delete", opencode_session_id]).output


def session_directory(opencode_session_id: str) -> str | None:
    """该会话当初跑在哪个目录。会话不在库里 / 库读不出来 / 没记目录时返回 None。

    续接一场已有会话时要用它起 tmux：``opencode -s <id>`` 本身不带目录，进程的工作
    目录就是 tmux 起会话时给的那个。给错了续接照样成功，但 agent 看到的是另一个
    仓库——比起不了还难发现，所以调用方 MUST 拿这个目录去起会话。

    与 ``session_exists`` 分工：那个回答"还在不在"（库读不出来时保守答"在"），这个
    回答"在哪儿"（读不出来就是不知道）。两者 NEVER 合并成一个返回值。
    """
    conn = _connect()
    if conn is None:
        return None
    names = _table_names(conn) or frozenset()
    row = None
    try:
        for table in (_V2_SESSION_TABLE, _LEGACY_SESSION_TABLE):
            if table not in names:
                continue
            row = conn.execute(
                f"SELECT directory FROM {table} WHERE id = ? LIMIT 1",  # noqa: S608
                (opencode_session_id,),
            ).fetchone()
            if row:
                break
    except sqlite3.Error as exc:
        logger.debug("opencode session_directory failed: %s", exc)
        return None
    finally:
        conn.close()
    if not row:
        return None
    return str(row[0]) if isinstance(row[0], str) and row[0] else None


# ── 本轮完成判定 ────────────────────────────────────────────────────
def _v2_turn_text(turn: list[tuple[str, dict[str, Any]]]) -> str:
    """聚合这批 v2 助手消息里嵌的 text 片段，按消息次序拼接。

    规则与 1.18 那条路一致：``reasoning``（思考）与工具片段一律丢弃；
    ``synthetic`` 是 opencode 自己注入的编辑器上下文，也不是答案。
    """
    chunks: list[str] = []
    for _mid, data in turn:
        for part in _v2_content(data):
            if part.get("type") != _TEXT_PART_TYPE:
                continue
            if part.get("synthetic"):
                continue
            piece = part.get("text")
            if isinstance(piece, str) and piece.strip():
                chunks.append(piece.strip())
    return "\n".join(chunks).strip()


def _v2_latest_turn(conn: sqlite3.Connection, session_id: str) -> OpencodeTurn | None:
    """2.0 会话的本轮判定。

    轮次边界从 ``parentID`` 改由**次序**推出：最后一条真人打的 ``user`` 消息是锚点，
    它之后（下一个 ``user`` 之前）的 ``assistant`` 消息属于本轮。``synthetic`` 的
    user 消息是 opencode 自己注入的编辑器上下文，不当锚点——它一旦落在真人提问之后，
    拿它当锚点会让本轮一条助手消息都圈不到，本轮就永远判不出答完。
    """
    rows = _v2_rows(conn, session_id)
    anchor: int | None = None
    for index, (_mid, mtype, data) in enumerate(rows):
        if mtype == "user" and not _v2_is_synthetic(mtype, data):
            anchor = index
    if anchor is None:
        return None

    parent_id = rows[anchor][0]
    turn = [(mid, data) for mid, mtype, data in rows[anchor + 1 :] if mtype == "assistant"]

    final_message_id: str | None = None
    completed_at: int | None = None
    for mid, data in turn:
        stamp = (data.get("time") or {}).get("completed")
        if not isinstance(stamp, int):
            # 还在写：正在流式生成的那条消息没有完成时刻。
            continue
        if data.get("finish") == FINISH_CONTINUES:
            # 工具调用段：这一段确实写完了，但后面还有下一段。
            continue
        final_message_id = mid
        completed_at = stamp

    return OpencodeTurn(
        parent_id=parent_id,
        final_message_id=final_message_id,
        done=final_message_id is not None,
        text=_v2_turn_text(turn),
        completed_at=completed_at,
    )


def latest_turn(opencode_session_id: str) -> OpencodeTurn | None:
    """读该会话最新一轮。轮次范围以 ``parentID`` 圈定，NEVER 靠时间猜。

    最新一条 ``role=="user"`` 的消息是本轮锚点；本轮的助手消息是全部
    ``parentID`` 指向它的消息。``done`` 的判据是本轮存在**带完成时刻、且结束标记不是
    ``tool-calls``** 的助手消息：完成时刻是"这一段写完了"的结构化证据，
    ``tool-calls`` 是唯一表示"后面还有下一段"的取值（理由见 ``FINISH_CONTINUES``）。
    库不存在 / 会话不存在 / 读失败一律返回 None。

    2.0 的会话在 :func:`_v2_latest_turn` 里单独走一遍：那套表没有 ``parentID``，
    轮次边界改由 ``seq`` 次序推出，片段也嵌在消息里。
    """
    conn = _connect()
    if conn is None:
        return None
    try:
        kind = _session_kind(conn, opencode_session_id)
        if kind == KIND_V2:
            return _v2_latest_turn(conn, opencode_session_id)
        if kind is None or _LEGACY_MESSAGE_TABLE not in (_table_names(conn) or frozenset()):
            return None
        rows = conn.execute(
            "SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created ASC, id ASC",
            (opencode_session_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode latest_turn message read failed: %s", exc)
        return None
    finally:
        conn.close()

    messages = [(str(mid), _loads(raw)) for mid, raw in rows]
    parent_id = next(
        (mid for mid, data in reversed(messages) if data.get("role") == "user"),
        None,
    )
    if parent_id is None:
        return None

    turn_messages = [
        (mid, data)
        for mid, data in messages
        if data.get("role") == "assistant" and data.get("parentID") == parent_id
    ]
    final_message_id: str | None = None
    completed_at: int | None = None
    for mid, data in turn_messages:
        stamp = (data.get("time") or {}).get("completed")
        if not isinstance(stamp, int):
            # 还在写：正在流式生成的那条消息没有完成时刻。
            continue
        if data.get("finish") == FINISH_CONTINUES:
            # 工具调用段：这一段确实写完了，但后面还有下一段。
            continue
        final_message_id = mid
        completed_at = stamp

    text = _turn_text([mid for mid, _ in turn_messages])
    return OpencodeTurn(
        parent_id=parent_id,
        final_message_id=final_message_id,
        done=final_message_id is not None,
        text=text,
        completed_at=completed_at,
    )


def _turn_text(message_ids: list[str]) -> str:
    """聚合这批助手消息下的 text 片段，按 ``part.time_created`` 升序拼接。

    ``reasoning``（思考）与工具类片段一律丢弃——它们不是给人看的答案。
    """
    if not message_ids:
        return ""
    conn = _connect()
    if conn is None:
        return ""
    placeholders = ",".join("?" * len(message_ids))
    try:
        rows = conn.execute(
            f"SELECT data FROM part WHERE message_id IN ({placeholders}) "  # noqa: S608
            "ORDER BY time_created ASC, id ASC",
            tuple(message_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode part read failed: %s", exc)
        return ""
    finally:
        conn.close()

    chunks: list[str] = []
    for (raw,) in rows:
        data = _loads(raw)
        if data.get("type") != _TEXT_PART_TYPE:
            continue
        piece = data.get("text")
        if isinstance(piece, str) and piece.strip():
            chunks.append(piece.strip())
    return "\n".join(chunks).strip()


# ── 增量片段读取 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class PartCursor:
    """片段游标：已消费到 ``(time_updated, part_id)`` 这一点。

    维度是**更新时间**而不是创建时间。opencode 的写法是先插一个空壳片段、再把内容
    流式地 UPDATE 进去（实测 400 条抽样里 365 条创建后又被改写，文本片段最长滞后
    4.3 秒）。建在创建时间上，每个片段只会在"刚诞生、内容还是空的"那一刻被看见
    一次，之后填进来的正文与工具完成态永远越不过游标——实时流因此只吐得出一条
    工具调用。

    id 只做次序兜底，不参与筛选：取增量用 ``time_updated >=``（同一毫秒内多条更新
    用严格大于会漏），重复由 ``OpencodeTranscriptSource`` 侧的簿记抑制。
    """

    time_updated: int
    part_id: str


def latest_cursor(opencode_session_id: str) -> PartCursor | None:
    """该会话当前最末一次更新的位置（用来锚基线）。没有 / 读失败返回 None。

    2.0 的片段不再单独成表，锚点落在**消息行**上（``session_message.time_updated``）：
    正文是随消息一起被改写进去的，消息行的更新时刻就是"这一轮又写了什么"的时刻。
    """
    conn = _connect()
    if conn is None:
        return None
    try:
        kind = _session_kind(conn, opencode_session_id)
        if kind == KIND_V2:
            row = conn.execute(
                "SELECT time_updated, id FROM session_message WHERE session_id = ? "
                "ORDER BY time_updated DESC, id DESC LIMIT 1",
                (opencode_session_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT time_updated, id FROM part WHERE session_id = ? "
                "ORDER BY time_updated DESC, id DESC LIMIT 1",
                (opencode_session_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("opencode latest_cursor failed: %s", exc)
        return None
    finally:
        conn.close()
    if not row:
        return None
    updated = row[0] if isinstance(row[0], int) else 0
    return PartCursor(time_updated=updated, part_id=str(row[1]))


def parts_since(
    opencode_session_id: str, cursor: PartCursor | None
) -> tuple[list[dict[str, Any]], PartCursor | None]:
    """按 ``(time_updated, id)`` 升序取游标之后（含同刻）的片段，连带消息角色。

    每项形如 ``{"part": <片段 JSON>, "role": "assistant"|"user",
    "message_id": ..., "time_created": ..., "time_updated": ..., "part_id": ...}``。

    筛选用 ``>=`` 而非 ``>``：同一毫秒可以落多条更新，严格大于会把它们漏掉。代价是
    边界那一刻的片段会被反复取回，故调用方 MUST 自己记账去重。

    第二个返回值是新游标：即使全部片段都被上层过滤掉，游标也照样推进到最末一条，
    否则下一拍会把同一批再扫一遍。读失败返回 ``([], 原游标)``——不推进，下一拍重试。
    """
    conn = _connect()
    if conn is None:
        return [], cursor
    try:
        kind = _session_kind(conn, opencode_session_id)
    except sqlite3.Error as exc:
        logger.debug("opencode parts_since kind probe failed: %s", exc)
        conn.close()
        return [], cursor
    if kind == KIND_V2:
        try:
            items, trailing = _v2_part_items(
                conn,
                opencode_session_id,
                order="seq",
                since_updated=cursor.time_updated if cursor is not None else None,
            )
        except sqlite3.Error as exc:
            logger.debug("opencode v2 parts_since failed: %s", exc)
            return [], cursor
        finally:
            conn.close()
        return items, trailing or cursor

    sql = (
        "SELECT p.id, p.message_id, p.time_created, p.time_updated, p.data, m.data "
        "FROM part p JOIN message m ON m.id = p.message_id "
        "WHERE p.session_id = ? "
    )
    params: list[Any] = [opencode_session_id]
    if cursor is not None:
        sql += "AND p.time_updated >= ? "
        params.append(cursor.time_updated)
    sql += "ORDER BY p.time_updated ASC, p.id ASC"
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode parts_since failed: %s", exc)
        return [], cursor
    finally:
        conn.close()

    items: list[dict[str, Any]] = []
    new_cursor = cursor
    for part_id, message_id, created, updated, part_raw, message_raw in rows:
        created_int = created if isinstance(created, int) else 0
        updated_int = updated if isinstance(updated, int) else created_int
        new_cursor = PartCursor(time_updated=updated_int, part_id=str(part_id))
        part = _loads(part_raw)
        if not part:
            # data 损坏：位置照样吃掉（游标已推进），内容当不存在。
            continue
        message = _loads(message_raw)
        items.append(
            {
                "part": part,
                "role": message.get("role") or "assistant",
                "message_id": str(message_id),
                "time_created": created_int,
                "time_updated": updated_int,
                "part_id": str(part_id),
            }
        )
    return items, new_cursor


# ── 片段翻成记录：两个消费方共用的唯一一份规则 ──────────────────────
# 实时流（driver）与归档同步（opencode_sync）必须按同一套规则把片段翻成记录，
# 否则同一个会话在 WebSocket 上与在归档里长得不一样。规则是纯函数：只看片段本身，
# 不带 tmux 会话概念、不做任何去重簿记——"这条发过没有"是流式特有的问题，留在
# driver 的账本里解决。
PART_USER_TEXT = "user_text"
PART_TEXT = "text"
PART_TOOL_CALL = "tool_call"
PART_TOOL_RESULT = "tool_result"

# 片段类型：只有这两类进记录，其余（reasoning / step-start / step-finish）全丢。
_TOOL_PART_TYPE = "tool"
# 工具片段的完成态。只有进了完成态才发结果记录，否则拿到的是空 output。
_TOOL_ERROR_STATUS = "error"
_TOOL_DONE_STATUSES = frozenset({"completed", _TOOL_ERROR_STATUS})


def part_time(time_created: int) -> datetime:
    """片段的创建时刻（opencode 存的是毫秒）。异常值退回当下，NEVER 因此崩。"""
    try:
        return datetime.fromtimestamp(time_created / 1000)
    except (OverflowError, OSError, ValueError):
        return datetime.now()


@functools.lru_cache(maxsize=1)
def _hook_injection_pattern() -> re.Pattern[str] | None:
    """成对标记之间那段注入内容的匹配式（含标记本身）。

    标记从打包资源里取——桥接插件读的是同一个文件，NEVER 在这边另写一份字面量，
    否则改一处就漏另一处，剥离会静默失效。资源读不出来时返回 None（不剥），
    因为那时也无从判断哪段是注入。

    历史上用过的标记一并认：改名那天之前归档的会话里存的是旧标记，只认当前这对
    的话，那些会话的详情页会把注入内容当成用户自己打的字显示出来。
    """
    from frago.init.opencode_plugin import get_all_injection_markers

    try:
        pairs = get_all_injection_markers()
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("frago injection markers unavailable: %s", exc)
        return None
    if not pairs:
        return None
    alternatives = "|".join(f"{re.escape(begin)}.*?{re.escape(end)}" for begin, end in pairs)
    return re.compile(alternatives, re.DOTALL)


def strip_hook_injection(text: str) -> str:
    """剥掉用户文本里被 frago-hook 标记包裹的全部注入段，返回剩下的正文。

    一条消息可能被注入多段（会话首轮会同时带 SessionStart 与 UserPromptSubmit
    两次注入），所以全部剥；剥完首尾空白一并去掉，正文为空就是空字符串。
    """
    pattern = _hook_injection_pattern()
    if pattern is None:
        return text.strip()
    return pattern.sub("", text).strip()


def part_payloads(
    item: dict[str, Any], session_id: str, *, include_user: bool = False
) -> list[tuple[str, dict[str, Any]]]:
    """把一个片段翻成 0~2 条 ``(种类, 归一化记录字典)``。

    记录字典就是 ``session.monitor`` 的 opencode adapter 的入参形状。种类只用来告诉
    调用方"这是文本还是工具调用还是工具结果"，adapter 不看它。

    规则：

    - assistant 的 ``text`` 片段 → 一条文本记录（内容是该片段当前的全文）；
    - ``synthetic`` 为真的 ``text`` 片段 → **丢弃**。那是 opencode 自己注入的编辑器
      上下文，不是答案，混进去等于把注入回显重新捡回来；
    - user 的 ``text`` 片段 → 仅当 ``include_user`` 为真时产出。实时流不要它（用户
      那半轮由主路径自己投递，重复投会在前端出现两遍），归档要它；
    - ``tool`` 片段 → 一条调用记录；该片段已进完成态时再追一条结果记录，消费方因此
      能先亮出"在调什么"再补上结果；
    - ``reasoning`` / ``step-start`` / ``step-finish`` / 其他 → 丢弃。
    """
    part = item["part"]
    role = item["role"]
    part_id = item["part_id"]
    base = {
        "session_id": session_id,
        "parent_uuid": item["message_id"],
        "timestamp": part_time(item["time_created"]),
        "role": "assistant",
    }
    kind = part.get("type")

    if kind == _TEXT_PART_TYPE:
        if part.get("synthetic"):
            return []
        text = part.get("text")
        if not isinstance(text, str) or not text.strip():
            # 空壳片段：内容还没 UPDATE 进来，等它被改写时再说。
            return []
        if role != "assistant":
            if not include_user:
                return []
            # 用户正文里混着 frago-hook 注入的行为守则（opencode 的桥接把它拼进
            # 消息正文，claude 那边落在独立的附件记录里所以天然不进归档）。剥掉，
            # 否则会话详情里每条用户消息都顶着一大段守则，真正的提问被淹没。
            text = strip_hook_injection(text)
            if not text:
                # 整条只有注入、没有真实提问：不产出步骤。
                return []
            return [
                (
                    PART_USER_TEXT,
                    {**base, "role": "user", "uuid": part_id, "content": text},
                )
            ]
        return [(PART_TEXT, {**base, "uuid": part_id, "content": text})]

    if kind == _TOOL_PART_TYPE:
        return _tool_part_payloads(part, base, part_id)

    return []


def _tool_part_payloads(
    part: dict[str, Any], base: dict[str, Any], part_id: str
) -> list[tuple[str, dict[str, Any]]]:
    """工具片段 → 调用记录（+ 已进完成态时的结果记录）。"""
    state = part.get("state")
    state = state if isinstance(state, dict) else {}
    call_id = part.get("callID") or part_id
    payloads: list[tuple[str, dict[str, Any]]] = [
        (
            PART_TOOL_CALL,
            {
                **base,
                "uuid": part_id,
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "name": part.get("tool") or "",
                        "input": state.get("input") if isinstance(state.get("input"), dict) else {},
                    }
                ],
            },
        )
    ]
    status = state.get("status")
    if status not in _TOOL_DONE_STATUSES:
        # 还在跑：结果那条留到它进完成态之后再说。
        return payloads
    is_error = status == _TOOL_ERROR_STATUS
    output = state.get("output")
    if is_error and not output:
        output = state.get("error")
    payloads.append(
        (
            PART_TOOL_RESULT,
            {
                **base,
                # 同一片段发两条记录，uuid 必须分开，否则按 uuid 去重会吃掉一条。
                "uuid": f"{part_id}:result",
                "content": "",
                "tool_results": [
                    {
                        "tool_use_id": call_id,
                        "content": output if isinstance(output, str) else "",
                        "is_error": is_error,
                    }
                ],
            },
        )
    )
    return payloads


# ── 全量读取（归档同步用） ──────────────────────────────────────────
@dataclass(frozen=True)
class OpencodeSessionRow:
    """会话库里的一行会话。标题是 opencode 自己生成的那条。"""

    session_id: str
    title: str
    directory: str
    time_created: int
    time_updated: int


def list_sessions() -> list[OpencodeSessionRow]:
    """列出库里全部会话，按最后活动时间降序。库不存在 / 读失败返回空列表。

    两套表并起来：升级当天的库里，1.18 的旧会话还在 ``session``，2.0 之后新建的
    全在 ``session_v2``。只看其中一张，另一些会话在归档与搜索里就凭空消失。
    """
    conn = _connect()
    if conn is None:
        return []
    names = _table_names(conn) or frozenset()
    rows: list[Any] = []
    try:
        for table in (_V2_SESSION_TABLE, _LEGACY_SESSION_TABLE):
            if table not in names:
                continue
            rows.extend(
                conn.execute(
                    f"SELECT id, title, directory, time_created, time_updated FROM {table}"  # noqa: S608 - 表名是常量
                ).fetchall()
            )
    except sqlite3.Error as exc:
        logger.debug("opencode list_sessions failed: %s", exc)
        return []
    finally:
        conn.close()

    sessions: list[OpencodeSessionRow] = []
    for sid, title, directory, created, updated in rows:
        created_int = created if isinstance(created, int) else 0
        sessions.append(
            OpencodeSessionRow(
                session_id=str(sid),
                title=title if isinstance(title, str) else "",
                directory=directory if isinstance(directory, str) else "",
                time_created=created_int,
                time_updated=updated if isinstance(updated, int) else created_int,
            )
        )
    sessions.sort(key=lambda row: (row.time_updated, row.session_id), reverse=True)
    return sessions


def sessions_containing(terms: list[str]) -> set[str] | None:
    """哪些会话的片段里同时出现了这几个字面量。库读不出来时返回 None。

    这是**粗筛**，不是判定：片段的 ``data`` 是整块 JSON，工具输出里出现这个词也会命
    中。粗筛之后还要把命中的会话翻成统一记录，确认那个词确实落在对话正文里——两步都
    要有，只做粗筛会把工具输出当成人说的话。

    返回空集合与返回 None 是两回事：空集合是"查过了，一场都没有"，None 是"没查成"。
    调用方据此决定是退回全翻还是直接交白卷，NEVER 把两者混成同一个值。
    """
    if not terms:
        return set()
    conn = _connect()
    if conn is None:
        return None
    where = " AND ".join(["data LIKE ? ESCAPE '\\'"] * len(terms))
    params = [f"%{_like_escape(term)}%" for term in terms]
    names = _table_names(conn) or frozenset()
    hits: set[str] = set()
    try:
        for table in (_LEGACY_PART_TABLE, _V2_MESSAGE_TABLE):
            if table not in names:
                continue
            rows = conn.execute(
                f"SELECT DISTINCT session_id FROM {table} WHERE {where}",  # noqa: S608 - 表名是常量，占位符只由词数决定
                params,
            ).fetchall()
            hits.update(str(row[0]) for row in rows if row and row[0])
    except sqlite3.Error as exc:
        logger.debug("opencode sessions_containing failed: %s", exc)
        return None
    finally:
        conn.close()
    return hits


def _like_escape(term: str) -> str:
    """LIKE 的三个元字符转义。用户搜 ``100%`` 时 ``%`` 是要找的字，不是通配符。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def session_parts(opencode_session_id: str) -> list[dict[str, Any]]:
    """该会话的全部片段，按创建时间升序，形状与 ``parts_since`` 的元素一致。

    归档要的是"这个会话从头到尾发生了什么"，故按**创建**时间排（时间轴），而不是
    像实时流那样按更新时间取增量。读失败返回空列表，NEVER 抛。
    """
    conn = _connect()
    if conn is None:
        return []
    try:
        kind = _session_kind(conn, opencode_session_id)
    except sqlite3.Error as exc:
        logger.debug("opencode session_parts kind probe failed: %s", exc)
        conn.close()
        return []
    if kind == KIND_V2:
        try:
            items, _trailing = _v2_part_items(conn, opencode_session_id, order="created")
        except sqlite3.Error as exc:
            logger.debug("opencode v2 session_parts failed: %s", exc)
            return []
        finally:
            conn.close()
        return items
    try:
        rows = conn.execute(
            "SELECT p.id, p.message_id, p.time_created, p.time_updated, p.data, m.data "
            "FROM part p JOIN message m ON m.id = p.message_id "
            "WHERE p.session_id = ? "
            "ORDER BY p.time_created ASC, p.id ASC",
            (opencode_session_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode session_parts failed: %s", exc)
        return []
    finally:
        conn.close()

    items: list[dict[str, Any]] = []
    for part_id, message_id, created, updated, part_raw, message_raw in rows:
        part = _loads(part_raw)
        if not part:
            continue
        created_int = created if isinstance(created, int) else 0
        message = _loads(message_raw)
        items.append(
            {
                "part": part,
                "role": message.get("role") or "assistant",
                "message_id": str(message_id),
                "time_created": created_int,
                "time_updated": updated if isinstance(updated, int) else created_int,
                "part_id": str(part_id),
            }
        )
    return items


def last_assistant_finish(opencode_session_id: str) -> str | None:
    """该会话最后一条助手消息的 ``finish``。没有助手消息 / 读失败返回 None。"""
    conn = _connect()
    if conn is None:
        return None
    try:
        kind = _session_kind(conn, opencode_session_id)
        if kind == KIND_V2:
            # v2 的助手消息靠行上的 ``type`` 认，角色不在 data 里（见 _v2_rows）。
            rows = [
                (data,)
                for _mid, mtype, data in _v2_rows(conn, opencode_session_id)
                if mtype == "assistant"
            ]
        else:
            rows = conn.execute(
                "SELECT data FROM message WHERE session_id = ? ORDER BY time_created ASC, id ASC",
                (opencode_session_id,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode last_assistant_finish failed: %s", exc)
        return None
    finally:
        conn.close()
    for (raw,) in reversed(rows):
        data = raw if isinstance(raw, dict) else _loads(raw)
        if kind != KIND_V2 and data.get("role") != "assistant":
            continue
        finish = data.get("finish")
        return finish if isinstance(finish, str) else None
    return None


# ── 身份映射 ────────────────────────────────────────────────────────
def _load_bindings() -> dict[str, dict[str, Any]]:
    """读映射文件。不存在 / 损坏一律当"没有绑定"，NEVER 让调用方崩。"""
    try:
        raw = BINDINGS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("opencode bindings file corrupt, treated as empty")
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items() if isinstance(v, dict)}


def _save_bindings(bindings: dict[str, dict[str, Any]]) -> None:
    """先写临时文件再原子替换，避免半截文件把下次读取带崩。"""
    BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(BINDINGS_PATH.parent), prefix=BINDINGS_PATH.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(bindings, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, BINDINGS_PATH)
    except OSError:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def get_binding(frago_session_id: str) -> str | None:
    """取该 frago 会话已认领的 opencode 会话 id；没有则 None。"""
    entry = _load_bindings().get(frago_session_id)
    if not entry:
        return None
    value = entry.get("opencode_session_id")
    return value if isinstance(value, str) and value else None


def put_binding(frago_session_id: str, opencode_session_id: str, directory: str) -> None:
    """写入映射。一旦建立就不再重认（重认会让两个会话记录互串）。

    directory 存归一化后的真实路径，与库里的取值保持同一坐标系。
    """
    bindings = _load_bindings()
    bindings[frago_session_id] = {
        "frago_session_id": frago_session_id,
        "opencode_session_id": opencode_session_id,
        "directory": normalize_directory(directory),
        "claimed_at": int(time.time() * 1000),
    }
    _save_bindings(bindings)


def drop_binding(frago_session_id: str) -> None:
    """清掉映射（如续接一个已被用户删除的 opencode 会话）。"""
    bindings = _load_bindings()
    if bindings.pop(frago_session_id, None) is None:
        return
    _save_bindings(bindings)


def drop_bindings_pointing_at(opencode_session_id: str) -> list[str]:
    """清掉所有指向这场 opencode 会话的映射，回被清掉的 frago 会话编号。

    有人把一场 opencode 会话删掉之后，映射里那些还指着它的条目就永远匹配不上了。
    驱动那侧碰见失效映射会自己清（见 ``drivers/opencode.py`` 的自愈），但那是**下一次
    起会话时**才发生的事；在那之前，删掉的会话仍以「已认领」的样子留在映射里。人是
    主动删的，顺手摘干净。

    方向是"按 opencode 编号找 frago 编号"：映射的键是 frago 侧的编号，而人删的是引擎
    侧那一场，两边不是同一个编号空间，NEVER 拿删掉的那个编号直接去 ``pop`` 键。
    """
    bindings = _load_bindings()
    dropped = [
        key
        for key, entry in bindings.items()
        if entry.get("opencode_session_id") == opencode_session_id
    ]
    if not dropped:
        return []
    for key in dropped:
        del bindings[key]
    _save_bindings(bindings)
    return dropped
