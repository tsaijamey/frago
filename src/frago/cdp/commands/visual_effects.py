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
        color: str = "147, 51, 234",
        duration: float = 120.0,
    ) -> None:
        """
        Display an animated wavy border around the viewport with gradient and blur effects.

        Args:
            color: RGB color values (e.g., "147, 51, 234" for purple)
            duration: Wave animation cycle duration in seconds
        """
        self.logger.info("Showing viewport border indicator")

        script = f"""
        (() => {{
            const id = '__frago_viewport_border__';
            const existing = document.getElementById(id);
            if (existing) existing.remove();
            const existingLabel = document.getElementById('__frago_auto_label__');
            if (existingLabel) existingLabel.remove();

            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.id = id;
            svg.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 2147483647;';

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

            // Definitions for gradients and filters
            const defs = document.createElementNS(svgNS, 'defs');

            // Create gradient elements that will be updated dynamically
            const gradients = {{
                top: document.createElementNS(svgNS, 'linearGradient'),
                bottom: document.createElementNS(svgNS, 'linearGradient'),
                left: document.createElementNS(svgNS, 'linearGradient'),
                right: document.createElementNS(svgNS, 'linearGradient')
            }};

            // Setup gradient directions
            gradients.top.setAttribute('id', '__frago_grad_top__');
            gradients.top.setAttribute('x1', '0%'); gradients.top.setAttribute('y1', '0%');
            gradients.top.setAttribute('x2', '0%'); gradients.top.setAttribute('y2', '100%');

            gradients.bottom.setAttribute('id', '__frago_grad_bottom__');
            gradients.bottom.setAttribute('x1', '0%'); gradients.bottom.setAttribute('y1', '100%');
            gradients.bottom.setAttribute('x2', '0%'); gradients.bottom.setAttribute('y2', '0%');

            gradients.left.setAttribute('id', '__frago_grad_left__');
            gradients.left.setAttribute('x1', '0%'); gradients.left.setAttribute('y1', '0%');
            gradients.left.setAttribute('x2', '100%'); gradients.left.setAttribute('y2', '0%');

            gradients.right.setAttribute('id', '__frago_grad_right__');
            gradients.right.setAttribute('x1', '100%'); gradients.right.setAttribute('y1', '0%');
            gradients.right.setAttribute('x2', '0%'); gradients.right.setAttribute('y2', '0%');

            // Add stops to each gradient
            Object.values(gradients).forEach(grad => {{
                const stop1 = document.createElementNS(svgNS, 'stop');
                stop1.setAttribute('offset', '0%');
                stop1.setAttribute('stop-opacity', '0.85');
                const stop2 = document.createElementNS(svgNS, 'stop');
                stop2.setAttribute('offset', '100%');
                stop2.setAttribute('stop-opacity', '0');
                grad.appendChild(stop1);
                grad.appendChild(stop2);
                defs.appendChild(grad);
            }});

            // Add blur filter
            const filter = document.createElementNS(svgNS, 'filter');
            filter.setAttribute('id', '__frago_blur__');
            filter.setAttribute('x', '-50%'); filter.setAttribute('y', '-50%');
            filter.setAttribute('width', '200%'); filter.setAttribute('height', '200%');
            const blur = document.createElementNS(svgNS, 'feGaussianBlur');
            blur.setAttribute('stdDeviation', '8');
            filter.appendChild(blur);
            defs.appendChild(filter);

            svg.appendChild(defs);

            // HSL to RGB conversion
            function hslToRgb(h, s, l) {{
                let r, g, b;
                if (s === 0) {{
                    r = g = b = l;
                }} else {{
                    const hue2rgb = (p, q, t) => {{
                        if (t < 0) t += 1;
                        if (t > 1) t -= 1;
                        if (t < 1/6) return p + (q - p) * 6 * t;
                        if (t < 1/2) return q;
                        if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
                        return p;
                    }};
                    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
                    const p = 2 * l - q;
                    r = hue2rgb(p, q, h + 1/3);
                    g = hue2rgb(p, q, h);
                    b = hue2rgb(p, q, h - 1/3);
                }}
                return `rgb(${{Math.round(r * 255)}}, ${{Math.round(g * 255)}}, ${{Math.round(b * 255)}})`;
            }}

            // Color cycle duration (slower than wave movement)
            const colorCycleDuration = 60000;  // 60 seconds for full hue rotation

            // Create 4 paths for each side
            const sides = {{
                top: document.createElementNS(svgNS, 'path'),
                right: document.createElementNS(svgNS, 'path'),
                bottom: document.createElementNS(svgNS, 'path'),
                left: document.createElementNS(svgNS, 'path')
            }};

            sides.top.setAttribute('fill', 'url(#__frago_grad_top__)');
            sides.right.setAttribute('fill', 'url(#__frago_grad_right__)');
            sides.bottom.setAttribute('fill', 'url(#__frago_grad_bottom__)');
            sides.left.setAttribute('fill', 'url(#__frago_grad_left__)');

            Object.values(sides).forEach(el => {{
                el.setAttribute('filter', 'url(#__frago_blur__)');
                svg.appendChild(el);
            }});

            document.body.appendChild(svg);

            // Configuration
            const THICKNESS = 45;
            const BASE_AMP = 30;
            const TARGET_WAVE_LEN = 280;  // Longer wavelength = less dense waves
            const STEP = 15;

            // Pre-generate amplitude variation using seeded random for consistency
            let seed = 31415;
            function seededRandom() {{
                seed = (seed * 1103515245 + 12345) & 0x7fffffff;
                return seed / 0x7fffffff;
            }}

            // Generate amplitude modulation points along perimeter
            const ampModPoints = [];
            for (let i = 0; i < 20; i++) {{
                ampModPoints.push(0.3 + seededRandom() * 1.5);  // 0.3 to 1.8 variation
            }}

            let startTime = performance.now();

            function animate(t) {{
                if (!document.getElementById(id)) return;

                const W = window.innerWidth;
                const H = window.innerHeight;

                // Seamless loop calculation
                const perimeter = 2 * W + 2 * H;
                const cycleCount = Math.round(perimeter / TARGET_WAVE_LEN);
                const waveLen = perimeter / Math.max(cycleCount, 1);

                const totalDuration = {duration} * 1000;
                const phaseShift = ((t - startTime) % totalDuration) / totalDuration * perimeter;

                // Update gradient colors - metallic shimmer (silver <-> gray)
                const progress = ((t - startTime) % colorCycleDuration) / colorCycleDuration;
                const triangle = progress < 0.5 ? progress * 2 : 2 - progress * 2;
                // Interpolate between silver (l=0.85) and gray (l=0.45)
                const lightness = 0.85 - triangle * 0.4;  // 0.85 -> 0.45 -> 0.85
                const color = hslToRgb(0, 0.05, lightness);

                Object.values(gradients).forEach(grad => {{
                    grad.children[0].setAttribute('stop-color', color);
                    grad.children[1].setAttribute('stop-color', color);
                }});

                // Get amplitude with variation
                const getAmp = (p) => {{
                    const baseWave = Math.sin((p - phaseShift) * 2 * Math.PI / waveLen);
                    // Smooth amplitude modulation based on position
                    const modIndex = (p / perimeter) * ampModPoints.length;
                    const idx = Math.floor(modIndex) % ampModPoints.length;
                    const nextIdx = (idx + 1) % ampModPoints.length;
                    const frac = modIndex - Math.floor(modIndex);
                    const ampMod = ampModPoints[idx] * (1 - frac) + ampModPoints[nextIdx] * frac;
                    return baseWave * BASE_AMP * ampMod;
                }};

                let d;

                // TOP EDGE
                d = "";
                for (let x = 0; x <= W; x += STEP) {{
                    const y = THICKNESS + getAmp(x);
                    d += (x === 0 ? `M ${{x}} ${{y}}` : ` L ${{x}} ${{y}}`);
                }}
                d += ` L ${{W}} 0 L 0 0 Z`;
                sides.top.setAttribute('d', d);

                // RIGHT EDGE
                d = "";
                for (let y = 0; y <= H; y += STEP) {{
                    const p = W + y;
                    const x = W - (THICKNESS + getAmp(p));
                    d += (y === 0 ? `M ${{x}} ${{y}}` : ` L ${{x}} ${{y}}`);
                }}
                d += ` L ${{W}} ${{H}} L ${{W}} 0 Z`;
                sides.right.setAttribute('d', d);

                // BOTTOM EDGE
                d = "";
                for (let x = W; x >= 0; x -= STEP) {{
                    const p = W + H + (W - x);
                    const y = H - (THICKNESS + getAmp(p));
                    d += (x === W ? `M ${{x}} ${{y}}` : ` L ${{x}} ${{y}}`);
                }}
                d += ` L 0 ${{H}} L ${{W}} ${{H}} Z`;
                sides.bottom.setAttribute('d', d);

                // LEFT EDGE
                d = "";
                for (let y = H; y >= 0; y -= STEP) {{
                    const p = W + H + W + (H - y);
                    const x = THICKNESS + getAmp(p);
                    d += (y === H ? `M ${{x}} ${{y}}` : ` L ${{x}} ${{y}}`);
                }}
                d += ` L 0 0 L 0 ${{H}} Z`;
                sides.left.setAttribute('d', d);

                requestAnimationFrame(animate);
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
            const label = document.getElementById('__frago_auto_label__');
            if (label) label.remove();
            const style = document.getElementById('__frago_border_style__');
            if (style) style.remove();
            const svg = document.getElementById('__frago_svg_defs__');
            if (svg) svg.remove();
        })()
        """

        self.session.send_command("Runtime.evaluate", {"expression": script})
