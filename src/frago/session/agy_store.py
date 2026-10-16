"""agy (Antigravity CLI) 会话记录的读取层。

agy 把自己的东西全部落在 ``~/.gemini/antigravity-cli/``（官方文档称 app data
directory）下，与 frago 相关的有三处：

``brain/<conversation_id>/.system_generated/logs/transcript.jsonl``
    会话原文，每行一条 JSON。**这是权威记录**，完成判定与答案抽取都读它。
    记录类型见 ``RECORD_*`` 那几条常量。
``conversation_summaries.db``
    一张 ``conversation_summaries`` 表，每个会话一行，含标题、工作目录、最后
    修改时刻。认领会话编号时读它的元数据列，这里**不读**内容。
``cache/last_conversations.json``
    形如 ``{工作目录: conversation_id}``。一个目录只记最近那一场会话，故它只是
    认领的线索之一，不作唯一依据。
``conversations/<conversation_id>.db``
    同一场会话的另一份表示，内容是 protobuf blob ``step_payload``。**本模块只从它
    里取一样东西**：这场会话用的是哪匹模型（见 :func:`session_model`）。其余一律不碰
    ——解析它要把 protobuf 反序列化出来，而 transcript.jsonl 已经把别的事实写成了
    明文 JSON。

身份问题与 codex / opencode 同一类：agy 没有「用调用方给的 id 新建会话」的开关，
编号由它自己分配，frago 只能在会话起来之后**认领**。认领结果落在
``~/.frago/agy-sessions.json``，与另外两家的映射文件同一套做法。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# frago 侧的身份映射文件：frago 会话标识 → agy 原生会话编号。设备本地产物，
# 与 codex / opencode 的映射文件同级同规格。
BINDINGS_PATH = Path.home() / ".frago" / "agy-sessions.json"

# transcript.jsonl 的已知记录类型（``type`` 字段的取值）。
#
# 只列本模块要判的那几类；其余（``CONVERSATION_HISTORY`` 等）一律当背景。
RECORD_USER_INPUT = "USER_INPUT"
"""用户这一轮说的话。``content`` 里裹着 ``<USER_REQUEST>`` 与几段元数据。"""
RECORD_PLANNER = "PLANNER_RESPONSE"
"""模型这一拍的产出。带 ``tool_calls`` 表示还要动手，带 ``content`` 表示给话。"""
RECORD_CONVERSATION_HISTORY = "CONVERSATION_HISTORY"
"""开场补记的一条历史回放标记：``source`` 为 SYSTEM、没有正文。翻时间线时跳过。"""
RECORD_SYSTEM_MESSAGE = "SYSTEM_MESSAGE"
"""系统消息。**两种来源共用这一个类型**：agy 自己发的通知（``source`` 为 ``SYSTEM``），
以及 hook 经 ``injectSteps`` 注进来的内容（``source`` 为 ``SYSTEM_SDK``，正文里带一句
``The following system message was injected by a … hook:``）。分得开才有意义——前者不是
任何人注入的，后者是 frago 自己的规则说的。"""
RECORD_EPHEMERAL_MESSAGE = "EPHEMERAL_MESSAGE"
"""一条**用完即弃**的注入。``source`` 为 ``SYSTEM_SDK``，正文就是注进来的原文，外面没有
任何包裹。

