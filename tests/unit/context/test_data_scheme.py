"""``data:<关键词>`` 的解析与渲染。

三条硬要求来自需求本身：data 目录不存在要报错、完全搜不到要报错、
多个目录都够分时不替调用方选。外加一条工程要求：吐出的全文有上限，
但被留在外面的东西 MUST 在输出里看得见——NEVER 让截断看起来像全部。
"""

import pytest

from frago.context import data_scheme
from frago.context.data_scheme import (
    INLINE_MAX_BYTES,
    TOTAL_INLINE_BUDGET,
    render,
    resolve_data,
)
from frago.context.errors import ContextError
from frago.context.resolver import resolve_ref, split_ref


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """把 DATA_ROOT 指到临时目录。NEVER 碰真人的 ~/.frago/data。"""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(data_scheme, "DATA_ROOT", root)
    return root


def make_dir(root, name, files):
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return target


class TestErrorPaths:
    def test_missing_data_root_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(data_scheme, "DATA_ROOT", tmp_path / "nope")
        with pytest.raises(ContextError) as exc:
            resolve_data("anything")
        assert "不存在" in exc.value.message
        assert exc.value.fixes  # 报错必须带可执行的下一步

    def test_data_root_that_is_a_file_raises(self, tmp_path, monkeypatch):
        bogus = tmp_path / "data"
        bogus.write_text("not a dir")
        monkeypatch.setattr(data_scheme, "DATA_ROOT", bogus)
        with pytest.raises(ContextError, match="不是目录"):
            resolve_data("anything")

    def test_empty_data_root_raises(self, data_root):
        with pytest.raises(ContextError, match="一个目录都没有"):
            resolve_data("anything")

    def test_no_match_raises_and_lists_near_names(self, data_root):
        make_dir(data_root, "etf-dma-trading-plan", {"a.md": "x"})
        with pytest.raises(ContextError) as exc:
            resolve_data("kubernetes-operator")
        assert "没有名字匹配" in exc.value.message

    def test_ambiguous_match_refuses_to_guess(self, data_root):
        make_dir(data_root, "20260725-cxmt-ipo-video", {"a.md": "x"})
        make_dir(data_root, "video-corpus", {"a.md": "x"})
        with pytest.raises(ContextError) as exc:
            resolve_data("video")
        assert "不替你选" in exc.value.message
        # 候选必须以可直接执行的形式给出，省掉调用方再拼一次命令
        assert any("video-corpus" in fix for fix in exc.value.fixes)


class TestResolution:
    def test_single_match_resolves(self, data_root):
        make_dir(data_root, "20260728-agent-session-workbench", {"spec.md": "hello"})
        result = resolve_data("session-workbench")
        assert result.path.name == "20260728-agent-session-workbench"

    def test_exact_name_wins_over_ambiguity(self, data_root):
        """目录名唯一，完全同名就不存在选错——此时展开它，其余只报名字。"""
        make_dir(data_root, "etf", {"a.md": "x"})
        make_dir(data_root, "etf-dma-trading-plan", {"a.md": "x"})
        result = resolve_data("etf")
        assert result.path.name == "etf"
        assert [c.name for c in result.also_matched] == ["etf-dma-trading-plan"]

    def test_date_prefixed_dir_found_by_semantic_name(self, data_root):
        make_dir(data_root, "20260725-cxmt-ipo-video", {"a.md": "x"})
        assert resolve_data("cxmt-ipo-video").path.name == "20260725-cxmt-ipo-video"


