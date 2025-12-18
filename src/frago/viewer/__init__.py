"""Frago Viewer - Universal content viewer with presentation and document modes.

This module provides a pywebview-based viewer for displaying various content types:
- Presentation mode: reveal.js-powered slideshows
- Document mode: scrollable documents (Markdown, HTML, PDF, code)
"""

from frago.viewer.window import ViewerWindow, show_content

__all__ = ["ViewerWindow", "show_content"]