这是 ``injectSteps`` 里 ``ephemeralMessage`` 那一型的落盘形态（2026-10-14 在本机实测：
一条 ``{"ephemeralMessage": "PROBE-EPHEMERAL-99887"}`` 原样落成了这个类型的一条记录）。
**它带不来事件名**——正文里没有那句 ``injected by a … hook`` 标签，所以认它的路只有类型
本身。"""

# 完成探针每次回读的字节数。transcript.jsonl 是整场会话的流水账，一轮里的
# 用户输入与模型几个回复永远贴在末尾，整读没必要。
_TAIL_BYTES = 256 * 1024


# ── 路径 ────────────────────────────────────────────────────────────
def get_app_data_dir() -> Path:
    """agy 的应用数据目录。

    官方文档把它称为 app data directory，Antigravity CLI 那一份是
    ``~/.gemini/antigravity-cli``（2.0 与 IDE 各是同级另一个目录）。这里写死 CLI
    那一份：frago 驱动的就是 CLI。``FRAGO_AGY_APP_DIR`` 只给测试用，正常路径不设。
    """
    override = os.environ.get("FRAGO_AGY_APP_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".gemini" / "antigravity-cli"


def is_agy_present() -> bool:
    """agy 在这台机器上看起来装了没有。"""
    return get_app_data_dir().is_dir() or shutil.which("agy") is not None


def brain_root() -> Path:
    """会话原文的根目录（不创建）。"""
    return get_app_data_dir() / "brain"


def summaries_db_path() -> Path:
    """会话摘要库的位置。"""
    return get_app_data_dir() / "conversation_summaries.db"


def last_conversations_path() -> Path:
    """工作目录 → 最近一场会话编号的映射文件。"""
    return get_app_data_dir() / "cache" / "last_conversations.json"


def _transcripts_dir(conversation_id: str) -> Path:
    """某场会话那两份转录所在的目录（不判断存在与否）。"""
    return brain_root() / conversation_id / ".system_generated" / "logs"


def transcript_path(conversation_id: str) -> Path:
    """``transcript.jsonl`` —— **agy 的主账**（不判断存在与否）。

    换过位置的只是外层目录；文件名与中间那两节由 agy 自己固定。

    **完成探针与存在性判断用这一份**，不用下面那份未截的：探针只回读文件末尾一段固定
    字节数，而未截那份体积大出四成（本机实测一场 32KB → 47KB），同样一段窗口盖住的记录
    就少了一截，长会话里会读不到最后那条用户输入。两份记录的**条数与次序一致**（本机
    9 场逐个核过），所以按条数判事的那条路用哪份都对。
    """
    return _transcripts_dir(conversation_id) / "transcript.jsonl"


def full_transcript_path(conversation_id: str) -> Path:
    """``transcript_full.jsonl`` —— 同一场会话那份**没被截过**的（不判断存在与否）。

    agy 把长正文在主账里剪短（``truncated_fields`` 里列着 ``content`` 的那种），完整原文
    另存这一份。本机实测：同一条 SessionStart 注入，主账 1882 字，这份 2826 字——被剪掉的
    是宪法尾部一整段。
    """
    return _transcripts_dir(conversation_id) / "transcript_full.jsonl"


def display_transcript_path(conversation_id: str) -> Path:
    """**读给人看的那一份**：未截的在就用它，不在退回主账。

    工作台展示记录、取原文、以及递给复核的那段提要都走这里——正文被无声剪掉一截，在界面
    上就是"当时注进来的只有这么点"。缺那份时退回主账：宁可显示得短一点，也不能因为多
    一份文件不在，就让整场会话读不出来。
    """
    full = full_transcript_path(conversation_id)
    return full if full.exists() else transcript_path(conversation_id)


def conversation_db_path(conversation_id: str) -> Path:
    """某场会话那份 protobuf 库的路径（不判断存在与否）。"""
    return get_app_data_dir() / "conversations" / f"{conversation_id}.db"


def normalize_directory(directory: str) -> str:
    """把工作目录归一化到解析过软链接的真实路径。

    与 codex 侧同一个理由：agy 记的是它看到的那个目录，macOS 上 ``/tmp`` 是指向
    ``/private/tmp`` 的软链接，不归一化就会**静默**匹配不上。
    """
    try:
        return os.path.realpath(directory)
    except OSError:
        return directory


def conversation_exists(conversation_id: str) -> bool:
    """该会话的原文件还在不在。

    整个 brain 目录读不到时返回 True：读不到不等于会话没了，NEVER 因为一次读不到
    就清掉一条好绑定（与 codex / opencode 同一条原则）。
    """
    if not brain_root().is_dir():
        return True
    return transcript_path(conversation_id).exists()


def session_directory(conversation_id: str) -> str | None:
    """这场会话当初在哪个工作目录跑的。读不到时 None。

    续接要用：agy 的 ``--conversation <id>`` 必须在原来那个目录里起，才接得回同一场。
    目录记在摘要库的 ``workspace_uris`` 里（与 codex 的 rollout 元数据、opencode 的会话库
    同一个用途）。
    """
    for conv in list_conversations():
        if conv.conversation_id == conversation_id:
            return conv.workspace or None
    return None


# ── 记录读取 ────────────────────────────────────────────────────────
def _iter_records(path: Path, *, tail_bytes: int | None = None) -> list[dict[str, Any]]:
    """把一份 transcript 读成记录列表；坏行跳过。

    ``tail_bytes`` 给定时只回读末段，并丢弃第一条（很可能被切成半行）的残缺行。
    """
    try:
        if tail_bytes is None:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        else:
            size = path.stat().st_size
            with path.open("rb") as fh:
                if size > tail_bytes:
                    fh.seek(size - tail_bytes)
                    chunk = fh.read()
                    _, _, chunk = chunk.partition(b"\n")
                else:
                    chunk = fh.read()
            lines = chunk.decode("utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.debug("agy transcript read failed for %s: %s", path, exc)
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def read_records(path: Path) -> list[dict[str, Any]]:
    """把一份转录文件读成记录列表（坏行跳过）。读不动时空列表，NEVER 抛。

    **按路径读**，与 :func:`latest_turn` 按会话编号读是两回事：hook 触发时手里只有 agy
    递过来的 ``transcriptPath``，编号要另去别处换；而且那条路上读的还是**正在写**的那份
    文件，不能整读。
    """
    return _iter_records(path)


def _model_text(record: dict[str, Any]) -> str:
    """模型这一拍给的话；没给话（还在调工具）时是空串。"""
    content = record.get("content")
    return content.strip() if isinstance(content, str) else ""


def _is_final_model_turn(record: dict[str, Any]) -> bool:
    """这一拍是不是「本轮到此说完」。

    模型每一拍都写一条 ``PLANNER_RESPONSE``：带 ``tool_calls`` 的是「我还要动手」，
    带 ``content`` 且不带 ``tool_calls`` 的是「我说完了」。两者都可能同时带
    ``thinking``，故 ``thinking`` 不作为判据。

    这与工具步区分得开：工具步的 ``type`` 是那个工具自己的名字（实测见到
    ``SEARCH_WEB``），带 ``content`` 但是模型的工具产出，不是给用户的话。
    """
    if record.get("type") != RECORD_PLANNER:
        return False
    if record.get("tool_calls"):
        return False
    return bool(_model_text(record))


@dataclass(frozen=True)
class AgyTurn:
    """从 transcript 读出的最新一轮。"""

    turn_id: str | None
    """本轮的锚点：那一条用户输入的 ``step_index``。每轮唯一，用作去重。"""

    done: bool
    """本轮是否已答完（用户输入之后出现了收尾的模型回复）。"""

    text: str
    """本轮终答。"""

    error: str | None
    """暂恒为 None。agy 把失败写在别处（如配额耗尽提示），本模块暂不解析。"""


def latest_turn(conversation_id: str) -> AgyTurn | None:
    """读该会话最新一轮的完成状态与终答。定位不到 / 读不出时返回 None。

    判据是**用户输入之后有没有收尾的模型回复**，而不是「最后一行的类型是什么」：
    模型说完话之后 agy 还会补记别的行，按最后一行判会永远判不出答完。窗口被某一轮
    的长工具输出撑爆时，退化成「末尾那一轮没看到用户输入」，此时返回 None，主路径
    当帧退回读屏信号，本轮照常跑完。
    """
    path = transcript_path(conversation_id)
    if not path.exists():
        return None
    records = _iter_records(path, tail_bytes=_TAIL_BYTES)
    if not records:
        return None

    last_user_pos: int | None = None
    last_user_step: Any = None
    for position, record in enumerate(records):
        if record.get("type") == RECORD_USER_INPUT:
            last_user_pos = position
            last_user_step = record.get("step_index")

    if last_user_pos is None:
        return None

    # 只在**最后一条**用户输入之后找收尾回复。上一轮那次收尾也在同一个窗口里，
    # 不划这条线的话，第二轮刚提交就会被判成"已经答完"，取回上一轮的答案。
    final_text: str | None = None
    for record in records[last_user_pos + 1 :]:
        if _is_final_model_turn(record):
            final_text = _model_text(record)
    marker = str(last_user_step) if last_user_step is not None else None
    if final_text is None:
        return AgyTurn(turn_id=marker, done=False, text="", error=None)
    return AgyTurn(turn_id=marker, done=True, text=final_text, error=None)


# ── 模型名 ──────────────────────────────────────────────────────────
#: 模型 slug 的形状：``claude-sonnet-5-5-medium`` / ``gemini-3.8-flash-medium`` 这类。
#:
#: 写成一条**收尾必须落在档位词上**的式子，而不是「找出所有像模型名的串」：同一个 blob
#: 里还躺着 ``used_non_gemini_model``、``disable-teamwork-forced-flash-model``、
#: ``model_enum``、``gemini-3.8-flash-n`` 这几个近邻，只有「厂商前缀 + 收在 low/medium/
#: high/xhigh/max」这一条能把它们全挡在外面（2026-10-14 在本机 10 场会话上逐个核过）。
_MODEL_SLUG_RE = re.compile(
    rb"(?:claude|gemini|gpt|o[0-9])[a-z0-9.\-]*(?:low|medium|high|xhigh|max)"
)


def session_model(conversation_id: str) -> str | None:
    """这场会话用的是哪匹模型；读不到时 None。

    **转录里没有这个事实。** transcript.jsonl 的每一条模型回复都带 token 数，却一个字
    都没写是谁答的；摘要库、``cache/conversation_metadata.json`` 同样没有。全机只有一处
    记着它：``conversations/<id>.db`` 里那几块 protobuf，每一次模型调用都会把 slug 原样
    写进去（本机实测 10 场，场场有、块与块之间一致）。

    所以这里只做一件事——把那几块二进制当字节流扫一遍，抠出那个 slug。**不做 protobuf
    反序列化**：为了一个字符串去引入一套 schema 依赖不划算，而 slug 是 ASCII 明文、
    前后都有长度前缀兜着，扫出来就是它。

    读不到（库不在、表是空的、agy 换了格式）一律返回 None。**失效方式是静默降级**：
    界面上那一格空着，上下文与总量照常，绝不编一个名字顶上。
    """
    path = conversation_db_path(conversation_id)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        logger.debug("agy conversation db open failed for %s: %s", conversation_id, exc)
        return None
    try:
        # ``gen_metadata`` 是每一次模型调用的生成元数据，``executor_metadata`` 是执行器
        # 那份。先问前者（它一定带 slug），前者空再退到后者。
        for table in ("gen_metadata", "executor_metadata"):
            try:
                rows = conn.execute(f"SELECT data FROM {table} ORDER BY idx LIMIT 4").fetchall()
            except sqlite3.Error:
                continue
            for (blob,) in rows:
                if not isinstance(blob, bytes | bytearray):
                    continue
                found = _MODEL_SLUG_RE.search(bytes(blob))
                if found is not None:
                    return found.group(0).decode("ascii", errors="replace")
    finally:
        conn.close()
    return None


# ── 会话元数据与认领 ────────────────────────────────────────────────
@dataclass(frozen=True)
class AgyConversation:
    """一场 agy 会话的门面信息（来自摘要库，不读内容）。"""

    conversation_id: str
    title: str
    """模型给这场会话起的名字。绝大多数会话没有，是空串。"""
    preview: str
    """agy 自己存的一句提要，多半就是开口那句。空会话时也是空串。"""
    workspace: str
    last_modified: float
    """最后修改时刻（epoch 秒）。认领与排序都拿它当判据。"""
    last_user_input: float
    """最后一条用户输入的时刻（epoch 秒）。上面那个为零时拿它兜底。"""
    step_count: int


def _open_summaries() -> sqlite3.Connection | None:
    """只读打开摘要库。不存在 / 打不开时返回 None，NEVER 抛。

    ``mode=ro`` 且不建 WAL：agy 自己正开着这个库，读的一侧只借一眼元数据，
    不该因为一次读取去动它的写前日志。
    """
    path = summaries_db_path()
    if not path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        logger.debug("agy summaries db open failed: %s", exc)
        return None


def _parse_modified(raw: Any) -> float:
    """摘要库里的时刻是文本（``YYYY-MM-DD HH:MM:SS.ffffff+00:00``）。"""
    if not isinstance(raw, str) or not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def _parse_timestamp(raw: Any) -> datetime | None:
    """转录行上的时刻（``2026-10-13T11:42:52Z``）→ ``datetime``。解不出来时 None。

    ``Z`` 后缀 CANNOT 直接喂 ``fromisoformat``（3.10 及以前不认），要换成正偏移再解；
    与 codex 那一侧同一个写法，两家的时间戳因此落进同一个口径。
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _workspace_of(raw: Any) -> str:
    """``workspace_uris`` 是一段 JSON 数组，形如 ``["file:///Users/frago"]``。

    取第一个并剥掉 ``file://`` 前缀；剥不掉时原样返回，交给调用方比对。
    """
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    if not isinstance(parsed, list) or not parsed:
        return ""
    first = parsed[0]
    if not isinstance(first, str):
        return ""
    return first[7:] if first.startswith("file://") else first