class TestListingAndInlining:
    def test_small_text_files_are_inlined(self, data_root):
        make_dir(data_root, "proj", {"spec.md": "SPEC BODY", "notes.txt": "NOTE BODY"})
        result = resolve_data("proj")
        bodies = {e.rel: e.text for e in result.entries}
        assert bodies["spec.md"] == "SPEC BODY"
        assert bodies["notes.txt"] == "NOTE BODY"

    def test_large_file_is_listed_not_inlined(self, data_root):
        make_dir(data_root, "proj", {"huge.md": "x" * (INLINE_MAX_BYTES + 1)})
        entry = resolve_data("proj").entries[0]
        assert entry.text is None
        assert "大文件" in entry.skip_reason

    def test_binary_file_is_listed_not_inlined(self, data_root):
        target = make_dir(data_root, "proj", {"a.md": "x"})
        (target / "blob.json").write_bytes(b"\x00\x01\x02binary")
        entries = {e.rel: e for e in resolve_data("proj").entries}
        assert entries["blob.json"].text is None
        assert entries["blob.json"].skip_reason == "非文本"

    def test_index_files_win_the_budget(self, data_root):
        """预算不够时，先保住入口文件——读完它才知道其余文件是干什么的。"""
        half = INLINE_MAX_BYTES
        make_dir(
            data_root,
            "proj",
            {
                "zzz-filler-a.md": "a" * half,
                "zzz-filler-b.md": "b" * half,
                "zzz-filler-c.md": "c" * half,
                "zzz-filler-d.md": "d" * half,
                "zzz-filler-e.md": "e" * half,
                "notebook.md": "THE INDEX",
            },
        )
        result = resolve_data("proj")
        entries = {e.rel: e for e in result.entries}
        assert entries["notebook.md"].text == "THE INDEX"
        assert result.inlined_bytes <= TOTAL_INLINE_BUDGET + INLINE_MAX_BYTES

    def test_budget_exhaustion_is_stated_never_silent(self, data_root):
        half = INLINE_MAX_BYTES
        make_dir(data_root, "proj", {f"f{i}.md": str(i) * half for i in range(8)})
        result = resolve_data("proj")
        skipped = [e for e in result.entries if e.text is None]
        assert skipped, "预算必须真的用尽，否则这条用例没在测东西"
        assert all(e.skip_reason for e in skipped)
        assert "预算已用尽" in render(result) or all(
            "预算" in e.skip_reason for e in skipped
        )

    def test_nested_files_are_walked(self, data_root):
        make_dir(data_root, "proj", {"sub/deep/note.md": "DEEP"})
        assert resolve_data("proj").entries[0].rel.endswith("note.md")

    def test_cache_dirs_are_skipped(self, data_root):
        make_dir(
            data_root,
            "proj",
            {"a.md": "x", "node_modules/pkg/index.js": "junk", "__pycache__/m.pyc": "junk"},
        )
        assert [e.rel for e in resolve_data("proj").entries] == ["a.md"]

    def test_empty_dir_renders_without_crashing(self, data_root):
        make_dir(data_root, "proj", {})
        assert "(空目录)" in render(resolve_data("proj"))


class TestRender:
    def test_render_states_what_was_left_out(self, data_root):
        make_dir(data_root, "proj", {"a.md": "small", "huge.md": "x" * (INLINE_MAX_BYTES + 1)})
        text = render(resolve_data("proj"))
        assert "全文吐出 1/2 个文件" in text
        assert "--- a.md ---" in text
        assert "--- huge.md ---" not in text
        assert "按需自行 Read" in text

    def test_render_shows_path_and_match_reason(self, data_root):
        make_dir(data_root, "20260725-cxmt-ipo-video", {"a.md": "x"})
        text = render(resolve_data("cxmt-ipo-video"))
        assert "20260725-cxmt-ipo-video" in text
        assert "命中方式" in text


class TestRefParsing:
    def test_splits_scheme_and_key(self):
        assert split_ref("data:cxmt-ipo") == ("data", "cxmt-ipo")

    def test_key_may_contain_colons(self):
        assert split_ref("data:a:b") == ("data", "a:b")

    def test_missing_scheme_suggests_the_data_prefix(self):
        with pytest.raises(ContextError) as exc:
            split_ref("cxmt-ipo")
        assert "frago context data:cxmt-ipo" in exc.value.fixes

    def test_empty_key_raises(self):
        with pytest.raises(ContextError, match="没给关键词"):
            split_ref("data:")

    def test_unknown_scheme_lists_available(self):
        with pytest.raises(ContextError, match="不认识的 scheme"):
            resolve_ref("run:etf")

    def test_scheme_is_case_insensitive(self, data_root):
        make_dir(data_root, "proj", {"a.md": "x"})
        assert resolve_ref("DATA:proj").path.name == "proj"
