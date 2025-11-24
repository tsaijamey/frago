"""
Frago - 自动化视觉管理系统CDP控制库

提供Chrome DevTools Protocol的Python封装，
用于浏览器自动化控制和视觉管理。
"""

__version__ = "0.1.0"
__author__ = "Frago Team"
__email__ = "caijia@frago.ai"

from . import cdp
from . import cli

__all__ = ["cdp", "cli"]