def list_conversations(limit: int | None = None) -> list[AgyConversation]:
    """列出本机的 agy 会话，最新在上。读不到时返回空列表。

    排序按最后修改时刻。摘要库里的行是 agy 自己维护的，本模块只读不改。
    """
    conn = _open_summaries()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT conversation_id, title, preview, workspace_uris, last_modified_time,"
            " last_user_input_time, step_count"
            " FROM conversation_summaries ORDER BY last_modified_time DESC"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("agy summaries query failed: %s", exc)
        return []
    finally:
        conn.close()
    out = [
        AgyConversation(
            conversation_id=str(row[0]),
            title=str(row[1] or ""),
            preview=str(row[2] or ""),
            workspace=_workspace_of(row[3]),
            last_modified=_parse_modified(row[4]),
            last_user_input=_parse_modified(row[5]),
            step_count=int(row[6] or 0),
        )
        for row in rows
        if row and row[0]
    ]
    return out[:limit] if limit is not None else out


def _last_conversation_for(directory: str) -> str | None:
    """``cache/last_conversations.json`` 里这个目录对应的会话编号。

    键是 agy 自己记下的目录原值，可能带软链接差异，故两侧都比一次。
    """
    path = last_conversations_path()
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    for key in (directory, normalize_directory(directory)):
        value = parsed.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def bound_session_ids() -> set[str]:
    """映射表里已经认出去的 agy 会话编号。

    认领时拿它排除：一个编号只属于一个 frago 会话。两场会话把同一个编号各认一遍，
    等于把两场对话的记录接到一起。
    """
    out: set[str] = set()
    for entry in _load_bindings().values():
        value = entry.get("agy_conversation_id")
        if isinstance(value, str) and value:
            out.add(value)
    return out


