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

**会话编号带 ``core_`` 前缀**，与 opencode 的 ``ses_`` 是同一个办法：判这场属于哪一家只看
前缀，不用去三家的档案里挨个试。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

from pathlib import Path

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

__all__ = [
    "SESSION_ID_PREFIX",
    "CoreAgentRecordAdapter",
    "delete_session_files",
    "find_session_file",
    "session_exists",
    "sessions_root",
]

#: 会话编号的前缀。frago-core 那边生成编号时写的也是它（``kernel/transcript_log.rs``）。
SESSION_ID_PREFIX = "core_"


def sessions_root() -> Path:
    """CoreAgent 会话记录的根目录。"""
    return Path.home() / ".frago" / "coreagent" / "sessions"


def find_session_file(session_id: str, root: Path | None = None) -> Path | None:
    """按会话编号找到那个 JSONL。找不到返回 None，NEVER 抛。"""
    return _find_file(session_id, root if root is not None else sessions_root())


def session_exists(session_id: str, root: Path | None = None) -> bool:
    """本机还有没有这场会话的记录。"""
    return find_session_file(session_id, root) is not None


def delete_session_files(
    session_id: str, root: Path | None = None
) -> DeletedSessionFiles | None:
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
