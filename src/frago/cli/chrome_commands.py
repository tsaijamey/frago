"""chrome 命令组 - Chrome CDP 浏览器自动化

包含:
  - 生命周期: start, stop, status
  - Tab 管理: list-tabs, switch-tab
  - 页面操作: navigate, scroll, scroll-to, zoom, wait
  - 元素交互: click, exec-js, get-title, get-content
  - 视觉效果: screenshot, highlight, pointer, spotlight, annotate, underline, clear-effects
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
)
from .agent_friendly import AgentFriendlyGroup


@click.group(name="chrome", cls=AgentFriendlyGroup)
def chrome_group():
    """
    Chrome CDP 浏览器自动化

    通过 Chrome DevTools Protocol 控制浏览器。

    \b
    子命令分类:
      生命周期:  start, stop, status
      Tab 管理:  list-tabs, switch-tab
      页面操作:  navigate, scroll, scroll-to, zoom, wait
      元素交互:  click, exec-js, get-title, get-content
      视觉效果:  screenshot, highlight, pointer, spotlight, ...

    \b
    示例:
      frago chrome start                    # 启动 Chrome
      frago chrome navigate https://...     # 导航到 URL
      frago chrome click "#button"          # 点击元素
      frago chrome screenshot out.png       # 截图
    """
    pass


# 生命周期
chrome_group.add_command(chrome_start, name="start")
chrome_group.add_command(chrome_stop, name="stop")
chrome_group.add_command(status, name="status")

# Tab 管理
chrome_group.add_command(list_tabs, name="list-tabs")
chrome_group.add_command(switch_tab, name="switch-tab")

# 页面操作
chrome_group.add_command(navigate, name="navigate")
chrome_group.add_command(scroll, name="scroll")
chrome_group.add_command(scroll_to, name="scroll-to")
chrome_group.add_command(zoom, name="zoom")
chrome_group.add_command(wait, name="wait")

# 元素交互
chrome_group.add_command(click_element, name="click")
chrome_group.add_command(execute_javascript, name="exec-js")
chrome_group.add_command(get_title, name="get-title")
chrome_group.add_command(get_content, name="get-content")

# 视觉效果
chrome_group.add_command(screenshot, name="screenshot")
chrome_group.add_command(highlight, name="highlight")
chrome_group.add_command(pointer, name="pointer")
chrome_group.add_command(spotlight, name="spotlight")
chrome_group.add_command(annotate, name="annotate")
chrome_group.add_command(underline, name="underline")
chrome_group.add_command(clear_effects, name="clear-effects")