def claim_conversation(directory: str, since_ms: int) -> str | None:
    """认领会话编号：取工作目录匹配、在 ``since_ms`` 之后动过、且还没被认过的那个。

    两个来源依次试：

    1. ``cache/last_conversations.json`` —— 最直接，一个目录一条。但它只记"最近
       一场"，同一目录里先后起了两场时它已经指向新的那场。故取到之后 MUST 拿摘要库
       对一次时刻：早于锚点的说明那场是**别人**起的，弃用。
    2. 摘要库按时刻筛 —— 工作目录匹配、最后修改晚于锚点、且未被认过的那些里取**最早**
       起的那个。锚点之后最早起的才是这一次新建出来的；取最晚会认到同一目录里另一场
       正在跑的会话上。

    找不到返回 None，NEVER 抛。
    """
    candidates = {directory, normalize_directory(directory)}
    since_s = since_ms / 1000.0
    taken = bound_session_ids()

    def _matches(conv: AgyConversation) -> bool:
        return conv.workspace in candidates or normalize_directory(conv.workspace) in candidates

    conversations = {c.conversation_id: c for c in list_conversations()}

    hinted = _last_conversation_for(directory)
    if hinted and hinted not in taken:
        conv = conversations.get(hinted)
        if conv is not None and conv.last_modified >= since_s and _matches(conv):
            return hinted

    best: tuple[float, str] | None = None
    for conv in conversations.values():
        if conv.conversation_id in taken or not _matches(conv):
            continue
        if conv.last_modified < since_s:
            continue
        if best is None or conv.last_modified < best[0]:
            best = (conv.last_modified, conv.conversation_id)
    return best[1] if best else None


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
        logger.debug("agy bindings file corrupt, treated as empty")
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
    """取该 frago 会话已认领的 agy 会话编号；没有则 None。"""
    entry = _load_bindings().get(frago_session_id)
    if not entry:
        return None
    value = entry.get("agy_conversation_id")
    return value if isinstance(value, str) and value else None


def put_binding(frago_session_id: str, conversation_id: str, directory: str) -> None:
    """写入映射。一旦建立就不再重认（重认会让两场会话的记录互串）。"""
    bindings = _load_bindings()
    bindings[frago_session_id] = {
        "frago_session_id": frago_session_id,
        "agy_conversation_id": conversation_id,
        "directory": normalize_directory(directory),
        "claimed_at": int(time.time() * 1000),
    }
    _save_bindings(bindings)


def drop_binding(frago_session_id: str) -> None:
    """清掉映射（如续接一场已被用户删掉的 agy 会话）。"""
    bindings = _load_bindings()
    if bindings.pop(frago_session_id, None) is None:
        return
    _save_bindings(bindings)
