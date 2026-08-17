"""会话内容检索（``frago.session.record_search``）。

这一层最容易出的错不是"搜不到"，而是"搜出一堆不是人说的话"：工具输出、hook 注入、
引擎记账在语料里的体量是对话的几十倍，只要判据松一点，结果就全是它们。所以这里的
断言大多是**反向**的——命中了不该命中的东西才叫失败。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from frago.session import record_search


@pytest.fixture(autouse=True)
def _no_real_opencode_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 opencode 库指到一个不存在的路径，NEVER 让单测搜到用户真库里的话。"""
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "absent.db"))


def _write_session(root: Path, project: str, sid: str, records: list[dict[str, Any]]) -> Path:
    proj = root / project
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )
    return path


def _user(text: str, uuid: str = "u1") -> dict[str, Any]:
    return {
        "type": "user",
        "uuid": uuid,
        "timestamp": "2026-08-01T10:00:00.000Z",
        "message": {"content": text},
    }


def _assistant(text: str, uuid: str = "a1") -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": "2026-08-01T10:00:05.000Z",
        "message": {"content": [{"type": "text", "text": text}]},
    }


def _search(root: Path, query: str, **kwargs: Any) -> record_search.SearchOutcome:
    """只搜给定的语料目录。opencode 那一侧在单测环境里读不出库，自然交白卷。"""
    return record_search.search_sessions(query, projects_root=root, **kwargs)


class Test搜的是对话:
    def test_提示词与回复都搜得到(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root, "proj", "aaa", [_user("帮我修一下飞书推送"), _assistant("推送已经修好了")]
        )

        prompts = _search(root, "帮我修")
        replies = _search(root, "已经修好")

        assert [m.session_id for m in prompts.matches] == ["aaa"]
        assert prompts.matches[0].hits[0].kind == "user.say"
        assert [m.session_id for m in replies.matches] == ["aaa"]
        assert replies.matches[0].hits[0].kind == "agent.say"

    def test_工具输出里出现不算命中(self, tmp_path: Path) -> None:
        """ripgrep 命中的是整行 JSON。只到这一步就收工，结果会全是工具输出。"""
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "bbb",
            [
                _user("看看目录"),
                {
                    "type": "assistant",
                    "uuid": "a1",
                    "message": {
                        "content": [
                            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}
                        ]
                    },
                },
                {
                    "type": "user",
                    "uuid": "u2",
                    "toolUseResult": {"stdout": "机密口令在这里"},
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "content": "机密口令在这里"}
                        ]
                    },
                },
            ],
        )

        assert _search(root, "机密口令").matches == []

    def test_hook注入的话不算人说的话(self, tmp_path: Path) -> None:
        """hook 注入的内容在中栏单独有一格，但它不是提示词，不该混进搜索结果。"""
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "ccc",
            [
                _user("随便说句话"),
                {
                    "type": "attachment",
                    "uuid": "h1",
                    "attachment": {
                        "type": "hook_additional_context",
                        "content": ["产出一律落 data 目录"],
                        "hookName": "PreToolUse:Write",
                    },
                },
            ],
        )

        assert _search(root, "产出一律").matches == []


class Test多个词是并且:
    def test_几个词要落在同一句话里(self, tmp_path: Path) -> None:
        """人打"飞书 chat id"，找的是那句同时提到这三样的话。

        松成"会话里各处都出现过"的话，几乎每场会话都会命中，等于没搜。
        """
        root = tmp_path / "projects"
        _write_session(root, "proj", "ddd", [_user("把飞书的 chat id 换掉")])
        _write_session(
            root, "proj", "eee", [_user("飞书那边挺好"), _assistant("chat 记录我看过了")]
        )

        outcome = _search(root, "飞书 chat")

        assert [m.session_id for m in outcome.matches] == ["ddd"]

    def test_大小写不敏感(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(root, "proj", "fff", [_user("走 CloudFlare 那条路")])

        assert [m.session_id for m in _search(root, "cloudflare").matches] == ["fff"]


class Test报出来的东西:
    def test_摘要围着命中处截且压平空白(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root, "proj", "ggg", [_user("前面很长的铺垫\n\n  关键词在这里  \n后面还有很多")]
        )

        (match,) = _search(root, "关键词").matches

        assert "关键词在这里" in match.hits[0].snippet
        assert "\n" not in match.hits[0].snippet

    def test_命中条数报的是记录数(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "hhh",
            [_user("同一个词", "u1"), _assistant("同一个词又说了一遍", "a1")],
        )

        (match,) = _search(root, "同一个词").matches

        assert match.hit_count == 2
        assert len(match.hits) <= 2

    def test_每场最多附几条摘要说了算(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "iii",
            [_user("重复的词", "u1"), _assistant("重复的词", "a1"), _user("重复的词", "u2")],
        )

        (match,) = _search(root, "重复的词", per_session=1).matches

        assert match.hit_count == 3
        assert len(match.hits) == 1

    def test_太短的查询直接交白卷并说明(self, tmp_path: Path) -> None:
        """一个字能命中几乎所有会话，报出来没用，但 NEVER 静悄悄地返回空。"""
        root = tmp_path / "projects"
        _write_session(root, "proj", "jjj", [_user("一二三四五")])

        outcome = _search(root, "一")

        assert outcome.matches == []
        assert outcome.warnings

    def test_语料目录不存在时不炸(self, tmp_path: Path) -> None:
        outcome = _search(tmp_path / "根本没有这个目录", "随便什么")

        assert outcome.matches == []


class Test词的切分:
    def test_按空白切开并去重转小写(self) -> None:
        assert record_search.split_terms("  飞书   Chat 飞书 ") == ["飞书", "chat"]

    def test_空查询切不出词(self) -> None:
        assert record_search.split_terms("   ") == []


class Test重复的话只摆一遍:
    def test_逐字重复的命中不占两格(self, tmp_path: Path) -> None:
        """会话里有大量逐字重复的话（固定开场白、模板消息），一场能出上百条。

        照直取前两条，卡片上就是同一句话摆两遍，那一格等于白占。
        """
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "kkk",
            [
                _user("系统自动按来源投递", "u1"),
                _user("系统自动按来源投递", "u2"),
                _assistant("系统自动按来源投递，这句不一样", "a1"),
            ],
        )

        (match,) = _search(root, "自动按来源").matches

        assert match.hit_count == 3
        assert len(match.hits) == 2
        assert len({hit.snippet for hit in match.hits}) == 2
