"""CoreAgent 那一侧的会话记录在哪儿、怎么找。

CoreAgent 是 frago 自己的 agent（frago-core 的 agent 循环）。它跑定时任务里那类自然语言
任务，一个跑完就退出的子进程。在此之前，它跑的每一步只打到启动它的那个进程的标准输出，
不落盘——调度器只收最后那一行结论，中途执行了哪些命令、哪些被拦下，事后无从查起。

现在它边跑边写一份会话记录，**行的形状与 Claude Code 的会话记录一模一样**。这不是巧合，
是刻意的：frago 的会话页已经有一整套读 Claude Code 记录的判据（二十三条按序命中，见
:mod:`frago.session.adapters.claude_code_records`），自定一套格式等于再写一套判据，两套
迟早各走各的，同一件事在两个地方长得不一样。

**落点不与 Claude Code 共用。** 记录躺在 ``~/.frago/coreagent/sessions/`` 下，目录层级照抄
Claude Code（``<工作目录编码>/<会话编号>.jsonl``），所以读法换个根目录就能用；但两家的清单
分得开——往 ``~/.claude/projects/`` 里塞别人的会话，Claude Code 下次列会话时会把它当成
自己的。

**会话编号带 ``core_`` 前缀**，与 opencode 的 ``ses_`` 是同一个办法：判这场属于哪一家先看
前缀，不用去三家的档案里挨个试。但前缀只是**发号那一侧**的约定：编号由调用方原样递进内核
时（直接起 ``frago-core``），落盘的编号就不带它。所以 ``core_`` 只够一眼认出**是**这一家，
认不出**不是**——编号不带前缀时还要去本模块的目录里认一眼，见
:func:`~frago.session.record_reader.detect_family`。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session.adapters.claude_code_records import (
    ClaudeCodeRecordAdapter,
    DeletedSessionFiles,
)
from frago.session.adapters.claude_code_records import (
    delete_session_files as _delete_files,
)
from frago.session.adapters.claude_code_records import (
    find_session_file as _find_file,
)
from frago.session.models import SessionStatus

__all__ = [
    "COREAGENT_RUNNING_WINDOW_SECONDS",
    "SESSION_ID_PREFIX",
    "CoreAgentRecordAdapter",
    "CoreAgentSessionStats",
    "delete_session_files",
    "find_session_file",
    "inspect_session_file",
    "iter_session_files",
    "session_exists",
    "sessions_root",
]

#: 会话编号的前缀。frago-core 那边生成编号时写的也是它（``kernel/transcript_log.rs``）。
SESSION_ID_PREFIX = "core_"

#: 与 ``session_index.RUNNING_WINDOW_SECONDS`` 对齐：当 CoreAgent 会话停在中间态且距今超过
#: 该窗口仍无新写入时，视为已结束（CoreAgent 是单次进程，收场或中断后不会像常驻 TUI 那样挂数小时）。
COREAGENT_RUNNING_WINDOW_SECONDS = 90.0

_EMPLOYEE_BLOCK_RE = re.compile(
    r"^\s*<frago-employee\b[^>]*>.*?</frago-employee>\s*",
    re.DOTALL,
)

#: 一份会话记录就是一个 JSONL，文件名是会话编号。同一级目录下还有观察者槽位
#: （``observer-*.json``）这类附属文件，认扩展名就不会把它们当成会话。
_RECORD_GLOB = "*.jsonl"


def sessions_root() -> Path:
    """CoreAgent 会话记录的根目录。"""
    return Path.home() / ".frago" / "coreagent" / "sessions"


def iter_session_files(root: Path | None = None) -> list[Path]:
    """本机全部 CoreAgent 会话记录，最新在前。

    落点是 ``<根>/<工作目录编码>/<会话编号>.jsonl``，所以按一级目录下的 ``*.jsonl``
    扫一遍就是全部。读不动的文件跳过，NEVER 因为一个坏文件让整批消失。
    """
    base = root if root is not None else sessions_root()
    if not base.is_dir():
        return []
    stamped: list[tuple[float, Path]] = []
    for path in base.glob(f"*/{_RECORD_GLOB}"):
        try:
            stamped.append((path.stat().st_mtime, path))
        except OSError:
            continue
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in stamped]


def find_session_file(session_id: str, root: Path | None = None) -> Path | None:
    """按会话编号找到那个 JSONL。找不到返回 None，NEVER 抛。"""
    return _find_file(session_id, root if root is not None else sessions_root())


def session_exists(session_id: str, root: Path | None = None) -> bool:
    """本机还有没有这场会话的记录。"""
    return find_session_file(session_id, root) is not None


def delete_session_files(session_id: str, root: Path | None = None) -> DeletedSessionFiles | None:
    """删掉这场会话的记录。找不到返回 None，NEVER 抛。

    删法与 Claude Code 那侧是同一份：记录就是一个 JSONL，位置稳定、格式一样。
    """
    return _delete_files(session_id, root if root is not None else sessions_root())


class CoreAgentRecordAdapter(ClaudeCodeRecordAdapter):
    """CoreAgent 这一家的翻译层。

    **判据一个字不改，只换根目录。** 记录的形状就是 Claude Code 的形状，翻译层照抄下来
    另写一份，两份迟早各走各的——那时同一种记录在两处会翻出不一样的东西，而没有人看得出
    是哪一处错了。
    """

    family = "coreagent"

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root if root is not None else sessions_root())


@dataclass(frozen=True)
class CoreAgentSessionStats:
    """从 CoreAgent JSONL 记录（原件或 ``raw.jsonl`` 镜像）提取的会话运行统计与状态。"""

    started_at: datetime | None
    last_activity: datetime | None
    ended_at: datetime | None
    status: SessionStatus
    step_count: int
    tool_call_count: int
    project_path: str
    name: str | None


def _parse_iso_to_local_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        epoch = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        return datetime.fromtimestamp(epoch)
    except (ValueError, AttributeError, OSError, OverflowError):
        return None


def _extract_first_user_title(content: Any) -> str | None:
    raw_text = ""
    if isinstance(content, str):
        raw_text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                txt = item.get("text")
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt)
        raw_text = "\n".join(parts)
    if not raw_text:
        return None
    cleaned = _EMPLOYEE_BLOCK_RE.sub("", raw_text).strip()
    for line in cleaned.splitlines():
        compact = " ".join(line.split())
        if compact:
            return compact[:80]
    return None


def inspect_session_file(
    path: Path,
    *,
    now: datetime | None = None,
) -> CoreAgentSessionStats | None:
    """解析单份 CoreAgent JSONL（支持原生记录与 ``raw.jsonl`` 镜像）。

    返回 ``started_at``、``last_activity``、``ended_at``、``status``、``step_count``、
    ``tool_call_count``、``project_path`` 与 ``name``。文件不存在或为空时返回 None。
    """
    try:
        st = path.stat()
        if st.st_size <= 0:
            return None
        mtime_dt = datetime.fromtimestamp(st.st_mtime)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    first_dt: datetime | None = None
    last_dt: datetime | None = None
    project_path = ""
    custom_title: str | None = None
    ai_title: str | None = None
    first_user_title: str | None = None
    step_count = 0
    tool_call_count = 0
    last_event_kind: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue

        rec_dt = _parse_iso_to_local_dt(
            record.get("timestamp") or record.get("created_at")
        )
        if rec_dt is not None:
            if first_dt is None:
                first_dt = rec_dt
            last_dt = rec_dt

        if not project_path:
            cwd = record.get("cwd")
            if isinstance(cwd, str) and cwd:
                project_path = cwd

        rec_type = record.get("type")
        if rec_type == "custom-title":
            val = record.get("customTitle")
            if isinstance(val, str) and val.strip():
                custom_title = val.strip()
            continue
        if rec_type == "ai-title":
            val = record.get("aiTitle")
            if isinstance(val, str) and val.strip():
                ai_title = val.strip()
            continue

        if rec_type == "user":
            if record.get("isCompactSummary"):
                continue
            step_count += 1
            last_event_kind = "user"
            if first_user_title is None and not record.get("isMeta"):
                msg = record.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                first_user_title = _extract_first_user_title(content)
        elif rec_type == "assistant":
            msg = record.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            n_tools = 0
            has_text = False
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "tool_use":
                        n_tools += 1
                    elif btype == "text" and str(block.get("text") or "").strip():
                        has_text = True
            elif isinstance(content, str) and content.strip():
                has_text = True
            tool_call_count += n_tools
            if n_tools > 0 or has_text:
                step_count += 1
            last_event_kind = "assistant_tool" if n_tools > 0 else "assistant_text"
        elif rec_type == "system":
            step_count += 1
            subtype = record.get("subtype")
            if subtype in ("turn_duration", "stop_hook_summary"):
                last_event_kind = "turn_end"
            elif last_event_kind is None:
                last_event_kind = "system"

    started_at = first_dt or mtime_dt
    last_activity = mtime_dt
    current = now if now is not None else datetime.now()
    if current.tzinfo is not None:
        current = current.astimezone().replace(tzinfo=None)
    try:
        idle = (current - last_activity).total_seconds()
    except (OverflowError, OSError):
        idle = 0.0

    # 判定状态与 ended_at：
    # 1. 末尾明确落了 turn_duration / stop_hook_summary 收尾记账 → 已结束；
    # 2. 末尾对话停在纯文本 assistant 回复（无待执行 tool_use）→ 已结束；
    # 3. 停在中间态但最后活动距今已超过 COREAGENT_RUNNING_WINDOW_SECONDS（90s）→ 已结束；
    # 4. 其余（刚写入中间态且在 90s 活跃窗口内）→ running。
    if (
        last_event_kind in ("turn_end", "assistant_text")
        or idle > COREAGENT_RUNNING_WINDOW_SECONDS
    ):
        status = SessionStatus.COMPLETED
        ended_at = last_dt or mtime_dt
    else:
        status = SessionStatus.RUNNING
        ended_at = None

    name = custom_title or ai_title or first_user_title
    return CoreAgentSessionStats(
        started_at=started_at,
        last_activity=last_activity,
        ended_at=ended_at,
        status=status,
        step_count=step_count,
        tool_call_count=tool_call_count,
        project_path=project_path,
        name=name,
    )
