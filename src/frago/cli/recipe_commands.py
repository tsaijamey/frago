"""Recipe 管理命令"""
import json
import sys
from pathlib import Path
from typing import Optional

import click

from frago.recipes import RecipeRegistry, RecipeRunner, OutputHandler
from frago.recipes.exceptions import RecipeError, MetadataParseError, RecipeValidationError
from frago.recipes.metadata import parse_metadata_file, validate_metadata
from .agent_friendly import AgentFriendlyGroup


@click.group(name='recipe', cls=AgentFriendlyGroup)
def recipe_group():
    """Recipe 管理命令组"""
    pass


@recipe_group.command(name='list')
@click.option(
    '--source',
    type=click.Choice(['project', 'user', 'example', 'all'], case_sensitive=False),
    default='all',
    help='过滤来源'
)
@click.option(
    '--type',
    'recipe_type',
    type=click.Choice(['atomic', 'workflow', 'all'], case_sensitive=False),
    default='all',
    help='过滤类型'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json', 'names'], case_sensitive=False),
    default='table',
    help='输出格式'
)
def list_recipes(source: str, recipe_type: str, output_format: str):
    """列出所有可用的 Recipe"""
    try:
        registry = RecipeRegistry()
        registry.scan()

        # 过滤 Recipe
        if source != 'all':
            # 指定来源时，直接从该来源获取配方
            recipes = registry.get_by_source(source)
        else:
            # 未指定来源时，返回每个配方的最高优先级版本
            recipes = registry.list_all()

        if recipe_type != 'all':
            recipes = [r for r in recipes if r.metadata.type == recipe_type]
        
        # 输出
        if output_format == 'json':
            # AI 友好的 JSON 输出
            output = [
                {
                    "name": r.metadata.name,
                    "type": r.metadata.type,
                    "runtime": r.metadata.runtime,
                    "description": r.metadata.description,
                    "use_cases": r.metadata.use_cases,
                    "tags": r.metadata.tags,
                    "output_targets": r.metadata.output_targets,
                    "version": r.metadata.version,
                    "source": r.source,
                    "path": str(r.script_path)
                }
                for r in recipes
            ]
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        elif output_format == 'names':
            for r in recipes:
                click.echo(r.metadata.name)
        else:  # table
            if not recipes:
                click.echo("未找到 Recipe")
                return

            # 表格输出
            click.echo(f"{'SOURCE':<10} {'TYPE':<10} {'NAME':<40} {'RUNTIME':<10} {'VERSION':<8}")
            click.echo("─" * 80)
            for r in recipes:
                click.echo(
                    f"{r.source:<10} {r.metadata.type:<10} {r.metadata.name:<40} "
                    f"{r.metadata.runtime:<10} {r.metadata.version:<8}"
                )

            # 检查是否有同名 Recipe 的情况
            recipe_names = [r.metadata.name for r in recipes]
            duplicates = []
            for recipe_name in set(recipe_names):
                all_sources = registry.find_all_sources(recipe_name)
                if len(all_sources) > 1:
                    duplicates.append((recipe_name, [s for s, _ in all_sources]))

            if duplicates:
                click.echo()
                click.echo("注意: 以下 Recipe 在多个来源中存在（使用优先级高的）:")
                for name, sources in duplicates:
                    click.echo(f"  • {name}: {' > '.join(sources)}")
    
    except RecipeError as e:
        click.echo(f"错误: {e}", err=True)


