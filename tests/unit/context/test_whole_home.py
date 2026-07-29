"""裸关键词的全盘兜底：翻遍整个 ~/.frago。

这条路径存在的理由只有一个——``data:`` 锁死在一处，而东西不一定落在那一处。
所以这里钉的是"范围真的覆盖了 data 之外"，以及"拿不到同意就连扫都不扫"。
"""

import shutil

import pytest

from frago.context import whole_home
from frago.context.errors import ContextError
from frago.context.resolver import resolve_ref
from frago.context.whole_home import resolve_anywhere

needs_rg = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep 不在 PATH 上")


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "frago_home"
    (root / "data" / "etf-plan").mkdir(parents=True)
    (root / "data" / "etf-plan" / "spec.md").write_text("etf 计划", encoding="utf-8")
    (root / "app-state" / "hook_rules_dashboard").mkdir(parents=True)
    (root / "app-state" / "hook_rules_dashboard" / "state.md").write_text(
        "面板状态", encoding="utf-8"
    )
    (root / "cache" / "x" / "node_modules" / "dep").mkdir(parents=True)
    monkeypatch.setattr(whole_home, "FRAGO_ROOT", root)
    return root


class TestScope:
    def test_reaches_beyond_the_data_root(self, home):
        """全盘搜索的全部意义就在这儿：data: 找不到的地方它能找到。"""
        report = resolve_anywhere("hook-rules-dashboard")
        assert [h.rel for h in report.dir_hits] == ["app-state/hook_rules_dashboard"]

    def test_root_is_the_whole_frago_home(self, home):
        assert resolve_anywhere("etf").root == home

    def test_ref_is_the_bare_keyword(self, home):
        assert resolve_anywhere("etf").ref == "etf"

    def test_paths_are_relative_to_the_frago_home(self, home):
        assert resolve_anywhere("etf").dir_hits[0].rel == "data/etf-plan"

    def test_build_artefacts_are_pruned_and_counted(self, home):
        assert resolve_anywhere("etf").skipped_dirs == 1

    def test_missing_root_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(whole_home, "FRAGO_ROOT", tmp_path / "nope")
        with pytest.raises(ContextError, match="不存在"):
            resolve_anywhere("x")

    @needs_rg
    def test_content_search_also_spans_the_whole_tree(self, home):
        rels = [h.rel for h in resolve_anywhere("面板状态").content_hits]
        assert rels == ["app-state/hook_rules_dashboard/state.md"]


class TestConsentGate:
    def test_consent_routes_here(self, home):
        report = resolve_ref("hook-rules-dashboard", allow_whole_home=True)
        assert report.root == home

    def test_without_consent_nothing_is_walked(self, home, monkeypatch):
        """拒绝时 MUST 连扫描都不发生，否则那道确认就白设了。"""

        def boom(*_args, **_kwargs):
            raise AssertionError("没拿到同意却动手扫了")

        monkeypatch.setattr(whole_home, "resolve_anywhere", boom)
        with pytest.raises(ContextError, match="需要先确认"):
            resolve_ref("hook-rules-dashboard")
