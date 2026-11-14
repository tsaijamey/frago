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
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# frago 侧的身份映射文件：frago 会话标识 → agy 原生会话编号。设备本地产物，
# 与 codex / opencode 的映射文件同级同规格。
_DEFAULT_BINDINGS_PATH = Path.home() / ".frago" / "agy-sessions.json"
BINDINGS_PATH = _DEFAULT_BINDINGS_PATH
_claim_lock = threading.Lock()


def _bindings_path() -> Path:
    """身份映射账本路径：测试若显式 monkeypatch 了 ``BINDINGS_PATH`` 则从之；
    若设了 ``FRAGO_AGY_APP_DIR`` 隔离测试目录则落在该目录下；否则走 ``Path.home()``。
    """
    if BINDINGS_PATH != _DEFAULT_BINDINGS_PATH:
        return BINDINGS_PATH
    override = os.environ.get("FRAGO_AGY_APP_DIR")
    if override:
        return Path(override).expanduser() / "agy-sessions.json"
    return Path.home() / ".frago" / "agy-sessions.json"

# transcript.jsonl 的已知记录类型（``type`` 字段的取值）。
#
# 只列本模块要判的那几类；其余（``CONVERSATION_HISTORY`` 等）一律当背景。
RECORD_USER_INPUT = "USER_INPUT"
"""用户这一轮说的话。``content`` 里裹着 ``<USER_REQUEST>`` 与几段元数据。"""
RECORD_PLANNER = "PLANNER_RESPONSE"
"""模型这一拍的产出。带 ``tool_calls`` 表示还要动手，带 ``content`` 表示给话。"""

STATUS_ERROR = "ERROR"
"""``status`` 取这个值表示这一拍没跑通。

**它不等于"工具失败了"。** 实测（agy 1.3.5，2026-10-20）两种情形要分开看：

- 命令自己跑了但退出码非零（``exit 1``）→ 记录是 ``status: DONE``，失败信息在
  ``content`` 正文里。这不是"被拒"，模型拿到输出后照常往下走。
- 工具调用**在跑之前就被 hook 挡下** → 记录是 ``status: ERROR``，并带一个 ``error``
  字段，正文形如 ``tool call denied by pre-tool hook: …``。

判断"上一拍是不是刚被拒"，认的是后一种：``status == ERROR``。"""
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
RECORD_ERROR_MESSAGE = "ERROR_MESSAGE"
"""流式连接中断或上游接口报错时 agy 落下的错误记录（如 ``The stream was interrupted``）。"""

# 完成探针每次回读的字节数。transcript.jsonl 是整场会话的流水账，一轮里的
# 用户输入与模型几个回复永远贴在末尾，整读没必要。
_TAIL_BYTES = 256 * 1024


