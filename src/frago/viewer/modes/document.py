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
        ".jsonl": "json",
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
    resources_base: str = "",
) -> str:
    """Render a document HTML page.

    Args:
        content: Document content
        content_type: Type of content
        theme: Code highlighting theme
        title: Page title
        language: Programming language for code highlighting
        resources_base: Base path for resources (e.g., "/viewer/resources")

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
        return _render_pdf_page(title, theme, resources_base)

    # Add viewer controls for code content (json/code) and markdown
    show_wrap_toggle = content_type in ("json", "code")
    show_wechat_copy = content_type == "markdown"

    # Build viewer controls dynamically
    control_buttons = []
    if show_wrap_toggle:
        control_buttons.append('''
        <button id="wrap-toggle" class="active" type="button" title="Toggle word wrap" aria-label="Toggle word wrap">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 6h18M3 12h15a3 3 0 1 1 0 6h-4"/>
                <polyline points="13 16 16 19 13 22"/>
            </svg>
            Wrap
        </button>''')

    if show_wechat_copy:
        control_buttons.append('''
        <button id="wechat-copy" type="button" title="复制公众号格式" aria-label="Copy for WeChat">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <span class="btn-text">复制公众号格式</span>
        </button>''')

    viewer_controls = ""
    if control_buttons:
        viewer_controls = f'''
    <div class="viewer-controls">{"".join(control_buttons)}
    </div>'''

    wrap_toggle_script = ""
    if show_wrap_toggle:
        wrap_toggle_script = '''
        // Word wrap toggle
        const wrapToggle = document.getElementById('wrap-toggle');
        const codeContent = document.querySelector('.code-content');
        if (wrapToggle && codeContent) {
            wrapToggle.addEventListener('click', () => {
                codeContent.classList.toggle('no-wrap');
                wrapToggle.classList.toggle('active');
            });
        }'''

    wechat_copy_script = ""
    if show_wechat_copy:
        wechat_copy_script = '''
        // WeChat copy functionality - optimized for light background
        function showToast(message, type) {
            const existing = document.querySelector('.copy-toast');
            if (existing) existing.remove();

            const toast = document.createElement('div');
            toast.className = 'copy-toast ' + type;
            toast.textContent = message;
            document.body.appendChild(toast);

            requestAnimationFrame(() => toast.classList.add('show'));

            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // WeChat-friendly styles (light theme for white background)
        const wechatStyles = {
            article: 'color: #333; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 16px; line-height: 1.8;',
            h1: 'color: #1a1a1a; font-size: 24px; font-weight: 600; margin: 24px 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #eee;',
            h2: 'color: #1a1a1a; font-size: 20px; font-weight: 600; margin: 20px 0 12px 0; padding-bottom: 6px; border-bottom: 1px solid #eee;',
            h3: 'color: #1a1a1a; font-size: 18px; font-weight: 600; margin: 16px 0 10px 0;',
            h4: 'color: #1a1a1a; font-size: 16px; font-weight: 600; margin: 14px 0 8px 0;',
            p: 'color: #333; margin: 0 0 16px 0; text-align: justify;',
            a: 'color: #576b95; text-decoration: none;',
            strong: 'color: #1a1a1a; font-weight: 600;',
            em: 'font-style: italic;',
            code: 'background-color: #f6f8fa; color: #d14; padding: 2px 6px; border-radius: 4px; font-family: Consolas, Monaco, "Courier New", monospace; font-size: 14px;',
            pre: 'background-color: #f6f8fa; padding: 16px; border-radius: 8px; overflow-x: auto; margin: 16px 0;',
            'pre code': 'background-color: transparent; color: #333; padding: 0; font-family: Consolas, Monaco, "Courier New", monospace; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;',
            blockquote: 'border-left: 4px solid #ddd; padding-left: 16px; color: #666; margin: 16px 0; font-style: italic;',
            ul: 'padding-left: 24px; margin: 0 0 16px 0;',
            ol: 'padding-left: 24px; margin: 0 0 16px 0;',
            li: 'color: #333; margin: 4px 0; line-height: 1.8;',
            table: 'border-collapse: collapse; width: 100%; margin: 16px 0;',
            th: 'background-color: #f6f8fa; border: 1px solid #ddd; padding: 10px 12px; text-align: left; font-weight: 600;',
            td: 'border: 1px solid #ddd; padding: 10px 12px;',
            hr: 'border: none; border-top: 1px solid #eee; margin: 24px 0;',
            img: 'max-width: 100%; height: auto;'
        };

        function processForWeChat(element) {
            const clone = element.cloneNode(true);

            // Apply styles to root
            clone.setAttribute('style', wechatStyles.article);

            // Process all elements
            const tagMap = {
                'H1': 'h1', 'H2': 'h2', 'H3': 'h3', 'H4': 'h4', 'H5': 'h4', 'H6': 'h4',
                'P': 'p', 'A': 'a', 'STRONG': 'strong', 'B': 'strong',
                'EM': 'em', 'I': 'em', 'CODE': 'code', 'PRE': 'pre',
                'BLOCKQUOTE': 'blockquote', 'UL': 'ul', 'OL': 'ol', 'LI': 'li',
                'TABLE': 'table', 'TH': 'th', 'TD': 'td', 'HR': 'hr', 'IMG': 'img'
            };

            clone.querySelectorAll('*').forEach(el => {
                const tag = el.tagName;
                const styleKey = tagMap[tag];

                // Special handling for code inside pre
                if (tag === 'CODE' && el.parentElement && el.parentElement.tagName === 'PRE') {
                    el.setAttribute('style', wechatStyles['pre code']);
                } else if (styleKey && wechatStyles[styleKey]) {
                    el.setAttribute('style', wechatStyles[styleKey]);
                }

                // Remove class and data-* attributes
                el.removeAttribute('class');
                [...el.attributes].forEach(attr => {
                    if (attr.name.startsWith('data-')) {
                        el.removeAttribute(attr.name);
                    }
                });
            });

            // Handle mermaid diagrams - convert to placeholder text
            clone.querySelectorAll('.mermaid, pre.mermaid').forEach(el => {
                const placeholder = document.createElement('p');
                placeholder.setAttribute('style', 'color: #666; font-style: italic; text-align: center; padding: 20px; background: #f9f9f9; border-radius: 8px;');
                placeholder.textContent = '[图表请在公众号中重新绘制]';
                el.parentNode.replaceChild(placeholder, el);
            });

            return clone;
        }

        async function copyForWeChat() {
            const btn = document.getElementById('wechat-copy');
            const article = document.querySelector('.markdown-body');
            if (!btn || !article) return;

            btn.classList.add('loading');

            try {
                const processed = processForWeChat(article);
                const html = processed.outerHTML;
                const text = article.textContent || '';

                if (navigator.clipboard && window.ClipboardItem) {
                    await navigator.clipboard.write([
                        new ClipboardItem({
                            'text/html': new Blob([html], { type: 'text/html' }),
                            'text/plain': new Blob([text], { type: 'text/plain' })
                        })
                    ]);
                } else {
                    const textarea = document.createElement('textarea');
                    textarea.value = text;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                }

                showToast('已复制到剪贴板，可直接粘贴到公众号编辑器', 'success');
            } catch (err) {
                console.error('Copy failed:', err);
                showToast('复制失败: ' + err.message, 'error');
            } finally {
                btn.classList.remove('loading');
            }
        }

        const wechatBtn = document.getElementById('wechat-copy');
        if (wechatBtn) {
            wechatBtn.addEventListener('click', copyForWeChat);
        }'''

    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <link rel="stylesheet" href="{resources_base}/highlight/styles/{theme}.min.css">
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
        /* Code content styles - default: wrap enabled */
        .code-content pre {{
            background-color: #161b22;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .code-content code {{
            font-family: 'SF Mono', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 14px;
            line-height: 1.5;
        }}
        /* No-wrap mode */
        .code-content.no-wrap pre {{
            white-space: pre;
            word-break: normal;
        }}
        /* Viewer controls - floating toggle button */
        .viewer-controls {{
            position: fixed;
            top: 16px;
            right: 16px;
            display: flex;
            gap: 8px;
            z-index: 100;
        }}
        .viewer-controls button {{
            background: rgba(48, 54, 61, 0.9);
            border: 1px solid #30363d;
            color: #c9d1d9;
            padding: 6px 12px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: background-color 0.15s, border-color 0.15s;
        }}
        .viewer-controls button:hover {{
            background: rgba(48, 54, 61, 1);
        }}
        .viewer-controls button.active {{
            background: #238636;
            border-color: #238636;
        }}
        .viewer-controls button svg {{
            width: 14px;
            height: 14px;
        }}
        /* Button loading state */
        .viewer-controls button.loading {{
            opacity: 0.7;
            cursor: wait;
        }}
        /* Toast notification */
        .copy-toast {{
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: rgba(0, 0, 0, 0.85);
            color: white;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 14px;
            z-index: 1000;
            opacity: 0;
            transition: all 0.3s ease;
            pointer-events: none;
            max-width: 90vw;
            text-align: center;
        }}
        .copy-toast.show {{
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }}
        .copy-toast.success {{
            background: #238636;
        }}
        .copy-toast.error {{
            background: #da3633;
        }}
    </style>
</head>
<body>{viewer_controls}
    {body_content}
    <script src="{resources_base}/highlight/highlight.min.js"></script>
    <script src="{resources_base}/mermaid/mermaid.min.js"></script>
    <script>
        document.querySelectorAll('pre code').forEach((block) => {{
            hljs.highlightElement(block);
        }});
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'dark',
            securityLevel: 'loose'
        }});{wrap_toggle_script}{wechat_copy_script}
    </script>
</body>
</html>'''


def _render_pdf_viewer() -> str:
    """Render PDF viewer container."""
    return '<div id="pdf-container"></div>'


def _render_pdf_page(title: str, theme: str, resources_base: str = "") -> str:
    """Render complete PDF viewer page.

    Args:
        title: Page title
        theme: Theme name (unused for PDF but kept for consistency)
        resources_base: Base path for resources
    """
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
        import * as pdfjsLib from '{resources_base}/pdfjs/pdf.min.mjs';

        pdfjsLib.GlobalWorkerOptions.workerSrc = '{resources_base}/pdfjs/pdf.worker.min.mjs';

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
