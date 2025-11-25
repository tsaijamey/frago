#!/usr/bin/env python3
"""
Workflow: fetch_academic_paper
Description: 统一论文获取接口，根据来源自动选择合适的 Atomic Recipe
Created: 2025-11-25
Version: 2.0.0
"""

import json
import re
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# 如果不在 frago 环境中运行，需要手动导入
try:
    from frago.recipes import RecipeRunner, RecipeExecutionError
except ImportError:
    # 回退方案：直接调用脚本文件
    import subprocess

    class RecipeRunner:
        def run(self, recipe_name: str, params: dict) -> dict:
            """简单的 Recipe 执行器（回退方案）"""
            # 尝试多个可能的路径
            possible_paths = [
                Path(__file__).parent.parent / "atomic" / "system" / f"{recipe_name}.py",
                Path(__file__).parent.parent / "examples" / "atomic" / "system" / f"{recipe_name}.py",
            ]

            script_path = None
            for path in possible_paths:
                if path.exists():
                    script_path = path
                    break

            if not script_path:
                raise FileNotFoundError(f"Recipe not found: {recipe_name}")

            try:
                result = subprocess.run(
                    ["python3", str(script_path), json.dumps(params)],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.stdout:
                    return {"success": True, "data": json.loads(result.stdout)}
                else:
                    return {"success": False, "error": result.stderr or "No output"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    class RecipeExecutionError(Exception):
        def __init__(self, recipe_name, runtime, exit_code, stderr):
            self.recipe_name = recipe_name
            self.runtime = runtime
            self.exit_code = exit_code
            self.stderr = stderr


def detect_source(identifier: str) -> str:
    """
    检测论文来源

    Args:
        identifier: 论文标识符（URL 或 ID）

    Returns:
        来源类型: 'arxiv', 'pubmed', 'pmc', 或 'unknown'
    """
    identifier_lower = identifier.lower()

    # arXiv
    if 'arxiv.org' in identifier_lower:
        return 'arxiv'
    if re.match(r'^\d{4}\.\d{4,5}$', identifier):  # 新格式 ID
        return 'arxiv'
    if re.match(r'^[a-z-]+/\d{7}$', identifier_lower):  # 旧格式 ID
        return 'arxiv'

    # PMC - 支持新旧两种 URL 格式
    # 旧格式: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/
    # 新格式: https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/
    if 'pmc' in identifier_lower and 'articles/pmc' in identifier_lower:
        return 'pmc'
    if re.match(r'^PMC\d+$', identifier, re.IGNORECASE):
        return 'pmc'

    # PubMed
    if 'pubmed.ncbi.nlm.nih.gov' in identifier_lower:
        return 'pubmed'
    if re.match(r'^\d{7,8}$', identifier):  # 7-8位数字可能是 PMID
        return 'pubmed'

    return 'unknown'


def fetch_single_paper(identifier: str, output_dir: str, runner: RecipeRunner, delay: float = 0) -> dict:
    """
    获取单篇论文

    Args:
        identifier: 论文标识符
        output_dir: 输出目录
        runner: Recipe 执行器
        delay: 请求延迟（秒）

    Returns:
        获取结果
    """
    # 添加延迟（批量下载时避免限流）
    if delay > 0:
        time.sleep(delay)

    source = detect_source(identifier)

    if source == 'unknown':
        return {
            'success': False,
            'identifier': identifier,
            'error': f'无法识别论文来源: {identifier}'
        }

    # 选择合适的 Recipe
    if source == 'arxiv':
        recipe_name = 'arxiv_fetch_paper'
        # arXiv 使用直接 PDF 下载，不需要 formats 参数
        params = {
            'identifier': identifier,
            'output_dir': output_dir
        }
    else:  # pubmed 或 pmc
        recipe_name = 'pubmed_fetch_paper'
        params = {
            'identifier': identifier,
            'output_dir': output_dir,
            'formats': ['pdf', 'xml', 'abstract']
        }

    print(f"📥 正在获取: {identifier} (来源: {source})", file=sys.stderr)

    try:
        result = runner.run(recipe_name, params=params)

        # 处理 RecipeRunner 返回的嵌套结构
        if result.get('success') and result.get('data'):
            inner_data = result['data']
            inner_data['detected_source'] = source
            inner_data['recipe_used'] = recipe_name
            return inner_data
        elif result.get('success') and 'content' in result:
            # 直接返回的结果
            result['detected_source'] = source
            result['recipe_used'] = recipe_name
            return result
        else:
            return {
                'success': False,
                'identifier': identifier,
                'detected_source': source,
                'error': result.get('error', 'Unknown error')
            }

    except Exception as e:
        return {
            'success': False,
            'identifier': identifier,
            'detected_source': source,
            'error': {
                'type': type(e).__name__,
                'message': str(e)
            }
        }


def main():
    """主函数：统一论文获取入口"""

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

    # 支持单个或多个论文
    identifiers = params.get('identifiers') or params.get('papers') or []

    # 也支持单个 identifier 参数
    single_id = params.get('identifier') or params.get('url')
    if single_id:
        identifiers = [single_id]

    if not identifiers:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: identifiers, papers, identifier 或 url"
        }), file=sys.stderr)
        sys.exit(1)

    # 其他参数
    output_dir = params.get('output_dir', './papers')
    parallel = params.get('parallel', False)  # 默认串行，避免触发限流
    max_workers = params.get('max_workers', 2)
    delay = params.get('delay', 3.0)  # 默认 3 秒延迟

    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 初始化 Recipe Runner
    runner = RecipeRunner()

    print(f"📚 准备获取 {len(identifiers)} 篇论文", file=sys.stderr)
    print(f"📁 输出目录: {output_dir}", file=sys.stderr)
    if not parallel:
        print(f"⏱️  请求间隔: {delay}s", file=sys.stderr)

    results = []
    stats = {
        'total': len(identifiers),
        'success': 0,
        'failed': 0,
        'sources': {}
    }

    if parallel and len(identifiers) > 1:
        # 并行获取（注意：可能触发限流）
        print("⚠️  并行模式：可能触发 arXiv 限流", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(fetch_single_paper, id_, output_dir, runner, 0): id_
                for id_ in identifiers
            }

            for future in as_completed(future_to_id):
                paper_id = future_to_id[future]
                try:
                    result = future.result()
                    results.append(result)

                    if result.get('success'):
                        stats['success'] += 1
                        source = result.get('detected_source', 'unknown')
                        stats['sources'][source] = stats['sources'].get(source, 0) + 1
                        file_size = result.get('content', {}).get('file_size_mb', '?')
                        print(f"✅ 成功: {paper_id} ({file_size} MB)", file=sys.stderr)
                    else:
                        stats['failed'] += 1
                        print(f"❌ 失败: {paper_id}", file=sys.stderr)

                except Exception as e:
                    stats['failed'] += 1
                    results.append({
                        'success': False,
                        'identifier': paper_id,
                        'error': str(e)
                    })
                    print(f"❌ 异常: {paper_id} - {e}", file=sys.stderr)
    else:
        # 串行获取（推荐，避免限流）
        for i, id_ in enumerate(identifiers):
            # 第一个不需要延迟
            actual_delay = delay if i > 0 else 0
            result = fetch_single_paper(id_, output_dir, runner, actual_delay)
            results.append(result)

            if result.get('success'):
                stats['success'] += 1
                source = result.get('detected_source', 'unknown')
                stats['sources'][source] = stats['sources'].get(source, 0) + 1
                file_size = result.get('content', {}).get('file_size_mb', '?')
                print(f"✅ 成功: {id_} ({file_size} MB)", file=sys.stderr)
            else:
                stats['failed'] += 1
                error_msg = result.get('error', {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get('message', 'Unknown error')
                print(f"❌ 失败: {id_} - {error_msg}", file=sys.stderr)

    # 输出结果
    output = {
        'success': stats['failed'] == 0,
        'workflow': 'fetch_academic_paper',
        'output_dir': output_dir,
        'stats': stats,
        'results': results
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    # 至少有一个成功就返回 0
    sys.exit(0 if stats['success'] > 0 else 1)


if __name__ == "__main__":
    main()
