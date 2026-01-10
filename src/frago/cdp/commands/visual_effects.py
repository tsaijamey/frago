"""
Visual effects related CDP commands

Encapsulates CDP commands for visual effects functionality, including highlight, pointer, spotlight, annotation, etc.
"""

from typing import Dict, Any, Optional

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
        color: str = "255, 180, 0",
        duration: float = 3.0,
    ) -> None:
        """
        Display a breathing gradient border around the viewport to indicate automation control.

        Args:
            color: RGB color values (e.g., "255, 180, 0" for yellow)
            duration: Breathing animation cycle duration in seconds
        """
        self.logger.info("Showing viewport border indicator")

        script = f"""
        (() => {{
            // Clean up existing elements
            const existing = document.getElementById('__frago_viewport_border__');
            if (existing) existing.remove();
            const existingStyle = document.getElementById('__frago_border_style__');
            if (existingStyle) existingStyle.remove();

            // Add animation style
            const style = document.createElement('style');
            style.id = '__frago_border_style__';
            style.textContent = `
                @keyframes __frago_breathe__ {{
                    0%, 100% {{
                        box-shadow:
                            inset 0 0 15px 5px rgba({color}, 0.6),
                            inset 0 0 35px 12px rgba({color}, 0.35),
                            inset 0 0 55px 20px rgba({color}, 0.15);
                    }}
                    50% {{
                        box-shadow:
                            inset 0 0 25px 10px rgba({color}, 0.75),
                            inset 0 0 50px 20px rgba({color}, 0.45),
                            inset 0 0 80px 35px rgba({color}, 0.2);
                    }}
                }}
            `;
            document.head.appendChild(style);

            // Create border element
            const border = document.createElement('div');
            border.id = '__frago_viewport_border__';
            border.style.cssText = `
                position: fixed;
                top: 0; left: 0; right: 0; bottom: 0;
                pointer-events: none;
                z-index: 2147483647;
                box-sizing: border-box;
                animation: __frago_breathe__ {duration}s ease-in-out infinite;
            `;
            document.body.appendChild(border);
        }})()
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})

    def clear_viewport_border(self) -> None:
        """Remove the viewport border indicator."""
        self.logger.info("Clearing viewport border indicator")

        script = """
        (() => {
            const border = document.getElementById('__frago_viewport_border__');
            if (border) border.remove();
            const style = document.getElementById('__frago_border_style__');
            if (style) style.remove();
        })()
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})
