"""
Scroll-related CDP commands

Encapsulates CDP commands for page scrolling functionality.
"""


from ..logger import get_logger


class ScrollCommands:
    """Scroll commands class"""

    def __init__(self, session):
        """
        Initialize scroll commands

        Args:
            session: CDP session instance
        """
        self.session = session
        self.logger = get_logger()

    def scroll(self, distance: int) -> dict:
        """
        Scroll page by specified distance and report what actually moved.

        The requested distance is not the outcome: the page may already
        be at the bottom, or may render nothing at all while its tab is
        hidden (x.com's timeline does). Callers that echo the request
        instead of the measurement report success for a page that never
        budged.

        Args:
            distance: Scroll distance (positive for down, negative for up)

        Returns:
            dict: requested / scrolled / y / max_y / at_bottom / hidden
        """
        self.logger.info(f"Scrolling by {distance} pixels")

        # 平滑滚动（scroll-behavior:smooth）是动画，滚完立刻读位置读到
        # 的是中途值——轮询到位置不再变化为止。
        script = f"""
        (async () => {{
            const doc = document.documentElement;
            const read = () => ({{
                y: Math.round(window.scrollY),
                max: Math.round(Math.max(
                    0, doc.scrollHeight - window.innerHeight)),
            }});
            const y0 = read().y;
            window.scrollBy(0, {int(distance)});
            let prev = -1, cur = read();
            for (let i = 0; i < 15 && cur.y !== prev; i++) {{
                prev = cur.y;
                await new Promise(r => setTimeout(r, 100));
                cur = read();
            }}
            return JSON.stringify({{y0, y: cur.y, max: cur.max,
                                    hidden: document.hidden}});
        }})()
        """
        raw = self.session.evaluate(script, return_by_value=True)
        try:
            import json
            r = json.loads(raw if isinstance(raw, str) else str(raw))
        except Exception:
            self.logger.warning(f"unparsable scroll result: {raw!r}")
            return {"requested": int(distance), "scrolled": None}
        return {
            "requested": int(distance),
            "scrolled": r["y"] - r["y0"],
            "y": r["y"],
            "max_y": r["max"],
            "at_bottom": r["max"] - r["y"] <= 2,
            "hidden": r["hidden"],
        }

    def scroll_to_top(self) -> None:
        """Scroll to page top"""
        self.logger.info("Scrolling to top")

        script = "window.scrollTo(0, 0);"
        self.session.send_command("Runtime.evaluate", {"expression": script})

    def scroll_to_bottom(self) -> None:
        """Scroll to page bottom"""
        self.logger.info("Scrolling to bottom")

        script = "window.scrollTo(0, document.body.scrollHeight);"
        self.session.send_command("Runtime.evaluate", {"expression": script})

    def scroll_up(self, distance: int = 100) -> None:
        """
        Scroll up

        Args:
            distance: Scroll distance (pixels)
        """
        self.scroll(-distance)

    def scroll_down(self, distance: int = 100) -> None:
        """
        Scroll down

        Args:
            distance: Scroll distance (pixels)
        """
        self.scroll(distance)