@recipe_group.command(name='info')
@click.argument('name')
@click.option(
    '--source',
    type=click.Choice(['project', 'user', 'example'], case_sensitive=False),
    default=None,
    help='指定配方来源（默认按优先级自动选择）'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json', 'yaml'], case_sensitive=False),
    default='text',
    help='输出格式'
)
def recipe_info(name: str, source: Optional[str], output_format: str):
    """显示指定 Recipe 的详细信息"""
    try:
        registry = RecipeRegistry()
        registry.scan()
        recipe = registry.find(name, source=source)
        
        if output_format == 'json':
            # 获取示例文件列表
            examples = [str(e.name) for e in recipe.list_examples()]

            output = {
                "name": recipe.metadata.name,
                "type": recipe.metadata.type,
                "runtime": recipe.metadata.runtime,
                "version": recipe.metadata.version,
                "source": recipe.source,
                "base_dir": str(recipe.base_dir) if recipe.base_dir else None,
                "script_path": str(recipe.script_path),
                "metadata_path": str(recipe.metadata_path),
                "description": recipe.metadata.description,
                "use_cases": recipe.metadata.use_cases,
                "tags": recipe.metadata.tags,
                "output_targets": recipe.metadata.output_targets,
                "inputs": recipe.metadata.inputs,
                "outputs": recipe.metadata.outputs,
                "dependencies": recipe.metadata.dependencies,
                "env": recipe.metadata.env,
                "examples": examples,
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        else:  # text
            m = recipe.metadata
            click.echo(f"Recipe: {m.name}")
            click.echo("=" * 50)
            click.echo()
            click.echo("基本信息")
            click.echo("─" * 50)
            click.echo(f"名称:     {m.name}")
            click.echo(f"类型:     {m.type}")
            click.echo(f"运行时:   {m.runtime}")
            click.echo(f"版本:     {m.version}")
            click.echo(f"来源:     {recipe.source}")

            # 检查是否有同名 Recipe 在其他来源
            all_sources = registry.find_all_sources(name)
            if len(all_sources) > 1:
                other_sources = [s for s, _ in all_sources if s != recipe.source]
                if other_sources:
                    click.echo(f"          (同名 Recipe 也存在于: {', '.join(other_sources)})")

            click.echo(f"路径:     {recipe.script_path}")
            click.echo()
            click.echo("描述")
            click.echo("─" * 50)
            click.echo(m.description)
            click.echo()
            if m.use_cases:
                click.echo("使用场景")
                click.echo("─" * 50)
                for case in m.use_cases:
                    click.echo(f"• {case}")
                click.echo()
            if m.tags:
                click.echo("标签")
                click.echo("─" * 50)
                click.echo(", ".join(m.tags))
                click.echo()
            click.echo("输出目标")
            click.echo("─" * 50)
            click.echo(", ".join(m.output_targets))
            click.echo()
            if m.inputs:
                click.echo("输入参数")
                click.echo("─" * 50)
                for param_name, param_def in m.inputs.items():
                    required = "必需" if param_def.get('required', False) else "可选"
                    param_type = param_def.get('type', 'unknown')
                    desc = param_def.get('description', '')
                    click.echo(f"• {param_name} ({param_type}, {required}): {desc}")
                click.echo()
            if m.env:
                click.echo("环境变量")
                click.echo("─" * 50)
                for env_name, env_def in m.env.items():
                    required = "必需" if env_def.get('required', False) else "可选"
                    default = env_def.get('default', '')
                    desc = env_def.get('description', '')
                    if default:
                        click.echo(f"• {env_name} ({required}, 默认: {default}): {desc}")
                    else:
                        click.echo(f"• {env_name} ({required}): {desc}")
                click.echo()
            if m.dependencies:
                click.echo("依赖")
                click.echo("─" * 50)
                click.echo(", ".join(m.dependencies))
                click.echo()
            else:
                click.echo("依赖")
                click.echo("─" * 50)
                click.echo("无")
                click.echo()

            # 显示示例文件
            examples = recipe.list_examples()
            click.echo("示例文件")
            click.echo("─" * 50)
            if examples:
                for example in examples:
                    click.echo(f"• {example.name}")
            else:
                click.echo("无")

    except RecipeError as e:
        click.echo(f"错误: {e}", err=True)


@recipe_group.command(name='run')
@click.argument('name')
@click.option(
    '--source',
    type=click.Choice(['project', 'user', 'example'], case_sensitive=False),
    default=None,
    help='指定配方来源（默认按优先级自动选择）'
)
@click.option(
    '--params',
    type=str,
    default='{}',
    help='JSON 格式参数字符串'
)
@click.option(
    '--params-file',
    type=click.Path(exists=True),
    help='从文件读取参数（JSON 格式）'
)
@click.option(
    '--env', '-e',
    'env_vars',
    multiple=True,
    help='环境变量覆盖，格式: KEY=VALUE（可多次使用）'
)
@click.option(
    '--output-file',
    type=click.Path(),
    help='将结果写入文件'
)
@click.option(
    '--output-clipboard',
    is_flag=True,
    help='将结果复制到剪贴板'
)
@click.option(
    '--timeout',
    type=int,
    default=300,
    help='执行超时时间（秒）'
)
def run_recipe(
    name: str,
    source: Optional[str],
    params: str,
    params_file: Optional[str],
    env_vars: tuple,
    output_file: Optional[str],
    output_clipboard: bool,
    timeout: int
):
    """执行指定的 Recipe"""
    try:
        # 解析参数
        if params_file:
            with open(params_file, 'r', encoding='utf-8') as f:
                params_dict = json.load(f)
        else:
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError as e:
                click.echo(f"错误: 参数格式无效\n{e}", err=True)
                sys.exit(2)

        # 解析环境变量覆盖
        env_overrides: dict[str, str] = {}
        for env_var in env_vars:
            if '=' not in env_var:
                click.echo(f"错误: 环境变量格式无效: '{env_var}'（应为 KEY=VALUE）", err=True)
                sys.exit(2)
            key, value = env_var.split('=', 1)
            env_overrides[key] = value

        # 确定输出目标
        if output_clipboard:
            output_target = 'clipboard'
            output_options = {}
        elif output_file:
            output_target = 'file'
            output_options = {'path': output_file}
        else:
            output_target = 'stdout'
            output_options = {}

        # 执行 Recipe
        runner = RecipeRunner()
        result = runner.run(
            name,
            params_dict,
            output_target,
            output_options,
            env_overrides=env_overrides if env_overrides else None,
            source=source
        )
        
        # 处理输出
        if output_target == 'stdout':
            OutputHandler.handle(result, 'stdout')
        elif output_target == 'file':
            OutputHandler.handle(result, 'file', output_options)
            if result.get('success'):
                click.echo(f"✓ 结果已保存到: {output_file}", err=True)
        elif output_target == 'clipboard':
            OutputHandler.handle(result, 'clipboard')
            if result.get('success'):
                click.echo("✓ 结果已复制到剪贴板", err=True)

        # 如果执行失败，返回非零退出码
        if not result.get('success'):
            click.echo("配方执行失败", err=True)

    except RecipeError as e:
        click.echo(f"错误: {e}", err=True)
    except Exception as e:
        click.echo(f"错误: {e}", err=True)


@recipe_group.command('validate')
@click.argument('path', type=click.Path(exists=True))
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='输出格式'
)
def validate_recipe(path: str, output_format: str):
    """
    验证配方目录的字段完整性和正确性

    PATH 可以是：
    - 配方目录路径（包含 recipe.md 和脚本文件）
    - recipe.md 文件路径
    """
    recipe_path = Path(path)

    # 确定 recipe.md 和配方目录
    if recipe_path.is_file():
        if recipe_path.name != 'recipe.md':
            click.echo(f"错误: 指定的文件不是 recipe.md: {recipe_path.name}", err=True)
            return
        metadata_path = recipe_path
        recipe_dir = recipe_path.parent
    else:
        # 目录形式
        metadata_path = recipe_path / 'recipe.md'
        recipe_dir = recipe_path
        if not metadata_path.exists():
            click.echo(f"错误: 配方目录中未找到 recipe.md: {recipe_dir}", err=True)
            return

    errors: list[str] = []
    warnings: list[str] = []
    metadata = None

    # 1. 解析元数据
    try:
        metadata = parse_metadata_file(metadata_path)
    except MetadataParseError as e:
        errors.append(f"元数据解析失败: {e.reason}")

    # 2. 验证元数据字段
    if metadata:
        try:
            validate_metadata(metadata)
        except RecipeValidationError as e:
            errors.extend(e.errors)

    # 3. 检查脚本文件
    if metadata:
        script_extensions = {
            'chrome-js': '.js',
            'python': '.py',
            'shell': '.sh'
        }
        ext = script_extensions.get(metadata.runtime, '')
        script_path = recipe_dir / f"recipe{ext}"

        if not script_path.exists():
            errors.append(f"脚本文件不存在: recipe{ext}（runtime: {metadata.runtime}）")
        else:
            # 检查脚本是否为空
            content = script_path.read_text(encoding='utf-8').strip()
            if not content:
                errors.append(f"脚本文件为空: recipe{ext}")

            # 检查脚本基本语法（可选的简单检查）
            if metadata.runtime == 'python':
                try:
                    compile(content, str(script_path), 'exec')
                except SyntaxError as e:
                    errors.append(f"Python 语法错误: {e.msg} (行 {e.lineno})")
            elif metadata.runtime == 'chrome-js':
                # JavaScript 简单检查：是否包含基本结构
                if 'return' not in content and 'console' not in content:
                    warnings.append("JavaScript 脚本未包含 return 语句或 console 输出")

    # 4. 检查 examples 目录（可选）
    examples_dir = recipe_dir / 'examples'
    if examples_dir.exists():
        example_files = list(examples_dir.glob('*'))
        if not example_files:
            warnings.append("examples 目录存在但为空")

    # 5. 检查依赖（如果是 workflow）
    if metadata and metadata.type == 'workflow' and metadata.dependencies:
        registry = RecipeRegistry()
        registry.scan()
        for dep in metadata.dependencies:
            if dep not in registry.recipes:
                errors.append(f"依赖的配方不存在: {dep}")

    # 输出结果
    is_valid = len(errors) == 0

    if output_format == 'json':
        result = {
            "valid": is_valid,
            "path": str(recipe_dir),
            "name": metadata.name if metadata else None,
            "type": metadata.type if metadata else None,
            "runtime": metadata.runtime if metadata else None,
            "errors": errors,
            "warnings": warnings,
        }
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # text 格式
        if is_valid:
            click.echo(f"✓ 配方验证通过: {recipe_dir}")
            if metadata:
                click.echo(f"  名称: {metadata.name}")
                click.echo(f"  类型: {metadata.type}")
                click.echo(f"  运行时: {metadata.runtime}")
            if warnings:
                click.echo()
                click.echo("⚠ 警告:")
                for w in warnings:
                    click.echo(f"  • {w}")
        else:
            click.echo(f"✗ 配方验证失败: {recipe_dir}", err=True)
            click.echo()
            click.echo("错误:")
            for e in errors:
                click.echo(f"  • {e}", err=True)
            if warnings:
                click.echo()
                click.echo("警告:")
                for w in warnings:
                    click.echo(f"  • {w}")