# ── 路径 ────────────────────────────────────────────────────────────
def get_app_data_dir() -> Path:
    """agy 的应用数据目录。

    官方文档把它称为 app data directory，Antigravity CLI 在 POSIX 下是
    ``~/.gemini/antigravity-cli``。这里写死 CLI 那一份：frago 驱动的就是 CLI。
    ``FRAGO_AGY_APP_DIR`` 只给测试用，正常路径不设。
    在 Windows 平台优先探测 LOCALAPPDATA / APPDATA，避免主目录残留空目录短路；
    在所有候选目录均未创建时，Windows 默认回退到 %LOCALAPPDATA%（或 %APPDATA%）
    标准路径，POSIX 默认返回 ~/.gemini/antigravity-cli。
    """
    override = os.environ.get("FRAGO_AGY_APP_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        # 1. 优先探测 Windows 标准环境变量路径是否存在
        for env_var in ("LOCALAPPDATA", "APPDATA"):
            val = os.environ.get(env_var)
            if val:
                cand = Path(val) / "Gemini" / "antigravity-cli"
                if cand.is_dir():
                    return cand

        # 2. 其次探测用户主目录下的 ~/.gemini/antigravity-cli
        default_dir = Path.home() / ".gemini" / "antigravity-cli"
        if default_dir.is_dir():
            return default_dir

        # 3. 零先验未创建场景：Windows 默认回退标准 LOCALAPPDATA / APPDATA
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_app_data:
            return Path(local_app_data) / "Gemini" / "antigravity-cli"
        return Path.home() / "AppData" / "Local" / "Gemini" / "antigravity-cli"

    default_dir = Path.home() / ".gemini" / "antigravity-cli"
    return default_dir


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


def history_path() -> Path:
    """agy 输入历史流水（每次敲下回车即落一行含 ``timestamp`` / ``text`` / ``workspace``）。"""
    return get_app_data_dir() / "history.jsonl"


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


def find_session_file(conversation_id: str) -> Path | None:
    """定位 agy 会话的原始转录文件。找不到返回 None，NEVER 抛。

    单一事实源出口：优先返回主账 transcript.jsonl（实时写入与完成判定均使用该文件）；
    若主账不存在但 transcript_full.jsonl 存在，则退回到未截断转录；
    若文件尚未落盘但会话目录已就绪（刚启动），仍返回主账路径（便于实时桥接预先挂载监听）；
    定位不到会话目录或 Antigravity CLI 未安装时返回 None。
    """
    if not is_agy_present():
        return None
    primary = transcript_path(conversation_id)
    if primary.is_file():
        return primary
    full = full_transcript_path(conversation_id)
    if full.is_file():
        return full
    if primary.parent.is_dir() or has_conversation(conversation_id):
        return primary
    return None


def conversation_db_path(conversation_id: str) -> Path:
    """某场会话那份 protobuf 库的路径（不判断存在与否）。"""
    return get_app_data_dir() / "conversations" / f"{conversation_id}.db"


def brain_dir(conversation_id: str) -> Path:
    """某场会话在 brain/ 下的独立目录（不判断存在与否）。"""
    return brain_root() / conversation_id


def conversation_metadata_path() -> Path:
    """会话元数据缓存 JSON 的位置。"""
    return get_app_data_dir() / "cache" / "conversation_metadata.json"


def annotation_path(conversation_id: str) -> Path:
    """某场会话标题注解文件的位置（不判断存在与否）。"""
    return get_app_data_dir() / "annotations" / f"{conversation_id}.pbtxt"


def presence_lock_path(conversation_id: str) -> Path:
    """某场会话在线锁文件的位置（不判断存在与否）。"""
    return get_app_data_dir() / "presence" / f"{conversation_id}.lock"


def has_conversation(conversation_id: str) -> bool:
    """本机 agy 里还有没有这场会话的落盘痕迹（用于家族识别与删除前探测）。

    与 :func:`conversation_exists` 分工相反：后者在目录读不到时保守回 True（防误清好绑定），
    这里回答"这场到底在不在 agy 那边"——目录整个不在时回 False，免得把别家的裸 UUID
    全认成 agy。只要转录文件、brain 子目录、独立会话库或摘要库行任一存在，就认作是它。
    """
    app_dir = get_app_data_dir()
    if not app_dir.is_dir():
        return False
    if (
        transcript_path(conversation_id).exists()
        or brain_dir(conversation_id).is_dir()
        or conversation_db_path(conversation_id).exists()
    ):
        return True
    conn = _open_summaries()
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM conversation_summaries WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


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

    优先读摘要库 ``conversation_summaries.db`` 的 ``workspace_uris``；若摘要库尚未写入
    或冷启动恢复时被 agy 覆写为空串，再回退查 ``~/.frago/agy-sessions.json`` 认领账本里
    记下的 ``directory``。
    """
    for conv in list_conversations():
        if conv.conversation_id == conversation_id and conv.workspace:
            return conv.workspace
    return bound_directory(conversation_id)


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
    """若本轮末尾停在 SYSTEM ERROR_MESSAGE 且无后续推进与后台任务，记录该错误文本；否则为 None。"""


_BG_TASK_START_RE = re.compile(r"Tool is running as a background task with task id:\s*(\S+)")
_BG_TASK_DONE_RE = re.compile(
    r'Task id "([^"]+)" (?:finished with result:|was canceled with result:|failed with)'
)
_BG_TASK_CANCEL_RE = re.compile(r'Task "([^"]+)" cancelled\.')
_BG_TASK_SYSTEM_SENDER_RE = re.compile(r"\bsender=(\S+/(?:task-\d+|subagent-\S+))\b")
_BG_TASK_STOPPED_ALL = "All your subagents and background tasks have been stopped"


def _update_pending_bg_tasks(record: dict[str, Any], pending: set[str]) -> None:
    """按单条记录推进本轮后台任务集合：转入后台入集，收到完成/取消/定时器到期/重启通知出集。"""
    record_type = record.get("type")
    if record_type == RECORD_CONVERSATION_HISTORY:
        # 跨进程续接会话回放边界：此前进程遗留的后台任务全部失效归零
        pending.clear()
        return

    content = record.get("content")
    if not isinstance(content, str) or not content:
        return
    if record.get("status") == "RUNNING":
        match = _BG_TASK_START_RE.search(content)
        if match:
            pending.add(match.group(1))
            return
    if record_type == RECORD_PLANNER:
        # 模型自身发言（含过渡播报末尾可能粘连的 fused 文本）不执行任务销账，
        # 留待紧随其后的独立 SYSTEM_MESSAGE 记录触发销账并作废过渡播报。
        return
    if _BG_TASK_STOPPED_ALL in content:
        pending.clear()
        return
    for match in _BG_TASK_DONE_RE.finditer(content):
        pending.discard(match.group(1))
    for match in _BG_TASK_CANCEL_RE.finditer(content):
        pending.discard(match.group(1))
    if record_type == RECORD_SYSTEM_MESSAGE:
        for match in _BG_TASK_SYSTEM_SENDER_RE.finditer(content):
            pending.discard(match.group(1))


def latest_turn(conversation_id: str) -> AgyTurn | None:
    """读该会话最新一轮的完成状态与终答。定位不到 / 读不出时返回 None。

    判据是**用户输入之后有没有收尾的模型回复，且本轮没有尚未完结的后台任务**：
    1. 模型说完话之后 agy 还会补记别的行，按最后一行判会永远判不出答完。
    2. 当命令超过 ``WaitMsBeforeAsync`` 转入后台（``status == "RUNNING"``）时，agy 强制
       模型先输出一条不带 ``tool_calls`` 的过渡播报并结束当前小拍、挂起等待后台完成回调；
       若本轮仍有未收到完成通知的后台任务，或者是后台任务刚回调、模型还没给出回调后的新回复，
       本轮都尚未完结。
    回读窗口先走 ``_TAIL_BYTES``（256KB）快速路径；若单轮长输出将最后一条 ``USER_INPUT``
    挤出初始窗口，则按倍增窗口（512KB → 1MB → … → 整文件）向上扩读重试，直至找到最近一条
    用户输入，或确认全文件确无用户输入记录后再返回 None（下游在未确定态下退回读屏信号）。
    """
    path = transcript_path(conversation_id)
    if not path.exists():
        return None
    try:
        file_size = path.stat().st_size
    except OSError:
        return None
    if file_size <= 0:
        return None

    window = _TAIL_BYTES
    records: list[dict[str, Any]] = []
    last_user_pos: int | None = None
    last_user_step: Any = None
    while True:
        exhausted = window >= file_size
        records = _iter_records(path, tail_bytes=None if exhausted else window)
        last_user_pos = None
        last_user_step = None
        for position, record in enumerate(records):
            if record.get("type") == RECORD_USER_INPUT:
                last_user_pos = position
                last_user_step = record.get("step_index")
        if last_user_pos is not None:
            break
        if exhausted:
            return None
        window *= 2
        try:
            file_size = path.stat().st_size
        except OSError:
            return None

    # 只在**最后一条**用户输入之后找收尾回复。上一轮那次收尾也在同一个窗口里，
    # 不划这条线的话，第二轮刚提交就会被判成"已经答完"，取回上一轮的答案。
    final_text: str | None = None
    terminal_error: str | None = None
    pending_bg_tasks: set[str] = set()
    for record in records[last_user_pos + 1 :]:
        before_pending = set(pending_bg_tasks)
        _update_pending_bg_tasks(record, pending_bg_tasks)
        if before_pending != pending_bg_tasks and not pending_bg_tasks:
            # 后台任务刚刚完结或被终止：此前为了等待它而留下的过渡播报作废，等后续真正的收尾回复。
            final_text = None
            terminal_error = None
        record_type = record.get("type")
        if record_type == RECORD_PLANNER and record.get("tool_calls"):
            # 模型继续发起新一拍工具调用：早先的文字回复只是中间播报。
            final_text = None
            terminal_error = None
        elif record_type == RECORD_ERROR_MESSAGE and record.get("source") == "SYSTEM":
            # 系统级错误帧（如 401 UNAUTHENTICATED / unexpected EOF / stream interrupted）：
            # 先废掉此前可能落盘的半截回复并记录错误文本；若后续 agy 自动续写（追加
            # EPHEMERAL_MESSAGE 或新的 PLANNER_RESPONSE），则在后续帧中清掉 terminal_error。
            final_text = None
            raw_err = record.get("error") or record.get("content")
            terminal_error = (
                str(raw_err).strip()
                if isinstance(raw_err, str) and str(raw_err).strip()
                else "AGY system error (ERROR_MESSAGE)"
            )
        elif record_type in (RECORD_ERROR_MESSAGE, RECORD_EPHEMERAL_MESSAGE) or (
            record.get("status") == STATUS_ERROR
        ):
            # 流式断连报错（ERROR_MESSAGE）或新一拍模型调用启动前的 PreInvocation 注入
            # （EPHEMERAL_MESSAGE）出现在回复之后：说明方才那条无 tool_calls 的
            # PLANNER_RESPONSE 只是断流残片或中间播报，本轮尚未真正收尾。
            final_text = None
            terminal_error = None
        elif _is_final_model_turn(record):
            final_text = _model_text(record)
            terminal_error = None
        elif record_type not in (RECORD_CONVERSATION_HISTORY, RECORD_SYSTEM_MESSAGE):
            terminal_error = None
    marker = str(last_user_step) if last_user_step is not None else None
    if final_text is None or pending_bg_tasks:
        return AgyTurn(
            turn_id=marker,
            done=False,
            text="",
            error=None if pending_bg_tasks else terminal_error,
        )
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
    当新会话首轮连续密集调工具、``conversation_summaries.db`` 尚未写入这一行，但
    ``agy-sessions.json`` 已完成认领且 ``brain/<id>/.../transcript.jsonl`` 已落盘时，
    按绑定的目录与转录修改时刻补入清单，避免新会话在摘要库滞后期的 60~95 秒内从左栏和备份隐身。
    """
    conn = _open_summaries()
    rows: list[Any] = []
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT conversation_id, title, preview, workspace_uris, last_modified_time,"
                " last_user_input_time, step_count"
                " FROM conversation_summaries ORDER BY last_modified_time DESC"
            ).fetchall()
        except sqlite3.Error as exc:
            logger.debug("agy summaries query failed: %s", exc)
            rows = []
        finally:
            conn.close()
    out = [
        AgyConversation(
            conversation_id=str(row[0]),
            title=str(row[1] or ""),
            preview=str(row[2] or ""),
            workspace=_workspace_of(row[3]) or (bound_directory(str(row[0])) or ""),
            last_modified=_parse_modified(row[4]),
            last_user_input=_parse_modified(row[5]),
            step_count=int(row[6] or 0),
        )
        for row in rows
        if row and row[0]
    ]
    seen_ids = {conv.conversation_id for conv in out}
    for entry in _load_bindings().values():
        cid = entry.get("agy_conversation_id")
        if not isinstance(cid, str) or not cid or cid in seen_ids:
            continue
        t_path = transcript_path(cid)
        try:
            st_mtime = t_path.stat().st_mtime
        except OSError:
            continue
        directory = entry.get("directory")
        out.append(
            AgyConversation(
                conversation_id=cid,
                title="",
                preview="",
                workspace=directory.strip() if isinstance(directory, str) else "",
                last_modified=st_mtime,
                last_user_input=st_mtime,
                step_count=0,
            )
        )
        seen_ids.add(cid)
    out.sort(key=lambda c: c.last_modified, reverse=True)
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


