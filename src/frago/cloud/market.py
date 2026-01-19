"""
frago Cloud 市场客户端

提供 Recipe 市场操作:
- search: 搜索 Recipe
- get_detail: 获取详情
- download: 下载 Recipe 内容
- install: 下载并安装到本地
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import yaml

from .config import FRAGO_RECIPES_DIR, ensure_config_dir
from .client import CloudClient, CloudAPIError, AuthenticationError, NetworkError
from .auth import require_login


logger = logging.getLogger(__name__)


class MarketError(Exception):
    """市场操作错误"""

    def __init__(self, message: str, code: str = 'market_error'):
        super().__init__(message)
        self.message = message
        self.code = code


def search(
    keyword: Optional[str] = None,
    author: Optional[str] = None,
    runtime: Optional[str] = None,
    min_rating: Optional[float] = None,
    is_premium: Optional[bool] = None,
    ordering: str = '-download_count',
    page: int = 1,
    page_size: int = 20
) -> Dict[str, Any]:
    """
    搜索 Recipe

    Args:
        keyword: 关键词（匹配名称、描述）
        author: 作者用户名
        runtime: 运行时类型（chrome-js, python, shell）
        min_rating: 最低评分
        is_premium: 是否为 Premium
        ordering: 排序字段
        page: 页码
        page_size: 每页数量

    Returns:
        搜索结果字典，包含 count, results 等

    Raises:
        MarketError: 搜索失败
    """
    client = CloudClient()

    params = {}
    if keyword:
        params['q'] = keyword
    if author:
        params['author'] = author
    if runtime:
        params['runtime'] = runtime
    if min_rating is not None:
        params['min_rating'] = min_rating
    if is_premium is not None:
        params['is_premium'] = 'true' if is_premium else 'false'
    params['ordering'] = ordering
    params['page'] = page
    params['page_size'] = page_size

    try:
        result = client.get('/recipes/', params=params, authenticated=False)
        return result.get('data', result)
    except NetworkError as e:
        raise MarketError(f'无法连接到服务器: {e.message}', code='network_error')
    except CloudAPIError as e:
        raise MarketError(f'搜索失败: {e.message}', code='api_error')


def get_detail(recipe_id: int) -> Dict[str, Any]:
    """
    获取 Recipe 详情

    Args:
        recipe_id: Recipe ID

    Returns:
        Recipe 详情字典

    Raises:
        MarketError: 获取失败
    """
    client = CloudClient()

    try:
        result = client.get(f'/recipes/{recipe_id}/', authenticated=False)
        return result.get('data', result)
    except NetworkError as e:
        raise MarketError(f'无法连接到服务器: {e.message}', code='network_error')
    except CloudAPIError as e:
        if e.status_code == 404:
            raise MarketError('Recipe 不存在', code='not_found')
        raise MarketError(f'获取详情失败: {e.message}', code='api_error')


def download(recipe_id: int, version: Optional[str] = None) -> Dict[str, Any]:
    """
    下载 Recipe 内容

    Args:
        recipe_id: Recipe ID
        version: 指定版本（默认最新）

    Returns:
        Recipe 内容字典，包含 name, version, runtime, content

    Raises:
        MarketError: 下载失败
    """
    client = CloudClient()

    params = {}
    if version:
        params['version'] = version

    try:
        result = client.post(f'/recipes/{recipe_id}/download', params=params)
        return result.get('data', result)
    except AuthenticationError:
        raise MarketError('请先登录: frago login', code='auth_required')
    except NetworkError as e:
        raise MarketError(f'无法连接到服务器: {e.message}', code='network_error')
    except CloudAPIError as e:
        if e.status_code == 404:
            raise MarketError('Recipe 或版本不存在', code='not_found')
        if e.status_code == 403:
            raise MarketError('此 Recipe 需要订阅才能下载', code='premium_required')
        raise MarketError(f'下载失败: {e.message}', code='api_error')


def install(
    recipe_id: int,
    version: Optional[str] = None,
    force: bool = False
) -> Path:
    """
    下载并安装 Recipe 到本地

    Args:
        recipe_id: Recipe ID
        version: 指定版本（默认最新）
        force: 是否覆盖已存在的文件

    Returns:
        安装路径

    Raises:
        MarketError: 安装失败
    """
    ensure_config_dir()

    # 下载内容
    content = download(recipe_id, version)

    name = content['name']
    recipe_version = content['version']
    runtime = content['runtime']
    script_content = content['content']

    # 确定文件扩展名
    ext_map = {
        'chrome-js': '.js',
        'python': '.py',
        'shell': '.sh',
    }
    ext = ext_map.get(runtime, '.recipe')

    # 构建文件路径
    filename = f'{name}{ext}'
    filepath = FRAGO_RECIPES_DIR / filename

    # 检查是否已存在
    if filepath.exists() and not force:
        # 读取现有文件检查版本
        existing_meta = _read_recipe_meta(filepath)
        if existing_meta and existing_meta.get('version') == recipe_version:
            print(f'Recipe {name}@{recipe_version} 已是最新版本')
            return filepath
        else:
            print(f'Recipe {name} 已存在，使用 --force 覆盖')
            raise MarketError(f'Recipe {name} 已存在', code='already_exists')

    # 写入文件
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            # 添加元信息注释头
            meta_header = _generate_meta_header(content, runtime)
            f.write(meta_header)
            f.write('\n')
            f.write(script_content)

        # 设置可执行权限
        if runtime in ('python', 'shell'):
            os.chmod(filepath, 0o755)

        print(f'已安装 {name}@{recipe_version} 到 {filepath}')
        return filepath

    except IOError as e:
        raise MarketError(f'写入文件失败: {e}', code='io_error')


def list_installed() -> List[Dict[str, Any]]:
    """
    列出已安装的 Recipe

    Returns:
        已安装的 Recipe 列表
    """
    ensure_config_dir()

    recipes = []
    for filepath in FRAGO_RECIPES_DIR.iterdir():
        if filepath.is_file() and filepath.suffix in ('.js', '.py', '.sh', '.recipe'):
            meta = _read_recipe_meta(filepath)
            if meta:
                meta['path'] = str(filepath)
                recipes.append(meta)

    return recipes


def uninstall(name: str) -> bool:
    """
    卸载 Recipe

    Args:
        name: Recipe 名称

    Returns:
        是否成功

    Raises:
        MarketError: 卸载失败
    """
    ensure_config_dir()

    # 查找匹配的文件
    for ext in ('.js', '.py', '.sh', '.recipe'):
        filepath = FRAGO_RECIPES_DIR / f'{name}{ext}'
        if filepath.exists():
            filepath.unlink()
            print(f'已卸载 {name}')
            return True

    raise MarketError(f'Recipe {name} 未安装', code='not_installed')


def _generate_meta_header(content: Dict[str, Any], runtime: str) -> str:
    """生成元信息注释头"""
    comment_prefix = {
        'chrome-js': '//',
        'python': '#',
        'shell': '#',
    }.get(runtime, '#')

    lines = [
        f'{comment_prefix} frago Recipe: {content["name"]}',
        f'{comment_prefix} Version: {content["version"]}',
        f'{comment_prefix} Runtime: {content["runtime"]}',
        f'{comment_prefix} Author: {content.get("author", "unknown")}',
        f'{comment_prefix} ---',
    ]

    return '\n'.join(lines) + '\n'


def _read_recipe_meta(filepath: Path) -> Optional[Dict[str, Any]]:
    """从文件中读取 Recipe 元信息"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # 读取前 10 行查找元信息
            meta = {
                'name': filepath.stem,
            }

            for i, line in enumerate(f):
                if i >= 10:
                    break

                line = line.strip()
                # 跳过注释前缀
                for prefix in ('//', '#'):
                    if line.startswith(prefix):
                        line = line[len(prefix):].strip()
                        break

                # 解析元信息
                if line.startswith('frago Recipe:'):
                    meta['name'] = line.split(':', 1)[1].strip()
                elif line.startswith('Version:'):
                    meta['version'] = line.split(':', 1)[1].strip()
                elif line.startswith('Runtime:'):
                    meta['runtime'] = line.split(':', 1)[1].strip()
                elif line.startswith('Author:'):
                    meta['author'] = line.split(':', 1)[1].strip()
                elif line == '---':
                    break

            return meta if 'version' in meta else None

    except Exception:
        return None


