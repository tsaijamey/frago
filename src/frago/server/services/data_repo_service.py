"""The data repository: what is waiting to be backed up, and driving the backup.

``~/.frago`` is the user's own working directory — recipes, knowledge books,
task output, hook rules — kept in a private GitHub repository of their own.
Between syncs it accumulates: on a machine in daily use, tens of thousands of
changed files is normal, not exceptional. That number is the whole reason this
exists as a page rather than a line in settings; nobody reviews 26,000 files by
scrolling, and nobody remembers to run `git push` in a directory they never cd
into.

Two jobs here:

1. Say what is pending, in a shape a person can act on — totals, a rollup by
   top-level area, and a capped sample of actual paths. Never the whole list:
   a megabyte of JSON to render a scrollbar helps nobody.
2. Hand an agent the job of grouping, committing and pushing it, with the
   repository's own governance rules baked into the brief.

On (2): the rules below are *distilled* from ``~/.frago/AGENTS.md``, not read
out of it. That file is 300 lines, and a large part of it is history — a 2026-05
history rewrite, a re-baseline that has since converged, a salvage incident, an
unrelated-histories branch that only existed because of a one-off filter-repo
run. Feeding all of that to an agent does not make it more careful; it makes it
act on contracts that expired. What stays here is what still decides an
outcome today.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.subprocess_utils import get_utf8_env

logger = logging.getLogger(__name__)

# How many individual paths the status endpoint will hand back. The rollup and
# the totals describe the whole set; this is a sample so the page can show real
# names, not an attempt to ship the entire index.
DEFAULT_FILE_LIMIT = 500
MAX_FILE_LIMIT = 2000

# `git status` on a working directory this size takes well under a second, but
# a wedged index lock would otherwise hang the request forever.
GIT_TIMEOUT = 30


def repo_path() -> Path:
    """Where the data repository lives."""
    return Path(os.environ.get("FRAGO_HOME") or (Path.home() / ".frago"))


def _git(*args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path()), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=get_utf8_env(),
        timeout=timeout,
        check=False,
    )


# ----------------------------------------------------------------------------
# What is not backed up, and why
# ----------------------------------------------------------------------------

# Shown in the confirmation dialog before anything runs. The user is about to
# publish their own working directory to a repository; they are owed a plain
# statement of what is deliberately left behind — otherwise "同步到仓库" reads
# like a promise of a complete backup, which it is not and should not be.
EXCLUDED_CATEGORIES: list[dict[str, Any]] = [
    {
        "key": "browser",
        "title": "浏览器身份与配置",
        "examples": ["chrome_profile*/", "edge_profile*/", "profiles/", "chrome/extension-profile/"],
        "why": "登录态和 cookie 只对这台机器有效，换台设备拿去也用不了，传上去反而是把身份凭证外泄。",
    },
    {
        "key": "session",
        "title": "会话与运行记录",
        "examples": ["sessions/", "executions/", "traces/", "threads/", "logs/", "projects/misc/"],
        "why": "每开一个会话就刷一批，属于本机簿记。唯一的例外是 sessions/claude-misc/ —— 那批录像已定型且是唯一存世的一份，照常同步。",
    },
    {
        "key": "cache",
        "title": "缓存与可再生产物",
        "examples": ["cache/", ".cache/", "__pycache__/", "*.pyc", "current_run"],
        "why": "丢了能再算出来，占体积却不带信息。",
    },
    {
        "key": "device-state",
        "title": "设备状态文件",
        "examples": ["config.json", "profiles.json", "gui_config.json", "runtime.json", "sessions.json", ".device_id"],
        "why": "里面是这台机器的端口、路径、账号选择。同步过去会把另一台设备的配置覆盖掉。",
    },
    {
        "key": "secret",
        "title": "凭证与私钥",
        "examples": [".env", ".env.*", "certs/", "*.pem", "*.key"],
        "why": "仓库是私有的，但私有不等于该放密钥。这一类无论如何都不进 git。",
    },
    {
        "key": "binary",
        "title": "媒体与大体积二进制",
        "examples": ["*.mp4 *.mov *.wav *.mp3", "*.png *.jpg *.webp", "*.pdf *.zip *.tar.gz"],
        "why": "git 存不好二进制，每改一次留一整份。需要的设备自己取，仓库不当搬运工。早期已经跟踪的图片不受影响。",
    },
    {
        "key": "vendor",
        "title": "第三方项目的完整检出",
        "examples": ["tools/seed-vc/ 这类 clone 下来的开源仓库"],
        "why": "别处能自取，仓库不做搬运工。",
    },
]

# The other half of the same answer: what *does* go up. Without this the dialog
# only says what the user loses, and "同步到仓库" starts to look pointless.
INCLUDED_AREAS: list[dict[str, str]] = [
    {"path": "recipes/", "note": "配方定义（.py/.md/.json 等），配方跑出来的数据和媒体不进"},
    {"path": "community-recipes/", "note": "社区配方"},
    {"path": "books/", "note": "知识领域的全部条目"},
    {"path": "workspaces/", "note": "各设备收上来的 skills / commands / 项目记忆"},
    {"path": "data/", "note": "直驱任务的工作区产出，文本部分"},
    {"path": "projects/<域>/", "note": "文本形态的运行状态与产出：metadata.json、steps.jsonl、summary、insights/"},
    {"path": "todo/", "note": "跨设备的待办定义"},
    {"path": "hook-rules.json", "note": "hook 规则"},
    {"path": "AGENTS.md / .gitignore", "note": "治理文档与忽略规则本身"},
]


def get_policy() -> dict[str, Any]:
    """What the confirmation dialog shows before the user commits to a sync."""
    return {"excluded": EXCLUDED_CATEGORIES, "included": INCLUDED_AREAS}


# ----------------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------------

_STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "conflicted",
    "?": "untracked",
    "!": "ignored",
}


def _classify(code: str) -> str:
    """Reduce a two-letter porcelain code to the one word the page shows."""
    if code == "??":
        return "untracked"
    # Index side wins when both are set: it is the more advanced state.
    for char in (code[0], code[1] if len(code) > 1 else " "):
        if char != " " and char in _STATUS_LABELS:
            return _STATUS_LABELS[char]
    return "modified"


def _top_level(path: str) -> str:
    """The area a path belongs to, for the rollup.

    Twenty-six thousand paths become comprehensible the moment they are grouped
    by where they live — `data/` being 18,000 of them is the fact that decides
    what the user does next.
    """
    head, _, rest = path.partition("/")
    return f"{head}/" if rest else head


def get_status(limit: int = DEFAULT_FILE_LIMIT) -> dict[str, Any]:
    """What is waiting to be backed up.

    Returns ``configured: False`` rather than raising when ``~/.frago`` is not
    a git repository yet — that is a setup state to explain on the page, not an
    error to throw at the user.
    """
    limit = max(0, min(limit, MAX_FILE_LIMIT))
    path = repo_path()

    result: dict[str, Any] = {
        "configured": False,
        "repo_path": str(path),
        "remote_url": None,
        "branch": None,
        "ahead": 0,
        "behind": 0,
        "pending_total": 0,
        "counts": {},
        "rollup": [],
        "files": [],
        "truncated": False,
        "last_commit": None,
        "error": None,
    }

    if not (path / ".git").exists():
        return result

    try:
        remote = _git("remote", "get-url", "origin")
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        result["configured"] = True
        result["remote_url"] = remote.stdout.strip() or None
        result["branch"] = branch.stdout.strip() or None

        # Ahead/behind against the tracking branch. A repository that has never
        # been pushed has no upstream; that is a zero, not a failure.
        counts = _git("rev-list", "--left-right", "--count", "@{upstream}...HEAD")
        if counts.returncode == 0:
            parts = counts.stdout.split()
            if len(parts) == 2:
                result["behind"], result["ahead"] = int(parts[0]), int(parts[1])

        last = _git("log", "-1", "--format=%H%x1f%s%x1f%cI")
        if last.returncode == 0 and last.stdout.strip():
            sha, subject, when = (last.stdout.strip().split("\x1f") + ["", "", ""])[:3]
            result["last_commit"] = {"sha": sha[:9], "subject": subject, "committed_at": when}

        # -uall so an untracked directory counts as its files rather than as
        # one line: "1 pending" and "1,866 pending" are different decisions.
        status = _git("status", "--porcelain", "-uall", "-z")
        if status.returncode != 0:
            result["error"] = status.stderr.strip() or "git status failed"
            return result

        by_status: dict[str, int] = {}
        by_area: dict[str, int] = {}
        files: list[dict[str, str]] = []
        total = 0

        # -z is NUL-separated; a rename additionally carries its old path as a
        # second NUL-terminated field, which is why this walks an iterator
        # instead of splitting into a list.
        entries = iter(status.stdout.split("\0"))
        for entry in entries:
            if not entry:
                continue
            # Codes are two columns wide and may themselves contain a space
            # (" M" = modified in the worktree only), so this slices by
            # position rather than splitting on whitespace.
            code, name = entry[:2], entry[3:]
            if not name:
                continue
            kind = _classify(code)
            if kind == "renamed":
                # Consume the paired old path so it is not counted twice.
                next(entries, None)

            total += 1
            by_status[kind] = by_status.get(kind, 0) + 1
            area = _top_level(name)
            by_area[area] = by_area.get(area, 0) + 1
            if len(files) < limit:
                files.append({"path": name, "status": kind})

        result["pending_total"] = total
        result["counts"] = by_status
        result["files"] = files
        result["truncated"] = total > len(files)
        result["rollup"] = [
            {"area": area, "count": count}
            for area, count in sorted(by_area.items(), key=lambda kv: -kv[1])
        ]

    except subprocess.TimeoutExpired:
        result["error"] = "git 响应超时，仓库可能正被另一个进程占用"
    except Exception as e:  # noqa: BLE001 - the page has to render regardless
        logger.warning("Failed to read data repo status: %s", e)
        result["error"] = str(e)

    return result


# ----------------------------------------------------------------------------
# The brief handed to the agent
# ----------------------------------------------------------------------------

# Distilled from ~/.frago/AGENTS.md — the rules that still decide an outcome.
# Deliberately left out, because acting on them today would be wrong:
#   - the 2026-05 history rewrite and the re-baseline that followed it
#     (converged; local and origin have shared history again)
#   - the unrelated-histories path (`merge --allow-unrelated-histories`), which
#     only existed because of that one-off filter-repo run — offering it now
#     invites an agent to reach for it when a plain rebase is correct
#   - the 2026-05-23 salvage incident and the deleted sync_repo.py post-mortem
#   - collect/deploy of workspaces, which is a different operation than
#     "commit what is pending and push it"
_GOVERNANCE = """\
## 这个仓库同步什么、不同步什么

