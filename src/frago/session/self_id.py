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


@dataclass(frozen=True)
class CliAgentSpec:
    """单家 CLI Agent 的展示名与提交签名元数据。"""

    agent_type: str
    display_name: str
    url: str

    @property
    def generated_with(self) -> str:
        return f"🤖 Generated with [{self.display_name}]({self.url})"


CLI_AGENTS: dict[str, CliAgentSpec] = {
    "claude": CliAgentSpec(
        agent_type="claude",
        display_name="Claude Code",
        url="https://claude.com/claude-code",
    ),
    "codex": CliAgentSpec(
        agent_type="codex",
        display_name="Codex CLI",
        url="https://github.com/openai/codex",
    ),
    "opencode": CliAgentSpec(
        agent_type="opencode",
        display_name="opencode",
        url="https://opencode.ai",
    ),
    "agy": CliAgentSpec(
        agent_type="agy",
        display_name="Antigravity CLI",
        url="https://antigravity.google",
    ),
    "coreagent": CliAgentSpec(
        agent_type="coreagent",
        display_name="CoreAgent",
        url="https://frago.ai",
    ),
}

_AGENT_ALIASES: dict[str, str] = {
    "claude": "claude",
    "claude-code": "claude",
    "claudecode": "claude",
    "codex": "codex",
    "codex-cli": "codex",
    "opencode": "opencode",
    "agy": "agy",
    "antigravity": "agy",
    "antigravity-cli": "agy",
    "coreagent": "coreagent",
    "frago-core": "coreagent",
}


@dataclass
class SelfAgent:
    """当前命令所处的 CLI Agent 身份及提交签名。"""

    agent_type: str
    display_name: str
    url: str
    generated_with: str
    source: str            # env:<VAR> | process:<comm> | transcript-mtime
    session_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_cli_agent(raw: str | None) -> str | None:
    """把各种习惯叫法归一成标准 agent_type（claude/codex/opencode/agy/coreagent）。"""
    if not raw:
        return None
    return _AGENT_ALIASES.get(raw.strip().lower())


def _build_self_agent(
    agent_type: str,
    *,
    source: str,
    session_id: str | None = None,
) -> SelfAgent:
    spec = CLI_AGENTS[agent_type]
    return SelfAgent(
        agent_type=spec.agent_type,
        display_name=spec.display_name,
        url=spec.url,
        generated_with=spec.generated_with,
        source=source,
        session_id=session_id,
    )


def _session_id_for_agent(agent_type: str, environ: dict[str, str] | os._Environ[str]) -> str | None:
    """按已认出的 agent_type 从环境里捞出对应的会话 id（若有）。"""
    env_by_agent: dict[str, tuple[str, ...]] = {
        "claude": ("CLAUDE_CODE_SESSION_ID", "FRAGO_SESSION_ID"),
        "agy": ("ANTIGRAVITY_CONVERSATION_ID", "FRAGO_SESSION_ID"),
        "codex": ("CODEX_THREAD_ID", "FRAGO_SESSION_ID"),
        "opencode": ("OPENCODE_SESSION_ID", "FRAGO_SESSION_ID"),
        "coreagent": ("FRAGO_SESSION_ID",),
    }
    for key in env_by_agent.get(agent_type, ("FRAGO_SESSION_ID",)):
        val = (environ.get(key) or "").strip()
        if val:
            return val
    return None


def _classify_process_entry(comm: str, args: str) -> tuple[str | None, str | None, bool]:
    """判定单条进程记录属于哪家 CLI Agent。

    返回 ``(agent_type, source, stop_walking)``。遇到 ``tmux`` 服务进程时 ``stop_walking=True``：
    tmux 之上的父进程属于启动 tmux server 的那一场（可能是别的 CLI Agent），不能再往上追。
    """
    import shlex

    comm_str = comm.strip()
    args_str = args.strip()
    comm_name = Path(comm_str).name.lower() if comm_str else ""
    try:
        tokens = shlex.split(args_str) if args_str else []
    except ValueError:
        tokens = args_str.split()
    arg0_name = Path(tokens[0]).name.lower() if tokens else ""

    if comm_name.startswith("tmux") or arg0_name.startswith("tmux"):
        return None, None, True

    names = {comm_name, arg0_name} - {""}
    if names & {"agy", "antigravity-cli"}:
        matched = "agy" if "agy" in names else "antigravity-cli"
        return "agy", f"process:{matched}", True
    if "codex" in names:
        return "codex", "process:codex", True
    if names & {"opencode", ".opencode"}:
        return "opencode", "process:opencode", True
    if (
        "claude" in names
        or "/.local/share/claude/versions/" in comm_str
        or "/.local/share/claude/versions/" in args_str
        or "@anthropic-ai/claude-code" in args_str
    ):
        return "claude", "process:claude", True
    if "frago-core" in names and "--engine" not in tokens:
        return "coreagent", "process:frago-core", True

    return None, None, False


