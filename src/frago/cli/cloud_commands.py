"""
frago Cloud CLI 命令

提供云端服务相关命令:
- login: 登录到 frago Cloud
- logout: 退出登录
- whoami: 显示当前用户信息
- config: 配置管理
"""

import click

from frago.cloud.auth import (
    login as cloud_login,
    logout as cloud_logout,
    whoami,
    print_user_info,
    is_logged_in,
    AuthError,
)
from frago.cloud.config import (
    config_get,
    config_set,
    config_list,
)
from frago.cloud import market
from frago.cloud.market import MarketError


@click.command('login')
@click.option('--no-browser', is_flag=True, help='不自动打开浏览器')
@click.option('--timeout', type=int, default=600, help='登录超时时间（秒）')
def login_cmd(no_browser: bool, timeout: int):
    """
    登录到 frago Cloud

    使用设备授权流程登录，会显示一个代码需要在浏览器中输入。
    """
    if is_logged_in():
        user_info = whoami()
        if user_info:
            click.echo(f'已登录为: {user_info.get("username", "未知")}')
            if not click.confirm('是否重新登录?'):
                return

    try:
        cloud_login(
            open_browser=not no_browser,
            timeout=timeout
        )
    except AuthError as e:
        click.echo(f'登录失败: {e}', err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f'登录失败: {e}', err=True)
        raise SystemExit(1)


@click.command('logout')
def logout_cmd():
    """
    退出登录

    清除本地保存的认证信息。
    """
    if not is_logged_in():
        click.echo('当前未登录')
        return

    cloud_logout()


@click.command('whoami')
@click.option('--refresh', '-r', is_flag=True, help='强制从服务器获取最新信息')
def whoami_cmd(refresh: bool):
    """
    显示当前登录用户信息

    显示用户名、邮箱、订阅类型等信息。
    """
    if not is_logged_in():
        click.echo('未登录')
        click.echo('使用 `frago login` 登录')
        return

    user_info = whoami(force_refresh=refresh)
    print_user_info(user_info)


@click.group('config')
def config_group():
    """
    配置管理

    管理 frago Cloud 相关配置。
    """
    pass


@config_group.command('get')
@click.argument('key')
def config_get_cmd(key: str):
    """
    获取配置项

    KEY: 配置项名称（如 api_url）
    """
    value = config_get(key)
    if value is None:
        click.echo(f'{key}: (未设置)')
    else:
        click.echo(f'{key}: {value}')


@config_group.command('set')
@click.argument('key')
@click.argument('value')
def config_set_cmd(key: str, value: str):
    """
    设置配置项

    KEY: 配置项名称
    VALUE: 配置值
    """
    config_set(key, value)
    click.echo(f'已设置 {key} = {value}')


@config_group.command('list')
def config_list_cmd():
    """
    列出所有配置项
    """
    configs = config_list()
    if not configs:
        click.echo('没有配置项')
        return

    click.echo()
    for key, info in configs.items():
        value = info['value']
        default = info.get('default')
        desc = info.get('description', '')

        if value == default:
            click.echo(f'{key}: {value} (默认)')
        else:
            click.echo(f'{key}: {value}')
        if desc:
            click.echo(f'  # {desc}')
    click.echo()


# ==================== Market 命令组 ====================

@click.group('market')
def market_group():
    """
    Recipe 市场

    搜索、下载、管理 Recipe。
    """
    pass


@market_group.command('search')
@click.argument('keyword', required=False)
@click.option('--author', '-a', help='按作者筛选')
@click.option('--runtime', '-r', type=click.Choice(['chrome-js', 'python', 'shell']), help='按运行时类型筛选')
@click.option('--min-rating', type=float, help='最低评分')
@click.option('--premium/--no-premium', default=None, help='只显示 Premium/非 Premium')
@click.option('--page', '-p', type=int, default=1, help='页码')
@click.option('--page-size', '-n', type=int, default=20, help='每页数量')
def market_search(keyword, author, runtime, min_rating, premium, page, page_size):
    """
    搜索 Recipe

    KEYWORD: 搜索关键词（可选，匹配名称和描述）

    \b
    示例:
      frago market search                    # 列出热门 Recipe
      frago market search twitter            # 搜索 "twitter" 相关
      frago market search -a yammi           # 搜索 yammi 的 Recipe
      frago market search --runtime python   # 搜索 Python 脚本
    """
    try:
        result = market.search(
            keyword=keyword,
            author=author,
            runtime=runtime,
            min_rating=min_rating,
            is_premium=premium,
            page=page,
            page_size=page_size
        )

        count = result.get('count', 0)
        recipes = result.get('results', [])

        click.echo()
        click.echo(f'找到 {count} 个 Recipe')
        click.echo()

        market.print_recipe_list(recipes)

        # 显示分页信息
        if count > page_size:
            total_pages = (count + page_size - 1) // page_size
            click.echo(f'第 {page}/{total_pages} 页')
            if result.get('next'):
                click.echo(f'使用 -p {page + 1} 查看下一页')

    except MarketError as e:
        click.echo(f'搜索失败: {e.message}', err=True)
        raise SystemExit(1)


