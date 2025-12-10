"""Agent-Friendly CLI 增强模块

为 AI Agent 提供更友好的错误信息和帮助输出：
- 未知命令时显示相似命令建议和可用命令列表
- 缺少参数时直接展示正确用法示例
- 帮助信息中展开子命令组
"""

import difflib
from typing import List, Optional, Tuple

import click
from click import Context


def get_command_examples(cmd_name: str, group_prefix: str = "") -> List[str]:
    """获取命令的使用示例

    Args:
        cmd_name: 命令名称
        group_prefix: 命令组前缀（如 "chrome"）

    Returns:
        示例列表
    """
    # 延迟导入避免循环依赖
    from .commands import COMMAND_EXAMPLES

    # 尝试多种键名格式
    keys_to_try = [
        f"{group_prefix}/{cmd_name}" if group_prefix else cmd_name,
        cmd_name,
        cmd_name.replace("-", "_"),
    ]

    for key in keys_to_try:
        if key in COMMAND_EXAMPLES:
            return COMMAND_EXAMPLES[key]

    return []


class AgentFriendlyGroup(click.Group):
    """Agent 友好的命令组

    增强错误处理，在命令解析失败时提供：
    - 相似命令建议（基于编辑距离）
    - 正确用法示例
    - 可用命令列表
    """

    def resolve_command(
        self, ctx: Context, args: List[str]
    ) -> Tuple[Optional[str], Optional[click.Command], List[str]]:
        """重写命令解析，增强错误信息"""
        cmd_name = args[0] if args else None

        if cmd_name:
            cmd = self.get_command(ctx, cmd_name)

            if cmd is None and not ctx.resilient_parsing:
                # 获取所有可用命令
                available = self.list_commands(ctx)

                # 使用模糊匹配找相似命令
                matches = difflib.get_close_matches(
                    cmd_name, available, n=3, cutoff=0.5
                )

                # 构建详细错误信息
                error_lines = [f"No such command '{cmd_name}'."]

                if matches:
                    error_lines.append(f"\nDid you mean: {', '.join(matches)}?")

                    # 展示最相似命令的用法示例
                    group_prefix = self._get_group_prefix(ctx)
                    examples = get_command_examples(matches[0], group_prefix)
                    if examples:
                        error_lines.append(f"\nExample usage for '{matches[0]}':")
                        for ex in examples[:3]:
                            error_lines.append(f"  {ex}")

                # 始终显示可用命令列表
                error_lines.append(f"\nAvailable commands: {', '.join(sorted(available))}")

                ctx.fail("\n".join(error_lines))

        return super().resolve_command(ctx, args)

    def _get_group_prefix(self, ctx: Context) -> str:
        """获取当前命令组的前缀（如 'chrome'）"""
        if ctx.info_name:
            return ctx.info_name
        return ""

    def make_context(
        self,
        info_name: Optional[str],
        args: List[str],
        parent: Optional[Context] = None,
        **extra,
    ) -> Context:
        """重写上下文创建，捕获并增强参数错误"""
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.MissingParameter as e:
            # 增强缺少参数的错误信息
            self._enhance_missing_param_error(e, info_name, parent)
            raise
        except click.BadParameter as e:
            # 增强参数错误的错误信息
            self._enhance_bad_param_error(e, info_name, parent)
            raise

    def _enhance_missing_param_error(
        self,
        error: click.MissingParameter,
        info_name: Optional[str],
        parent: Optional[Context],
    ) -> None:
        """增强 MissingParameter 错误信息"""
        if not info_name:
            return

        group_prefix = parent.info_name if parent else ""
        examples = get_command_examples(info_name, group_prefix)

        if examples:
            original_msg = error.format_message()
            enhanced_msg = f"{original_msg}\n\nCorrect usage:"
            for ex in examples[:3]:
                enhanced_msg += f"\n  {ex}"
            error.message = enhanced_msg

    def _enhance_bad_param_error(
        self,
        error: click.BadParameter,
        info_name: Optional[str],
        parent: Optional[Context],
    ) -> None:
        """增强 BadParameter 错误信息"""
        # BadParameter 通常已经由自定义 ParamType 处理得很好
        # 这里作为额外的增强点
        pass


class AgentFriendlyCommand(click.Command):
    """Agent 友好的命令

    在参数解析失败时提供正确用法示例
    """

    def make_context(
        self,
        info_name: Optional[str],
        args: List[str],
        parent: Optional[Context] = None,
        **extra,
    ) -> Context:
        """重写上下文创建，捕获并增强参数错误"""
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.MissingParameter as e:
            self._enhance_error_with_examples(e, info_name, parent)
            raise
        except click.BadParameter as e:
            # BadParameter 通常已有详细信息，不额外处理
            raise

    def _enhance_error_with_examples(
        self,
        error: click.MissingParameter,
        info_name: Optional[str],
        parent: Optional[Context],
    ) -> None:
        """为错误添加使用示例"""
        if not info_name:
            return

        # 获取命令组前缀
        group_prefix = ""
        if parent and parent.info_name:
            group_prefix = parent.info_name

        examples = get_command_examples(info_name, group_prefix)

        if examples:
            original_msg = error.format_message()
            enhanced_msg = f"{original_msg}\n\nCorrect usage:"
            for ex in examples[:3]:
                enhanced_msg += f"\n  {ex}"
            error.message = enhanced_msg


def _get_available_options(ctx: Optional[Context]) -> List[str]:
    """从上下文中获取可用的选项列表"""
    if not ctx or not ctx.command:
        return []

    options = []
    for param in ctx.command.params:
        if isinstance(param, click.Option):
            # 获取选项名（优先使用长选项）
            opt_names = param.opts
            if opt_names:
                # 优先选择 -- 开头的长选项
                long_opts = [o for o in opt_names if o.startswith("--")]
                if long_opts:
                    options.append(long_opts[0])
                else:
                    options.append(opt_names[0])

    return sorted(options)


def install_agent_friendly_errors():
    """安装全局的 Agent 友好错误处理

    通过 monkey-patch Click 的 UsageError.show 方法，
    在所有错误信息后自动添加使用示例。
    """
    original_show = click.UsageError.show

    def enhanced_show(self, file=None):
        """增强的错误显示"""
        # 先调用原始的 show 方法
        original_show(self, file)

        # 尝试从上下文获取命令信息并添加示例
        if not self.ctx:
            return

        cmd_name = self.ctx.info_name
        if not cmd_name:
            return

        # 获取父上下文的命令组名
        group_prefix = ""
        if self.ctx.parent and self.ctx.parent.info_name:
            group_prefix = self.ctx.parent.info_name

        # 获取示例
        examples = get_command_examples(cmd_name, group_prefix)
        if not examples:
            return

        # 检查错误类型，添加相应的示例
        error_msg = self.format_message()
        import sys
        err_file = file or sys.stderr

        # 处理缺少参数的错误
        if "Missing" in error_msg or "required" in error_msg.lower():
            click.echo("\nCorrect usage:", file=err_file)
            for ex in examples[:3]:
                click.echo(f"  {ex}", file=err_file)
        # 处理无效选项的错误
        elif "No such option" in error_msg or "no such option" in error_msg.lower():
            # 显示可用选项
            available_options = _get_available_options(self.ctx)
            if available_options:
                click.echo(f"\nAvailable options: {', '.join(available_options)}", file=err_file)
            # 显示正确用法
            click.echo("\nCorrect usage:", file=err_file)
            for ex in examples[:3]:
                click.echo(f"  {ex}", file=err_file)

    click.UsageError.show = enhanced_show


# 自动安装增强错误处理
install_agent_friendly_errors()
