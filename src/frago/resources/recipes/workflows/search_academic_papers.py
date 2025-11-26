#!/usr/bin/env python3
"""
Workflow: search_academic_papers
Description: 并行查询多个学术数据库（arXiv + PubMed），合并结果并按时间排序
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime


# 如果不在 frago 环境中运行，需要手动导入
try:
    from frago.recipes import RecipeRunner, RecipeExecutionError
except ImportError:
    # 回退方案：直接调用脚本文件
    import subprocess

    class RecipeRunner:
        def run(self, recipe_name: str, params: dict) -> dict:
            """简单的 Recipe 执行器（回退方案）"""
            script_path = Path(__file__).parent.parent / "examples" / "atomic" / "system" / f"{recipe_name}.py"
            if not script_path.exists():
                raise FileNotFoundError(f"Recipe not found: {recipe_name}")

            try:
                result = subprocess.run(
                    ["python3", str(script_path), json.dumps(params)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                return json.loads(result.stdout) if result.stdout else {"success": False, "error": "No output"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    class RecipeExecutionError(Exception):
        def __init__(self, recipe_name, runtime, exit_code, stderr):
            self.recipe_name = recipe_name
            self.runtime = runtime
            self.exit_code = exit_code
            self.stderr = stderr


def normalize_date(date_str: str, source: str) -> str:
    """
    统一日期格式为 YYYY-MM-DD

    Args:
        date_str: 原始日期字符串
        source: 数据源（arXiv 或 PubMed）

    Returns:
        标准化的日期字符串
    """
    try:
        if source == 'arXiv':
            # arXiv 格式: YYYY-MM-DD
            return date_str[:10]
        elif source == 'PubMed':
            # PubMed 格式: YYYY Mon DD (如 "2025 Nov 23")
            dt = datetime.strptime(date_str, "%Y %b %d")
            return dt.strftime("%Y-%m-%d")
        else:
            return date_str
    except:
        return date_str


def search_database(database: str, query: str, max_results: int, runner: RecipeRunner) -> dict:
    """
    在单个数据库中搜索

    Args:
        database: 数据库名称（arxiv 或 pubmed）
        query: 搜索关键词
        max_results: 最大返回结果数
        runner: Recipe 执行器

    Returns:
        搜索结果字典
    """
    recipe_map = {
        'arxiv': 'arxiv_search_papers',
        'pubmed': 'pubmed_search_papers'
    }

    recipe_name = recipe_map.get(database.lower())
    if not recipe_name:
        return {
            'success': False,
            'source': database,
            'error': f'不支持的数据库: {database}'
        }

    try:
        result = runner.run(recipe_name, params={
            'query': query,
            'max_results': max_results
        })

        # 处理 RecipeRunner 返回的嵌套结构
        # result 结构: {"success": bool, "data": {...}, "error": ...}
        if result.get('success') and result.get('data'):
            # 返回内部的 data
            inner_data = result['data']
            if not inner_data.get('success'):
                print(f"⚠️  {database} 查询失败: {inner_data.get('error')}", file=sys.stderr)
            return inner_data
        else:
            print(f"⚠️  {database} 查询失败: {result.get('error')}", file=sys.stderr)
            return {
                'success': False,
                'source': database,
                'error': result.get('error', 'Unknown error')
            }

    except Exception as e:
        return {
            'success': False,
            'source': database,
            'error': {
                'type': type(e).__name__,
                'message': str(e)
            }
        }


def main():
    """主函数：编排并行查询多个数据库"""

    # 解析输入参数
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"参数 JSON 解析失败: {e}"
            }), file=sys.stderr)
            sys.exit(1)

    # 验证必需参数
    query = params.get('query') or params.get('keywords')
    if not query:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: query 或 keywords"
        }), file=sys.stderr)
        sys.exit(1)

    # 可选参数
    databases = params.get('databases', ['arxiv', 'pubmed'])
    max_results_per_db = params.get('max_results', 10)
    sort_by = params.get('sort_by', 'date')  # date 或 relevance

    # 初始化 Recipe Runner
    runner = RecipeRunner()

    # 并行查询多个数据库
    print(f"🔍 开始在 {len(databases)} 个数据库中搜索: {', '.join(databases)}", file=sys.stderr)

    all_papers = []
    database_stats = {}

    with ThreadPoolExecutor(max_workers=len(databases)) as executor:
        # 提交所有查询任务
        future_to_db = {
            executor.submit(search_database, db, query, max_results_per_db, runner): db
            for db in databases
        }

        # 收集结果
        for future in as_completed(future_to_db):
            db_name = future_to_db[future]
            try:
                result = future.result()

                if result.get('success'):
                    papers = result.get('papers', [])
                    all_papers.extend(papers)
                    database_stats[db_name] = {
                        'success': True,
                        'count': len(papers)
                    }
                    print(f"✅ {db_name}: {len(papers)} 篇论文", file=sys.stderr)
                else:
                    database_stats[db_name] = {
                        'success': False,
                        'error': result.get('error')
                    }
                    print(f"❌ {db_name}: 查询失败", file=sys.stderr)

            except Exception as e:
                database_stats[db_name] = {
                    'success': False,
                    'error': str(e)
                }
                print(f"❌ {db_name}: 执行异常 - {e}", file=sys.stderr)

    # 统一日期格式
    for paper in all_papers:
        paper['published_normalized'] = normalize_date(
            paper.get('published', ''),
            paper.get('source', '')
        )

    # 排序结果
    if sort_by == 'date':
        all_papers.sort(key=lambda p: p.get('published_normalized', ''), reverse=True)
    # relevance 排序保持原始顺序（API 已按相关性排序）

    # 返回汇总结果
    output = {
        'success': True,
        'workflow': 'search_academic_papers',
        'query': query,
        'databases_queried': databases,
        'total_papers': len(all_papers),
        'database_stats': database_stats,
        'papers': all_papers
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
