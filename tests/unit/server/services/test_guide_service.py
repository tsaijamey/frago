"""Unit tests for GuideService pure helpers (Phase 5: 原零覆盖).

以单元测试为准：断言 frontmatter 解析 / TOC 抽取 / slugify（中英）/ 片段高亮的契约。
纯字符串函数，不碰文件系统。
"""

from frago.server.services.guide_service import GuideService


def test_parse_frontmatter_manual():
    text = "---\ntitle: Hello\norder: 2\n---\nbody line\n"
    meta, content = GuideService._parse_frontmatter_manual(text)
    assert meta == {"title": "Hello", "order": 2}
    assert content.strip() == "body line"


def test_parse_frontmatter_no_frontmatter():
    meta, content = GuideService._parse_frontmatter_manual("plain body")
    assert meta == {}
    assert content == "plain body"


def test_slugify_english_and_chinese():
    assert GuideService._slugify("Hello World") == "hello-world"
    assert GuideService._slugify("快速 开始") == "快速-开始"
    assert GuideService._slugify("A: B?!") == "a-b"


def test_extract_toc_levels_and_anchors():
    md = "# Title\n## Section One\nbody\n### Sub Section\n#not a heading"
    toc = GuideService._extract_toc(md)
    # H1 excluded (pattern is #{2,6}); H2 + H3 captured
    assert [t["level"] for t in toc] == [2, 3]
    assert toc[0]["title"] == "Section One"
    assert toc[0]["anchor"] == "section-one"
    assert toc[1]["anchor"] == "sub-section"


def test_highlight_snippet_wraps_match():
    text = "the quick brown fox jumps"
    out = GuideService._highlight_snippet(text, "brown", max_length=200)
    assert "<mark>brown</mark>" in out


def test_highlight_snippet_no_match_returns_text():
    assert GuideService._highlight_snippet("abc", "zzz") == "abc"


def test_highlight_snippet_adds_ellipsis_when_truncated():
    text = "x" * 100 + "TARGET" + "y" * 200
    out = GuideService._highlight_snippet(text, "TARGET")
    assert out.startswith("...")
    assert out.endswith("...")
    assert "<mark>TARGET</mark>" in out
