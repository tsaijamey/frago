"""一场会话动过哪些文件。

会话详情要能列出「这一场改过、新建了哪些文件」，这份清单就是那一格的来源。它从会话
自己的记录里读出来，**不新埋点**：会话记录里每一次写文件、改文件都留着工具调用的原始
参数，路径就在里面。

五家留下的东西不一样，本模块一家一家地认：

- Claude Code / CoreAgent：``Write``（新建）、``Edit`` / ``MultiEdit`` / ``NotebookEdit``
  （改），路径在 ``args.file_path``。
- opencode：``write``（新建）、``edit``（改），路径在 ``args.filePath``（2.0 起
  ``read`` 那边改名成 ``path``，写侧没动）。
- codex：``apply_patch``（一次补丁改一批文件），路径在补丁头的
  ``*** Add File:`` / ``*** Update File:`` / ``*** Delete File:`` 那几行上。它带的正文就是
  补丁本身，不是一条顺手提到文件名的命令，所以照抄那几行是安全的（见 :func:`_patch_paths`）。
- agy：``write_file`` / ``write_to_file`` / ``create_file``（新建）、``edit_file`` /
  ``replace_file_content`` / ``multi_replace_file_content`` / ``edit_notebook``（改），
  ``delete_file``（删）；路径在 ``args.Path`` / ``args.TargetFile`` / ``args.AbsolutePath``
  / ``args.NotebookPath``（主账 ``transcript.jsonl`` 截断 ``tool_calls`` 时，会把字符串值
  再包一层双引号，取的时候一并剥掉）。

两条边界写在这里，别处不再解释第二遍：

**看不见经由 shell 命令动的文件。** ``mv``、``sed -i``、脚本自己生成的文件，哪一家都
不带结构化字段，所以这份清单是**下界**，不是全集。界面上那行说明说的就是这句话。

**只收写与改，不收读。** ``Read`` / ``read`` / ``grep`` 看过什么不算动过，收进来会把
清单淹掉。以后要「增删改查」全收，在这里开口子，不在调用方各自过滤。

**不收会话工具自己的临时区。** 那些文件确实被这场会话创建过，但人问的是「它在我项目里
改了什么」；中间过程倒出来的东西混进来，真正改过的文件就被淹了。判据见
:func:`is_scratch_path`，本机实测最多的是 opencode 的临时区与它的工具输出目录。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from frago.session import record_reader
from frago.session.record_reader import MAX_LIMIT

__all__ = ["SessionFile", "is_scratch_path", "session_files"]

# 工具名 → 这一下算「新建」「改」还是「删」。键一律小写，比对时也把工具名转小写。
# 同一个文件先写后改，按第一次动它那一下定档（先 Write 就是新建，先 Edit 就是改）。
_CREATE_TOOLS = frozenset({"write", "write_file", "write_to_file", "create_file"})
_DELETE_TOOLS = frozenset({"delete_file"})
_WRITE_TOOLS = frozenset(
    {
        "write",
        "edit",
        "multiedit",
        "notebookedit",
        # agy 的两套写改工具（CLI 当前模型声明 write_file / edit_file，同核另一批模型
        # 声明 write_to_file / replace_file_content / multi_replace_file_content 等）。
        "write_file",
        "write_to_file",
        "create_file",
        "edit_file",
        "replace_file_content",
        "multi_replace_file_content",
        "edit_notebook",
        "delete_file",
    }
)

# codex 的写改工具：一次调用带着一整份补丁，路径在补丁头里（见 :func:`_patch_paths`）。
# 它与上面几个不是一路——那几个一次只说一个文件，路径在一个字段里。
_PATCH_TOOL = "apply_patch"

# 路径在这几个键里，按顺序取第一个命中的。claude 用 file_path、opencode 用 filePath、
# agy 用 Path / TargetFile / AbsolutePath / NotebookPath。
_PATH_KEYS = ("file_path", "filePath", "Path", "TargetFile", "AbsolutePath", "NotebookPath")

# 会话工具自己的临时区。这些文件确实被这场会话创建过，判据上不算错，但它们回答不了
# 「它在我项目里改了什么」——中间过程倒出来的东西混进清单，真正改过的文件就被淹了。
# 本机实测最多的几处：opencode 自己的临时区与工具输出目录、系统临时目录、Claude 自己
# 的 scratchpad（落在系统临时目录下面，被前缀一起盖住）。
_TMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/tmp/", "/private/var/tmp/")

# codex 的补丁头：一次补丁里这几行各点一个文件。``*** Move to:`` 那种改名不放进来——
# 本机实测 65 次补丁里一次都没有，等真出现了再按它该有的样子收（改名前那个路径在改名后
# 就不存在了，照现在这么读会列出一个点不开的路径）。
_PATCH_HEADER_RE = re.compile(r"^\*\*\*\s+(Add|Update|Delete) File:\s*(.+?)\s*$")

_PATCH_ACTION = {"add": "created", "update": "modified", "delete": "deleted"}

# macOS 的按用户临时区长这样：/var/folders/<两位 hash>/<一长串>/T/…。中间两段每台机器、
# 每个用户都不一样，所以按形状认，不按某一个具体目录认——同一台机器上这个月的会话与
# 上个月的，落在的那一段也可能不同。
_FOLDERS_TMP = re.compile(r"^/(?:private/)?var/folders/[^/]+/[^/]+/T/")

# opencode 把工具输出落在这里，那是它自己的工作区，不是人的项目。
_OPENCODE_SCRATCH = (".local", "share", "opencode", "tool-output")

# agy 把每场会话的临时脚本与工具日志落在 ~/.gemini/antigravity-cli/brain/<id>/scratch/
# 与 .system_generated/ 下（系统提示词专门规定临时文件写进 scratch/）。
_AGY_SCRATCH_RE = re.compile(
    r"/(?:\.gemini/)?antigravity(?:-cli)?/brain/[^/]+/(?:scratch|\.system_generated)/"
)

# 一场会话最多读这么多条记录。超了就不再往下翻——大会话整个读一遍代价摆在那儿，
# 而这个数字已经盖住本机绝大多数的会话。
_MAX_RECORDS = 20000


@dataclass(frozen=True)
class SessionFile:
    """这场会话动过的一个文件。"""

    path: str
    """记录里写的那个路径，原样留着（可能是 ``~`` 开头；codex 补丁里那种相对的按会话工作
    目录拼成绝对路径）。"""

    action: str
    """"created"、"modified" 或 "deleted"。**最后那一下说了算**：最后动它是删，就是删掉了
    （文件这会儿不在了）；不然它还在——还在的话，这场会话是不是从零建起来的，看**第一次
    写**它用的是写工具还是改工具，而它前面若先被删过一次，就说明它本来就在，算改不算新建。

    这一条是实测改出来的：一场会话常把「整份换掉」记成先删、紧接着再新建（10 秒内一对），
    只看第一下会把这些文件全报成「已删除」，而它们好好地在磁盘上（2026-10-10）。"""

    count: int
    """这场会话对它动了几次。"""

    first_seq: int
    """第一次动它的那条记录的序号，清单按它排序（会话里的先后顺序）。"""

    @property
    def is_created(self) -> bool:
        return self.action == "created"

    @property
    def is_deleted(self) -> bool:
        return self.action == "deleted"


def _path_in(args: object) -> str | None:
    """从工具参数里取出文件路径。取不到返回 None——宁可不认，也不猜。

    agy 的主账 ``transcript.jsonl`` 在截断 ``tool_calls`` 时，会把每个参数值再序列化一层，
    字符串参数于是变成 ``'"/path/to/file"'``（未截的 ``transcript_full.jsonl`` 里是正常字符串，
    但缺那份时翻译层会退回主账）。成对裹在最外层的双引号一并剥掉，免得退回主账时读出一条带引号
    的假路径。
    """
    if not isinstance(args, dict):
        return None
    for key in _PATH_KEYS:
        value = args.get(key)
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"':
            cleaned = cleaned[1:-1].strip()
        if cleaned:
            return cleaned
    return None


def _patch_paths(args: object, cwd: str | None) -> list[tuple[str, str]]:
    """codex 那一次补丁动过的文件：``(新建/改/删, 路径)``，一次补丁可能好几个。

    补丁正文里 ``*** Add File:`` / ``*** Update File:`` / ``*** Delete File:`` 各点一个文件，
    照抄这些行就是，**不去读补丁体**——读它要认 diff 语法，而认错一行就会把别人的文件算到
    这一场头上。认准「这一格的工具名叫 apply_patch」这个前提，它带的正文就是补丁本身，不是
    某条顺手提到文件名的命令。

    补丁里写的多半是**相对路径**（本机实测 ``note.md``、``src/a.py`` 这种），按这场会话的
    工作目录拼成绝对路径；拼不出（这一场没留下工作目录）就原样留着——清单照实记它动过什么，
    能不能打开是另一层的事。
    """
    if not isinstance(args, dict):
        return []
    text = args.get("input")
    if not isinstance(text, str) or not text:
        return []
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = _PATCH_HEADER_RE.match(line)
        if not m:
            continue
        path = m.group(2)
        if not path:
            continue
        if cwd and not os.path.isabs(path):
            path = os.path.normpath(os.path.join(os.path.expanduser(cwd), path))
        out.append((_PATCH_ACTION[m.group(1).lower()], path))
    return out


def is_scratch_path(path: str) -> bool:
    """这个路径是不是会话工具自己的临时区。

    独立成一条判据、而不是散在过滤的调用点上：口径要改（比如某些临时路径也想留着）时，
    只改这里一处，别处不会各判各的。**只认临时区的根，不认名字里带 tmp 的普通目录**——
    项目里叫 ``tmp/`` 或 ``.tmp/`` 的子目录是人自己的东西，照收。
    """
    p = str(path or "").strip()
    if not p:
        return False
    if p.startswith(_TMP_PREFIXES) or _FOLDERS_TMP.match(p) or _AGY_SCRATCH_RE.search(p):
        return True
    # 后面补一个斜杠，免得一个叫 tool-output-2 的邻居被当成临时区一起滤掉。
    return p.startswith(str(Path.home().joinpath(*_OPENCODE_SCRATCH)) + "/")


def _all_records(session_id: str) -> list:
    """把这场会话的记录一页页读完。到上限就停，不停在半个文件上也没关系——
    清单本来就是下界。"""
    out: list = []
    after = 0
    while len(out) < _MAX_RECORDS:
        batch = record_reader.read_records(session_id, after, MAX_LIMIT)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < MAX_LIMIT:
            break
        after = batch[-1].seq + 1
    return out


def _settle(entry: dict) -> str:
    """这一档最后算新建、改，还是删掉。判据见 :class:`SessionFile` 的 ``action``。"""
    if entry["last"] == "deleted":
        return "deleted"
    if entry["first_write"] == "created" and not entry["deleted_before_write"]:
        return "created"
    return "modified"


def session_files(session_id: str) -> list[SessionFile]:
    """这场会话写到、改过、删掉的文件，按第一次动它的先后排。

    一场没动过任何文件的会话返回空表；认不出这场会话由 :mod:`record_reader` 那侧抛，
    本模块不吞它的异常——「认不出」与「没动过文件」是两件事，合并了界面就没法区分。
    """
    seen: dict[str, dict] = {}
    order: list[str] = []
    cwd: str | None = None

    def note(path: str, action: str, seq: int) -> None:
        """记下这一下。一趟只攒原始事实，算哪一档推到 :func:`_settle`——先动后删、先删后
        建各自是什么意思，在那里一处说清。"""
        if is_scratch_path(path):
            return
        entry = seen.get(path)
        if entry is None:
            seen[path] = {
                "path": path,
                # 第一次写它的那一下（删不算写）；一次都还没写时是 None。
                "first_write": None if action == "deleted" else action,
                # 它前面先被删过一次吗——是的话它本来就在，别报成新建。开篇就是删，那这一次
                # 删就在每一次写之前。头一下就写的话，后面再删也不翻这个案（那时它已经在场）。
                "deleted_before_write": action == "deleted",
                "last": action,
                "count": 1,
                "first_seq": seq,
            }
            order.append(path)
            return
        entry["count"] += 1
        entry["last"] = action
        if entry["first_write"] is None and action != "deleted":
            entry["first_write"] = action

    for record in _all_records(session_id):
        # 这场会话的工作目录：codex 的补丁写的是相对路径，按它拼成绝对路径。这条记录在
        # 整场的最前面，所以轮到补丁时它已经在手上了。
        if record.kind == "session.state":
            found = (record.payload or {}).get("cwd")
            if isinstance(found, str) and found.strip():
                cwd = found.strip()
            continue
        if record.kind != "tool.call":
            continue
        payload = record.payload or {}
        tool = str(payload.get("tool_name") or "").lower()
        if tool == _PATCH_TOOL:
            # 一次补丁可能点好几个文件，各记各的。
            for action, path in _patch_paths(payload.get("args"), cwd):
                note(path, action, record.seq)
            continue
        if tool not in _WRITE_TOOLS:
            continue
        path = _path_in(payload.get("args"))
        if path is None:
            continue
        if tool in _DELETE_TOOLS:
            action = "deleted"
        elif tool in _CREATE_TOOLS:
            action = "created"
        else:
            action = "modified"
        note(path, action, record.seq)

    return [
        SessionFile(
            path=entry["path"],
            action=_settle(entry),
            count=entry["count"],
            first_seq=entry["first_seq"],
        )
        for entry in (seen[path] for path in order)
    ]
