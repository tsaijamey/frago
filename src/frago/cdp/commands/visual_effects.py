"""
Visual effects related CDP commands

Encapsulates CDP commands for visual effects functionality, including highlight, pointer, spotlight, annotation, etc.
"""


from ..logger import get_logger


class VisualEffectsCommands:
    """Visual effects commands class"""

    def __init__(self, session):
        """
        Initialize visual effects commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def highlight(self, selector: str, color: str = "magenta", border_width: int = 3) -> None:
        """
        Highlight specified element

        Args:
            selector: CSS selector
            color: Highlight color
            border_width: Border width (pixels)
        """
        self.logger.info(f"Highlighting element: {selector} with color {color}")

        script = f"""
        (function() {{
            const element = document.querySelector('{selector}');
            if (element) {{
                element.style.border = '{border_width}px solid {color}';
                element.style.outline = '{border_width}px solid {color}';
                element.setAttribute('data-frago-highlight', 'true');
            }}
        }})();
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})

    def spotlight(self, selector: str, opacity: float = 0.7) -> None:
        """
        Spotlight effect to highlight element

        Args:
            selector: CSS selector
            opacity: Mask opacity (0-1)
        """
        self.logger.info(f"Applying spotlight to element: {selector}")

        script = f"""
        (function() {{
            const element = document.querySelector('{selector}');
            if (element) {{
                const overlay = document.createElement('div');
                overlay.id = 'frago-spotlight';
                overlay.style.position = 'fixed';
                overlay.style.top = '0';
                overlay.style.left = '0';
                overlay.style.width = '100%';
                overlay.style.height = '100%';
                overlay.style.backgroundColor = 'rgba(0, 0, 0, {opacity})';
                overlay.style.zIndex = '999998';
                overlay.style.pointerEvents = 'none';
                document.body.appendChild(overlay);
                
                const rect = element.getBoundingClientRect();
                element.style.position = 'relative';
                element.style.zIndex = '999999';
            }}
        }})();
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})

    def annotate(self, selector: str, text: str, position: str = "top") -> None:
        """
        Add annotation text on element

        Args:
            selector: CSS selector
            text: Annotation text
            position: Annotation position ("top", "bottom", "left", "right")
        """
        self.logger.info(f"Adding annotation to element: {selector}")

        position_map = {
            "top": "bottom: 100%; left: 50%; transform: translateX(-50%);",
            "bottom": "top: 100%; left: 50%; transform: translateX(-50%);",
            "left": "right: 100%; top: 50%; transform: translateY(-50%);",
            "right": "left: 100%; top: 50%; transform: translateY(-50%);"
        }

        position_style = position_map.get(position, position_map["top"])

        script = f"""
        (function() {{
            const element = document.querySelector('{selector}');
            if (element) {{
                const annotation = document.createElement('div');
                annotation.className = 'frago-annotation';
                annotation.textContent = '{text}';
                annotation.style.position = 'absolute';
                annotation.style.cssText += '{position_style}';
                annotation.style.padding = '4px 8px';
                annotation.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
                annotation.style.color = 'white';
                annotation.style.fontSize = '12px';
                annotation.style.borderRadius = '4px';
                annotation.style.whiteSpace = 'nowrap';
                annotation.style.zIndex = '999999';
                annotation.style.pointerEvents = 'none';
                
                element.style.position = 'relative';
                element.appendChild(annotation);
            }}
        }})();
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})

    def clear_effects(self) -> None:
        """Clear all visual effects added by Frago"""
        self.logger.info("Clearing all visual effects")

        script = """
        (function() {
            document.querySelectorAll('[data-frago-highlight]').forEach(el => {
                el.style.border = '';
                el.style.outline = '';
                el.removeAttribute('data-frago-highlight');
            });
            
            ['frago-spotlight'].forEach(id => {
                const element = document.getElementById(id);
                if (element) element.remove();
            });
            
            document.querySelectorAll('.frago-annotation').forEach(el => el.remove());
        })();
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})

    def viewport_border(
        self,
        color: str = "80, 200, 120",
        duration: float = 3.0,
    ) -> None:
        """
        Display a breathing gradient border around the viewport.

        Args:
            color: RGB color values (e.g., "80, 200, 120" for green)
            duration: Breathing animation cycle duration in seconds
        """
        self.logger.info("Showing viewport border indicator")

        script = f"""
        (() => {{
            const id = '__frago_viewport_border__';
            const styleId = '__frago_border_style__';

            // Remove existing elements
            const existing = document.getElementById(id);
            if (existing) existing.remove();
            const existingStyle = document.getElementById(styleId);
            if (existingStyle) existingStyle.remove();
            const existingLabel = document.getElementById('__frago_auto_label__');
            if (existingLabel) existingLabel.remove();

            // Add keyframes style
            const style = document.createElement('style');
            style.id = styleId;
            style.textContent = `
                @keyframes __frago_breathe__ {{
                    0%, 100% {{
                        box-shadow:
                            inset 0 0 20px 8px rgba({color}, 0.6),
                            inset 0 0 40px 15px rgba({color}, 0.3),
                            inset 0 0 60px 25px rgba({color}, 0.1);
                    }}
                    50% {{
                        box-shadow:
                            inset 0 0 30px 12px rgba({color}, 0.8),
                            inset 0 0 60px 25px rgba({color}, 0.5),
                            inset 0 0 90px 40px rgba({color}, 0.2);
                    }}
                }}
            `;
            document.head.appendChild(style);

            // Create border element
            const border = document.createElement('div');
            border.id = id;
            border.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                z-index: 2147483647;
                animation: __frago_breathe__ {duration}s ease-in-out infinite;
            `;
            document.body.appendChild(border);

            // Add automation indicator label
            const label = document.createElement('div');
            label.id = '__frago_auto_label__';
            label.innerHTML = '<span style="margin-right: 6px;">&#9881;</span>Controlled by frago';
            label.style.cssText = `
                position: fixed;
                top: 12px;
                left: 50%;
                transform: translateX(-50%);
                padding: 6px 16px;
                background: rgba(0, 0, 0, 0.75);
                color: #fff;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                font-weight: 500;
                border-radius: 20px;
                pointer-events: none;
                z-index: 2147483647;
                backdrop-filter: blur(8px);
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            `;
            document.body.appendChild(label);
        }})()
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})

    def clear_viewport_border(self) -> None:
        """Remove the viewport border indicator."""
        self.logger.info("Clearing viewport border indicator")

        script = """
        (() => {
            ['__frago_viewport_border__', '__frago_auto_label__', '__frago_border_style__'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.remove();
            });
        })()
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})
