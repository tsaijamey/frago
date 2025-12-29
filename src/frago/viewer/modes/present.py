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
    # Remove leading HTML comments (common in markdown files)
    content = re.sub(r'^\s*<!--[\s\S]*?-->\s*', '', content)
    # Remove leading separator (after comment removal)
    content = re.sub(r'^[\s\n]*---[\s\n]*', '', content)

    # Split by horizontal separator first
    h_sections = re.split(r'\n---\n', content)
    slides = []

    for h_section in h_sections:
        section_content = h_section.strip()
        # Skip empty sections
        if not section_content:
            continue

        # Check for vertical slides
        v_sections = re.split(r'\n--\n', section_content)

        if len(v_sections) > 1:
            # Vertical slide group
            inner_slides = []
            for v in v_sections:
                v_content = v.strip()
                if v_content:
                    inner_slides.append(f'<section data-markdown><textarea data-template>\n{v_content}\n</textarea></section>')
            if inner_slides:
                slides.append(f'<section>\n{"".join(inner_slides)}\n</section>')
        else:
            # Single horizontal slide
            slides.append(f'<section data-markdown><textarea data-template>\n{section_content}\n</textarea></section>')

    return '\n'.join(slides)


def render_presentation(
    content: str,
    content_type: Literal["markdown", "html"],
    theme: str = "black",
    title: str = "Presentation",
    resources_base: str = "",
) -> str:
    """Render a reveal.js presentation HTML.

    Args:
        content: Slide content (markdown or HTML)
        content_type: Type of content
        theme: reveal.js theme name
        title: Page title
        resources_base: Base path for resources (e.g., "/viewer/resources")

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
    <link rel="stylesheet" href="{resources_base}/reveal/dist/reset.css">
    <link rel="stylesheet" href="{resources_base}/reveal/dist/reveal.css">
    <link rel="stylesheet" href="{resources_base}/reveal/dist/theme/{theme}.css">
    <!-- Code highlighting theme -->
    <link rel="stylesheet" href="{resources_base}/highlight/styles/github-dark.min.css">
    <style>
        /* Smaller font sizes for better content fit */
        .reveal {{
            font-size: 24px;
        }}
        .reveal h1 {{
            font-size: 1.8em;
            text-transform: none;
        }}
        .reveal h2 {{
            font-size: 1.4em;
            text-transform: none;
        }}
        .reveal h3 {{
            font-size: 1.1em;
            text-transform: none;
        }}
        .reveal p, .reveal li {{
            font-size: 0.9em;
            line-height: 1.4;
        }}
        .reveal table {{
            font-size: 0.8em;
        }}
        .reveal pre {{
            width: 100%;
            box-shadow: none;
            font-size: 0.7em;
        }}
        .reveal code {{
            max-height: 500px;
        }}
        .reveal blockquote {{
            font-size: 0.85em;
        }}
        .reveal img {{
            max-height: 50vh;
        }}
        /* Enable scrolling for long content */
        .reveal .slides section {{
            overflow-y: auto;
            max-height: 95vh;
            padding: 20px;
        }}
        .reveal .slides section::-webkit-scrollbar {{
            width: 6px;
        }}
        .reveal .slides section::-webkit-scrollbar-thumb {{
            background: rgba(255,255,255,0.3);
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            {slides_html}
        </div>
    </div>

    <script src="{resources_base}/reveal/dist/reveal.js"></script>
    <script src="{resources_base}/reveal/dist/plugin/markdown/markdown.js"></script>
    <script src="{resources_base}/reveal/dist/plugin/highlight/highlight.js"></script>
    <script src="{resources_base}/reveal/dist/plugin/notes/notes.js"></script>
    <script src="{resources_base}/reveal/dist/plugin/math/math.js"></script>
    <script src="{resources_base}/reveal/dist/plugin/search/search.js"></script>
    <script src="{resources_base}/reveal/dist/plugin/zoom/zoom.js"></script>
    <script>
        Reveal.initialize({{
            hash: true,
            controls: true,
            progress: true,
            center: false,
            transition: 'slide',
            width: '100%',
            height: '100%',
            margin: 0.04,
            minScale: 0.2,
            maxScale: 2.0,
            disableLayout: false,
            plugins: [ RevealMarkdown, RevealHighlight, RevealNotes, RevealMath, RevealSearch, RevealZoom ]
        }});
    </script>
</body>
</html>'''
