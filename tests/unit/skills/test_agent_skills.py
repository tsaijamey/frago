"""各家 agent 的 skill 扫描与 frago 集中副本。

盯三件事：各家默认路径扫得到（含插件、云端同步那两种带前缀的）；同一个目录被两家同时
读到只算一份；副本在原件变了时整包换掉、原件没了时跟着删，且不留备份。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from frago.skills.agent_skills import (
    ManagedSkillStore,
    agent_skill_inputs,
    discover,
    store_dir_name,
)


def _skill(dir_: Path, name: str, desc: str = "说明", extra: dict[str, str] | None = None) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n正文", encoding="utf-8")
    for rel, text in (extra or {}).items():
        path = dir_ / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return dir_


def _home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


class TestInputMethods:
    def test_四家都列出来_连不认skill的coreagent也在(self, tmp_path, monkeypatch):
        rows = {a.family: a for a in agent_skill_inputs(_home(tmp_path, monkeypatch))}
        assert set(rows) == {"claude-code", "codex", "opencode", "coreagent"}
        assert rows["claude-code"].native_syntax.startswith("/")
        assert rows["codex"].native_syntax.startswith("$")
        assert rows["opencode"].native_syntax is None
        assert rows["coreagent"].roots == ()
        assert all(a.webui_delivery == "embed" for a in rows.values())

    def test_codex_home_环境变量改得动codex的目录(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "cx"))
        codex = next(a for a in agent_skill_inputs(home) if a.family == "codex")
        assert codex.roots[0].path == tmp_path / "cx" / "skills"


class TestDiscover:
    def test_各家默认路径与插件_云端同步都扫得到(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        _skill(home / ".claude/skills/git-push", "git-push")
        _skill(home / ".claude/skills/synced/bucket-1/docs", "docs")
        plugin_dir = home / ".claude/plugins/cache/mk/superpowers/6.3.0"
        _skill(plugin_dir / "skills/brainstorming", "brainstorming")
        (home / ".claude/plugins").mkdir(parents=True, exist_ok=True)
        (home / ".claude/plugins/installed_plugins.json").write_text(
            json.dumps({"plugins": {"superpowers@mk": [{"installPath": str(plugin_dir)}]}}),
            encoding="utf-8",
        )
        _skill(home / ".codex/skills/.system/imagegen", "imagegen")
        _skill(home / ".agents/skills/remotion", "remotion")

        names = {s.name for s in discover(agent_skill_inputs(home))}
        assert names == {
            "git-push",
            "anthropic-skills:docs",
            "superpowers:brainstorming",
            "imagegen",
            "remotion",
        }

    def test_两家共读的目录只算一份_两家都记上(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        _skill(home / ".claude/skills/git-push", "git-push")
        found = discover(agent_skill_inputs(home))
        assert len(found) == 1
        assert found[0].agents == ["claude-code", "opencode"]

    def test_同名的包只收第一份(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        first = _skill(home / ".claude/skills/skill-creator", "skill-creator")
        _skill(home / ".codex/skills/skill-creator", "skill-creator")
        found = discover(agent_skill_inputs(home))
        assert [f.source_dir for f in found] == [first.resolve()]

    def test_没有前言时名字退回目录名(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        bare = home / ".claude/skills/bare"
        bare.mkdir(parents=True)
        (bare / "SKILL.md").write_text("# 没有前言", encoding="utf-8")
        assert [f.name for f in discover(agent_skill_inputs(home))] == ["bare"]


class TestStore:
    def test_插件前缀的冒号不进目录名(self):
        assert store_dir_name("superpowers:brainstorming") == "superpowers__brainstorming"

    def test_新包复制进来_附属文件一起带上_版本库不带(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        _skill(home / ".claude/skills/git-push", "git-push", extra={"scripts/run.sh": "echo", ".git/HEAD": "x"})
        store = ManagedSkillStore(tmp_path / "store")
        report = store.sync(discover(agent_skill_inputs(home)))
        assert report.added == ["git-push"]
        assert (store.root / "git-push/scripts/run.sh").is_file()
        assert not (store.root / "git-push/.git").exists()
        assert store.get("git-push").agents == ["claude-code", "opencode"]

    def test_原件没变就不动(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        _skill(home / ".claude/skills/git-push", "git-push")
        store = ManagedSkillStore(tmp_path / "store")
        store.sync(discover(agent_skill_inputs(home)))
        report = store.sync(discover(agent_skill_inputs(home)))
        assert (report.added, report.updated, report.unchanged) == ([], [], 1)

    def test_原件改了就整包替换_不留备份(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        src = _skill(home / ".claude/skills/git-push", "git-push", extra={"old.md": "旧"})
        store = ManagedSkillStore(tmp_path / "store")
        store.sync(discover(agent_skill_inputs(home)))

        (src / "old.md").unlink()
        md = src / "SKILL.md"
        md.write_text(md.read_text(encoding="utf-8") + "\n新加的一段", encoding="utf-8")
        st = md.stat()
        os.utime(md, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))

        report = store.sync(discover(agent_skill_inputs(home)))
        assert report.updated == ["git-push"]
        assert "新加的一段" in (store.root / "git-push/SKILL.md").read_text(encoding="utf-8")
        assert not (store.root / "git-push/old.md").exists()
        leftovers = sorted(p.name for p in store.root.iterdir())
        assert leftovers == [".index.json", "git-push"], "替换 NEVER 留下备份或半成品目录"

    def test_原件卸掉了副本跟着删_人手放的目录不碰(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        src = _skill(home / ".claude/skills/git-push", "git-push")
        store = ManagedSkillStore(tmp_path / "store")
        store.sync(discover(agent_skill_inputs(home)))
        (store.root / "hand-made").mkdir()

        for p in sorted(src.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        src.rmdir()

        report = store.sync(discover(agent_skill_inputs(home)))
        assert report.removed == ["git-push"]
        assert not (store.root / "git-push").exists()
        assert (store.root / "hand-made").is_dir()
        assert store.list() == []
