"""
Frago - 自动化视觉管理系统CDP控制库

提供Chrome DevTools Protocol的Python封装，
用于浏览器自动化控制和视觉管理。
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("frago-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"  # 开发模式下未安装时的回退值
__author__ = "Jamey Tsai"
__email__ = "caijia@frago.ai"

# 推荐使用详细导入方式：
# from frago.recipes import RecipeRegistry, RecipeRunner
# from frago.run import RunInstance, RunManager
# from frago.cdp import CDPClient, CDPSession
# from frago.cli import cli

# 子模块通过路径访问（避免顶层命名空间污染）
# 例如：import frago.recipes, import frago.run

__all__ = [
    "__version__",
    "__author__",
    "__email__",
]