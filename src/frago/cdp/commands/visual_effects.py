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
        color: str = "147, 51, 234",
        duration: float = 4.0,
    ) -> None:
        """
        Display an animated wavy border around the viewport to indicate automation control.

        Args:
            color: RGB color values (e.g., "147, 51, 234" for purple)
            duration: Wave animation cycle duration in seconds
        """
        self.logger.info("Showing viewport border indicator")

        script = f"""
        (() => {{
            // Clean up existing elements
            const existing = document.getElementById('__frago_viewport_border__');
            if (existing) existing.remove();
            const existingStyle = document.getElementById('__frago_border_style__');
            if (existingStyle) existingStyle.remove();

            const W = window.innerWidth;
            const H = window.innerHeight;
            const THICKNESS = 45;
            const WAVE_AMP = 35;
            const WAVE_LEN = 180;
            const EXTRA_LEN = WAVE_LEN * 2;  // Extra length for seamless loop

            // Seeded random
            let seed = 12345;
            function random() {{
                seed = (seed * 1103515245 + 12345) & 0x7fffffff;
                return seed / 0x7fffffff;
            }}

            // Generate fixed wavy edge (longer than needed for animation)
            function generateWavyEdge(length, seedVal) {{
                seed = seedVal;
                const totalLen = length + EXTRA_LEN;
                const steps = Math.ceil(totalLen / WAVE_LEN);
                const points = [];

                for (let i = 0; i <= steps; i++) {{
                    const ampVariance = 0.5 + random() * 0.8;
                    const posVariance = 0.3 + random() * 0.4;
                    points.push({{
                        pos: (i + posVariance) * WAVE_LEN,
                        amp: (i % 2 === 0 ? 1 : -1) * WAVE_AMP * ampVariance
                    }});
                }}
                return points;
            }}

            // Pre-generate wave data for each edge
            const topWave = generateWavyEdge(W, 11111);
            const rightWave = generateWavyEdge(H, 22222);
            const bottomWave = generateWavyEdge(W, 33333);
            const leftWave = generateWavyEdge(H, 44444);

            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.id = '__frago_viewport_border__';
            svg.setAttribute('width', W);
            svg.setAttribute('height', H);
            svg.style.cssText = `position: fixed; top: 0; left: 0; pointer-events: none; z-index: 2147483647; opacity: 0.75;`;

            const defs = document.createElementNS(svgNS, 'defs');
            defs.innerHTML = `
                <linearGradient id="__frago_grad_top__" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" style="stop-color:rgb({color});stop-opacity:0.85"/>
                    <stop offset="100%" style="stop-color:rgb({color});stop-opacity:0"/>
                </linearGradient>
                <linearGradient id="__frago_grad_bottom__" x1="0%" y1="100%" x2="0%" y2="0%">
                    <stop offset="0%" style="stop-color:rgb({color});stop-opacity:0.85"/>
                    <stop offset="100%" style="stop-color:rgb({color});stop-opacity:0"/>
                </linearGradient>
                <linearGradient id="__frago_grad_left__" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" style="stop-color:rgb({color});stop-opacity:0.85"/>
                    <stop offset="100%" style="stop-color:rgb({color});stop-opacity:0"/>
                </linearGradient>
                <linearGradient id="__frago_grad_right__" x1="100%" y1="0%" x2="0%" y2="0%">
                    <stop offset="0%" style="stop-color:rgb({color});stop-opacity:0.85"/>
                    <stop offset="100%" style="stop-color:rgb({color});stop-opacity:0"/>
                </linearGradient>
                <filter id="__frago_blur__" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="8"/>
                </filter>
            `;
            svg.appendChild(defs);

            const topEl = document.createElementNS(svgNS, 'path');
            topEl.setAttribute('fill', 'url(#__frago_grad_top__)');
            topEl.setAttribute('filter', 'url(#__frago_blur__)');
            svg.appendChild(topEl);

            const rightEl = document.createElementNS(svgNS, 'path');
            rightEl.setAttribute('fill', 'url(#__frago_grad_right__)');
            rightEl.setAttribute('filter', 'url(#__frago_blur__)');
            svg.appendChild(rightEl);

            const bottomEl = document.createElementNS(svgNS, 'path');
            bottomEl.setAttribute('fill', 'url(#__frago_grad_bottom__)');
            bottomEl.setAttribute('filter', 'url(#__frago_blur__)');
            svg.appendChild(bottomEl);

            const leftEl = document.createElementNS(svgNS, 'path');
            leftEl.setAttribute('fill', 'url(#__frago_grad_left__)');
            leftEl.setAttribute('filter', 'url(#__frago_blur__)');
            svg.appendChild(leftEl);

            document.body.appendChild(svg);

            // Build path from wave data with offset
            function buildPath(wave, length, offset, horizontal, reverse, basePos, outward) {{
                let d = '';
                const startOffset = offset % EXTRA_LEN;

                for (let i = 0; i < wave.length - 1; i++) {{
                    let p1 = wave[i].pos - startOffset;
                    let p2 = wave[i + 1].pos - startOffset;
                    const amp = wave[i].amp * outward;

                    if (reverse) {{
                        p1 = length - p1;
                        p2 = length - p2;
                    }}

                    if (p2 < 0 || p1 > length) continue;

                    const cp = (p1 + p2) / 2;
                    let x1, y1, cx, cy, x2, y2;

                    if (horizontal) {{
                        x1 = Math.max(0, Math.min(length, p1));
                        x2 = Math.max(0, Math.min(length, p2));
                        y1 = y2 = basePos;
                        cx = cp; cy = basePos + amp;
                    }} else {{
                        y1 = Math.max(0, Math.min(length, p1));
                        y2 = Math.max(0, Math.min(length, p2));
                        x1 = x2 = basePos;
                        cy = cp; cx = basePos + amp;
                    }}

                    if (d === '') d = `M ${{x1}} ${{y1}}`;
                    d += ` Q ${{cx}} ${{cy}} ${{x2}} ${{y2}}`;
                }}
                return d;
            }}

            const cycleDuration = {duration} * 1000;
            let startTime = performance.now();

            function animate(timestamp) {{
                const elapsed = timestamp - startTime;
                const offset = (elapsed / cycleDuration) * EXTRA_LEN;

                // Clockwise: top(L→R), right(T→B), bottom(R→L), left(B→T)
                const topPath = buildPath(topWave, W, offset, true, false, THICKNESS, -1);
                topEl.setAttribute('d', topPath + ` L ${{W}} 0 L 0 0 Z`);

                const rightPath = buildPath(rightWave, H, offset, false, false, W - THICKNESS, 1);
                rightEl.setAttribute('d', rightPath + ` L ${{W}} ${{H}} L ${{W}} 0 Z`);

                const bottomPath = buildPath(bottomWave, W, offset, true, true, H - THICKNESS, 1);
                bottomEl.setAttribute('d', bottomPath + ` L 0 ${{H}} L ${{W}} ${{H}} Z`);

                const leftPath = buildPath(leftWave, H, offset, false, true, THICKNESS, -1);
                leftEl.setAttribute('d', leftPath + ` L 0 0 L 0 ${{H}} Z`);

                if (document.getElementById('__frago_viewport_border__')) {{
                    requestAnimationFrame(animate);
                }}
            }}
            requestAnimationFrame(animate);
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
            const svg = document.getElementById('__frago_svg_defs__');
            if (svg) svg.remove();
        })()
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})