def _squeeze(text: str) -> str:
    """去掉全部空白字符，抹平输入框折行与段落缩进差异。"""
    return "".join(text.split())


def _first_user_input_from_transcript(path: Path) -> tuple[float | None, str]:
    """从转录文件开头读取首条 ``USER_INPUT`` 的创建时刻（epoch 秒）与原始 ``content``。

    首条用户输入恒在开头几行，只读头部最多 64KB 即可，不扫整份大文件。
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(64 * 1024).decode("utf-8", errors="replace")
    except OSError:
        return None, ""
    for raw_line in head.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == RECORD_USER_INPUT:
            dt = _parse_timestamp(rec.get("created_at"))
            ts = dt.timestamp() if dt is not None else None
            content = rec.get("content")
            return ts, (content if isinstance(content, str) else "")
    return None, ""


def _recent_history_entries(since_s: float) -> list[tuple[str, str]]:
    """读取 ``history.jsonl`` 尾部在 ``since_s`` 之后提交的 ``(workspace, squeezed_text)``。"""
    path = history_path()
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > 64 * 1024:
                fh.seek(size - 64 * 1024)
                chunk = fh.read()
                _, _, chunk = chunk.partition(b"\n")
            else:
                chunk = fh.read()
        lines = chunk.decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries: list[tuple[str, str]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        dt = _parse_timestamp(rec.get("timestamp"))
        if dt is not None and dt.timestamp() + 1.0 < since_s:
            continue
        workspace = rec.get("workspace")
        text = rec.get("text")
        if isinstance(workspace, str) and isinstance(text, str) and text.strip():
            entries.append((workspace, _squeeze(text)))
    return entries


def _history_contradicts_workspace(
    candidates: set[str], since_s: float, squeezed_tail: str
) -> bool:
    """若 ``history.jsonl`` 存在且记下了含 ``squeezed_tail`` 的近期输入，核对是否全落在别的目录。"""
    entries = _recent_history_entries(since_s)
    if not entries:
        return False
    matched_workspaces = [
        ws for ws, text in entries if squeezed_tail in text or text[-32:] in squeezed_tail
    ]
    if not matched_workspaces:
        return False
    return not any(
        ws in candidates or normalize_directory(ws) in candidates for ws in matched_workspaces
    )


def _iter_fresh_unclaimed_transcripts(
    since_s: float,
    taken: set[str],
    conversations: dict[str, AgyConversation],
    matches_workspace: Any,
) -> list[tuple[float, str, str]]:
    """枚举 ``brain/`` 下未认领、修改时刻不早于 ``since_s`` 且首条用户输入不早于 ``since_s`` 的转录。

    返回 ``[(moment, conversation_id, first_user_content), ...]``，按 ``moment`` 升序。
    ``transcript.jsonl`` 的 ``created_at`` 精确到整秒（无毫秒小数），而 ``since_ms`` 含毫秒，
    故时刻比较统一留 1 秒整秒截断余量（``+ 1.0 >= since_s``）。
    """
    root = brain_root()
    if not root.is_dir():
        return []
    fresh: list[tuple[float, str, str]] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return []
    for dentry in entries:
        if not dentry.is_dir():
            continue
        cid = dentry.name
        if cid in taken:
            continue
        conv = conversations.get(cid)
        if conv is not None and conv.workspace and not matches_workspace(conv):
            continue
        t_path = transcript_path(cid)
        try:
            st = t_path.stat()
        except OSError:
            continue
        if st.st_mtime + 1.0 < since_s:
            continue
        first_ts, first_content = _first_user_input_from_transcript(t_path)
        if first_ts is not None and first_ts + 1.0 < since_s:
            continue
        moment = first_ts if first_ts is not None else st.st_mtime
        fresh.append((moment, cid, first_content))
    fresh.sort(key=lambda item: (item[0], item[1]))
    return fresh


def claim_conversation(
    directory: str,
    since_ms: int,
    *,
    prompt_tail: str | None = None,
    handle: str | None = None,
) -> str | None:
    """认领会话编号：取工作目录匹配、在 ``since_ms`` 之后动过、且还没被认过的那个。

    四个来源依次试：

    1. **实时转录精确因果认领**（``brain/<id>/.system_generated/logs/transcript.jsonl``）——
       agy 在按下回车后 2~4 秒内即写下第 0 步 ``USER_INPUT``，而 ``conversation_summaries.db``
       在首轮连续调工具时可能滞后 60~95 秒才写入。若调用方给出了本次把手 ``handle``（落在
       载体文件路径中）或提示词尾段 ``prompt_tail``，直接与新转录首条用户输入比对，秒级命中。
    2. ``cache/last_conversations.json`` —— 目录最近一场会话线索。摘要库已有行时核对摘要库时刻；
       摘要库尚未刷新时直接核对该会话转录文件的首条记录时刻。
    3. 摘要库按时刻筛 —— 工作目录匹配、最后修改晚于锚点、且未被认过的那些里取**最早**起的那个。
    4. ``history.jsonl`` + 新转录兜底 —— 跨进程未传 ``prompt_tail`` 且摘要库滞后时，用
       ``history.jsonl`` 里记录的同目录近期输入文本配对新转录的首条 ``USER_INPUT``。

    找不到返回 None，NEVER 抛。
    """
    if handle:
        already = get_binding(handle)
        if already:
            return already

    candidates = {directory, normalize_directory(directory)}
    since_s = since_ms / 1000.0
    taken = bound_session_ids()

    def _matches(conv: AgyConversation) -> bool:
        return conv.workspace in candidates or normalize_directory(conv.workspace) in candidates

    conversations = {c.conversation_id: c for c in list_conversations()}

    safe_handle = (
        "".join(c if (c.isalnum() or c in "_-") else "_" for c in handle) if handle else ""
    )
    squeezed_tail = _squeeze(prompt_tail or "")
    fresh_transcripts: list[tuple[float, str, str]] | None = None

    if (len(safe_handle) >= 6) or squeezed_tail:
        fresh_transcripts = _iter_fresh_unclaimed_transcripts(
            since_s, taken, conversations, _matches
        )
        if len(safe_handle) >= 6:
            for _moment, cid, first_content in fresh_transcripts:
                if first_content and safe_handle in first_content:
                    return cid
        if squeezed_tail and not _history_contradicts_workspace(
            candidates, since_s, squeezed_tail
        ):
            for _moment, cid, first_content in fresh_transcripts:
                if first_content and squeezed_tail in _squeeze(first_content):
                    return cid

    hinted = _last_conversation_for(directory)
    if hinted and hinted not in taken:
        conv = conversations.get(hinted)
        if conv is not None:
            if conv.last_modified >= since_s and _matches(conv):
                return hinted
        else:
            t_path = transcript_path(hinted)
            try:
                st = t_path.stat()
            except OSError:
                st = None
            if st is not None and st.st_mtime + 1.0 >= since_s:
                first_ts, _ = _first_user_input_from_transcript(t_path)
                moment = first_ts if first_ts is not None else st.st_mtime
                if moment + 1.0 >= since_s:
                    return hinted

    best: tuple[float, str] | None = None
    for conv in conversations.values():
        if conv.conversation_id in taken or not _matches(conv):
            continue
        if conv.last_modified < since_s:
            continue
        if best is None or conv.last_modified < best[0]:
            best = (conv.last_modified, conv.conversation_id)
    if best is not None:
        return best[1]

    history_tails = [
        text[-32:]
        for ws, text in _recent_history_entries(since_s)
        if (ws in candidates or normalize_directory(ws) in candidates) and text
    ]
    if history_tails:
        if fresh_transcripts is None:
            fresh_transcripts = _iter_fresh_unclaimed_transcripts(
                since_s, taken, conversations, _matches
            )
        for _moment, cid, first_content in fresh_transcripts:
            if not first_content:
                continue
            squeezed_content = _squeeze(first_content)
            if any(ht in squeezed_content for ht in history_tails):
                return cid

    return None


def claim_and_bind(
    frago_session_id: str,
    directory: str,
    since_ms: int,
    *,
    prompt_tail: str | None = None,
) -> str | None:
    """互斥执行「认领 + 落盘绑定」：防止并发会话在各自写绑定前挑中同一个编号。"""
    with _claim_lock:
        existing = get_binding(frago_session_id)
        if existing is not None:
            return existing
        claimed = claim_conversation(
            directory,
            since_ms,
            prompt_tail=prompt_tail,
            handle=frago_session_id,
        )
        if not claimed:
            return None
        put_binding(frago_session_id, claimed, directory)
        return claimed


# ── 身份映射 ────────────────────────────────────────────────────────
def _load_bindings() -> dict[str, dict[str, Any]]:
    """读映射文件。不存在 / 损坏一律当"没有绑定"，NEVER 让调用方崩。"""
    path = _bindings_path()
    try:
        raw = path.read_text(encoding="utf-8")
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
    path = _bindings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(bindings, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
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


def bound_directory(conversation_id: str) -> str | None:
    """从身份映射账本反查该 agy 会话认领时记下的工作目录；没有则 None。

    agy 在冷启动 ``--conversation <id>`` 重建轨迹时可能把 ``conversation_summaries.db``
    里的 ``workspace_uris`` 覆写为空串，但 frago 首次认领该会话时已在 ``agy-sessions.json``
    里记下了真实启动目录，据此兜底。
    """
    if not conversation_id:
        return None
    for entry in _load_bindings().values():
        if entry.get("agy_conversation_id") == conversation_id:
            directory = entry.get("directory")
            if isinstance(directory, str) and directory.strip():
                return directory.strip()
    return None


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
    try:
        from frago.session.async_dispatch import sync_claimed_target_session_id

        sync_claimed_target_session_id(
            frago_session_id,
            conversation_id,
            agent_type="agy",
            cwd=directory,
        )
    except Exception:
        logger.debug(
            "sync_claimed_target_session_id failed for %s -> %s",
            frago_session_id,
            conversation_id,
            exc_info=True,
        )


def drop_binding(frago_session_id: str) -> None:
    """清掉映射（如续接一场已被用户删掉的 agy 会话）。"""
    bindings = _load_bindings()
    if bindings.pop(frago_session_id, None) is None:
        return
    _save_bindings(bindings)


def drop_bindings_pointing_at(conversation_id: str) -> list[str]:
    """清掉所有指向这场 agy 会话的映射，回被清掉的 frago 会话编号。

    与 codex / opencode 同一条规矩：映射的键是 frago 侧的编号、值是 agy 侧的编号，
    两边不是同一个编号空间，按值反查并摘除。
    """
    bindings = _load_bindings()
    dropped = [
        key
        for key, entry in bindings.items()
        if entry.get("agy_conversation_id") == conversation_id
    ]
    if not dropped:
        return []
    for key in dropped:
        del bindings[key]
    _save_bindings(bindings)
    return dropped


# ── 会话删除 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DeletedAgySession:
    """删掉一场 agy 会话在本机落盘后的交代。"""

    conversation_id: str
    removed: list[str]
    problems: list[str]


def _write_json_atomic(path: Path, payload: Any) -> None:
    """先写同目录临时文件再原子替换，避免半截 JSON 把 agy 自己的读取带崩。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except OSError:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _prune_last_conversations(conversation_id: str) -> bool:
    """从 ``cache/last_conversations.json`` 里摘掉指着这场会话的目录映射。"""
    path = last_conversations_path()
    if not path.exists():
        return False
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, TypeError):
        return False
    if not isinstance(parsed, dict):
        return False
    keys = [k for k, v in parsed.items() if v == conversation_id]
    if not keys:
        return False
    for k in keys:
        del parsed[k]
    _write_json_atomic(path, parsed)
    return True


