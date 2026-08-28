"""「我是谁」——解析当前这场会话的 id。

会话结束时把没做完的事写成待办，光写清楚剩什么是不够的：接手的人还要能回到当时
的原话去看细节。会话 id 就是回去的那把钥匙。可 agent 自己往往报不出这个 id——它
不在提示词里，只在启动它的环境里。这个模块负责把它找出来。

三条来源，从确定到推断：

1. ``FRAGO_SESSION_ID`` —— 调用方显式声明。frago 起 worker、或非 Claude 的命令行
   agent 想让自己被认出来时，导出这个变量即可。
2. ``CLAUDE_CODE_SESSION_ID`` —— Claude Code 自己注入的，日常最常命中的一条。
3. 当前工作目录对应的记录目录里、最近还在写的那份 ``<sid>.jsonl`` —— 前两条都没有
   时的兜底。它是**推断**：同一个目录下同时开着两场会话时会挑错。所以结果里带
   ``certain=False``，调用方要么提示人确认，要么干脆别用。

拿不到就返回 ``None``，NEVER 编一个 id 出来——一个错的会话 id 比没有更糟，它会把
下一个 agent 送去看一场不相干的对话。
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.monitor import encode_project_path
from frago.session.transcript_completion import locate_transcript

# 调用方显式声明的优先，其次是 Claude Code 自己注入的。
ENV_KEYS = ("FRAGO_SESSION_ID", "CLAUDE_CODE_SESSION_ID")

# 兜底时只认「最近还在写」的记录：当前这场会话每调一次工具就会追加一行，文件修改
# 时间是秒级新鲜的。一小时以外的那些是别的会话留下的，认了就是认错人。
FALLBACK_MAX_AGE_S = 3600


@dataclass
class SelfSession:
    """当前这场会话的身份。"""

    session_id: str
    source: str            # env:<VAR> | transcript-mtime
    certain: bool          # False = 按最近写入推断出来的，可能挑错
    agent: str             # claude / unknown
    cwd: str
    transcript: str | None  # 原始记录文件；找不到不代表 id 是错的
    resume_command: str | None
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _newest_transcript(cwd: str, projects_root: Path, max_age_s: float) -> tuple[Path | None, int]:
    """当前目录的记录里，最近还在写的那一份；以及同样新鲜的一共有几份。

    第二个返回值是给「可能挑错」这句话找证据用的：同一目录下同时有两份在写，说明
    此刻确实开着两场会话。
    """
    proj_dir = projects_root / encode_project_path(cwd)
    if not proj_dir.is_dir():
        return None, 0
    cutoff = time.time() - max_age_s
    fresh = []
    for path in proj_dir.glob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            fresh.append((mtime, path))
    if not fresh:
        return None, 0
    fresh.sort(reverse=True)
    return fresh[0][1], len(fresh)


def resolve_self(
    *,
    cwd: str | None = None,
    projects_root: Path | None = None,
    env: dict[str, str] | None = None,
    max_age_s: float = FALLBACK_MAX_AGE_S,
) -> SelfSession | None:
    """解析当前会话；解析不出来返回 ``None``。"""
    environ = os.environ if env is None else env
    here = cwd or os.getcwd()
    root = projects_root or CLAUDE_PROJECTS_DIR

    for key in ENV_KEYS:
        sid = (environ.get(key) or "").strip()
        if not sid:
            continue
        transcript = locate_transcript(sid, cwd=here, projects_root=root)
        return SelfSession(
            session_id=sid,
            source=f"env:{key}",
            certain=True,
            agent="claude" if transcript else "unknown",
            cwd=here,
            transcript=str(transcript) if transcript else None,
            resume_command=f"claude --resume {sid}" if transcript else None,
            note=None if transcript else "没找到对应的原始记录文件，id 本身仍以环境变量为准",
        )

    path, fresh_count = _newest_transcript(here, root, max_age_s)
    if path is None:
        return None

    sid = path.stem
    note = "按当前目录最近写入的记录推断，不是环境声明的"
    if fresh_count > 1:
        note += f"；同一目录下还有 {fresh_count - 1} 份记录同样在写，可能挑错"
    return SelfSession(
        session_id=sid,
        source="transcript-mtime",
        certain=False,
        agent="claude",
        cwd=here,
        transcript=str(path),
        resume_command=f"claude --resume {sid}",
        note=note,
    )
