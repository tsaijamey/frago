"""opencode 会话库的只读访问层 + frago 侧身份映射。

opencode 把会话搬进了 SQLite（``~/.local/share/opencode/opencode.db``），
结构比 claude 的 JSONL 还整齐：一个用户轮次产生多条助手消息，中途每段工具
调用都带 ``finish=="tool-calls"``，末段带别的取值（``stop`` 居多，也有
``unknown`` 与干脆没有这个字段的），而同一轮的全部助手消息共享同一个指向那条
用户消息的 ``parentID``；每段写完那一刻都会补上 ``time.completed``。轮次边界与
完成时刻因此都是结构化可判的，NEVER 需要从屏幕上刮。

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
    找不到返回 None（NEVER 抛）。
    """
    conn = _connect()
    if conn is None:
        return None
    candidates = [normalize_directory(directory)]
    if directory not in candidates:
        candidates.append(directory)
    try:
        for candidate in candidates:
            row = conn.execute(
                "SELECT id FROM session "
                "WHERE directory = ? AND time_created >= ? "
                "ORDER BY time_created DESC, id DESC LIMIT 1",
                (candidate, since_ms),
            ).fetchone()
            if row:
                return str(row[0])
    except sqlite3.Error as exc:
        logger.debug("opencode claim_session failed: %s", exc)
        return None
    finally:
        conn.close()
    return None


def session_exists(opencode_session_id: str) -> bool:
    """该会话在库里是否还在。

    库不可读时返回 True——不可读不等于不存在，NEVER 因为一次读失败就把一条好
    绑定清掉。
    """
    conn = _connect()
    if conn is None:
        return True
    try:
        row = conn.execute(
            "SELECT 1 FROM session WHERE id = ? LIMIT 1",
            (opencode_session_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("opencode session_exists failed: %s", exc)
        return True
    finally:
        conn.close()
    return row is not None


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
    try:
        row = conn.execute(
            "SELECT directory FROM session WHERE id = ? LIMIT 1",
            (opencode_session_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("opencode session_directory failed: %s", exc)
        return None
    finally:
        conn.close()
    if not row:
        return None
    return str(row[0]) if isinstance(row[0], str) and row[0] else None


# ── 本轮完成判定 ────────────────────────────────────────────────────
def latest_turn(opencode_session_id: str) -> OpencodeTurn | None:
    """读该会话最新一轮。轮次范围以 ``parentID`` 圈定，NEVER 靠时间猜。

    最新一条 ``role=="user"`` 的消息是本轮锚点；本轮的助手消息是全部
    ``parentID`` 指向它的消息。``done`` 的判据是本轮存在**带完成时刻、且结束标记不是
    ``tool-calls``** 的助手消息：完成时刻是"这一段写完了"的结构化证据，
    ``tool-calls`` 是唯一表示"后面还有下一段"的取值（理由见 ``FINISH_CONTINUES``）。
    库不存在 / 会话不存在 / 读失败一律返回 None。
    """
    conn = _connect()
    if conn is None:
        return None
    try:
        rows = conn.execute(
            "SELECT id, data FROM message WHERE session_id = ? "
            "ORDER BY time_created ASC, id ASC",
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
    """该会话当前最末一次片段更新的位置（用来锚基线）。没有片段 / 读失败返回 None。"""
    conn = _connect()
    if conn is None:
        return None
    try:
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
    alternatives = "|".join(
        f"{re.escape(begin)}.*?{re.escape(end)}" for begin, end in pairs
    )
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
                        "input": state.get("input")
                        if isinstance(state.get("input"), dict)
                        else {},
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
    """列出库里全部会话，按最后活动时间降序。库不存在 / 读失败返回空列表。"""
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, title, directory, time_created, time_updated FROM session "
            "ORDER BY time_updated DESC, id DESC"
        ).fetchall()
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
    try:
        rows = conn.execute(
            f"SELECT DISTINCT session_id FROM part WHERE {where}",  # noqa: S608 - 占位符只由词数决定
            params,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode sessions_containing failed: %s", exc)
        return None
    finally:
        conn.close()
    return {str(row[0]) for row in rows if row and row[0]}


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
        rows = conn.execute(
            "SELECT data FROM message WHERE session_id = ? "
            "ORDER BY time_created ASC, id ASC",
            (opencode_session_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode last_assistant_finish failed: %s", exc)
        return None
    finally:
        conn.close()
    for (raw,) in reversed(rows):
        data = _loads(raw)
        if data.get("role") == "assistant":
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


def put_binding(
    frago_session_id: str, opencode_session_id: str, directory: str
) -> None:
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
