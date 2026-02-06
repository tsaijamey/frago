"""chrome command group - Chromium-based browser CDP automation

Supports Chrome, Edge, and Chromium browsers via Chrome DevTools Protocol.

Includes:
  - Lifecycle: start, stop, status, detect
  - Tab management: list-tabs, switch-tab, close-tab
  - Page operations: navigate, scroll, scroll-to, zoom, wait
  - Element interaction: click, exec-js, get-title, get-content
  - Visual effects: screenshot, highlight, pointer, spotlight, annotate, underline, clear-effects
"""

import click

from .commands import (
    navigate,
    click_element,
    screenshot,
    execute_javascript,
    get_title,
    get_content,
    status,
    scroll,
    scroll_to,
    wait,
    zoom,
    clear_effects,
    highlight,
    pointer,
    spotlight,
    annotate,
    underline,
    chrome_start,
    chrome_stop,
    list_tabs,
    switch_tab,
    close_tab,
)
from .agent_friendly import AgentFriendlyGroup


@click.command('detect')
def detect_browsers():
    """
    Detect available browsers on the system

    Shows which Chromium-based browsers are installed and their paths.
    Supports Chrome, Edge, and Chromium.

    \b
    Examples:
      frago chrome detect
    """
    from ..cdp.commands.chrome import detect_available_browsers, BrowserType

    browsers = detect_available_browsers()

    click.echo("Available browsers:")
    click.echo()

    found_any = False
    for browser_type in [BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM]:
        path = browsers.get(browser_type)
        name = browser_type.value.title()

        if path:
            click.echo(f"  {name:10} ✓  {path}")
            found_any = True
        else:
            click.echo(f"  {name:10} ✗  not found")

    click.echo()

    if found_any:
        # Show which would be selected by default
        default_type = None
        for bt in [BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM]:
            if browsers.get(bt):
                default_type = bt
                break

        if default_type:
            click.echo(f"Default: {default_type.value} (first available)")
    else:
        click.echo("No supported browsers found.")
        click.echo("Please install Chrome, Edge, or Chromium.")


@click.group(name="chrome", cls=AgentFriendlyGroup)
def chrome_group():
    """
    Chrome CDP browser automation

    Control browser through Chrome DevTools Protocol.

    \b
    Subcommand categories:
      Lifecycle:     start, stop, status
      Tab management: list-tabs, switch-tab, close-tab
      Page operations: navigate, scroll, scroll-to, zoom, wait
      Element interaction: click, exec-js, get-title, get-content
      Visual effects: screenshot, highlight, pointer, spotlight, ...

    \b
    Examples:
      frago chrome start                    # Start Chrome
      frago chrome navigate https://...     # Navigate to URL
      frago chrome click "#button"          # Click element
      frago chrome screenshot out.png       # Take screenshot
    """
    pass


# Lifecycle
chrome_group.add_command(chrome_start, name="start")
chrome_group.add_command(chrome_stop, name="stop")
chrome_group.add_command(status, name="status")
chrome_group.add_command(detect_browsers, name="detect")

# Tab management
chrome_group.add_command(list_tabs, name="list-tabs")
chrome_group.add_command(switch_tab, name="switch-tab")
chrome_group.add_command(close_tab, name="close-tab")

# Page operations
chrome_group.add_command(navigate, name="navigate")
chrome_group.add_command(scroll, name="scroll")
chrome_group.add_command(scroll_to, name="scroll-to")
chrome_group.add_command(zoom, name="zoom")
chrome_group.add_command(wait, name="wait")

# Element interaction
chrome_group.add_command(click_element, name="click")
chrome_group.add_command(execute_javascript, name="exec-js")
chrome_group.add_command(get_title, name="get-title")
chrome_group.add_command(get_content, name="get-content")

# Visual effects
chrome_group.add_command(screenshot, name="screenshot")
chrome_group.add_command(highlight, name="highlight")
chrome_group.add_command(pointer, name="pointer")
chrome_group.add_command(spotlight, name="spotlight")
chrome_group.add_command(annotate, name="annotate")
chrome_group.add_command(underline, name="underline")
chrome_group.add_command(clear_effects, name="clear-effects")
