"""Presentation mode - reveal.js powered slideshows."""

import html
import re
from typing import Literal


def markdown_to_slides(content: str) -> str:
    """Convert markdown content to reveal.js slide sections.

    Supports:
    - --- for horizontal slide separators
    - -- for vertical slide separators

    Args:
        content: Markdown content with slide separators

    Returns:
        HTML string with <section> tags for reveal.js
    """
    # Split by horizontal separator first
    h_sections = re.split(r'\n---\n', content)
    slides = []

    for h_section in h_sections:
        # Check for vertical slides
        v_sections = re.split(r'\n--\n', h_section.strip())

        if len(v_sections) > 1:
            # Vertical slide group
            inner_slides = []
            for v in v_sections:
                inner_slides.append(f'<section data-markdown><textarea data-template>\n{v.strip()}\n</textarea></section>')
            slides.append(f'<section>\n{"".join(inner_slides)}\n</section>')
        else:
            # Single horizontal slide
            slides.append(f'<section data-markdown><textarea data-template>\n{h_section.strip()}\n</textarea></section>')

    return '\n'.join(slides)


def render_presentation(
    content: str,
    content_type: Literal["markdown", "html"],
    theme: str = "black",
    title: str = "Presentation",
) -> str:
    """Render a reveal.js presentation HTML.

    Args:
        content: Slide content (markdown or HTML)
        content_type: Type of content
        theme: reveal.js theme name
        title: Page title

    Returns:
        Complete HTML document string
    """
    # Process content based on type
    if content_type == "markdown":
        slides_html = markdown_to_slides(content)
    else:
        # HTML content - check if already has section tags
        if '<section' in content:
            slides_html = content
        else:
            # Wrap in a single section
            slides_html = f'<section>{content}</section>'

    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <link rel="stylesheet" href="/reveal/dist/reset.css">
    <link rel="stylesheet" href="/reveal/dist/reveal.css">
    <link rel="stylesheet" href="/reveal/dist/theme/{theme}.css">
    <!-- Code highlighting theme -->
    <link rel="stylesheet" href="/highlight/styles/github-dark.min.css">
    <style>
        /* Custom styles */
        .reveal pre {{
            width: 100%;
            box-shadow: none;
        }}
        .reveal code {{
            max-height: 500px;
        }}
        .reveal h1, .reveal h2, .reveal h3 {{
            text-transform: none;
        }}
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            {slides_html}
        </div>
    </div>

    <script src="/reveal/dist/reveal.js"></script>
    <script src="/reveal/dist/plugin/markdown/markdown.js"></script>
    <script src="/reveal/dist/plugin/highlight/highlight.js"></script>
    <script src="/reveal/dist/plugin/notes/notes.js"></script>
    <script src="/reveal/dist/plugin/math/math.js"></script>
    <script src="/reveal/dist/plugin/search/search.js"></script>
    <script src="/reveal/dist/plugin/zoom/zoom.js"></script>
    <script>
        Reveal.initialize({{
            hash: true,
            controls: true,
            progress: true,
            center: true,
            transition: 'slide',
            plugins: [ RevealMarkdown, RevealHighlight, RevealNotes, RevealMath, RevealSearch, RevealZoom ]
        }});
    </script>
</body>
</html>'''