唯一准则：**只同步「可跨设备复用的策展知识与用户配置」；一切「设备本地的运行时 /
缓存 / 可再生 / 瞬时状态」绝不进同步。判断不确定 → 默认不同步。**

判定按顺序问两句，不能颠倒：

1. 本机自己还要不要这份内容？——不要就删除，不是加 .gitignore。把「本机也不要」的
   废料塞进 .gitignore 是判断错位：它需要的是删除，不是永久居留证。
2. 另一台设备同步之后，会不会需要用到？——会用到就提交；绝对不会就不提交；拿不准
   回到唯一准则，默认不同步。

.gitignore 只适用于第三种情形：本机要、他机不要（profile、缓存、含本机绝对路径的
脚本——本机离了它不行，他机拿去没用）。

判的时候看内容，不要只看目录名，三样东西最能说明问题：内容里有没有本机绝对路径或
本机身份；是不是第三方产物、别处能自取；是不是运行中途的瞬时状态。

### 该提交的（RESOURCE）

workspaces/、recipes/（**仅定义**：.py .md .js .json .html .css .yaml；配方跑出的
数据和媒体不进）、community-recipes/、books/、data/、todo/、hook-rules.json、
AGENTS.md 与根 .gitignore、projects/<命名域>/ 下的**文本** run-state 与产出
（metadata.json、steps.jsonl、summary.{json,md}、_domain.json、insights/，以及
scripts/ outputs/ 里的文本与代码）、sessions/claude-misc/（唯一放行的 sessions 子目录）。

