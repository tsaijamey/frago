"""「我是谁」——解析当前这场会话的 id。

会话结束时把没做完的事写成待办，光写清楚剩什么是不够的：接手的人还要能回到当时
的原话去看细节。会话 id 就是回去的那把钥匙。可 agent 自己往往报不出这个 id——它
不在提示词里，只在启动它的环境里。这个模块负责把它找出来。

三条来源，从确定到推断：

1. ``CLAUDE_CODE_SESSION_ID`` —— Claude Code 给**它自己这个进程**注入的，关于「我是谁」
   最硬的一条。日常最常命中。
2. ``FRAGO_SESSION_ID`` —— 拉起这个进程的那一方声明它属于哪场会话。coreagent 内核每跑
   一条命令都把它自己那一场的编号带进命令环境（见 frago-core ``src/kernel/tools.rs``），
   非 Claude 的命令行 agent 也靠它被认出来。
3. 当前工作目录对应的记录目录里、最近还在写的那份 ``<sid>.jsonl`` —— 前两条都没有
   时的兜底。它是**推断**：同一个目录下同时开着两场会话时会挑错。所以结果里带
   ``certain=False``，调用方要么提示人确认，要么干脆别用。

**自己报的 id 压过继承来的声明，这个次序不能反。** 一场会话的子进程会把上家的
``FRAGO_SESSION_ID`` 原样带下来；子进程若是 Claude Code，它同时又给自己注入了一个。
两者同时存在且不同时，继承来的那个说的是上家，不是自己。反过来排的话，子进程会集体
认成上家：2026-10-15 实测，我这场的 6 个 worker 全被记到了拉起我这场的 coreagent
名下，那场当时早已不写了。

拿不到就返回 ``None``，NEVER 编一个 id 出来——一个错的会话 id 比没有更糟，它会把
下一个 agent 送去看一场不相干的对话。
"""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.monitor import encode_project_path
from frago.session.transcript_completion import locate_transcript

# 自己报的 id 优先，其次是环境里的声明。次序为什么是这个方向，见模块开头。
ENV_KEYS = ("CLAUDE_CODE_SESSION_ID", "FRAGO_SESSION_ID")

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


def _fallback_roots(claude_root: Path) -> list[tuple[Path, str]]:
    """兜底时按目录翻哪几处记录，以及每处属于哪一家。

    Claude Code 与 CoreAgent 两处的目录层级是同一套
    （``<根>/<编码工作目录>/<编号>.jsonl``），所以一处代码能翻两处。主会话可能是任何
    一家——人自己开的 Claude Code 会话，或者 CoreAgent 那场常驻会话——只看一处的话，
    另一处当主 agent 时就认不出自己是谁。
    """
    roots: list[tuple[Path, str]] = [(claude_root, "claude")]
    with contextlib.suppress(Exception):
        from frago.session import coreagent_store

        core = coreagent_store.sessions_root()
        if core != claude_root:
            roots.append((core, "coreagent"))
    return roots


def _newest_transcript(
    cwd: str, roots: list[tuple[Path, str]], max_age_s: float
) -> tuple[Path | None, str | None, int]:
    """这几处记录里，当前目录下最近还在写的那一份；它属于哪一家；同样新鲜的一共有几份。

    第三个数是给「可能挑错」这句话找证据用的：同一目录下同时有两份在写，说明此刻确实
    开着两场会话。
    """
    cutoff = time.time() - max_age_s
    fresh: list[tuple[float, Path, str]] = []
    for root, family in roots:
        proj_dir = root / encode_project_path(cwd)
        if not proj_dir.is_dir():
            continue
        for path in proj_dir.glob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                fresh.append((mtime, path, family))
    if not fresh:
        return None, None, 0
    fresh.sort(key=lambda item: item[0], reverse=True)
    return fresh[0][1], fresh[0][2], len(fresh)


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

    path, family, fresh_count = _newest_transcript(here, _fallback_roots(root), max_age_s)
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
        agent=family or "unknown",
        cwd=here,
        transcript=str(path),
        resume_command=None,
        note=note,
    )