def _prune_conversation_metadata(conversation_id: str) -> bool:
    """从 ``cache/conversation_metadata.json`` 里摘掉这场会话的缓存条目。"""
    path = conversation_metadata_path()
    if not path.exists():
        return False
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, TypeError):
        return False
    if not isinstance(parsed, dict):
        return False
    convs = parsed.get("conversations")
    if not isinstance(convs, dict) or conversation_id not in convs:
        return False
    del convs[conversation_id]
    _write_json_atomic(path, parsed)
    return True


def _is_presence_locked(lock_file: Path) -> bool:
    """检测 ``presence/<id>.lock`` 是否正被活着的 agy 进程持有排他锁。

    本机实测：活着的 agy 进程全程在 ``presence/<id>.lock`` 上持 ``flock`` 排他锁，进程退出后
    0 字节锁文件仍留在盘上但不再持锁。删除前用非阻塞 ``LOCK_EX | LOCK_NB`` 试探一次：拿不到锁
    说明这场会话此刻正有 agy 进程在跑（哪怕不是由 frago 的 tmux 起的），绝不能在它写库时硬删。
    """
    if not lock_file.exists():
        return False
    try:
        import fcntl
    except ImportError:
        return False
    try:
        with lock_file.open("r") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                return False
    except OSError:
        return False


