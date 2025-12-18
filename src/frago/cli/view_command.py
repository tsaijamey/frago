"""View command - Universal content viewer CLI."""

import sys
from pathlib import Path
from typing import Optional

import click


@click.command("view", short_help="内容查看器：Markdown / PDF / 代码高亮")
@click.argument("file", type=click.Path(exists=True), required=False)
@click.option(
    "--theme", "-t",
    type=str,
    default="github-dark",
    help="Code highlighting theme (github-dark, monokai, etc.)"
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
    theme: str,
    title: Optional[str],
    width: int,
    height: int,
    fullscreen: bool,
    stdin: bool,
    content: Optional[str],
):
    """View content in a document window with syntax highlighting and Mermaid support.

    \b
    Supported formats:
      - Markdown (.md) - rendered with Mermaid diagram support
      - HTML (.html, .htm) - direct rendering
      - PDF (.pdf) - rendered with PDF.js
      - JSON (.json) - formatted and syntax highlighted
      - Code files - syntax highlighted with highlight.js

    \b
    Examples:
      frago view README.md           # View Markdown
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

    # Import and run viewer
    try:
        from frago.viewer import ViewerWindow

        viewer = ViewerWindow(
            content=content_input,
            mode="doc",
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