@market_group.command('info')
@click.argument('recipe_id', type=int)
def market_info(recipe_id):
    """
    查看 Recipe 详情

    RECIPE_ID: Recipe ID（从搜索结果获取）

    \b
    示例:
      frago market info 123
    """
    try:
        recipe = market.get_detail(recipe_id)
        market.print_recipe_detail(recipe)

    except MarketError as e:
        click.echo(f'获取详情失败: {e.message}', err=True)
        raise SystemExit(1)


@market_group.command('install')
@click.argument('recipe_id', type=int)
@click.option('--version', '-v', help='指定版本（默认最新）')
@click.option('--force', '-f', is_flag=True, help='覆盖已存在的 Recipe')
def market_install(recipe_id, version, force):
    """
    下载并安装 Recipe

    RECIPE_ID: Recipe ID（从搜索结果获取）

    安装到 ~/.frago/recipes/ 目录。

    \b
    示例:
      frago market install 123           # 安装最新版本
      frago market install 123 -v 1.0.0  # 安装指定版本
      frago market install 123 -f        # 强制覆盖
    """
    if not is_logged_in():
        click.echo('请先登录: frago login', err=True)
        raise SystemExit(1)

    try:
        filepath = market.install(recipe_id, version=version, force=force)
        click.echo()
        click.echo(f'安装成功: {filepath}')

    except MarketError as e:
        click.echo(f'安装失败: {e.message}', err=True)
        raise SystemExit(1)


@market_group.command('list')
def market_list_installed():
    """
    列出已安装的 Recipe

    显示本地 ~/.frago/recipes/ 中已安装的 Recipe。
    """
    recipes = market.list_installed()
    market.print_installed_list(recipes)


@market_group.command('uninstall')
@click.argument('name')
def market_uninstall(name):
    """
    卸载 Recipe

    NAME: Recipe 名称

    \b
    示例:
      frago market uninstall twitter-login
    """
    try:
        market.uninstall(name)

    except MarketError as e:
        click.echo(f'卸载失败: {e.message}', err=True)
        raise SystemExit(1)


# ==================== Install 命令组 ====================

@click.group('install')
def install_group():
    """
    安装工具

    安装 Claude Code 等工具到本地。
    """
    pass


@install_group.command('claude-code')
@click.option('--version', '-v', help='指定版本（默认最新）')
@click.option('--force', '-f', is_flag=True, help='强制重新安装')
@click.option('--mirror-only', is_flag=True, help='仅使用镜像源')
@click.option('--install-dir', type=click.Path(), help='指定安装目录')
def install_claude_code(version, force, mirror_only, install_dir):
    """
    安装 Claude Code

    自动检测官方源可达性，不可达时降级到镜像源。
    支持 Linux, macOS, Windows 平台。

    \b
    示例:
      frago install claude-code                 # 安装最新版本
      frago install claude-code -v 2.1.12       # 安装指定版本
      frago install claude-code --mirror-only   # 强制使用镜像源
      frago install claude-code -f              # 强制重新安装
    """
    from pathlib import Path
    from frago.cloud.installer import (
        ClaudeCodeInstaller,
        InstallerError,
        DownloadError,
        VerificationError,
        InstallError,
    )

    try:
        installer = ClaudeCodeInstaller(verbose=True)

        install_path = Path(install_dir) if install_dir else None

        installed_path = installer.install(
            version=version,
            force=force,
            mirror_only=mirror_only,
            install_dir=install_path
        )

        click.echo()
        click.echo('安装完成!')
        click.echo(f'运行 `{installed_path}` 或将安装目录添加到 PATH 后运行 `claude`')

    except DownloadError as e:
        click.echo(f'下载失败: {e.message}', err=True)
        raise SystemExit(1)
    except VerificationError as e:
        click.echo(f'校验失败: {e.message}', err=True)
        raise SystemExit(1)
    except InstallError as e:
        click.echo(f'安装失败: {e.message}', err=True)
        raise SystemExit(1)
    except InstallerError as e:
        click.echo(f'错误: {e.message}', err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f'未知错误: {e}', err=True)
        raise SystemExit(1)


@install_group.command('check-update')
@click.option('--tool', type=click.Choice(['claude-code']), default='claude-code', help='要检查的工具')
def install_check_update(tool):
    """
    检查工具更新

    \b
    示例:
      frago install check-update
      frago install check-update --tool claude-code
    """
    if tool == 'claude-code':
        from frago.cloud.installer import ClaudeCodeInstaller

        installer = ClaudeCodeInstaller(verbose=False)
        new_version = installer.check_update()

        if new_version:
            click.echo(f'有新版本可用: {new_version}')
            click.echo('运行 `frago install claude-code -f` 更新')
        else:
            click.echo('已是最新版本')


# 导出命令
__all__ = ['login_cmd', 'logout_cmd', 'whoami_cmd', 'config_group', 'market_group', 'install_group']
