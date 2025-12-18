"""Document mode - scrollable document rendering with syntax highlighting."""

import html
import json
import re
from typing import Literal


def get_language_from_extension(ext: str) -> str:
    """Map file extension to highlight.js language name."""
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".css": "css",
        ".html": "html",
        ".htm": "html",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".xml": "xml",
        ".md": "markdown",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".sql": "sql",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".r": "r",
        ".lua": "lua",
        ".vim": "vim",
        ".dockerfile": "dockerfile",
        ".makefile": "makefile",
    }
    return mapping.get(ext.lower(), "plaintext")


def render_markdown(content: str) -> str:
    """Render markdown to HTML with Mermaid support.

    Falls back to simple rendering if markdown library not available.
    """
    try:
        import markdown

        # Pre-process: protect mermaid blocks from code highlighting
        mermaid_blocks: list[str] = []

        def save_mermaid(match: re.Match) -> str:
            idx = len(mermaid_blocks)
            mermaid_blocks.append(match.group(1))
            return f"MERMAID_PLACEHOLDER_{idx}"

        content = re.sub(
            r"```mermaid\n([\s\S]*?)```", save_mermaid, content
        )

        md = markdown.Markdown(extensions=[
            'fenced_code',
            'codehilite',
            'tables',
            'toc',
            'sane_lists',
            'def_list',
            'abbr',
            'footnotes',
            'attr_list',
            'md_in_html',
        ])
        converted = md.convert(content)

        # Post-process: restore mermaid blocks with proper wrapper
        for idx, block in enumerate(mermaid_blocks):
            converted = converted.replace(
                f"MERMAID_PLACEHOLDER_{idx}",
                f'<pre class="mermaid">{html.escape(block)}</pre>',
            )

        return converted
    except ImportError:
        # Fallback: basic escaping and line breaks
        escaped = html.escape(content)
        return f'<pre style="white-space: pre-wrap;">{escaped}</pre>'


def render_json(content: str) -> str:
    """Render JSON with formatting and syntax highlighting."""
    try:
        parsed = json.loads(content)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        escaped = html.escape(formatted)
        return f'<pre><code class="language-json">{escaped}</code></pre>'
    except json.JSONDecodeError:
        escaped = html.escape(content)
        return f'<pre><code class="language-json">{escaped}</code></pre>'


def render_code(content: str, language: str) -> str:
    """Render code with syntax highlighting."""
    escaped = html.escape(content)
    return f'<pre><code class="language-{language}">{escaped}</code></pre>'


def render_document(
    content: str,
    content_type: Literal["markdown", "html", "pdf", "json", "code"],
    theme: str = "github-dark",
    title: str = "Document",
    language: str = "plaintext",
) -> str:
    """Render a document HTML page.

    Args:
        content: Document content
        content_type: Type of content
        theme: Code highlighting theme
        title: Page title
        language: Programming language for code highlighting

    Returns:
        Complete HTML document string
    """
    # Process content based on type
    if content_type == "pdf":
        body_content = _render_pdf_viewer()
    elif content_type == "markdown":
        body_content = f'<article class="markdown-body">{render_markdown(content)}</article>'
    elif content_type == "html":
        body_content = f'<article class="html-content">{content}</article>'
    elif content_type == "json":
        body_content = f'<article class="code-content">{render_json(content)}</article>'
    else:  # code
        body_content = f'<article class="code-content">{render_code(content, language)}</article>'

    # PDF viewer needs special handling
    if content_type == "pdf":
        return _render_pdf_page(title, theme)

    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <link rel="stylesheet" href="/highlight/styles/{theme}.min.css">
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #c9d1d9;
            background-color: #0d1117;
            margin: 0;
            padding: 20px 40px;
        }}
        article {{
            max-width: 900px;
            margin: 0 auto;
        }}
        /* Markdown styles */
        .markdown-body h1, .markdown-body h2, .markdown-body h3,
        .markdown-body h4, .markdown-body h5, .markdown-body h6 {{
            color: #c9d1d9;
            border-bottom: 1px solid #21262d;
            padding-bottom: 0.3em;
            margin-top: 24px;
            margin-bottom: 16px;
        }}
        .markdown-body h1 {{ font-size: 2em; }}
        .markdown-body h2 {{ font-size: 1.5em; }}
        .markdown-body h3 {{ font-size: 1.25em; }}
        .markdown-body p {{
            margin-bottom: 16px;
        }}
        .markdown-body a {{
            color: #58a6ff;
            text-decoration: none;
        }}
        .markdown-body a:hover {{
            text-decoration: underline;
        }}
        .markdown-body code {{
            background-color: rgba(110, 118, 129, 0.4);
            padding: 0.2em 0.4em;
            border-radius: 6px;
            font-size: 85%;
        }}
        .markdown-body pre {{
            background-color: #161b22;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        .markdown-body pre code {{
            background: none;
            padding: 0;
        }}
        .markdown-body blockquote {{
            border-left: 4px solid #30363d;
            padding-left: 16px;
            color: #8b949e;
            margin: 0 0 16px 0;
        }}
        .markdown-body table {{
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 16px;
        }}
        .markdown-body th, .markdown-body td {{
            border: 1px solid #30363d;
            padding: 8px 12px;
        }}
        .markdown-body th {{
            background-color: #161b22;
        }}
        .markdown-body ul, .markdown-body ol {{
            padding-left: 2em;
            margin-bottom: 16px;
        }}
        .markdown-body li {{
            margin-bottom: 4px;
        }}
        .markdown-body img {{
            max-width: 100%;
            height: auto;
        }}
        .markdown-body hr {{
            border: none;
            border-top: 1px solid #30363d;
            margin: 24px 0;
        }}
        /* Mermaid diagram styles */
        .mermaid {{
            background: transparent;
            text-align: center;
            margin: 16px 0;
        }}
        /* Code content styles */
        .code-content pre {{
            background-color: #161b22;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 0;
        }}
        .code-content code {{
            font-family: 'SF Mono', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 14px;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    {body_content}
    <script src="/highlight/highlight.min.js"></script>
    <script src="/mermaid/mermaid.min.js"></script>
    <script>
        document.querySelectorAll('pre code').forEach((block) => {{
            hljs.highlightElement(block);
        }});
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'dark',
            securityLevel: 'loose'
        }});
    </script>