def delete_session_files(conversation_id: str) -> DeletedAgySession | None:
    """全量清理一场 agy 会话在 ``~/.gemini/antigravity-cli/`` 下的落盘数据。

    agy 没有原生删除子命令，但它的落盘边界按会话编号天然隔离：

    1. ``conversation_summaries.db`` 的单表 ``conversation_summaries``（无外键、无触发器）
       ——WebUI 左栏与 ``agy`` 列表都读它，先删这一行；
    2. ``brain/<id>/`` —— 转录 ``transcript.jsonl`` 与工件目录，家族判定与会话详情读它；
    3. ``conversations/<id>.db``（含 ``-wal`` / ``-shm``）—— 单场独立的步骤 protobuf 库；
    4. ``annotations/<id>.pbtxt`` 与 ``presence/<id>.lock`` —— 标题注解与锁文件；
    5. ``cache/last_conversations.json`` 与 ``cache/conversation_metadata.json`` 里的对应键值。

    动手前先探 ``presence/<id>.lock`` 上有没有活着的 agy 进程持锁：有就抛 ``OSError``，一个文件
    都不动。**绝不碰 ``~/.frago/sessions/agy/`` 下的备份副本**，那份归 ``frago session search``
    检索用。本机已经没有任何该会话落盘时返回 None，由调用方转成 404。
    """
    cid = conversation_id.strip()
    if not cid:
        return None

    bdir = brain_dir(cid)
    db_file = conversation_db_path(cid)
    ann_file = annotation_path(cid)
    lock_file = presence_lock_path(cid)
    sum_db = summaries_db_path()

    if _is_presence_locked(lock_file):
        raise OSError(f"这场 agy 会话还在运行（{lock_file.name} 被占用），先结束运行再删")

    in_summaries = False
    if sum_db.exists():
        try:
            conn = sqlite3.connect(str(sum_db), timeout=5.0)
            try:
                row = conn.execute(
                    "SELECT 1 FROM conversation_summaries WHERE conversation_id = ? LIMIT 1",
                    (cid,),
                ).fetchone()
                in_summaries = row is not None
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise OSError(f"摘要库打不开：{exc}") from exc

    has_files = bdir.is_dir() or db_file.exists() or ann_file.exists() or lock_file.exists()
    if not in_summaries and not has_files:
        return None

    removed: list[str] = []
    problems: list[str] = []

    if in_summaries:
        try:
            conn = sqlite3.connect(str(sum_db), timeout=5.0)
            try:
                conn.execute(
                    "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                    (cid,),
                )
                conn.commit()
            finally:
                conn.close()
            removed.append(f"摘要库记录 {sum_db}")
        except sqlite3.Error as exc:
            raise OSError(f"摘要库记录没删掉：{exc}") from exc

    if bdir.is_dir() and bdir.name == cid:
        try:
            shutil.rmtree(bdir)
            removed.append(f"会话目录 {bdir}")
        except OSError as exc:
            if not removed:
                raise
            problems.append(f"会话目录没删掉：{exc}")

    if db_file.exists() or Path(f"{db_file}-wal").exists() or Path(f"{db_file}-shm").exists():
        db_err: OSError | None = None
        for target in (db_file, Path(f"{db_file}-wal"), Path(f"{db_file}-shm")):
            if not target.exists():
                continue
            try:
                target.unlink()
            except OSError as exc:
                db_err = exc
        if db_err is not None:
            if not removed:
                raise db_err
            problems.append(f"会话库没删掉：{db_err}")
        else:
            removed.append(f"会话库 {db_file}")

    if ann_file.exists():
        try:
            ann_file.unlink()
            removed.append(f"会话注解 {ann_file}")
        except OSError as exc:
            problems.append(f"会话注解没删掉：{exc}")

    if lock_file.exists():
        try:
            lock_file.unlink()
            removed.append(f"在线锁 {lock_file}")
        except OSError as exc:
            problems.append(f"在线锁没删掉：{exc}")

    try:
        if _prune_last_conversations(cid):
            removed.append(f"目录最近会话映射 {last_conversations_path()}")
    except OSError as exc:
        problems.append(f"目录最近会话映射没摘掉：{exc}")

    try:
        if _prune_conversation_metadata(cid):
            removed.append(f"元数据缓存 {conversation_metadata_path()}")
    except OSError as exc:
        problems.append(f"元数据缓存没摘掉：{exc}")

    return DeletedAgySession(conversation_id=cid, removed=removed, problems=problems)
