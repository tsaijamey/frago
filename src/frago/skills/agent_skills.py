"""各家 CLI agent 的 skill：它们各自从哪儿读、人各自怎么点名，以及 frago 的集中副本。

四家 agent 对 skill 的支持差别很大，同一个包在这家要打 ``/git-push``，在那家要写
``$git-push``，到了 opencode 只能靠模型自己去调它的 skill 工具，CoreAgent 干脆不认 skill。
会话页要让人用同一个动作点名一个 skill，就不能照搬任何一家的写法——上一回在 codex
会话里敲 ``/git-push``，codex 当它是自己的斜杠命令、报 Unrecognized command，那句话
始终没进会话。所以 frago 这边的做法是：**不走任何一家的原生点名，把 skill 正文直接
嵌进这一句话**（见 :mod:`frago.skills.skill_prompt`）。这样四家拿到的是同一份东西。

本模块做三件事：

1. :func:`agent_skill_inputs` —— 枚举每一家的 skill 原生输入方式与默认安装路径。
   路径全部是在本机实测过的（``opencode debug skill`` 的输出、codex 程序里写着的
   ``$CODEX_HOME/skills`` 与 ``.agents/skills``），不是照文档抄的。
2. :func:`discover` —— 按上面那些路径扫出已安装的 skill 包。一个目录里有 ``SKILL.md``
   就是一个包，不再往里钻。
3. :class:`ManagedSkillStore` —— 把扫到的包复制到 ``~/.frago/skills/`` 集中管理。已有的
   包内容变了就整包换掉，**不留备份**：这里是副本，原件一直在各家自己的目录里。

分层：纯逻辑层，不 import ``server/``。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"

#: 往下找 ``SKILL.md`` 最多钻几层。各家默认路径下的包都是直接子目录；Claude Code 云端
#: 同步来的包藏在 ``skills/synced/<桶>/`` 下，那几个桶各自单列成一个带前缀的目录
#: （见 :func:`_claude_synced_roots`）。往深处钻会把它们以不带前缀的名字再收一遍。
MAX_DEPTH = 1

#: 单个包的体积上限。超过的多半是把依赖目录一起装了进来，复制一份只会撑盘。
MAX_PACKAGE_BYTES = 50 * 1024 * 1024

#: 复制与算指纹时都跳过的东西：版本库、依赖、缓存。它们不是 skill 的内容。
IGNORED_NAMES = frozenset({".git", "node_modules", "__pycache__", ".DS_Store", ".venv"})

#: 集中副本里记录来源与指纹的那份清单。
INDEX_FILE = ".index.json"


@dataclass(frozen=True)
class SkillRoot:
    """一家 agent 读 skill 的一个目录。"""

    path: Path
    #: 这个目录里的包在那一家叫什么前缀。插件带的包在 Claude Code 里叫
    #: ``<插件>:<包名>``，云端同步来的叫 ``anthropic-skills:<包名>``；普通目录没有前缀。
    namespace: str | None = None


@dataclass(frozen=True)
class AgentSkillInput:
    """一家 agent 的 skill 原生输入方式。"""

    family: str
    """与会话清单同一套家族名：claude-code / codex / opencode / coreagent。"""

    label: str
    native_syntax: str | None
    """人在那一家的终端里点名一个 skill 的写法。没有原生写法为 None。"""

    native_how: str
    """那一家怎么认出并使用 skill，一两句话。"""

    roots: tuple[SkillRoot, ...]
    """默认安装路径，按优先级排。不存在的也列着——没装不等于不支持。"""

    webui_delivery: str = "embed"
    """会话页替人点名时走哪条路。四家一律是 embed：skill 正文嵌进 prompt。"""


def _codex_home(home: Path) -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser() if env else home / ".codex"


def _claude_plugin_roots(home: Path) -> list[SkillRoot]:
    """Claude Code 已安装插件各自带的 skill 目录。

    只认 ``installed_plugins.json`` 里登记的那一份安装路径。插件缓存目录里同一个插件往往
    躺着好几个旧版本，全扫进来会出现同名的好几份。
    """
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    roots: list[SkillRoot] = []
    for key, installs in (data.get("plugins") or {}).items():
        plugin = str(key).split("@", 1)[0]
        for install in installs or []:
            path = install.get("installPath") if isinstance(install, dict) else None
            if path:
                roots.append(SkillRoot(Path(path) / "skills", namespace=plugin))
    return roots


def _claude_synced_roots(home: Path) -> list[SkillRoot]:
    """Claude Code 从账号云端同步下来的 skill（界面上叫 ``anthropic-skills:<名字>``）。"""
    synced = home / ".claude" / "skills" / "synced"
    if not synced.is_dir():
        return []
    return [
        SkillRoot(bucket, namespace="anthropic-skills")
        for bucket in sorted(synced.iterdir())
        if bucket.is_dir() and not bucket.name.startswith(".")
    ]


def agent_skill_inputs(home: Path | None = None) -> list[AgentSkillInput]:
    """枚举四家 agent 的 skill 原生输入方式与默认安装路径。"""
    home = home or Path.home()
    codex_home = _codex_home(home)
    return [
        AgentSkillInput(
            family="claude-code",
            label="Claude Code",
            native_syntax="/<skill 名> [要求]",
            native_how=(
                "输入框里敲斜杠加 skill 名当命令调用，后面可跟要求；插件带的写成 "
                "/<插件>:<skill 名>。模型也会按 skill 说明自己调用 Skill 工具。"
            ),
            roots=(
                SkillRoot(home / ".claude" / "skills"),
                *_claude_plugin_roots(home),
                *_claude_synced_roots(home),
            ),
        ),
        AgentSkillInput(
            family="codex",
            label="Codex",
            native_syntax="$<skill 名> [要求]",
            native_how=(
                "在一句话里写 $<skill 名> 点名（也可在 /skills 菜单里挑）；codex 的斜杠只认它"
                "自己的命令，/<skill 名> 会被当成未知命令拦下，那句话不会进会话。"
            ),
            roots=(
                SkillRoot(codex_home / "skills"),
                SkillRoot(codex_home / "skills" / ".system"),
                SkillRoot(home / ".agents" / "skills"),
            ),
        ),
        AgentSkillInput(
            family="opencode",
            label="opencode",
            native_syntax=None,
            native_how=(
                "没有点名写法：模型按 skill 说明自己调用内置的 skill 工具按名字加载，"
                "人只能用大白话要求它用某个 skill。"
            ),
            roots=(
                SkillRoot(home / ".config" / "opencode" / "skills"),
                SkillRoot(home / ".config" / "opencode" / "skill"),
                SkillRoot(home / ".claude" / "skills"),
            ),
        ),
        AgentSkillInput(
            family="coreagent",
            label="CoreAgent",
            native_syntax=None,
            native_how="frago 自己的内核，不认 skill 包；只能把 skill 正文放进这一句话交给它。",
            roots=(),
        ),
    ]


@dataclass
class FoundSkill:
    """在某家 agent 目录里扫到的一个 skill 包。"""

    name: str
    description: str | None
    source_dir: Path
    signature: str
    agents: list[str] = field(default_factory=list)
    """哪几家 agent 原生看得见它。同一个目录可能同时是两家的默认路径。"""


def _walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_NAMES)
        for name in sorted(filenames):
            if name not in IGNORED_NAMES:
                yield Path(dirpath) / name


def package_signature(package: Path) -> tuple[str, int]:
    """一个包的指纹与总字节数。

    指纹只看每个文件的相对路径、大小与修改时刻，不读内容：复制时保留了修改时刻，
    内容一改修改时刻必变，这样每轮扫描不必把几十个包逐字节读一遍。
    """
    parts: list[str] = []
    total = 0
    for path in _walk_files(package):
        with contextlib.suppress(OSError):
            st = path.stat()
            total += st.st_size
            parts.append(f"{path.relative_to(package).as_posix()}:{st.st_size}:{st.st_mtime_ns}")
    return "|".join(parts), total


def _read_meta(skill_md: Path) -> tuple[str | None, str | None]:
    try:
        post = frontmatter.load(skill_md)
    except Exception as e:  # noqa: BLE001 — 前言坏了也照收，名字退回目录名
        logger.debug("skill frontmatter unreadable %s: %s", skill_md, e)
        return None, None
    name = post.get("name")
    desc = post.get("description")
    return (str(name).strip() if name else None), (str(desc).strip() if desc else None)


def _packages_under(root: Path, depth: int = 0):
    """``root`` 下每个含 ``SKILL.md`` 的目录。找到了就不再往它里面钻。"""
    try:
        children = sorted(root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir() or child.name in IGNORED_NAMES:
            continue
        if (child / SKILL_FILE).is_file():
            yield child
        elif depth + 1 < MAX_DEPTH and not child.name.startswith("."):
            yield from _packages_under(child, depth + 1)


def discover(inputs: list[AgentSkillInput] | None = None) -> list[FoundSkill]:
    """按各家默认路径扫出本机已安装的 skill 包。

    同名的包只收第一份（按家族顺序、再按路径顺序）。同一个目录被两家同时读到时，合成
    一份、两家都记上。
    """
    inputs = inputs if inputs is not None else agent_skill_inputs()
    by_source: dict[Path, FoundSkill] = {}
    by_name: dict[str, FoundSkill] = {}
    for agent in inputs:
        for root in agent.roots:
            if not root.path.is_dir():
                continue
            for package in _packages_under(root.path):
                source = package.resolve()
                seen = by_source.get(source)
                if seen is not None:
                    if agent.family not in seen.agents:
                        seen.agents.append(agent.family)
                    continue
                raw_name, desc = _read_meta(package / SKILL_FILE)
                base = raw_name or package.name
                name = f"{root.namespace}:{base}" if root.namespace else base
                if name in by_name:
                    logger.debug("skill %s already taken by %s, skip %s", name, by_name[name].source_dir, source)
                    continue
                signature, total = package_signature(package)
                if total > MAX_PACKAGE_BYTES:
                    logger.warning("skill %s is %d bytes, over the limit; not managed", source, total)
                    continue
                found = FoundSkill(name, desc, source, signature, [agent.family])
                by_source[source] = found
                by_name[name] = found
    return list(by_name.values())


def store_dir_name(name: str) -> str:
    """skill 名在集中副本里的目录名。``插件:包名`` 里的冒号换成双下划线。"""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name.replace(":", "__")).lstrip(".")
    return cleaned or "skill"


@dataclass
class ManagedSkill:
    """``~/.frago/skills/`` 里的一个包。"""

    name: str
    description: str | None
    dir_name: str
    source_dir: str
    agents: list[str]
    signature: str
    synced_at: float

    def skill_md(self, root: Path) -> Path:
        return root / self.dir_name / SKILL_FILE


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)

    def summary(self) -> str:
        return (
            f"added={len(self.added)} updated={len(self.updated)} "
            f"removed={len(self.removed)} unchanged={self.unchanged}"
        )


def default_store_root() -> Path:
    return Path.home() / ".frago" / "skills"


class ManagedSkillStore:
    """frago 集中管理的 skill 副本。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_store_root()

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_FILE

    def load_index(self) -> dict[str, ManagedSkill]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out: dict[str, ManagedSkill] = {}
        for name, entry in (raw.get("skills") or {}).items():
            with contextlib.suppress(TypeError):
                out[name] = ManagedSkill(**entry)
        return out

    def _write_index(self, index: dict[str, ManagedSkill]) -> None:
        payload = {"updated_at": time.time(), "skills": {n: asdict(s) for n, s in sorted(index.items())}}
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def _replace_package(self, source: Path, dest: Path) -> None:
        """整包换成原件的样子。先复制到旁边，再换名顶上去，读的人不会撞见半个包。"""
        staging = dest.with_name(f".{dest.name}.incoming")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
        if dest.exists():
            shutil.rmtree(dest)
        staging.rename(dest)

    def sync(self, found: list[FoundSkill]) -> SyncReport:
        """把扫到的包同步进集中副本：新的复制进来，变了的整包替换，原件没了的删掉。"""
        self.root.mkdir(parents=True, exist_ok=True)
        index = self.load_index()
        report = SyncReport()
        now = time.time()
        next_index: dict[str, ManagedSkill] = {}

        for skill in found:
            dir_name = store_dir_name(skill.name)
            dest = self.root / dir_name
            prev = index.get(skill.name)
            same = (
                prev is not None
                and prev.signature == skill.signature
                and prev.source_dir == str(skill.source_dir)
                and prev.dir_name == dir_name
                and (dest / SKILL_FILE).is_file()
            )
            if not same:
                try:
                    self._replace_package(skill.source_dir, dest)
                except OSError as e:
                    logger.warning("failed to sync skill %s from %s: %s", skill.name, skill.source_dir, e)
                    if prev is not None:
                        next_index[skill.name] = prev
                    continue
                (report.updated if prev is not None else report.added).append(skill.name)
            else:
                report.unchanged += 1
            next_index[skill.name] = ManagedSkill(
                name=skill.name,
                description=skill.description,
                dir_name=dir_name,
                source_dir=str(skill.source_dir),
                agents=list(skill.agents),
                signature=skill.signature,
                synced_at=now if not same else prev.synced_at,  # type: ignore[union-attr]
            )

        # 原件已经卸掉的包：副本跟着删。只删自己登记过的目录，人手放进来的东西不碰。
        kept_dirs = {s.dir_name for s in next_index.values()}
        for name, prev in index.items():
            if name in next_index:
                continue
            report.removed.append(name)
            if prev.dir_name not in kept_dirs:
                with contextlib.suppress(OSError):
                    shutil.rmtree(self.root / prev.dir_name)

        self._write_index(next_index)
        return report

    def list(self) -> list[ManagedSkill]:
        return sorted(self.load_index().values(), key=lambda s: s.name)

    def get(self, name: str) -> ManagedSkill | None:
        return self.load_index().get(name)


def scan_and_sync(store: ManagedSkillStore | None = None) -> SyncReport:
    """扫一遍各家目录并同步进集中副本。定时任务与手动刷新都走这一条。"""
    return (store or ManagedSkillStore()).sync(discover())