# ============== CLI 辅助函数 ==============

def print_recipe_list(recipes: List[Dict[str, Any]], show_id: bool = True):
    """打印 Recipe 列表"""
    if not recipes:
        print('没有找到 Recipe')
        return

    for recipe in recipes:
        premium_badge = ' [Premium]' if recipe.get('is_premium') else ''
        rating = recipe.get('average_rating', 0)
        rating_str = f'{rating:.1f}★' if rating > 0 else '无评分'
        downloads = recipe.get('download_count', 0)

        if show_id:
            print(f"  [{recipe['id']}] {recipe['name']}{premium_badge}")
        else:
            print(f"  {recipe['name']}{premium_badge}")

        print(f"      {recipe.get('description', '')[:60]}...")
        print(f"      作者: {recipe.get('author', 'unknown')} | "
              f"评分: {rating_str} | 下载: {downloads}")
        print()


def print_recipe_detail(recipe: Dict[str, Any]):
    """打印 Recipe 详情"""
    premium_badge = ' [Premium]' if recipe.get('is_premium') else ''
    rating = recipe.get('average_rating', 0)
    rating_str = f'{rating:.1f}★' if rating > 0 else '无评分'

    print()
    print(f"Recipe: {recipe['name']}{premium_badge}")
    print('=' * 50)
    print(f"描述: {recipe.get('description', '')}")
    print(f"作者: {recipe.get('author', {}).get('username', 'unknown')}")
    print(f"运行时: {recipe.get('runtime', 'unknown')}")
    print(f"评分: {rating_str} ({recipe.get('ratings_count', 0)} 条评价)")
    print(f"下载: {recipe.get('download_count', 0)}")
    print()

    versions = recipe.get('versions', [])
    if versions:
        print('版本历史:')
        for v in versions[:5]:  # 最多显示 5 个版本
            latest_mark = ' [最新]' if v.get('is_latest') else ''
            print(f"  - {v['version']}{latest_mark}: {v.get('changelog', '无更新说明')[:40]}")
    print()


def print_installed_list(recipes: List[Dict[str, Any]]):
    """打印已安装的 Recipe 列表"""
    if not recipes:
        print('没有已安装的 Recipe')
        return

    print('已安装的 Recipe:')
    print()

    for recipe in recipes:
        print(f"  {recipe['name']}@{recipe.get('version', '?')}")
        print(f"      路径: {recipe['path']}")
        print()