**已确定属于 RESOURCE 的新增与修改，一律无条件提交**，不得以「不是这次会话产生的」
「不确定是否就绪」为由搁置——作者本来就是各设备上的 agent，留在工作区不发布等于丢失。
「不确定就不动」只约束「这东西到底算 RESOURCE 还是 RUNTIME」拿不准的情形。

（这条只管新增和修改。**删除走下面单独一节**，判据完全不同。）

### 不该提交的（RUNTIME / device-local，多数已在 .gitignore）

浏览器 profile 与扩展目录；sessions/（claude-misc 除外）、executions/、traces/、
threads/、logs/、cache/、.cache/、tmp/；projects/misc/；二进制与媒体
（*.mp4 *.wav *.png *.jpg *.pdf *.zip 等）；设备状态 json（config.json、
profiles.json、gui_config.json、runtime.json、sessions.json、feishu_poll_state.json、
client_version、schedules.json、codex-sessions.json、opencode-sessions.json）；
.device_id 一类本机标识；轮转日志（*.log 以及 *.log.1 这类带序号的）；
第三方项目的完整检出。

**这几个是凭据，无论 .gitignore 里有没有写，一律不许提交**——`~/.frago` 根目录下的
`.gitignore` 可能还没跟上，你不能拿「它没被忽略」当成可以提交的理由：

