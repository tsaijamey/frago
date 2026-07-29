"""三类命中的检索与呈现——这个包的主体。

核心承诺只有一条：**不吐任何文件正文**。这条命令曾经把命中目录里的小文件整篇贴
出来，一次调用六万多字符、约两万 token，替调用方做了它没要求的决定还花光了它的
预算。现在只报"命中在哪儿"，读什么由调用方自己定。

其余的判据都围着"结果要可解释"转：内容命中按次数排（规则透明），每条带一行摘要
（噪音自己暴露），被排除和被截断的一律报出数量（NEVER 让"没找"看起来像"找了没有"）。
"""

import shutil

import pytest

from frago.context.report import (
    MACHINE_SUFFIXES,
    MAX_CONTENT_HITS,
    MAX_DIR_HITS,
    READABLE_SUFFIXES,
    human_size,
    render,
    search,
    walk_names,
)

needs_rg = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep 不在 PATH 上")


def make(root, rel, files=None):
    """造一个目录，可选地塞几个文件。"""
    target = root / rel
    target.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (target / name).write_text(content, encoding="utf-8")
    return target


@pytest.fixture
def root(tmp_path):
    base = tmp_path / "frago_home"
    base.mkdir()
    return base


def run(keyword, root):
    return search(keyword, root, ref=f"data:{keyword}")


# ── 名字扫描 ────────────────────────────────────────────────────────
class TestWalkNames:
    def test_collects_dirs_and_files_at_every_depth(self, root):
        make(root, "data/proj/sub", {"note.md": "x"})
        dirs, files, scanned, _ = walk_names(root)
        assert {"data", "proj", "sub"} <= set(dirs)
        assert "note.md" in files
        assert scanned == 3

    def test_build_artefacts_are_pruned_and_counted(self, root):
        make(root, "pkg/node_modules/left-pad/lib", {"index.js": "x"})
        make(root, "data/proj")
        dirs, files, scanned, skipped = walk_names(root)
        assert "left-pad" not in dirs
        assert "index.js" not in files, "被剪掉的整棵树不该有文件漏进来"
        assert skipped == 1
        assert scanned == 3  # pkg, data, proj

    def test_same_name_in_several_places_all_kept(self, root):
        """同名目录树里到处都是，全部保留——调用方要看见它们分别在哪儿。"""
        make(root, "a/logs")
        make(root, "b/logs")
        dirs, _, _, _ = walk_names(root)
        assert len(dirs["logs"]) == 2


# ── 目录命中 ────────────────────────────────────────────────────────
class TestDirHits:
    def test_matches_by_name_at_any_depth(self, root):
        make(root, "data/lenovo-dev", {"a.md": "x"})
        make(root, "agent_os/videos/20260727-lenovo-demo", {"b.md": "x"})
        report = run("lenovo", root)
        assert {h.rel for h in report.dir_hits} == {
            "data/lenovo-dev",
            "agent_os/videos/20260727-lenovo-demo",
        }

    def test_reports_size_and_file_count(self, root):
        make(root, "data/proj", {"a.md": "12345", "b.md": "67890"})
        make(root, "data/proj/sub", {"c.md": "1"})
        hit = run("proj", root).dir_hits[0]
        assert hit.file_count == 3
        assert hit.total_bytes == 11

    def test_size_ignores_build_artefacts_like_the_scan_does(self, root):
        make(root, "data/proj", {"a.md": "12345"})
        make(root, "data/proj/node_modules/dep", {"junk.js": "x" * 999})
        assert run("proj", root).dir_hits[0].total_bytes == 5

    def test_ranked_by_match_quality(self, root):
        make(root, "data/etf")
        make(root, "data/etf-dma-trading-plan")
        rels = [h.rel for h in run("etf", root).dir_hits]
        assert rels[0] == "data/etf", "完全同名排最前"

    def test_cap_is_stated_not_silent(self, root):
        for i in range(MAX_DIR_HITS + 4):
            make(root, f"data/proj-{i:02d}")
        report = run("proj", root)
        assert len(report.dir_hits) == MAX_DIR_HITS
        assert report.dir_total == MAX_DIR_HITS + 4
        assert "另有 4 个未列出" in render(report)

    def test_no_match_leaves_the_section_empty(self, root):
        make(root, "data/proj")
        report = run("kubernetes-operator", root)
        assert report.dir_hits == []
        assert report.empty


