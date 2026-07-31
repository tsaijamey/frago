"""Frago Viewer - Universal content viewer with presentation and document modes.

This module provides a browser-based viewer for displaying various content types:
- Presentation mode: reveal.js-powered slideshows
- Document mode: scrollable documents (Markdown, HTML, PDF, code)

Content is served via the frago server and displayed in the browser.
"""

from frago.viewer.browser import BrowserViewer, show_content

__all__ = ["BrowserViewer", "show_content"]