- `server-token` —— 本机 API 的 bearer，拿到它等于拿到这台机器上的 /api
- `remotes.json` —— 其他机器的 url 和 token
- `config.yaml` —— frago cloud 的 access / refresh token
- `users.json`、`users.json.lock` —— 账号口令散列
- `login-sessions/` —— 会话文件，持有即等于持有它指向的账号
- `certs/`、`*.pem`、`*.key`、`.env`、`.env.*`

碰到其中任何一个既没被忽略、又出现在待提交清单里：**不要提交，报告出来**，并建议把它
加进 `.gitignore`。

### 不可违反的硬规则

1. **禁止 `git add -f` 绕过 .gitignore**。被忽略的文件被忽略是有意的。
2. 新增一类文件前先判定 RESOURCE / RUNTIME，RUNTIME 就加 .gitignore，RESOURCE 才
   `git add`。不得「先 add 再说」。
3. .gitignore 顶层条目必须用 `/` 根锚定（写 `/data/` 不写 `data/`），裸目录名会匹配
   任意层级，误伤 workspaces 下的同名嵌套目录。
4. 要 untrack 已被忽略的文件，用 `git rm --cached` 保留工作文件。
5. **提交前自检**：`git ls-files -c -i --exclude-standard` 应为空（没有误 track 被忽略
   的文件）。早期已跟踪的图片会持续报出，属已知偏差，不必处理。

### 删除：必须归因，绝不跟着工作区一起删

工作区里少了一个文件，先分清是「本来就没传上去的新增」还是「被有意删掉的东西」——
看 git 历史能不能把这个缺失归到一次明确的删除动作上：

```
能归因到一次有意的删除      → 传播删除，提交它
只是对端还没有这个文件       → 那是新增，提交新增
归因不清 / 两边都动过        → 保守保留，既不擅自删也不复活
```

**绝不因为「工作区里没有了」就单方把它从仓库里删掉。**

尤其注意成规模的删除。少数几个文件消失，读一下历史就能判断；**几百上千个文件同时
显示为删除，默认当成异常而不是用户意图**——可能是某个清理脚本跑过、某次迁移没收尾、
某个目录被临时挪走。这种情况**停下来报告**：说清是哪个目录、多少个文件、git 历史里
它们是怎么进来的，让人来判断。不要把它当成一次普通的 `git add -A`。

判先进只有一个最终依据：**内容**。commit 时间会骗人（回退和抢救都会「晚提交盖旧内容」），
文件 mtime 更没有意义（git checkout 会把它重置成拉取时间）。

### 推送

`main` 是唯一权威历史。同步 = `git pull --rebase origin main` 之后 `git push origin main`。
不开 per-device 长期分支。append-only 的文件（如 insight.jsonl）rebase 冲突时两边条目
全部保留，`git add` 后 `git rebase --continue`。

推送被拒绝、或 rebase 出现你读不懂的冲突时，**停下来把情况写清楚**，不要 `--force`。"""


_GROUPING = """\
## 分组、提交、推送的原则

分组的判据是「这些文件是否服务于同一个意图」，不是它们在不在同一个目录。四个维度，
从强到弱：同一件事涉及的文件归一组，哪怕跨目录；改动性质相同的归一组（新增、修复、
重构、文档、配置各自成组）；有依赖关系的必须同组；文件类型只在前三条都分不出时才用。

几条经验：配置与文档各自独立成组；一个 commit 里塞进多个不相关的意图是典型的坏味道，
宁可拆细；某个文件同时属于两组，说明这次改动本身混了两件事。

commit message 学这个仓库既有的风格——先 `git log --oneline -20` 看它用什么语言、
用不用 conventional commits、scope 怎么写，然后与之一致，不要套用通用模板。主题行说
清这一组干了什么，正文说清为什么。

**署名用当前仓库身份**（`git config user.name` / `user.email`），NEVER 写成 Claude 或
任何非人类身份。

**不要加 `--no-verify`**，hooks 必须跑。某一组提交失败就停在那里说清楚，不要跳过它继续
提交后面的组。"""


_SAFETY = """\
## 提交前必须扫一遍

文件列表里出现 `.env`、`credentials.json`、私钥、token 一类凭据文件 → 停下来报告，
不要提交，并建议加进 .gitignore。

