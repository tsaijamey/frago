"""``data:<关键词>`` 的范围与引用解析。

检索与呈现的判据在 test_report 里钉；这里只管两件事：``data:`` 把范围锁在
``~/.frago/data`` 而不是别处，以及引用怎么拆成 scheme 和关键词。
"""

import pytest

from frago.context import data_scheme
from frago.context.data_scheme import resolve_data
from frago.context.errors import ContextError
from frago.context.resolver import resolve_ref, split_ref


@pytest.fixture
def home(tmp_path, monkeypatch):
    """造一个 ~/.frago 的镜像：data 下有东西，data 之外也有。

    两侧都放，才验得出范围锁没锁住。NEVER 碰真人的 ~/.frago。
    """
    root = tmp_path / "frago_home"
    (root / "data" / "etf-plan").mkdir(parents=True)
    (root / "data" / "etf-plan" / "spec.md").write_text("etf 计划", encoding="utf-8")
    (root / "projects" / "etf-runner").mkdir(parents=True)
    (root / "projects" / "etf-runner" / "run.md").write_text("etf 执行", encoding="utf-8")
    monkeypatch.setattr(data_scheme, "DATA_ROOT", root / "data")
    return root


class TestScope:
    def test_searches_only_the_data_root(self, home):
        report = resolve_data("etf")
        assert report.root == home / "data"
        rels = [h.rel for h in report.dir_hits]
        assert rels == ["etf-plan"], "data 之外的 etf-runner 不该出现"

    def test_paths_are_relative_to_the_data_root(self, home):
        assert resolve_data("etf").dir_hits[0].rel == "etf-plan"

    def test_ref_carries_the_scheme(self, home):
        assert resolve_data("etf").ref == "data:etf"

    def test_explicit_root_overrides(self, home):
        report = resolve_data("etf", root=home / "projects")
        assert [h.rel for h in report.dir_hits] == ["etf-runner"]

    def test_missing_data_root_raises_with_a_fix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(data_scheme, "DATA_ROOT", tmp_path / "nope")
        with pytest.raises(ContextError) as exc:
            resolve_data("anything")
        assert "不存在" in exc.value.message
        assert exc.value.fixes

    def test_data_root_that_is_a_file_raises(self, tmp_path, monkeypatch):
        bogus = tmp_path / "data"
        bogus.write_text("not a dir")
        monkeypatch.setattr(data_scheme, "DATA_ROOT", bogus)
        with pytest.raises(ContextError, match="不是目录"):
            resolve_data("anything")


class TestRefParsing:
    def test_splits_scheme_and_key(self):
        assert split_ref("data:cxmt-ipo") == ("data", "cxmt-ipo")

    def test_key_may_contain_colons(self):
        assert split_ref("data:a:b") == ("data", "a:b")

    def test_scheme_is_case_insensitive(self, home):
        assert resolve_ref("DATA:etf").root == home / "data"

    def test_bare_keyword_has_no_scheme(self):
        """裸关键词 NEVER 被当成 data: 的简写——它有自己的含义（全盘搜索）。"""
        assert split_ref("cxmt-ipo") == (None, "cxmt-ipo")

    def test_colon_inside_a_sentence_is_not_a_scheme(self):
        """前缀带空白说明那个冒号属于正文，不是命名空间。"""
        assert split_ref("看看 data:x") == (None, "看看 data:x")

    def test_empty_ref_raises(self):
        with pytest.raises(ContextError, match="引用是空的"):
            split_ref("   ")

    def test_empty_key_raises(self):
        with pytest.raises(ContextError, match="没给关键词"):
            split_ref("data:")


class TestRouting:
    def test_known_scheme_routes_to_its_scope(self, home):
        assert resolve_ref("data:etf").root == home / "data"

    def test_unknown_scheme_lists_available(self):
        with pytest.raises(ContextError, match="不认识的 scheme"):
            resolve_ref("run:etf")

    def test_bare_keyword_refuses_without_consent(self):
        """没拿到同意就 NEVER 去翻整个 ~/.frago，那趟活又慢又脏。"""
        with pytest.raises(ContextError) as exc:
            resolve_ref("cxmt-ipo")
        assert "需要先确认" in exc.value.message
        assert "frago context data:cxmt-ipo" in exc.value.fixes
        assert "frago context cxmt-ipo --yes" in exc.value.fixes