def _walk_process_chain(
    process_chain: list[tuple[str, str]] | None = None,
    *,
    max_depth: int = 16,
) -> tuple[str, str] | None:
    """从父进程一路往上找最近的 CLI Agent 进程（到 tmux 或 init 为止）。"""
    import subprocess

    if process_chain is not None:
        for comm, args in process_chain:
            agent_type, source, stop = _classify_process_entry(comm, args)
            if agent_type and source:
                return agent_type, source
            if stop:
                break
        return None

    pid = os.getppid()
    visited: set[int] = set()
    for _ in range(max_depth):
        if pid <= 1 or pid in visited:
            break
        visited.add(pid)
        try:
            proc = subprocess.run(
                ["ps", "-o", "ppid=,comm=,args=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except Exception:
            break
        line = (proc.stdout or "").strip()
        if not line:
            break
        parts = line.split(None, 2)
        if len(parts) < 2:
            break
        try:
            ppid = int(parts[0])
        except ValueError:
            break
        comm = parts[1]
        args = parts[2] if len(parts) > 2 else comm
        agent_type, source, stop = _classify_process_entry(comm, args)
        if agent_type and source:
            return agent_type, source
        if stop:
            break
        pid = ppid
    return None


def _detect_agent_from_env(
    environ: dict[str, str] | os._Environ[str],
    *,
    cwd: str,
    projects_root: Path,
) -> SelfAgent | None:
    """按环境变量识别当前 CLI Agent。

    各家给子进程注入的自报变量优先于通用 ``FRAGO_SESSION_ID``。
    """
    explicit = normalize_cli_agent(environ.get("FRAGO_CLI_AGENT"))
    if explicit:
        return _build_self_agent(
            explicit,
            source="env:FRAGO_CLI_AGENT",
            session_id=_session_id_for_agent(explicit, environ),
        )

    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDECODE"):
        val = (environ.get(key) or "").strip()
        if val:
            sid = (environ.get("CLAUDE_CODE_SESSION_ID") or "").strip() or None
            return _build_self_agent("claude", source=f"env:{key}", session_id=sid)

    for key in ("ANTIGRAVITY_CONVERSATION_ID", "ANTIGRAVITY_AGENT", "ANTIGRAVITY_CLI_ALIAS"):
        val = (environ.get(key) or "").strip()
        if val:
            sid = (environ.get("ANTIGRAVITY_CONVERSATION_ID") or "").strip() or None
            return _build_self_agent("agy", source=f"env:{key}", session_id=sid)

    for key in ("CODEX_THREAD_ID", "CODEX_CI", "CODEX_SANDBOX"):
        val = (environ.get(key) or "").strip()
        if val:
            sid = (environ.get("CODEX_THREAD_ID") or "").strip() or None
            return _build_self_agent("codex", source=f"env:{key}", session_id=sid)

    for key in ("OPENCODE_SESSION_ID", "OPENCODE"):
        val = (environ.get(key) or "").strip()
        if val:
            sid = (environ.get("OPENCODE_SESSION_ID") or "").strip() or None
            return _build_self_agent("opencode", source=f"env:{key}", session_id=sid)

    if (environ.get("AI_AGENT") or "").strip().lower() == "opencode":
        sid = (environ.get("OPENCODE_SESSION_ID") or "").strip() or None
        return _build_self_agent("opencode", source="env:AI_AGENT", session_id=sid)

    frago_sid = (environ.get("FRAGO_SESSION_ID") or "").strip()
    if frago_sid:
        if frago_sid.startswith("core_"):
            return _build_self_agent("coreagent", source="env:FRAGO_SESSION_ID", session_id=frago_sid)
        if frago_sid.startswith("ses_"):
            return _build_self_agent("opencode", source="env:FRAGO_SESSION_ID", session_id=frago_sid)
        with contextlib.suppress(Exception):
            from frago.session import record_reader

            family = normalize_cli_agent(record_reader.detect_family(frago_sid))
            if family:
                return _build_self_agent(family, source="env:FRAGO_SESSION_ID", session_id=frago_sid)
        if locate_transcript(frago_sid, cwd=cwd, projects_root=projects_root):
            return _build_self_agent("claude", source="env:FRAGO_SESSION_ID", session_id=frago_sid)

    return None


def resolve_self_agent(
    *,
    cwd: str | None = None,
    projects_root: Path | None = None,
    env: dict[str, str] | None = None,
    process_chain: list[tuple[str, str]] | None = None,
    max_age_s: float = FALLBACK_MAX_AGE_S,
) -> SelfAgent | None:
    """解析当前命令跑在哪一家 CLI Agent 里；认不出时返回 ``None``。

    判据次序：
    1. 显式声明 ``FRAGO_CLI_AGENT``。
    2. 真实运行时（或显式传入 ``process_chain``）顺着父进程链向上找最近的 CLI Agent 进程
       （到 ``tmux`` 为止）——能避免上层会话遗留在 tmux server 里的环境变量串台。
    3. 各家 CLI Agent 注入的环境变量（``CLAUDE_CODE_SESSION_ID`` / ``ANTIGRAVITY_CONVERSATION_ID``
       / ``CODEX_THREAD_ID`` / ``OPENCODE_SESSION_ID`` / ``FRAGO_SESSION_ID`` 等）。
    4. 当前工作目录最近写入的会话记录兜底。
    """
    environ = os.environ if env is None else env
    here = cwd or os.getcwd()
    root = projects_root or CLAUDE_PROJECTS_DIR

    explicit = normalize_cli_agent(environ.get("FRAGO_CLI_AGENT"))
    if explicit:
        return _build_self_agent(
            explicit,
            source="env:FRAGO_CLI_AGENT",
            session_id=_session_id_for_agent(explicit, environ),
        )

    if env is None or process_chain is not None:
        proc_hit = _walk_process_chain(process_chain)
        if proc_hit is not None:
            agent_type, source = proc_hit
            return _build_self_agent(
                agent_type,
                source=source,
                session_id=_session_id_for_agent(agent_type, environ),
            )

    env_hit = _detect_agent_from_env(environ, cwd=here, projects_root=root)
    if env_hit is not None:
        return env_hit

    session_hit = resolve_self(cwd=here, projects_root=root, env=environ, max_age_s=max_age_s)
    if session_hit is not None:
        normalized = normalize_cli_agent(session_hit.agent)
        if normalized:
            return _build_self_agent(
                normalized,
                source=session_hit.source,
                session_id=session_hit.session_id,
            )

    return None
