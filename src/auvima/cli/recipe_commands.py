"""Recipe 管理命令"""
import json
import sys
from pathlib import Path
from typing import Optional

import click

from auvima.recipes import RecipeRegistry, RecipeRunner, OutputHandler
from auvima.recipes.exceptions import RecipeError


@click.group(name='recipe')
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
        recipes = registry.list_all()
        
        if source != 'all':
            source_label = source.capitalize()
            recipes = [r for r in recipes if r.source == source_label]
        
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
        sys.exit(1)


@recipe_group.command(name='info')
@click.argument('name')
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json', 'yaml'], case_sensitive=False),
    default='text',
    help='输出格式'
)
def recipe_info(name: str, output_format: str):
    """显示指定 Recipe 的详细信息"""
    try:
        registry = RecipeRegistry()
        registry.scan()
        recipe = registry.find(name)
        
        if output_format == 'json':
            output = {
                "name": recipe.metadata.name,
                "type": recipe.metadata.type,
                "runtime": recipe.metadata.runtime,
                "version": recipe.metadata.version,
                "source": recipe.source,
                "script_path": str(recipe.script_path),
                "metadata_path": str(recipe.metadata_path),
                "description": recipe.metadata.description,
                "use_cases": recipe.metadata.use_cases,
                "tags": recipe.metadata.tags,
                "output_targets": recipe.metadata.output_targets,
                "inputs": recipe.metadata.inputs,
                "outputs": recipe.metadata.outputs,
                "dependencies": recipe.metadata.dependencies,
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
            if m.dependencies:
                click.echo("依赖")
                click.echo("─" * 50)
                click.echo(", ".join(m.dependencies))
            else:
                click.echo("依赖")
                click.echo("─" * 50)
                click.echo("无")
    
    except RecipeError as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@recipe_group.command(name='run')
@click.argument('name')
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
    params: str,
    params_file: Optional[str],
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
        result = runner.run(name, params_dict, output_target, output_options)
        
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
            sys.exit(3)

    except RecipeError as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@recipe_group.command('copy')
@click.argument('name')
@click.option(
    '--force',
    is_flag=True,
    help='覆盖已存在的 Recipe'
)
def copy_recipe(name: str, force: bool):
    """
    将示例 Recipe 复制到用户级目录

    将指定的示例 Recipe（脚本 + 元数据文件）复制到 ~/.auvima/recipes/，
    保持原有的目录结构（atomic/chrome, atomic/system, workflows）。
    """
    import shutil
    from pathlib import Path

    try:
        # 初始化注册表并查找 Recipe
        registry = RecipeRegistry()
        registry.scan()

        recipe = registry.find(name)

        # 检查是否为示例 Recipe
        if recipe.source != 'Example':
            click.echo(f"错误: '{name}' 不是示例 Recipe（来源: {recipe.source}）", err=True)
            click.echo("只能复制示例 Recipe 到用户目录", err=True)
            sys.exit(1)

        # 确定目标目录
        user_home = Path.home()
        user_recipes_dir = user_home / '.auvima' / 'recipes'

        # 检查用户目录是否存在
        if not user_recipes_dir.exists():
            click.echo(f"错误: 用户级 Recipe 目录不存在: {user_recipes_dir}", err=True)
            click.echo("请先运行 'auvima init' 初始化目录结构", err=True)
            sys.exit(1)

        # 计算相对路径（相对于 examples/ 目录）
        script_path = recipe.script_path
        metadata_path = recipe.metadata_path

        # 找到 examples/ 目录
        examples_dir = None
        for parent in script_path.parents:
            if parent.name == 'examples':
                examples_dir = parent
                break

        if not examples_dir:
            click.echo(f"错误: 无法确定示例 Recipe 的目录结构", err=True)
            sys.exit(1)

        # 计算相对路径
        rel_script_path = script_path.relative_to(examples_dir)
        rel_metadata_path = metadata_path.relative_to(examples_dir)

        # 目标路径
        dest_script_path = user_recipes_dir / rel_script_path
        dest_metadata_path = user_recipes_dir / rel_metadata_path

        # 检查是否已存在
        if dest_script_path.exists() or dest_metadata_path.exists():
            if not force:
                click.echo(f"错误: Recipe '{name}' 已存在于用户目录", err=True)
                click.echo(f"  脚本: {dest_script_path}", err=True)
                click.echo(f"  元数据: {dest_metadata_path}", err=True)
                click.echo("使用 --force 覆盖现有文件", err=True)
                sys.exit(1)

        # 创建目标目录
        dest_script_path.parent.mkdir(parents=True, exist_ok=True)
        dest_metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # 复制文件
        shutil.copy2(script_path, dest_script_path)
        shutil.copy2(metadata_path, dest_metadata_path)

        # 输出结果
        click.echo(f"✓ Recipe '{name}' 已复制到用户目录:")
        click.echo(f"  脚本: {dest_script_path}")
        click.echo(f"  元数据: {dest_metadata_path}")
        click.echo(f"\n现在可以编辑这些文件以自定义 Recipe")

    except RecipeNotFoundError as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