# ── 文件名命中 ──────────────────────────────────────────────────────
class TestFileHits:
    def test_matches_file_names(self, root):
        make(root, "data/proj", {"lenovo-notes.md": "irrelevant body"})
        hit = run("lenovo", root).file_hits[0]
        assert hit.rel == "data/proj/lenovo-notes.md"
        assert hit.size == len("irrelevant body")

    def test_directory_and_file_hits_are_separate_sections(self, root):
        make(root, "data/lenovo-dev", {"lenovo-notes.md": "x"})
        report = run("lenovo", root)
        assert [h.rel for h in report.dir_hits] == ["data/lenovo-dev"]
        assert [h.rel for h in report.file_hits] == ["data/lenovo-dev/lenovo-notes.md"]


# ── 内容命中 ────────────────────────────────────────────────────────
@needs_rg
class TestContentHits:
    def test_finds_the_keyword_in_prose(self, root):
        make(root, "data/proj", {"notes.md": "这里讲的是 lenovo 的事"})
        hit = run("lenovo", root).content_hits[0]
        assert hit.rel == "data/proj/notes.md"
        assert hit.count == 1

    def test_ranked_by_hit_count(self, root):
        make(
            root,
            "data/proj",
            {
                "few.md": "lenovo",
                "many.md": "lenovo lenovo lenovo lenovo",
                "some.md": "lenovo lenovo",
            },
        )
        rels = [h.rel for h in run("lenovo", root).content_hits]
        assert rels == [
            "data/proj/many.md",
            "data/proj/some.md",
            "data/proj/few.md",
        ]

    def test_ties_break_by_path_so_results_are_reproducible(self, root):
        make(root, "data/proj", {"b.md": "lenovo", "a.md": "lenovo"})
        first = [h.rel for h in run("lenovo", root).content_hits]
        second = [h.rel for h in run("lenovo", root).content_hits]
        assert first == second == ["data/proj/a.md", "data/proj/b.md"]

    def test_counts_matches_not_lines(self, root):
        """一行里出现三次就是三次。"""
        make(root, "data/proj", {"a.md": "lenovo lenovo lenovo"})
        assert run("lenovo", root).content_hits[0].count == 3

    def test_case_insensitive(self, root):
        make(root, "data/proj", {"a.md": "LENOVO Lenovo lenovo"})
        assert run("lenovo", root).content_hits[0].count == 3

    def test_machine_formats_are_counted_not_listed(self, root):
        """json / jsonl / html 的命中多半落在路径和标识符上，不是正文。"""
        make(root, "data/proj", {"notes.md": "lenovo", "dump.json": '{"p":"lenovo"}'})
        report = run("lenovo", root)
        assert [h.rel for h in report.content_hits] == ["data/proj/notes.md"]
        assert report.machine_total == 1
        assert "另有 1 个机器格式文件" in render(report)

    def test_unknown_extensions_are_searched_by_neither(self, root):
        make(root, "data/proj", {"blob.bin": "lenovo", "notes.md": "lenovo"})
        report = run("lenovo", root)
        assert [h.rel for h in report.content_hits] == ["data/proj/notes.md"]
        assert report.machine_total == 0

    def test_readable_and_machine_suffix_lists_do_not_overlap(self):
        assert not set(READABLE_SUFFIXES) & set(MACHINE_SUFFIXES)

    def test_cap_is_stated_not_silent(self, root):
        files = {f"f{i:02d}.md": "lenovo " * (60 - i) for i in range(MAX_CONTENT_HITS + 5)}
        make(root, "data/proj", files)
        report = run("lenovo", root)
        assert len(report.content_hits) == MAX_CONTENT_HITS
        assert report.content_total == MAX_CONTENT_HITS + 5
        assert "另有 5 个未列出" in render(report)


