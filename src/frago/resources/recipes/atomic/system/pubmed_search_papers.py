#!/usr/bin/env python3
"""
Recipe: pubmed_search_papers
Platform: PubMed
Description: 在 PubMed 生物医学数据库中搜索论文
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
import urllib.request
import urllib.parse


def search_pubmed(query: str, max_results: int = 10) -> dict:
    """
    在 PubMed 中搜索论文

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数

    Returns:
        包含论文列表的字典
    """
    try:
        # Step 1: 搜索获取 PMID 列表
        search_base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?'
        search_params = {
            'db': 'pubmed',
            'term': query,
            'retmax': max_results,
            'retmode': 'json',
            'sort': 'relevance'
        }
        search_url = search_base + urllib.parse.urlencode(search_params)

        with urllib.request.urlopen(search_url, timeout=15) as response:
            search_data = json.loads(response.read().decode('utf-8'))

        id_list = search_data.get('esearchresult', {}).get('idlist', [])

        if not id_list:
            return {
                'success': True,
                'source': 'PubMed',
                'query': query,
                'total': 0,
                'papers': []
            }

        # Step 2: 获取详细信息
        fetch_base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?'
        fetch_params = {
            'db': 'pubmed',
            'id': ','.join(id_list),
            'retmode': 'json'
        }
        fetch_url = fetch_base + urllib.parse.urlencode(fetch_params)

        with urllib.request.urlopen(fetch_url, timeout=15) as response:
            details_data = json.loads(response.read().decode('utf-8'))

        # 解析论文信息
        papers = []
        for pmid in id_list:
            paper_data = details_data.get('result', {}).get(pmid, {})

            # 提取作者列表（限制前10个）
            authors_data = paper_data.get('authors', [])
            authors = [a.get('name', 'N/A') for a in authors_data[:10]]

            # 提取发表日期
            pubdate = paper_data.get('pubdate', 'N/A')

            # 提取期刊信息
            source = paper_data.get('source', 'N/A')
            fulljournalname = paper_data.get('fulljournalname', source)

            paper = {
                'title': paper_data.get('title', 'N/A'),
                'authors': authors,
                'published': pubdate,
                'abstract': 'N/A',  # E-utilities esummary 不返回摘要，需要 efetch
                'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                'source': 'PubMed',
                'pmid': pmid,
                'journal': fulljournalname,
                'pub_type': paper_data.get('pubtype', [])
            }
            papers.append(paper)

        return {
            'success': True,
            'source': 'PubMed',
            'query': query,
            'total': len(papers),
            'papers': papers
        }

    except Exception as e:
        return {
            'success': False,
            'source': 'PubMed',
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
    result = search_pubmed(query, max_results)

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 设置退出码
    sys.exit(0 if result['success'] else 1)


if __name__ == "__main__":
    main()
