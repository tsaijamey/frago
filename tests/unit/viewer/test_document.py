"""Tests for frago.viewer.modes.document rendering.

Two things here were wrong in the same way — a document asked the page for
something at the wrong address — so each gets a test that would have caught it.

* Markdown wrapped in a layout container (`<div align="center">`) came out as
  literal text: the shell was passed through raw, so the reader saw
  `[Install](#install)` instead of a link.
* The PDF viewer asked for `/source.pdf`, which is the site root. The page
  lives at `/viewer/content/<id>/index.html` and the PDF sits beside it, so
  the request returned the WebUI's HTML and pdf.js failed on it.
"""

import re
from html import unescape

from frago.viewer.modes.document import _render_pdf_page, render_markdown


class TestMarkdownInContainer:
    """Markdown inside a layout container is prose and gets parsed."""

    def test_link_inside_centered_div_becomes_a_link(self):
        """The shape every README's title block has."""
        html = render_markdown(
            '<div align="center">\n\n# frago\n\n[Install](#install)\n\n</div>\n'
        )
        assert '<a href="#install">Install</a>' in html
        assert '[Install](#install)' not in html

    def test_heading_inside_centered_div_becomes_a_heading(self):
        html = render_markdown('<div align="center">\n\n# frago\n\n</div>\n')
        assert '<h1' in html
        assert '# frago' not in html

    def test_details_summary_carries_markdown(self):
        html = render_markdown(
            '<details>\n<summary>展开</summary>\n\n**粗** 与 [链接](a.md)\n\n</details>\n'
        )
        assert '<strong>粗</strong>' in html
        assert '<a href="a.md">链接</a>' in html

    def test_explicit_markdown_attribute_still_honoured(self):
        """A document that opted in by hand keeps working."""
        html = render_markdown('<div markdown="1">\n\n**粗**\n\n</div>\n')
        assert '<strong>粗</strong>' in html

    def test_fenced_code_is_left_alone(self):
        """`<div>` shown *as code* must stay code, tags and all."""
        html = render_markdown('```html\n<div align="center">\n  <b>x</b>\n</div>\n```\n')
        # The highlighter splits `&lt;` and `div` into separate spans, so read
        # the page the way a browser does: tags gone, entities resolved.
        text = unescape(re.sub(r'<[^>]+>', '', html))
        assert '<div align="center">' in text
        assert '<div align="center">' not in html

    def test_raw_table_inside_a_container_stays_raw(self):
        """A table's cells are markup, not prose — no Markdown pass over them."""
        html = render_markdown(
            '<div class="wrap">\n\n<table>\n<tr><td>*x*</td></tr>\n</table>\n\n</div>\n'
        )
        assert '*x*' in html
        assert '<em>x</em>' not in html

    def test_plain_markdown_is_untouched(self):
        html = render_markdown('# 标题\n\n- 甲\n- 乙\n\n段落 **粗** 与 `码`。\n')
        assert '<h1' in html
        assert '<li>甲</li>' in html
        assert '<strong>粗</strong>' in html


class TestPdfPage:
    """The PDF page asks for the document beside it, not the site root."""

    def test_requests_source_pdf_relative_to_the_page(self):
        html = _render_pdf_page("Report", "github-dark", "/viewer/resources")
        assert "getDocument('./source.pdf')" in html

    def test_does_not_request_source_pdf_from_the_site_root(self):
        """`/source.pdf` is the WebUI itself; pdf.js gets HTML and chokes."""
        html = _render_pdf_page("Report", "github-dark", "/viewer/resources")
        assert "getDocument('/source.pdf')" not in html
