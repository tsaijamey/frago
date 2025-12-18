"""View command - Universal content viewer CLI."""

import sys
from pathlib import Path
from typing import Optional

import click


@click.command("view", short_help="内容查看器：Markdown幻灯片 / PDF / 代码高亮")
@click.argument("file", type=click.Path(exists=True), required=False)
@click.option(
    "--present", "-p",
    is_flag=True,
    help="Force presentation mode (reveal.js slideshow)"
)
@click.option(
    "--doc", "-d",
    is_flag=True,
    help="Force document mode (scrollable document)"
)
@click.option(
    "--theme", "-t",
    type=str,
    default="black",
    help="Theme name (reveal.js theme for present mode, code theme for doc mode)"
)
@click.option(
    "--title",
    type=str,
    default=None,
    help="Window title"
)
@click.option(
    "--width", "-w",
    type=int,
    default=1280,
    help="Window width in pixels"
)
@click.option(
    "--height", "-h",
    type=int,
    default=800,
    help="Window height in pixels"
)
@click.option(
    "--fullscreen", "-f",
    is_flag=True,
    help="Start in fullscreen mode"
)
@click.option(
    "--stdin",
    is_flag=True,
    help="Read content from stdin"
)
@click.option(
    "--content", "-c",
    type=str,
    default=None,
    help="Direct content string to display"
)
def view(
    file: Optional[str],
    present: bool,
    doc: bool,
    theme: str,
    title: Optional[str],
    width: int,
    height: int,
    fullscreen: bool,
    stdin: bool,
    content: Optional[str],
):
    """View content in a presentation or document window.

    \b
    Supported formats:
      - Markdown (.md) - auto-detects slides with --- separators
      - HTML (.html, .htm) - direct rendering
      - PDF (.pdf) - rendered with PDF.js
      - JSON (.json) - formatted and syntax highlighted
      - Code files - syntax highlighted with highlight.js

    \b
    Examples:
      frago view slides.md           # Auto-detect mode
      frago view slides.md --present # Force presentation mode
      frago view README.md --doc     # Force document mode
      frago view report.pdf          # View PDF
      frago view config.json         # View formatted JSON
      cat script.py | frago view --stdin  # Read from stdin
    """
    # Determine content source
    if stdin:
        content_input = sys.stdin.read()
        if not content_input.strip():
            click.echo("Error: No content received from stdin", err=True)
            sys.exit(1)
    elif content:
        content_input = content
    elif file:
        content_input = Path(file)
    else:
        click.echo("Error: Must provide FILE, --stdin, or --content", err=True)
        sys.exit(1)

    # Determine mode
    if present and doc:
        click.echo("Error: Cannot use both --present and --doc", err=True)
        sys.exit(1)

    if present:
        mode = "present"
    elif doc:
        mode = "doc"
    else:
        mode = "auto"

    # Import and run viewer
    try:
        from frago.viewer import ViewerWindow

        viewer = ViewerWindow(
            content=content_input,
            mode=mode,
            theme=theme,
            title=title,
            width=width,
            height=height,
            fullscreen=fullscreen,
        )
        viewer.show()
    except ImportError as e:
        click.echo(f"Error: Missing dependency - {e}", err=True)
        click.echo("Try: pip install frago-cli[gui]", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