@needs_rg
class TestSnippets:
    def test_snippet_shows_the_surrounding_text(self, root):
        body = "开头无关的一段。这里讲的是 lenovo 的一张纸销售方法论画布。后面还有别的。"
        make(root, "data/proj", {"notes.md": body})
        snippet = run("lenovo", root).content_hits[0].snippet
        assert "lenovo" in snippet
        assert "一张纸销售方法论画布" in snippet

    def test_long_line_still_yields_a_snippet(self, root):
        """中文一段就是一行。整行截断的做法会让长行完全没有摘要，而摘要正是
        判断这条命中是不是噪音的唯一证据。"""
        body = "填充" * 2000 + " lenovo 关键的一句 " + "填充" * 2000
        make(root, "data/proj", {"notes.md": body})
        snippet = run("lenovo", root).content_hits[0].snippet
        assert "lenovo" in snippet
        assert "关键的一句" in snippet
        assert "Omitted" not in snippet

    def test_noise_is_visible_in_the_snippet(self, root):
        """机器清单不靠排序压下去，靠摘要让调用方一眼认出来。"""
        make(root, "data/proj", {"_concat.txt": "file '/x/lenovo-demo/S001.wav'"})
        snippet = run("lenovo", root).content_hits[0].snippet
        assert "S001.wav" in snippet

    def test_snippet_is_bounded(self, root):
        make(root, "data/proj", {"a.md": "x" * 5000 + "lenovo" + "y" * 5000})
        assert len(run("lenovo", root).content_hits[0].snippet) <= 200


@needs_rg
class TestLiteralKeyword:
    def test_regex_metacharacters_are_literal(self, root):
        """关键词里的 . ( + 是字面量。摘要那一趟用正则取窗口，转义漏了就会错配。"""
        make(root, "data/proj", {"hit.md": "see builtin-rules.json here", "miss.md": "builtin-rulesXjson"})
        rels = [h.rel for h in run("builtin-rules.json", root).content_hits]
        assert rels == ["data/proj/hit.md"]

    def test_bracket_keyword_does_not_crash_the_snippet_pass(self, root):
        make(root, "data/proj", {"a.md": "前 [MUST] 后"})
        hit = run("[MUST]", root).content_hits[0]
        assert hit.count == 1
        assert "[MUST]" in hit.snippet


# ── never inline ────────────────────────────────────────────────────
@needs_rg
class TestNeverInlinesContent:
    def test_file_bodies_are_never_printed(self, root):
        """这个包的核心承诺。回归了就等于又把两万 token 塞回调用方嘴里。"""
        secret = "这一整段正文不该出现在输出里" * 20
        make(root, "data/lenovo-dev", {"notebook.md": f"lenovo\n{secret}"})
        text = render(run("lenovo", root))
        assert secret not in text
        assert "notebook.md" in text

    def test_output_stays_small_even_for_a_fat_directory(self, root):
        files = {f"doc{i:02d}.md": "lenovo\n" + "正文" * 5000 for i in range(30)}
        make(root, "data/lenovo-dev", files)
        assert len(render(run("lenovo", root))) < 8000


# ── 降级与渲染 ──────────────────────────────────────────────────────
class TestDegradation:
    def test_missing_ripgrep_is_reported_not_fatal(self, root, monkeypatch):
        monkeypatch.setattr("frago.context.report.shutil.which", lambda _: None)
        make(root, "data/lenovo-dev", {"a.md": "lenovo"})
        report = run("lenovo", root)
        assert report.content_hits == []
        assert any("ripgrep" in n for n in report.notes)
        # 名字那两段照样要出结果——一半坏了 NEVER 拖垮另一半
        assert [h.rel for h in report.dir_hits] == ["data/lenovo-dev"]
        assert "[!]" in render(report)

    def test_missing_root_raises(self, tmp_path):
        from frago.context.errors import ContextError

        with pytest.raises(ContextError, match="不存在"):
            run("x", tmp_path / "nope")


class TestRender:
    def test_all_three_sections_always_present(self, root):
        make(root, "data/proj")
        text = render(run("nothing-matches-this", root))
        assert "目录命中" in text
        assert "文件名命中" in text
        assert "可读内容命中" in text

    def test_empty_sections_say_so(self, root):
        make(root, "data/proj")
        text = render(run("nothing-matches-this", root))
        assert "（没有目录名匹配）" in text
        assert "（没有文件名匹配）" in text

    def test_scan_scope_is_always_stated(self, root):
        make(root, "data/proj/node_modules/dep")
        text = render(run("proj", root))
        assert "个目录" in text
        assert "跳过 1 个构建产物目录" in text

    def test_human_size(self):
        assert human_size(512) == "512 B"
        assert human_size(2048) == "2.0 KB"
        assert human_size(5 * 1024 * 1024) == "5.0 MB"
        assert human_size(3 * 1024**3) == "3.0 GB"
