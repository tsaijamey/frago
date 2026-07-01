"""
Perception flow for chrome automation.

Relocated from cli/commands.py: DOM feature extraction, perception
screenshot capture, and post-action perception orchestration.  The CLI
layer only injects an output callback (printer) and the run screenshots
directory; the perception logic lives here.
"""

import time
from pathlib import Path
from typing import Callable, Optional

from ..chrome.cdp.session import CDPSession


def get_dom_features(session: CDPSession) -> dict:
    """Extract page DOM features, focusing on current visible area content"""
    script = """
    (function() {
        const body = document.body;
        const features = {
            title: document.title || '',
            url: window.location.href,
            body_class: body.className || '',
            body_id: body.id || '',
            forms: document.forms.length,
            buttons: document.querySelectorAll('button, input[type="button"], input[type="submit"]').length,
            links: document.querySelectorAll('a[href]').length,
            inputs: document.querySelectorAll('input, textarea, select').length,
            images: document.images.length,
            headings: document.querySelectorAll('h1, h2, h3').length
        };

        // Get text content within current viewport
        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;

        // Collect text from visible elements in viewport
        const visibleTexts = [];
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function(node) {
                    const parent = node.parentElement;
                    if (!parent) return NodeFilter.FILTER_REJECT;
                    const style = window.getComputedStyle(parent);
                    if (style.display === 'none' || style.visibility === 'hidden') {
                        return NodeFilter.FILTER_REJECT;
                    }
                    const rect = parent.getBoundingClientRect();
                    // Check if element is within viewport
                    if (rect.bottom < 0 || rect.top > viewportHeight ||
                        rect.right < 0 || rect.left > viewportWidth) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    const text = node.textContent.trim();
                    if (text.length < 2) return NodeFilter.FILTER_REJECT;
                    return NodeFilter.FILTER_ACCEPT;
                }
            }
        );

        let charCount = 0;
        const maxChars = 300;
        while (walker.nextNode() && charCount < maxChars) {
            const text = walker.currentNode.textContent.trim();
            if (text) {
                visibleTexts.push(text);
                charCount += text.length;
            }
        }

        const visibleContent = visibleTexts.join(' ').replace(/\\s+/g, ' ').trim();
        features.visible_content = visibleContent.substring(0, 300) + (visibleContent.length > 300 ? '...' : '');
        features.scroll_y = Math.round(window.scrollY);

        return features;
    })()
    """
    return session.evaluate(script, return_by_value=True) or {}


def take_perception_screenshot(
    session: CDPSession, screenshots_dir: Path, description: str = "page"
) -> Optional[str]:
    """
    Take perception screenshot

    Args:
        session: CDP session
        screenshots_dir: Directory to write screenshots into
        description: Screenshot description for filename generation

    Returns:
        Screenshot file path, None on failure
    """
    try:
        import base64

        from slugify import slugify

        from .screenshot import get_next_screenshot_number

        seq = get_next_screenshot_number(screenshots_dir)
        desc_slug = slugify(description or 'page', max_length=40)
        filename = f"{seq:03d}_{desc_slug}.png"
        file_path = screenshots_dir / filename

        result = session.screenshot.capture()
        screenshot_data = base64.b64decode(result.get("data", ""))
        file_path.write_bytes(screenshot_data)

        return str(file_path)
    except Exception:
        return None


def do_perception(
    session: CDPSession,
    action_desc: str,
    delay: float = 0,
    printer: Optional[Callable[[dict], None]] = None,
) -> None:
    """
    Post-action perception: get DOM features

    Note: No longer auto-screenshots. Screenshots should be explicitly called via screenshot command.
    Reason: Reduce hints to model, avoid over-reliance on screenshots over structured data extraction.

    Args:
        session: CDP session
        action_desc: Action description (kept for logging)
        delay: Delay before getting DOM features (seconds), for waiting page load
        printer: Optional callback to render the extracted features (CLI output)
    """
    # Optional delay
    if delay > 0:
        time.sleep(delay)

    # Get and print DOM features
    features = get_dom_features(session)
    if printer is not None:
        printer(features)
