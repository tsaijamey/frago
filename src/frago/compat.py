"""跨平台兼容性工具"""
import platform
import shutil
from typing import List


def prepare_command_for_windows(cmd: List[str]) -> List[str]:
    """为 Windows 平台调整命令格式

    npm 全局安装的命令在 Windows 上是 .CMD 批处理文件。
    直接使用完整路径执行，而非通过 cmd.exe /c（后者会在换行符处截断参数）。

    Args:
        cmd: 原始命令列表

    Returns:
        调整后的命令列表
    """
    if platform.system() != "Windows":
        return cmd

    if not cmd:
        return cmd

    # 查找可执行文件的完整路径
    executable = shutil.which(cmd[0])
    if executable:
        # 使用完整路径替换命令名
        # 这样 subprocess 可以直接执行 .CMD 文件，无需 cmd.exe /c
        # 重要：cmd.exe /c 会在换行符处截断参数，导致多行 prompt 丢失
        return [executable] + cmd[1:]

    return cmd
