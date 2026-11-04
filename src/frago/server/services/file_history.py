"""一份文件「改动之前」那一侧从哪来，以及两边怎么对齐着摆。

浮窗的「Changes」那一档要左右对照：左边是改动之前、右边是现在。**会话记录里没有文件的
快照**——它只记着「谁在什么时候动了哪个路径」，没记那一刻文件长什么样。所以左边这一侧取自
**git 的 HEAD**：这份文件在工作区里，git 里存着它的上一版。

三条边界写在这里，界面上照这三条说：

**它不是「这场会话开始那一刻」的快照。** HEAD 是最后一次提交，不是会话的起点。会话改的
东西若已经被提交，两边就一样了；反过来，工作区里别人改的、还没提交的东西也算进了这一侧。
界面上那行小字说的是实话：这一侧来自 git。

**不在 git 仓库里的文件没有左边。** 产物常常写在 `~/.frago/data` 下，那里不是仓库。那时
左边整列空着，界面写「这份不在 git 仓库里，没有上一版可对照」——不许假装它是新建的。

**新建的文件也没有左边。** git HEAD 里没有这个路径就是这一场新建的，那整份都是新增。

分层：服务端一层（跑 git、算对齐），NEVER 从这里 import `cli/`。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from frago.server.services.subprocess_utils import get_utf8_env

__all__ = [
    "Before",
    "EDIT_BASELINE_SOURCE",
    "added_rows",
    "before_at_head",
    "clear_edit_baselines",
    "diff_rows",
    "get_edit_baseline",
    "record_edit_baseline",
]

# `git show` 在一个仓库上很快；卡住的仓库（索引锁之类）不该把一条请求挂死。
GIT_TIMEOUT = 20

# 左边那一侧为什么没有正文。
NO_BEFORE_NEW = "new"
"""git HEAD 里没有这个路径：这一场新建的。"""

NO_BEFORE_NOT_GIT = "not-git"
"""这份文件不在 git 仓库里，没有上一版可对照。"""

NO_BEFORE_TOO_LARGE = "too-large"
"""上一版太大，没往这边搬。**不许当它是新建的**——那是两回事。"""

GIT_SOURCE = "git HEAD"
"""正文来自哪儿。界面上那行小字照它写。"""

EDIT_BASELINE_SOURCE = "编辑前快照"
"""非 git 或未提交新建文件在会话内首次被人类 Edit 保存前留下的基线。"""

_session_edit_baselines: dict[tuple[str, str], str] = {}


def record_edit_baseline(sid: str, resolved_path: str, before_text: str) -> None:
    """记录某场会话中某份文件首次被人类编辑保存前的原文，供后续版本比较对照。"""
    key = (sid, resolved_path)
    if key not in _session_edit_baselines:
        _session_edit_baselines[key] = before_text


def get_edit_baseline(sid: str, resolved_path: str) -> str | None:
    """读取该会话中该文件首次编辑前的原文快照；未编辑过返回 None。"""
    return _session_edit_baselines.get((sid, resolved_path))


def clear_edit_baselines() -> None:
    """清空内存中的编辑前快照（供单测隔离使用）。"""
    _session_edit_baselines.clear()



@dataclass(frozen=True)
class Before:
    """改动之前的那一侧。"""

    text: str | None
    """正文。取不到为 None，看 `reason`。"""

    reason: str | None
    """:data:`NO_BEFORE_NEW` / :data:`NO_BEFORE_NOT_GIT`。有正文时为 None。"""

    source: str | None
    """正文的来源。没有正文时为 None。"""


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=get_utf8_env(),
        timeout=GIT_TIMEOUT,
        check=False,
    )


def before_at_head(path: str, *, max_bytes: int) -> Before:
    """这份文件在 git HEAD 里的那一版。

    ``path`` 得是已经存在的文件，调用方负责先确认（不存在时这一侧本来也没什么可比的）。
    超出 ``max_bytes`` 的一律当没有：**不给半份**。
    """
    target = Path(path)
    root_result = _git(["rev-parse", "--show-toplevel"], target.parent)
    if root_result.returncode != 0:
        return Before(None, NO_BEFORE_NOT_GIT, None)
    root = Path(root_result.stdout.strip())
    if not root.is_dir():
        return Before(None, NO_BEFORE_NOT_GIT, None)
    try:
        # 按仓库根算相对路径：`git show` 认的是仓库内的位置，不是磁盘上的绝对路径。
        rel = target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # 文件不在这个仓库底下（仓库根是软链、文件在别处之类）。
        return Before(None, NO_BEFORE_NOT_GIT, None)

    shown = _git(["show", f"HEAD:{rel}"], root)
    if shown.returncode != 0:
        return Before(None, NO_BEFORE_NEW, None)
    if len(shown.stdout.encode("utf-8", "replace")) > max_bytes:
        return Before(None, NO_BEFORE_TOO_LARGE, None)
    return Before(shown.stdout, None, GIT_SOURCE)


def _lines(text: str) -> list[str]:
    """正文切成行。**末尾那个换行不另起一空行**：行数要与编辑器里看到的一致，
    不然每一份文件底下都多出一格空白，像是漏了一行。

    代价说在明处：只多／少了末尾那个换行时，两边看不出差别（git 那边会写
    「\\ No newline at end of file」，这里不写）。
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def diff_rows(before: str, after: str) -> list[list[dict | None]]:
    """两边的正文对齐成一行一格，给界面上左右两列照着摆。

    每一行是一对「左边那一格、右边那一格」，各格可能是 None（那一侧这一行没有东西，
    例如整行是删掉的时候右边空着）。**对齐**是这里最要紧的事：左右同一行说的得是同一处，
    界面才敢并排摆；按最长公共子序列配对，删的那几行与增的那几行按先后两两对上。

    对齐在服务端做（Python 的 difflib），不是因为这边更强，是因为它是唯一一处**两边都在**
    的地方：前端只拿得到现在这一份，左边那一侧本来就要从这里取。
    """
    a = _lines(before)
    b = _lines(after)

    rows: list[list[dict | None]] = []
    dels: list[dict] = []
    adds: list[dict] = []

    def flush() -> None:
        # 删与增按先后两两配对，多出来的那侧留空格——两列因此始终在同一格栅行上对齐。
        for i in range(max(len(dels), len(adds))):
            rows.append([dels[i] if i < len(dels) else None, adds[i] if i < len(adds) else None])
        dels.clear()
        adds.clear()

    # autojunk 关掉：大文件里重复的行很多，开了它 difflib 会把高频行当噪声丢掉，对齐就歪了。
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            flush()
            for k in range(i2 - i1):
                rows.append([
                    {"sign": " ", "no": i1 + k + 1, "text": a[i1 + k]},
                    {"sign": " ", "no": j1 + k + 1, "text": b[j1 + k]},
                ])
            continue
        for k in range(i1, i2):
            dels.append({"sign": "-", "no": k + 1, "text": a[k]})
        for k in range(j1, j2):
            adds.append({"sign": "+", "no": k + 1, "text": b[k]})
    flush()
    return rows


def added_rows(after: str) -> list[list[dict | None]]:
    """没有左边那一侧时的样子：整份都是新增，左边整列空着。"""
    return [
        [None, {"sign": "+", "no": i + 1, "text": line}]
        for i, line in enumerate(_lines(after))
    ]