</body>
</html>'''


def _render_pdf_viewer() -> str:
    """Render PDF viewer container."""
    return '<div id="pdf-container"></div>'


def _render_pdf_page(title: str, theme: str) -> str:
    """Render complete PDF viewer page."""
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            padding: 0;
            background-color: #525659;
            overflow: hidden;
        }}
        #pdf-container {{
            width: 100vw;
            height: 100vh;
            overflow: auto;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
            gap: 10px;
        }}
        .page-canvas {{
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            background: white;
        }}
        #controls {{
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.7);
            padding: 10px 20px;
            border-radius: 8px;
            color: white;
            display: flex;
            gap: 15px;
            align-items: center;
            z-index: 1000;
        }}
        #controls button {{
            background: #4a4a4a;
            border: none;
            color: white;
            padding: 5px 15px;
            border-radius: 4px;
            cursor: pointer;
        }}
        #controls button:hover {{
            background: #5a5a5a;
        }}
        #page-info {{
            min-width: 100px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div id="pdf-container"></div>
    <div id="controls">
        <button id="zoom-out">-</button>
        <span id="zoom-level">100%</span>
        <button id="zoom-in">+</button>
        <span id="page-info">Loading...</span>
    </div>

    <script type="module">
        import * as pdfjsLib from '/pdfjs/pdf.min.mjs';

        pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdfjs/pdf.worker.min.mjs';

        let pdfDoc = null;
        let scale = 1.0;
        const container = document.getElementById('pdf-container');
        const pageInfo = document.getElementById('page-info');
        const zoomLevel = document.getElementById('zoom-level');

        async function loadPDF() {{
            try {{
                pdfDoc = await pdfjsLib.getDocument('/source.pdf').promise;
                pageInfo.textContent = `${{pdfDoc.numPages}} pages`;
                renderAllPages();
            }} catch (error) {{
                container.innerHTML = `<div style="color: white; padding: 20px;">Error loading PDF: ${{error.message}}</div>`;
            }}
        }}

        async function renderAllPages() {{
            container.innerHTML = '';
            for (let i = 1; i <= pdfDoc.numPages; i++) {{
                const page = await pdfDoc.getPage(i);
                const viewport = page.getViewport({{ scale }});

                const canvas = document.createElement('canvas');
                canvas.className = 'page-canvas';
                canvas.width = viewport.width;
                canvas.height = viewport.height;

                const context = canvas.getContext('2d');
                await page.render({{ canvasContext: context, viewport }}).promise;

                container.appendChild(canvas);
            }}
        }}

        document.getElementById('zoom-in').onclick = () => {{
            scale = Math.min(scale + 0.25, 3.0);
            zoomLevel.textContent = `${{Math.round(scale * 100)}}%`;
            renderAllPages();
        }};

        document.getElementById('zoom-out').onclick = () => {{
            scale = Math.max(scale - 0.25, 0.5);
            zoomLevel.textContent = `${{Math.round(scale * 100)}}%`;
            renderAllPages();
        }};

        loadPDF();
    </script>
</body>
</html>'''
