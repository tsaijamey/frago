"""skill 正文嵌进投给 agent 的那句话。

盯的是 agent 读到的东西：路径与全文都在、排在人写的话前面、三种用法的说明分得开、
点名一个不存在的 skill 不会被悄悄丢掉。
"""

from __future__ import annotations

import pytest

from frago.skills.agent_skills import ManagedSkillStore, agent_skill_inputs, discover
from frago.skills.skill_prompt import (
    GUIDE_ONLY_SKILL,
    GUIDE_WITH_REQUEST,
    UnknownSkill,
    embed_skills,
    load_skills,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    for name in ("git-push", "pypi-publish"):
        d = home / ".claude/skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: 说明\n---\n\n# {name} 正文第一行\n最后一行",
            encoding="utf-8",
        )
    s = ManagedSkillStore(tmp_path / "store")
    s.sync(discover(agent_skill_inputs(home)))
    return s


def test_路径与全文都进了那句话_排在人写的话前面(store):
    skills = load_skills(["git-push"], store)
    prompt = embed_skills("帮我提交", skills, user_text="帮我提交")
    assert prompt.startswith('<must-use-skill name="git-push" path="')
    assert f"skill 文档：{store.root / 'git-push' / 'SKILL.md'}" in prompt
    assert "# git-push 正文第一行\n最后一行\n</must-use-skill>" in prompt
    assert prompt.endswith("</must-use-skill>\n\n帮我提交")


def test_只点名不写要求时说明是照流程执行(store):
    prompt = embed_skills("", load_skills(["git-push"], store), user_text="")
    assert GUIDE_ONLY_SKILL in prompt
    assert GUIDE_WITH_REQUEST not in prompt
    assert prompt.endswith("</must-use-skill>")


def test_带要求时说明分开了做事与研究skill两种(store):
    prompt = embed_skills("研究一下这个 skill", load_skills(["git-push"], store), user_text="研究一下这个 skill")
    assert GUIDE_WITH_REQUEST in prompt
    assert "不要执行 skill 里的流程" in prompt


def test_多个skill各一段_重复点名只算一次(store):
    prompt = embed_skills("x", load_skills(["git-push", "pypi-publish", "git-push"], store), user_text="x")
    assert prompt.count("<must-use-skill ") == 2
    assert prompt.index('name="git-push"') < prompt.index('name="pypi-publish"')


def test_不存在的skill整单拒掉(store):
    with pytest.raises(UnknownSkill, match="nope"):
        load_skills(["git-push", "nope"], store)


def test_没挑skill时原样返回(store):
    assert embed_skills("原话", [], user_text="原话") == "原话"


def test_拆回名字与人写的话_与嵌进去的形状对得上(store):
    from frago.skills.skill_prompt import split_skill_blocks

    prompt = embed_skills("帮我提交", load_skills(["git-push", "pypi-publish"], store), user_text="帮我提交")
    assert split_skill_blocks(prompt) == (["git-push", "pypi-publish"], "帮我提交")
    assert split_skill_blocks("聊聊 <must-use-skill 这个写法") == ([], "聊聊 <must-use-skill 这个写法")


def test_左栏标题只要名字加人写的话(store):
    from frago.session.session_index import _first_user_text

    prompt = embed_skills("帮我提交", load_skills(["git-push"], store), user_text="帮我提交")
    assert _first_user_text(prompt) == "/git-push 帮我提交"
    only = embed_skills("", load_skills(["git-push"], store), user_text="")
    assert _first_user_text(only) == "/git-push"