diff 内容里出现疑似密钥、密码、API token 的字符串同样要停——文件名安全不代表内容安全。"""


def build_sync_prompt(mode: str, instruction: str | None = None) -> str:
    """The brief the agent gets.

    ``mode`` is "all" (back up everything that qualifies) or "selective" (the
    user described in their own words what they want this time).

    One thing this brief must do that a normal /git-push cannot: tell the agent
    the human has *already* approved. The interactive flow stops and waits for
    someone to okay the grouping — here that approval happened in the dialog
    before this was ever called, and nobody is watching a terminal. An agent
    that stops to ask would simply hang.
    """
    parts: list[str] = [
        "把 ~/.frago（frago 数据仓库）里待提交的改动，按意图分组提交，然后推送到 origin/main。",
        "",
        "这是用户在 frago 的网页界面上按下「同步到仓库」触发的。**用户已经在界面上确认过了**——",
        "不要再呈现方案等人点头，不要问「是否继续」，没有人在终端前面看着。分好组就提交，提交完就推送。",
        "只有在遇到这四类情况时才停下，并把原因写清楚：凭据可能泄漏、推送被拒绝、冲突读不懂、",
        "成规模的删除归因不清（见下面「删除」一节——这一条最容易被当成普通改动放过去）。",
        "",
    ]

    if mode == "selective" and instruction and instruction.strip():
        parts += [
            "## 这次只备份用户指定的部分",
            "",
            "用户的原话：",
            "",
            f"> {instruction.strip()}",
            "",
            "先按这句话圈定范围，再在范围内按下面的原则分组。范围之外的改动**这次不要碰**——",
            "不提交、也不改动它们。如果这句话指的范围在工作区里根本不存在，不要自作主张扩大范围，",
            "把「没找到匹配的改动」说清楚就结束。",
            "",
        ]
    else:
        parts += [
            "## 这次备份全部符合条件的改动",
            "",
            "工作区里凡是符合下面「该提交」判定的，全部提交。不符合的一个都不要碰。",
            "",
        ]

    parts += [
        _GOVERNANCE,
        "",
        _GROUPING,
        "",
        _SAFETY,
        "",
        "## 收尾",
        "",
        "全部提交完成后 `git push origin main`。推送成功后用这三条自检，都满足才算完成：",
        "",
        "```",
        "git rev-list --left-right --count main...origin/main   # 应为 0  0",
        "git status -s                                          # 只剩被忽略的 runtime",
        "git ls-files -c -i --exclude-standard                  # 应为空（早期图片的已知偏差除外）",
        "```",
        "",
        "最后用中文说清楚：分了几组、每组是什么、推送结果如何、有没有你决定不碰的东西以及为什么。",
    ]

    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Driving the sync
# ----------------------------------------------------------------------------


class DataRepoSync:
    """Tracks the one sync run this server has going, if any.

    Only one at a time: two agents grouping and committing the same working
    directory would interleave their `git add`s and produce commits neither of
    them intended.
    """

    _lock = threading.Lock()
    _current: dict[str, Any] | None = None

    @classmethod
    def start(cls, mode: str, instruction: str | None = None) -> dict[str, Any]:
        from frago.server.services.agent_service import AgentService

        with cls._lock:
            if cls._is_running_locked():
                return {
                    "status": "error",
                    "error": "已经有一次同步在跑了，等它结束再开下一次。",
                    "already_running": True,
                    "task": cls._public_locked(),
                }

        prompt = build_sync_prompt(mode, instruction)
        result = AgentService.start_task(prompt=prompt, project_path=str(repo_path()))

        if result.get("status") != "ok":
            return {"status": "error", "error": result.get("error", "启动 agent 失败")}

        with cls._lock:
            cls._current = {
                "task_id": result.get("id"),
                "session_id": result.get("claude_session_id"),
                "pid": result.get("pid"),
                "mode": mode,
                "instruction": instruction if mode == "selective" else None,
                "started_at": datetime.now().isoformat(),
            }
            task = cls._public_locked()

        return {"status": "ok", "already_running": False, "task": task}

    @classmethod
    def get(cls) -> dict[str, Any]:
        with cls._lock:
            return {"running": cls._is_running_locked(), "task": cls._public_locked()}

    @classmethod
    def _is_running_locked(cls) -> bool:
        """Is the agent process still alive?

        The agent is a detached subprocess, so liveness is the pid — there is no
        callback when it finishes. A pid that has been reused by an unrelated
        process would read as "still running"; the window is minutes and the
        only cost is a stale spinner, so this stays simple rather than tracking
        process start times.
        """
        current = cls._current
        if not current or not current.get("pid"):
            return False
        try:
            os.kill(int(current["pid"]), 0)
            return True
        except (OSError, ValueError):
            return False

    @classmethod
    def _public_locked(cls) -> dict[str, Any] | None:
        if not cls._current:
            return None
        return dict(cls._current)

    @classmethod
    def reset(cls) -> None:
        """Forget the tracked run. For tests."""
        with cls._lock:
            cls._current = None
