"""把人点名的 skill 正文嵌进投给 agent 的那一句话。

会话页上人敲 ``/`` 挑中一个 skill，发出去的不是任何一家的原生点名写法（那些写法四家
各不相同，还会被 codex 当成它自己的斜杠命令拦下），而是这样一段：

.. code-block:: text

    <must-use-skill name="git-push" path="/Users/…/.frago/skills/git-push/SKILL.md">
    （怎么用这个 skill 的一段说明）
    skill 文档：/Users/…/.frago/skills/git-push/SKILL.md
    ---
    （SKILL.md 全文）
    </must-use-skill>

    人写的那句话

每挑一个 skill 一段，排在人写的话前面：agent 先读懂方法，再读要求。会话页渲染时认的是
``<must-use-skill name="…">`` 这一层壳，只把名字画成引用，正文不摆出来——前端
``skillBlocks.ts`` 里的写法 MUST 与这里逐字一致。

同一个 skill 有三种用法，语义不一样，说明段 MUST 把它们分开交代：

- 只点名、不写别的：照 skill 自己的流程完整执行；
- 点名加具体要求：以要求为目标，skill 是完成它的方法，两者冲突时以人的要求为准；
- 要求是研究、解释、评价这个 skill 本身：只读、只分析，不执行 skill 里的流程。

前两种服务端能分（正文空不空），第三种只能让 agent 读了人的原话自己判断。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from frago.skills.agent_skills import ManagedSkillStore

OPEN_TAG = "must-use-skill"

GUIDE_ONLY_SKILL = (
    "用户只点名了这个 skill，没有写别的要求：先完整读完下面的 skill 正文，"
    "再照 skill 自己规定的流程把它完整执行一遍。"
)

GUIDE_WITH_REQUEST = (
    "用户点名了这个 skill，要求写在这一段之后的正文里。先完整读完下面的 skill 正文，"
    "再按用户的实际要求判断怎么用它：\n"
    "- 要求是一件具体的事：以这件事为目标，按 skill 规定的方法与约束去完成；"
    "skill 与用户原话冲突时，以用户原话为准。\n"
    "- 要求是研究、解释、评价或修改这个 skill 本身：只阅读和分析 skill，"
    "不要执行 skill 里的流程。"
)

GUIDE_COMMON = (
    "skill 目录里的其他文件（脚本、参考资料、模板）按正文的指引用读文件的工具打开，"
    "路径相对于 skill 文档所在目录。"
)


#: 认 skill 段的写法。与前端 ``skillBlocks.ts`` 同一个形状。
_BLOCK_RE = re.compile(rf'<{OPEN_TAG}\s+name="([^"]*)"[^>]*>[\s\S]*?</{OPEN_TAG}>\s*')


def split_skill_blocks(text: str) -> tuple[list[str], str]:
    """把一句话拆成「点名的 skill 名」与「人写的话」。没有 skill 段时名字为空、原话照回。"""
    if f"<{OPEN_TAG}" not in text:
        return [], text
    names: list[str] = []

    def _take(m: re.Match[str]) -> str:
        names.append(html.unescape(m.group(1)))
        return ""

    rest = _BLOCK_RE.sub(_take, text)
    return (names, rest.strip()) if names else ([], text)


class UnknownSkill(LookupError):
    """点名的 skill 不在 frago 的集中副本里。"""


@dataclass(frozen=True)
class EmbeddedSkill:
    name: str
    path: Path
    body: str


def load_skills(names: list[str], store: ManagedSkillStore | None = None) -> list[EmbeddedSkill]:
    """按名字取出 skill 的文档路径与全文。重复点名只算一次；有一个取不到就整单拒掉。"""
    store = store or ManagedSkillStore()
    index = store.load_index()
    out: list[EmbeddedSkill] = []
    seen: set[str] = set()
    for raw in names:
        name = raw.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entry = index.get(name)
        if entry is None:
            raise UnknownSkill(f"没有叫 {name} 的 skill（frago 的集中副本里找不到）")
        path = entry.skill_md(store.root)
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as e:
            raise UnknownSkill(f"skill {name} 的文档读不出来：{e}") from e
        out.append(EmbeddedSkill(name=name, path=path, body=body))
    return out


def _attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;")


def skill_block(skill: EmbeddedSkill, *, has_request: bool) -> str:
    guide = GUIDE_WITH_REQUEST if has_request else GUIDE_ONLY_SKILL
    return (
        f'<{OPEN_TAG} name="{_attr(skill.name)}" path="{_attr(str(skill.path))}">\n'
        f"{guide}\n{GUIDE_COMMON}\n"
        f"skill 文档：{skill.path}\n"
        "---\n"
        f"{skill.body.rstrip()}\n"
        f"</{OPEN_TAG}>"
    )


def embed_skills(prompt: str, skills: list[EmbeddedSkill], *, user_text: str) -> str:
    """把 skill 段排在整句话前面。``user_text`` 是人写的原话，用来判这一句有没有要求。"""
    if not skills:
        return prompt
    has_request = bool(user_text.strip())
    blocks = "\n\n".join(skill_block(s, has_request=has_request) for s in skills)
    rest = prompt.strip()
    return f"{blocks}\n\n{rest}" if rest else blocks
