"""codex 会话记录（rollout JSONL）的读取层。

codex 把每个会话写成一个 JSONL «rollout» 文件，落在
``$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<本地时间>-<session_id>.jsonl``。
每行一条记录，形如 ``{"type": ..., "payload": {...}}``，本模块只认其中四类：

``session_meta``
    首行。带 ``session_id`` / ``cwd`` / ``timestamp``，是会话身份与归属目录的来源。
``event_msg`` → ``task_started`` / ``task_complete``
    一轮的开始与结束。``task_complete`` 带 ``turn_id``、``last_agent_message``
    （本轮终答，可能为 null）与可选的 ``error``。这是本模块判「本轮答完没有」的
    **唯一权威**，读屏只是它不可用时的退路。
``response_item``
    模型侧的结构化条目：``message``（含 role）、``function_call`` 与
    ``function_call_output``、``reasoning``。会话归档与流式据此还原对话。

与 opencode 的差别只有存储介质（文件 vs SQLite），身份问题是同一个：codex 不接受
「用我给的 id 建会话」，只接受 ``codex resume <id>`` 续接，所以一个新会话的 id 是
**认领**来的——按工作目录 + 起始时间窗从 rollout 目录里挑出那个刚建的文件。认领
结果落在 ``~/.frago/codex-sessions.json``，与 opencode 的映射文件同一套做法。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# frago 侧的身份映射文件：frago 会话标识 → codex 原生会话 id。设备本地产物，
# 与 opencode 的映射文件同级同规格。
BINDINGS_PATH = Path.home() / ".frago" / "codex-sessions.json"

# 完成探针每次回读的字节数。rollout 文件是整段对话的流水账，长会话能到几十 MB，
# 而探针在一轮里要被调用几十次——每次整读一遍是没必要的开销。一轮的
# ``task_started`` / ``task_complete`` 永远贴在文件末尾，故只回读末段。
#
# 判定逻辑本身 NEVER 依赖窗口罩得住 ``task_started``：它只看「窗口里最后出现的是
# 开始还是结束」，某一轮的工具输出撑爆窗口把开始记录挤出去时，结论依然正确。
_TAIL_BYTES = 256 * 1024


# ── 路径 ────────────────────────────────────────────────────────────
def get_codex_home() -> Path:
    """codex 的家目录。``CODEX_HOME`` 优先——codex 自己就是这么解析的。"""
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex"


def is_codex_present() -> bool:
    """codex 在这台机器上看起来装了没有。"""
    return get_codex_home().is_dir() or shutil.which("codex") is not None


def sessions_root() -> Path:
    """rollout 文件的根目录（不创建）。"""
    return get_codex_home() / "sessions"


def normalize_directory(directory: str) -> str:
    """把工作目录归一化到解析过软链接的真实路径。

    codex 的 ``session_meta.cwd`` 记的是真实路径：macOS 上 ``/tmp`` 是指向
    ``/private/tmp`` 的软链接，tmux 以 ``-c /tmp/x`` 起来时会话自己看到的 cwd 还是
    ``/tmp/x``。不归一化就精确匹配，认领永远落空，而且是**静默**落空——认不到就
    没有绑定，完成探针全程弃权，本轮悄悄退回读屏。
    """
    try:
        return os.path.realpath(directory)
    except OSError:
        return directory


# ── rollout 文件定位 ────────────────────────────────────────────────
@dataclass(frozen=True)
class RolloutMeta:
    """一个 rollout 文件的门面信息（首行 ``session_meta``）。"""

    session_id: str
    path: Path
    cwd: str
    started_at: datetime | None
    mtime: float


def _iter_rollout_paths() -> list[Path]:
    """列出全部 rollout 文件，按修改时间从新到旧。

    目录不存在 / 不可读时返回空列表，NEVER 抛——codex 没装、或者还没跑过任何
    会话，都是完全正常的状态。
    """
    root = sessions_root()
    try:
        paths = list(root.glob("*/*/*/rollout-*.jsonl"))
    except OSError as exc:
        logger.debug("codex rollout listing failed: %s", exc)
        return []
    stamped: list[tuple[float, Path]] = []
    for path in paths:
        try:
            stamped.append((path.stat().st_mtime, path))
        except OSError:
            continue
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in stamped]


def _read_meta(path: Path) -> RolloutMeta | None:
    """读一个 rollout 的首行 ``session_meta``。读不出来返回 None。

    只读首行：``session_meta`` 是 codex 写进去的第一条记录，为了拿会话 id 去整读
    一个几十 MB 的流水账没有道理。
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            first = fh.readline()
    except OSError as exc:
        logger.debug("codex rollout meta read failed for %s: %s", path, exc)
        return None
    if not first.strip():
        return None
    try:
        record = json.loads(first)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id") or payload.get("id")
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return RolloutMeta(
        session_id=session_id,
        path=path,
        cwd=str(payload.get("cwd") or ""),
        started_at=_parse_timestamp(payload.get("timestamp")),
        mtime=mtime,
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_rollout(session_id: str) -> Path | None:
    """定位某个 codex 会话的 rollout 文件。

    文件名里就带着会话 id，故先按名字直接 glob；命中不了才退回逐个读首行——
    codex 换过一次文件名格式的话，慢路径仍然能找到。
    """
    root = sessions_root()
    try:
        direct = sorted(root.glob(f"*/*/*/rollout-*-{session_id}.jsonl"))
    except OSError:
        direct = []
    if direct:
        return direct[-1]
    for path in _iter_rollout_paths():
        meta = _read_meta(path)
        if meta is not None and meta.session_id == session_id:
            return path
    return None


def session_exists(session_id: str) -> bool:
    """该 codex 会话的记录还在不在。

    ``sessions/`` 整个不存在时返回 True：读不到不等于会话没了，NEVER 因为一次
    读不到就把一条好绑定清掉（与 opencode 侧同一条原则）。
    """
    if not sessions_root().is_dir():
        return True
    return find_rollout(session_id) is not None


def claim_session(directory: str, since_ms: int) -> str | None:
    """认领会话：取工作目录匹配、且文件在 ``since_ms`` 之后才出现的最新那个。

    codex 的会话文件在 TUI 起来那一刻就建好（不像 opencode 要等首轮提交），所以
    认领的起算点锚在**启动之前**即可。目录先按真实路径比，未命中再按调用方给的
    原值比一次，两侧都试过才不会因为软链接差异静默落空。找不到返回 None，NEVER 抛。
    """
    candidates = {normalize_directory(directory), directory}
    since_s = since_ms / 1000.0
    for path in _iter_rollout_paths():
        meta = _read_meta(path)
        if meta is None:
            continue
        if meta.mtime < since_s:
            # 列表按 mtime 降序，走到比锚点还旧的就没有更新的了。
            break
        if meta.cwd in candidates or normalize_directory(meta.cwd) in candidates:
            return meta.session_id
    return None


def list_sessions(limit: int | None = None) -> list[RolloutMeta]:
    """列出本机的 codex 会话，最新在前。供会话索引 / WebUI 列表用。"""
    out: list[RolloutMeta] = []
    for path in _iter_rollout_paths():
        meta = _read_meta(path)
        if meta is None:
            continue
        out.append(meta)
        if limit is not None and len(out) >= limit:
            break
    return out


# ── 记录读取 ────────────────────────────────────────────────────────
def _iter_records(path: Path, *, tail_bytes: int | None = None) -> list[dict[str, Any]]:
    """把一个 rollout 读成记录列表；坏行跳过。

    ``tail_bytes`` 给定时只回读末段，并丢弃第一条（很可能被切成半行）的残缺行。
    """
    try:
        if tail_bytes is None:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
        else:
            size = path.stat().st_size
            with path.open("rb") as fh:
                if size > tail_bytes:
                    fh.seek(size - tail_bytes)
                    chunk = fh.read()
                    # 首行多半被从中间切断，丢掉它。
                    _, _, chunk = chunk.partition(b"\n")
                else:
                    chunk = fh.read()
            lines = chunk.decode("utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.debug("codex rollout read failed for %s: %s", path, exc)
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


def _payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class CodexTurn:
    """从 rollout 读出的最新一轮。"""

    turn_id: str | None
    """本轮的 ``turn_id``；同时充当去重锚点（每轮唯一）。"""

    done: bool
    """本轮是否已终结（末尾最后出现的是 ``task_complete`` 而不是 ``task_started``）。"""

    text: str
    """本轮终答。``task_complete.last_agent_message`` 优先，缺失时回落到本轮最后
    一条 assistant 消息的正文。"""

    error: str | None
    """codex 给这一轮标的错误（如 provider 拒绝）；正常收尾时为 None。"""


def latest_turn(session_id: str) -> CodexTurn | None:
    """读该会话最新一轮的完成状态与终答。定位不到 / 读不出时返回 None。

    判据只看**末段里最后出现的是开始还是结束**：``task_complete`` 在后就是答完，
    ``task_started`` 在后就是还在跑。这样即使某一轮的工具输出把 ``task_started``
    挤出回读窗口，结论依然正确——而按「配对 turn_id」判就会在那种情况下永远判不出
    答完，本轮空等到超时。
    """
    path = find_rollout(session_id)
    if path is None:
        return None
    records = _iter_records(path, tail_bytes=_TAIL_BYTES)
    if not records:
        return None

    started_turn: str | None = None
    complete: dict[str, Any] | None = None
    last_is_complete = False
    assistant_text: str | None = None

    for record in records:
        payload = _payload(record)
        kind = payload.get("type")
        if record.get("type") == "event_msg":
            if kind == "task_started":
                started_turn = payload.get("turn_id") or started_turn
                last_is_complete = False
            elif kind == "task_complete":
                complete = payload
                last_is_complete = True
        elif (
            record.get("type") == "response_item"
            and kind == "message"
            and payload.get("role") == "assistant"
        ):
            text = _message_text(payload)
            if text:
                assistant_text = text

    if complete is None and not last_is_complete:
        # 窗口里只有开始、没有结束：本轮还在跑。
        return CodexTurn(turn_id=started_turn, done=False, text="", error=None)
    if not last_is_complete:
        return CodexTurn(turn_id=started_turn, done=False, text="", error=None)

    payload = complete or {}
    final = payload.get("last_agent_message")
    text = final if isinstance(final, str) and final.strip() else (assistant_text or "")
    error = payload.get("error")
    if isinstance(error, dict):
        error = error.get("message") or json.dumps(error, ensure_ascii=False)
    elif error is not None and not isinstance(error, str):
        error = str(error)
    return CodexTurn(
        turn_id=payload.get("turn_id") or started_turn,
        done=True,
        text=text,
        error=error or None,
    )


def _message_text(payload: dict[str, Any]) -> str:
    """把一条 ``message`` 记录的正文拼出来。

    ``content`` 是分块数组，每块形如 ``{"type": "output_text", "text": ...}``。
    非文本块（图片等）没有可拼的正文，跳过。
    """
    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "".join(parts).strip()


# ── 记录归一化（流式与归档共用） ────────────────────────────────────
RECORD_USER_TEXT = "user_text"
RECORD_TEXT = "text"
RECORD_TOOL_CALL = "tool_call"
RECORD_TOOL_RESULT = "tool_result"


def record_payloads(
    record: dict[str, Any], session_id: str, *, include_user: bool = False
) -> list[tuple[str, dict[str, Any]]]:
    """把一条 rollout 记录翻成 0~1 条 ``(种类, 归一化记录字典)``。

    记录字典就是 ``session.monitor`` 的 codex adapter 的入参形状。种类只告诉调用方
    这是用户正文 / 助手正文 / 工具调用 / 工具结果，adapter 不看它。

    取哪几类记录是有讲究的。rollout 里同一句话往往出现两遍——一遍是发给模型的
    ``response_item``，一遍是给界面看的 ``event_msg``——而两者的内容并不等价：

    - 用户那半轮取 ``event_msg`` 的 ``user_message``，**不取** ``response_item``
      的 user 消息。后者里混着 codex 自己拼进去的 ``<environment_context>``，取它
      会让会话详情里每条用户消息都顶着一段环境说明，真正的提问被淹没。
    - 助手那半轮取 ``event_msg`` 的 ``agent_message``，只要 ``final_answer`` 这一
      相位，中途的阶段性发言不算终答。
    - frago 经钩子注入的上下文在 rollout 里是 ``role: developer`` 的消息。这里一条
      都不取，注入因此天然不会回流进归档——不像 opencode 那边得把注入从用户正文里
      再剥一次。
    - 工具调用与结果取 ``response_item``，它们只有这一种表示。
    - ``reasoning`` / ``token_count`` / ``world_state`` / ``turn_context`` 等一律丢弃。

    ``include_user`` 为假时不产出用户那半轮：实时流里用户消息由主路径自己投递，
    重复投会在前端出现两遍；归档要它。
    """
    kind = record.get("type")
    payload = _payload(record)
    inner = payload.get("type")
    timestamp = _parse_timestamp(record.get("timestamp")) or datetime.now()
    base = {
        "session_id": session_id,
        "timestamp": timestamp,
        "role": "assistant",
    }

    if kind == "event_msg":
        if inner == "user_message":
            if not include_user:
                return []
            text = payload.get("message")
            if not isinstance(text, str) or not text.strip():
                return []
            return [
                (
                    RECORD_USER_TEXT,
                    {
                        **base,
                        "role": "user",
                        "uuid": f"user_message:{record.get('timestamp')}",
                        "content": text,
                    },
                )
            ]
        if inner == "agent_message":
            if payload.get("phase") not in (None, "final_answer"):
                return []
            text = payload.get("message")
            if not isinstance(text, str) or not text.strip():
                return []
            return [
                (
                    RECORD_TEXT,
                    {
                        **base,
                        "uuid": f"agent_message:{record.get('timestamp')}",
                        "content": text,
                    },
                )
            ]
        return []

    if kind != "response_item":
        return []

    if inner == "function_call":
        call_id = payload.get("call_id") or payload.get("id") or ""
        return [
            (
                RECORD_TOOL_CALL,
                {
                    **base,
                    "uuid": str(payload.get("id") or call_id),
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "name": payload.get("name") or "",
                            "input": _decode_arguments(payload.get("arguments")),
                        }
                    ],
                },
            )
        ]

    if inner == "function_call_output":
        call_id = payload.get("call_id") or ""
        output = payload.get("output")
        return [
            (
                RECORD_TOOL_RESULT,
                {
                    **base,
                    "uuid": str(payload.get("id") or f"{call_id}:result"),
                    "content": "",
                    "tool_results": [
                        {
                            "tool_use_id": call_id,
                            "content": output if isinstance(output, str) else "",
                            "is_error": bool(payload.get("success") is False),
                        }
                    ],
                },
            )
        ]

    return []


def _decode_arguments(raw: Any) -> dict[str, Any]:
    """``function_call.arguments`` 是一段 JSON 文本；解不出来就当空参数。"""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
        logger.debug("codex bindings file corrupt, treated as empty")
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
    """取该 frago 会话已认领的 codex 会话 id；没有则 None。"""
    entry = _load_bindings().get(frago_session_id)
    if not entry:
        return None
    value = entry.get("codex_session_id")
    return value if isinstance(value, str) and value else None


def put_binding(frago_session_id: str, codex_session_id: str, directory: str) -> None:
    """写入映射。一旦建立就不再重认（重认会让两个会话的记录互串）。"""
    bindings = _load_bindings()
    bindings[frago_session_id] = {
        "frago_session_id": frago_session_id,
        "codex_session_id": codex_session_id,
        "directory": normalize_directory(directory),
        "claimed_at": int(time.time() * 1000),
    }
    _save_bindings(bindings)


def drop_binding(frago_session_id: str) -> None:
    """清掉映射（如续接一个已被用户删掉的 codex 会话）。"""
    bindings = _load_bindings()
    if bindings.pop(frago_session_id, None) is None:
        return
    _save_bindings(bindings)
