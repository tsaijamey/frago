#!/usr/bin/env python3
"""
Recipe: arxiv_search_papers
Platform: arXiv
Description: 在 arXiv 学术数据库中搜索论文
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET


def search_arxiv(query: str, max_results: int = 10) -> dict:
    """
    在 arXiv 中搜索论文

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数

    Returns:
        包含论文列表的字典
    """
    try:
        # 构建查询 URL
        base_url = 'http://export.arxiv.org/api/query?'
        params = {
            'search_query': f'all:{query}',
            'start': 0,
            'max_results': max_results,
            'sortBy': 'relevance',
            'sortOrder': 'descending'
        }
        url = base_url + urllib.parse.urlencode(params)

        # 发起请求
        with urllib.request.urlopen(url, timeout=15) as response:
            data = response.read().decode('utf-8')

        # 解析 XML
        root = ET.fromstring(data)
        ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}

        papers = []
        for entry in root.findall('atom:entry', ns):
            # 提取基本信息
            title_elem = entry.find('atom:title', ns)
            published_elem = entry.find('atom:published', ns)
            summary_elem = entry.find('atom:summary', ns)
            authors = entry.findall('atom:author', ns)
            link_elem = entry.find('atom:id', ns)

            # 提取分类信息
            primary_category = entry.find('arxiv:primary_category', ns)
            categories = entry.findall('atom:category', ns)

            paper = {
                'title': title_elem.text.strip().replace('\n', ' ') if title_elem is not None else 'N/A',
                'authors': [
                    a.find('atom:name', ns).text
                    for a in authors
                    if a.find('atom:name', ns) is not None
                ],
                'published': published_elem.text[:10] if published_elem is not None else 'N/A',  # YYYY-MM-DD
                'abstract': summary_elem.text.strip().replace('\n', ' ')[:300] + '...' if summary_elem is not None else 'N/A',
                'url': link_elem.text if link_elem is not None else 'N/A',
                'source': 'arXiv',
                'primary_category': primary_category.get('term') if primary_category is not None else 'N/A',
                'categories': [c.get('term') for c in categories if c.get('term')]
            }
            papers.append(paper)

        return {
            'success': True,
            'source': 'arXiv',
            'query': query,
            'total': len(papers),
            'papers': papers
        }

    except Exception as e:
        return {
            'success': False,
            'source': 'arXiv',
            'query': query,
            'error': {
                'type': type(e).__name__,
                'message': str(e)
            }
        }


def main():
    """主函数：解析参数并执行搜索"""

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

    max_results = params.get('max_results', 10)

    # 执行搜索
    result = search_arxiv(query, max_results)

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 设置退出码
    sys.exit(0 if result['success'] else 1)


if __name__ == "__main__":
    main()
