"""View command - Universal content viewer CLI using Chrome browser."""

import sys
from pathlib import Path
from typing import Optional

import click


@click.command("view", short_help="Content viewer: Markdown / PDF / Code highlighting")
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
    help="Content title"
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
    stdin: bool,
    content: Optional[str],
):
    """View content in Chrome browser with syntax highlighting and Mermaid support.

    Opens content in a new Chrome tab. Automatically starts frago server and
    Chrome if not already running.

    \b
    Supported formats:
      - Markdown (.md) - rendered with Mermaid diagram support
      - HTML (.html, .htm) - direct rendering or reveal.js slides
      - PDF (.pdf) - rendered with PDF.js
      - JSON (.json) - formatted and syntax highlighted
      - Code files - syntax highlighted with highlight.js
      - Video (.mp4, .webm, .mov) - HTML5 video player
      - Image (.png, .jpg, .gif, .svg) - image viewer with zoom
      - Audio (.mp3, .wav, .ogg) - HTML5 audio player
      - 3D models (.gltf, .glb) - three.js viewer with OrbitControls

    \b
    Examples:
      frago view README.md           # View Markdown
      frago view report.pdf          # View PDF
      frago view config.json         # View formatted JSON
      frago view slides.html         # View reveal.js slides
      frago view video.mp4           # Play video
      frago view model.glb           # View 3D model
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
        from frago.viewer.chrome import ChromeViewer

        viewer = ChromeViewer(
            content=content_input,
            mode="auto",
            theme=theme,
            title=title,
        )
        url = viewer.show()
        click.echo(f"Opened: {url}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
