"""列会话索引的行为约束（spec 20260729-session-workbench-webui Phase 2a）。

重点盯两件事：取到的字段与全量逐行扫描完全一致，以及文件一变缓存就得失效。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from frago.session import session_index
from frago.session.claude_sessions import _scan_file


def _write_session(root: Path, project: str, sid: str, records: list[dict[str, Any]]) -> Path:
    proj = root / project
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )
    return path


def _basic_records() -> list[dict[str, Any]]:
    return [
        {"type": "last-prompt", "leafUuid": "x", "sessionId": "s"},
        {
            "type": "user",
            "cwd": "/Users/frago/Repos/frago",
            "timestamp": "2026-07-29T10:00:00.000Z",
            "message": {"content": "帮我把列会话提速"},
        },
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "好"}]}},
    ]


class Test取到的字段:
    def test_开口第一句工作目录起始时刻都取得到(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(root, "proj", "sid-1", _basic_records())

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.sid == "sid-1"
        assert summary.cwd == "/Users/frago/Repos/frago"
        assert summary.first_user == "帮我把列会话提速"
        assert summary.first_ts is not None

    def test_标题记录躲在文件很后面也能取到(self, tmp_path: Path) -> None:
        """标题可能落在任何位置。只读开头若干行会把它们静默丢掉——实测本机有会话的
        ``slug`` 到第 2682 行才第一次出现、``custom-title`` 到第 3283 行。
        """
        root = tmp_path / "projects"
        noise = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 400}]}}
            for _ in range(300)
        ]
        records = [
            *_basic_records(),
            *noise,
            {"type": "ai-title", "aiTitle": "模型起的标题"},
            *noise,
            {"type": "custom-title", "customTitle": "人定的标题"},
        ]
        _write_session(root, "proj", "sid-2", records)

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.ai_title == "模型起的标题"
        assert summary.custom_title == "人定的标题"

    def test_后写的标题盖掉先写的(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        records = [
            *_basic_records(),
            {"type": "ai-title", "aiTitle": "旧标题"},
            {"type": "ai-title", "aiTitle": "新标题"},
        ]
        _write_session(root, "proj", "sid-3", records)

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.ai_title == "新标题"

    def test_首个slug胜出且与全量扫描一致(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        records = [
            *_basic_records(),
            {"type": "assistant", "slug": "first-slug", "message": {"content": "a"}},
            {"type": "assistant", "slug": "later-slug", "message": {"content": "b"}},
        ]
        path = _write_session(root, "proj", "sid-4", records)

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )
        full = _scan_file(path)

        assert summary.slug == "first-slug"
        assert full is not None
        assert summary.slug == full["slug"]

    def test_没有开口第一句时是空而不是编出来一个(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        records = [
            {"type": "assistant", "cwd": "/tmp/x", "timestamp": "2026-07-29T10:00:00.000Z",
             "message": {"content": "只有助手说话"}},
        ]
        _write_session(root, "proj", "sid-5", records)

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.first_user is None

    def test_斜杠命令的回声不算开口第一句(self, tmp_path: Path) -> None:
        """``/clear`` 这类是会话管理动作，不是人说的第一句。取值规则与全量扫描一致。"""
        root = tmp_path / "projects"
        records = [
            {"type": "user", "cwd": "/tmp/x", "timestamp": "2026-07-29T10:00:00.000Z",
             "message": {"content": "<command-name>/clear</command-name>"}},
            {"type": "user", "message": {"content": "这才是我说的第一句"}},
        ]
        path = _write_session(root, "proj", "sid-6", records)

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )
        full = _scan_file(path)

        assert summary.first_user == "这才是我说的第一句"
        assert full is not None
        assert summary.first_user == full["first_user"]


class Test缓存失效:
    def test_追加一行后拿到的是新值(self, tmp_path: Path) -> None:
        """会话文件随时在追加。追回来的必须是新标题，NEVER 是缓存里那个旧的。"""
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        path = _write_session(
            root, "proj", "sid-7", [*_basic_records(), {"type": "ai-title", "aiTitle": "旧标题"}]
        )

        (before,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)
        assert before.ai_title == "旧标题"

        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "ai-title", "aiTitle": "追加后的新标题"}) + "\n")

        (after,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)
        assert after.ai_title == "追加后的新标题"

    def test_大小没变但内容变了也要失效(self, tmp_path: Path) -> None:
        """改写而非追加时文件大小可能一模一样，这时候得靠修改时刻兜住。"""
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        path = _write_session(
            root, "proj", "sid-8", [*_basic_records(), {"type": "ai-title", "aiTitle": "AAA"}]
        )

        (before,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)
        assert before.ai_title == "AAA"

        text = path.read_text(encoding="utf-8").replace('"AAA"', '"BBB"')
        path.write_text(text, encoding="utf-8")

        (after,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)
        assert after.ai_title == "BBB"

    def test_没变过的文件不再重算(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        _write_session(root, "proj", "sid-9", _basic_records())

        session_index.list_session_summaries(projects_root=root, cache_file=cache)

        calls: list[Path] = []
        real = session_index._extract

        def counted(path: Path, sid: str, mtime: float):  # type: ignore[no-untyped-def]
            calls.append(path)
            return real(path, sid, mtime)

        monkeypatch.setattr(session_index, "_extract", counted)
        (again,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)

        assert calls == []
        assert again.first_user == "帮我把列会话提速"

    def test_删掉的会话不再留在索引里(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        _write_session(root, "proj", "sid-a", _basic_records())
        path_b = _write_session(root, "proj", "sid-b", _basic_records())

        assert len(session_index.list_session_summaries(projects_root=root, cache_file=cache)) == 2

        path_b.unlink()
        rows = session_index.list_session_summaries(projects_root=root, cache_file=cache)

        assert [r.sid for r in rows] == ["sid-a"]
        assert "sid-b" not in cache.read_text(encoding="utf-8")

    def test_索引文件损坏就整份重算而不是报错(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        _write_session(root, "proj", "sid-c", _basic_records())
        cache.write_text("这不是 JSON", encoding="utf-8")

        rows = session_index.list_session_summaries(projects_root=root, cache_file=cache)

        assert [r.sid for r in rows] == ["sid-c"]

    def test_目录不存在时是空清单(self, tmp_path: Path) -> None:
        rows = session_index.list_session_summaries(
            projects_root=tmp_path / "没有这个目录", cache_file=tmp_path / "index.json"
        )
        assert rows == []


class Test四档状态:
    """判定顺序即语义，四条判据换个次序就是另一套含义。"""

    def test_末条是报错时压过还在跑(self) -> None:
        """报错排第一。刚崩完那一刻同时满足"90 秒内有活动"，先判报错才对得上现实。"""
        now = 1_753_800_000.0
        assert session_index.derive_status("error", now - 5, now) == "error"

    def test_九十秒内有活动判还在跑(self) -> None:
        now = 1_753_800_000.0
        assert session_index.derive_status("agent.say", now - 30, now) == "running"
        assert session_index.derive_status("tool.result", now - 89, now) == "running"

    def test_过了九十秒且末条是agent回复判已完成(self) -> None:
        now = 1_753_800_000.0
        assert session_index.derive_status("agent.say", now - 91, now) == "done"

    def test_其余一律闲置(self) -> None:
        """停在工具结果、停在人说完话、什么都判不出——都只是停着，不是在等谁。"""
        now = 1_753_800_000.0
        for kind in ("tool.result", "user.say", "interrupt", None):
            assert session_index.derive_status(kind, now - 10_000, now) == "idle"

    def test_没有等你决策这一档(self) -> None:
        """末条是 agent 回复、放了很久没动，判"已完成"而不是"在等你"。

        两者在数据上一模一样，硬凑会把绝大多数正常答完的会话全标成在等你。
        """
        now = 1_753_800_000.0
        assert session_index.derive_status("agent.say", now - 86_400, now) == "done"


class Test末条记录与摘要:
    def test_末尾的引擎记账不算末条记录(self, tmp_path: Path) -> None:
        """答完之后引擎还会补轮次耗时、改标题、跑 hook。那些不是谁做的事。

        照字面取物理末条，本机绝大多数正常答完的会话都会判成闲置。
        """
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "sid-tail-1",
            [
                *_basic_records(),
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "干完了"}]}},
                {"type": "system", "subtype": "turn_duration", "durationMs": 1200},
                {"type": "ai-title", "aiTitle": "某个标题"},
                {"type": "last-prompt", "leafUuid": "z"},
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.last_kind == "agent.say"
        assert summary.tail.digest_done == "干完了"

    def test_末条是报错时把那句话留下(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "sid-tail-2",
            [
                *_basic_records(),
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "开始跑"}]}},
                {
                    "type": "assistant",
                    "isApiErrorMessage": True,
                    "error": "connection_closed",
                    "message": {"content": [{"type": "text", "text": "API Error: 连接中断"}]},
                },
                {"type": "system", "subtype": "turn_duration", "durationMs": 1},
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.last_kind == "error"
        assert summary.tail.error_message == "API Error: 连接中断"
        # 报错归报错，"最近做完的一件事"照样是那条回复，两格各有各的出处。
        assert summary.tail.digest_done == "开始跑"

    def test_停在工具结果上不算答完(self, tmp_path: Path) -> None:
        """会话被掐断在工具跑完那一刻，末条是工具结果，不该判成已完成。"""
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "sid-tail-3",
            [
                *_basic_records(),
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                        ]
                    },
                },
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.last_kind == "tool.result"

    def test_摘要取末尾最近那条回复而不是最早那条(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "sid-tail-4",
            [
                *_basic_records(),
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "先这样"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "后来这样"}]}},
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.digest_done == "后来这样"

    def test_摘要只要头一行且长了要截(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        long_line = "很长的一行" * 40
        _write_session(
            root,
            "proj",
            "sid-tail-5",
            [
                *_basic_records(),
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "头一行\n第二行\n第三行"}]},
                },
                {"type": "assistant", "message": {"content": [{"type": "text", "text": long_line}]}},
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.digest_done is not None
        assert summary.tail.digest_done.endswith("…")
        assert len(summary.tail.digest_done) <= session_index._DIGEST_MAX_CHARS + 1

    def test_一条回复都没有时摘要是空而不是编一句(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "sid-tail-6",
            [{"type": "user", "cwd": "/tmp/x", "message": {"content": "只有我说话"}}],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.digest_done is None
        assert summary.tail.last_kind == "user.say"

    def test_末尾全是记账时照实交白卷(self, tmp_path: Path) -> None:
        """判不出来就是判不出来，NEVER 顺手挑一条记账充当末条记录。"""
        root = tmp_path / "projects"
        _write_session(
            root,
            "proj",
            "sid-tail-7",
            [
                {"type": "ai-title", "aiTitle": "标题"},
                {"type": "last-prompt", "leafUuid": "z"},
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.last_kind is None
        assert summary.tail.digest_done is None

    def test_回复躲在末尾很多条之后也翻得到(self, tmp_path: Path) -> None:
        """头一档只读 3 条。回复被一串工具往返推远时要能自己退到更大的窗口。"""
        root = tmp_path / "projects"
        churn = []
        for i in range(15):
            churn.append(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {}}
                        ]
                    },
                }
            )
            churn.append(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}
                        ]
                    },
                }
            )
        _write_session(
            root,
            "proj",
            "sid-tail-8",
            [
                *_basic_records(),
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "起手"}]}},
                *churn,
            ],
        )

        (summary,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )

        assert summary.tail.last_kind == "tool.result"
        assert summary.tail.digest_done == "起手"


class Test状态跟着索引一起缓存:
    def test_追加一条报错后状态跟着变(self, tmp_path: Path) -> None:
        """状态与摘要跟索引同生共死。缓存不失效，左栏会一直显示上一次的样子。"""
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        path = _write_session(
            root,
            "proj",
            "sid-tail-9",
            [
                *_basic_records(),
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "答完了"}]}},
            ],
        )

        (before,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)
        assert before.tail.last_kind == "agent.say"

        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "isApiErrorMessage": True,
                        "error": "overloaded",
                        "message": {"content": [{"type": "text", "text": "API Error: 过载"}]},
                    }
                )
                + "\n"
            )

        (after,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)

        assert after.tail.last_kind == "error"
        assert after.tail.error_message == "API Error: 过载"

    def test_没变过的文件不重算状态(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """状态是从缓存里取回来的，不是每次列会话都重读一遍尾巴。"""
        root = tmp_path / "projects"
        cache = tmp_path / "index.json"
        _write_session(
            root,
            "proj",
            "sid-tail-a",
            [
                *_basic_records(),
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "答完了"}]}},
            ],
        )
        session_index.list_session_summaries(projects_root=root, cache_file=cache)

        def exploding(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("命中缓存时不该再读一次尾巴")

        monkeypatch.setattr(session_index, "_tail_signals", exploding)
        (again,) = session_index.list_session_summaries(projects_root=root, cache_file=cache)

        assert again.tail.last_kind == "agent.say"
        assert again.tail.digest_done == "答完了"


class Test与全量扫描逐字段一致:
    def test_同一份文件两条路径取到的字段完全相同(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        records = [
            *_basic_records(),
            {"type": "assistant", "slug": "the-slug", "message": {"content": "x"}},
            {"type": "ai-title", "aiTitle": "模型标题"},
            {"type": "custom-title", "customTitle": "人定标题"},
        ]
        path = _write_session(root, "proj", "sid-d", records)

        (fast,) = session_index.list_session_summaries(
            projects_root=root, cache_file=tmp_path / "index.json"
        )
        full = _scan_file(path)

        assert full is not None
        assert fast.slug == full["slug"]
        assert fast.ai_title == full["ai_title"]
        assert fast.custom_title == full["custom_title"]
        assert fast.cwd == full["cwd"]
        assert fast.first_user == full["first_user"]
