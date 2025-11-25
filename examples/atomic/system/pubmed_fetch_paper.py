#!/usr/bin/env python3
"""
Recipe: pubmed_fetch_paper
Platform: PubMed/PMC
Description: 从 PubMed/PMC 获取论文内容（PDF/XML全文/摘要）
Created: 2025-11-25
Version: 1.1.0
"""

import json
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path


def extract_pmid(identifier: str) -> str:
    """
    从各种格式中提取 PMID 或 PMCID

    支持格式:
    - 纯 PMID: 12345678
    - 纯 PMCID: PMC1234567
    - PubMed URL: https://pubmed.ncbi.nlm.nih.gov/12345678/
    - PMC URL (旧): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/
    - PMC URL (新): https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/

    Args:
        identifier: PubMed 论文标识符

    Returns:
        PMID 或 PMCID（带 PMC 前缀）
    """
    # PMC URL - 支持新旧两种格式
    # 旧格式: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/
    # 新格式: https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/
    if 'pmc' in identifier.lower() and 'articles/PMC' in identifier:
        match = re.search(r'PMC(\d+)', identifier, re.IGNORECASE)
        if match:
            return f'PMC{match.group(1)}'

    # PubMed URL
    if 'pubmed.ncbi.nlm.nih.gov' in identifier:
        match = re.search(r'/(\d+)/?', identifier)
        if match:
            return match.group(1)

    # 纯数字 PMID
    if re.match(r'^\d+$', identifier):
        return identifier

    # PMC ID (直接输入)
    if re.match(r'^PMC\d+$', identifier, re.IGNORECASE):
        return identifier.upper()

    return identifier


def get_pmcid_from_pmid(pmid: str) -> str:
    """
    从 PMID 获取 PMCID

    Args:
        pmid: PubMed ID

    Returns:
        PMCID 或 None
    """
    url = f'https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json'

    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))

        records = data.get('records', [])
        if records and 'pmcid' in records[0]:
            return records[0]['pmcid']
        return None
    except:
        return None


def get_paper_metadata_efetch(pmid: str) -> dict:
    """
    使用 E-utilities efetch 获取论文元数据和摘要

    Args:
        pmid: PubMed ID

    Returns:
        包含元数据的字典
    """
    url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml'

    with urllib.request.urlopen(url, timeout=15) as response:
        data = response.read().decode('utf-8')

    root = ET.fromstring(data)
    article = root.find('.//PubmedArticle')
    if article is None:
        return None

    # 提取标题
    title_elem = article.find('.//ArticleTitle')
    title = title_elem.text if title_elem is not None else 'N/A'

    # 提取作者
    authors = []
    for author in article.findall('.//Author'):
        lastname = author.find('LastName')
        forename = author.find('ForeName')
        if lastname is not None:
            name = lastname.text
            if forename is not None:
                name = f"{forename.text} {name}"
            authors.append(name)

    # 提取摘要
    abstract_texts = []
    for abstract_text in article.findall('.//AbstractText'):
        label = abstract_text.get('Label', '')
        text = ''.join(abstract_text.itertext())
        if label:
            abstract_texts.append(f"{label}: {text}")
        else:
            abstract_texts.append(text)
    abstract = ' '.join(abstract_texts) if abstract_texts else 'N/A'

    # 提取发表日期
    pub_date = article.find('.//PubDate')
    if pub_date is not None:
        year = pub_date.find('Year')
        month = pub_date.find('Month')
        day = pub_date.find('Day')
        date_parts = []
        if year is not None:
            date_parts.append(year.text)
        if month is not None:
            date_parts.append(month.text)
        if day is not None:
            date_parts.append(day.text)
        published = '-'.join(date_parts) if date_parts else 'N/A'
    else:
        published = 'N/A'

    # 提取期刊
    journal_elem = article.find('.//Journal/Title')
    journal = journal_elem.text if journal_elem is not None else 'N/A'

    # 提取 DOI
    doi_elem = article.find('.//ArticleId[@IdType="doi"]')
    doi = doi_elem.text if doi_elem is not None else None

    # 提取 PMCID
    pmcid_elem = article.find('.//ArticleId[@IdType="pmc"]')
    pmcid = pmcid_elem.text if pmcid_elem is not None else None

    return {
        'pmid': pmid,
        'pmcid': pmcid,
        'title': title,
        'authors': authors,
        'abstract': abstract,
        'published': published,
        'journal': journal,
        'doi': doi,
        'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
        'pmc_url': f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/' if pmcid else None
    }


def check_pmc_availability(pmcid: str) -> dict:
    """
    检查 PMC 文章的可用格式

    Args:
        pmcid: PMC ID

    Returns:
        可用格式信息
    """
    url = f'https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}'

    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = response.read().decode('utf-8')

        root = ET.fromstring(data)

        # 检查是否在 OA 子集中
        error = root.find('.//error')
        if error is not None:
            return {'available': False, 'reason': error.text}

        # 获取可用链接
        links = {}
        for link in root.findall('.//link'):
            format_type = link.get('format', 'unknown')
            href = link.get('href', '')
            links[format_type] = href

        return {
            'available': True,
            'formats': links
        }
    except Exception as e:
        return {'available': False, 'reason': str(e)}


def download_pmc_pdf(pmcid: str, output_dir: str) -> dict:
    """
    从 PMC 下载 PDF

    Args:
        pmcid: PMC ID
        output_dir: 输出目录

    Returns:
        下载结果
    """
    # 检查可用性
    availability = check_pmc_availability(pmcid)
    if not availability.get('available'):
        raise Exception(f"PMC 文章不可用: {availability.get('reason')}")

    formats = availability.get('formats', {})
    pdf_url = formats.get('pdf')

    if not pdf_url:
        raise Exception("PDF 格式不可用")

    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f'{pmcid}.pdf'

    req = urllib.request.Request(pdf_url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Frago/1.0; +https://github.com/user/frago)'
    })

    with urllib.request.urlopen(req, timeout=60) as response:
        content = response.read()

    with open(file_path, 'wb') as f:
        f.write(content)

    return {
        'format': 'pdf',
        'file_path': str(file_path),
        'file_size': len(content),
        'url': pdf_url
    }


def download_pmc_xml(pmcid: str, output_dir: str) -> dict:
    """
    从 PMC 下载 XML 全文

    Args:
        pmcid: PMC ID
        output_dir: 输出目录

    Returns:
        下载结果
    """
    # 使用 BioC API 获取 XML
    url = f'https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode'

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f'{pmcid}.xml'

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Frago/1.0; +https://github.com/user/frago)'
    })

    with urllib.request.urlopen(req, timeout=60) as response:
        content = response.read()

    # 检查是否获取成功
    if b'error' in content.lower()[:100]:
        raise Exception("XML 全文不可用")

    with open(file_path, 'wb') as f:
        f.write(content)

    return {
        'format': 'xml',
        'file_path': str(file_path),
        'file_size': len(content),
        'url': url
    }


def fetch_paper(identifier: str, output_dir: str = '.', formats: list = None) -> dict:
    """
    获取论文内容

    Args:
        identifier: PubMed 论文标识符（PMID, PMCID 或 URL）
        output_dir: 输出目录
        formats: 希望获取的格式列表，按优先级排序，默认 ['pdf', 'xml', 'abstract']

    Returns:
        获取结果
    """
    if formats is None:
        formats = ['pdf', 'xml', 'abstract']

    try:
        # 提取 ID
        paper_id = extract_pmid(identifier)

        # 判断是 PMID 还是 PMCID
        if paper_id.startswith('PMC'):
            pmcid = paper_id
            # 暂时无法反向获取 PMID，跳过详细元数据
            metadata = {
                'pmcid': pmcid,
                'url': f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/'
            }
        else:
            pmid = paper_id
            # 获取元数据
            metadata = get_paper_metadata_efetch(pmid)
            if metadata is None:
                return {
                    'success': False,
                    'error': f'未找到论文: {identifier}'
                }
            pmcid = metadata.get('pmcid')

        result = {
            'success': True,
            'source': 'PubMed',
            'metadata': metadata,
            'content': None
        }

        # 按优先级尝试获取内容
        for fmt in formats:
            try:
                if fmt == 'pdf' and pmcid:
                    content = download_pmc_pdf(pmcid, output_dir)
                    result['content'] = content
                    break
                elif fmt == 'xml' and pmcid:
                    content = download_pmc_xml(pmcid, output_dir)
                    result['content'] = content
                    break
                elif fmt == 'abstract':
                    # 摘要已在 metadata 中
                    abstract = metadata.get('abstract', 'N/A')
                    if abstract and abstract != 'N/A':
                        result['content'] = {
                            'format': 'abstract',
                            'text': abstract
                        }
                        break
            except Exception as e:
                # 当前格式失败，尝试下一个
                continue

        if result['content'] is None:
            # 如果没有 PMCID，说明论文不在 PMC 中
            if not pmcid:
                result['content'] = {
                    'format': 'abstract',
                    'text': metadata.get('abstract', 'N/A'),
                    'note': '论文不在 PMC Open Access 子集中，仅返回摘要'
                }
            else:
                result['success'] = False
                result['error'] = '无法获取任何格式的论文内容'

        return result

    except Exception as e:
        return {
            'success': False,
            'error': {
                'type': type(e).__name__,
                'message': str(e)
            }
        }


def main():
    """主函数：解析参数并执行获取"""

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
    identifier = params.get('identifier') or params.get('url') or params.get('pmid')
    if not identifier:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: identifier, url 或 pmid"
        }), file=sys.stderr)
        sys.exit(1)

    output_dir = params.get('output_dir', '.')
    formats = params.get('formats', ['pdf', 'xml', 'abstract'])

    # 执行获取
    result = fetch_paper(identifier, output_dir, formats)

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 设置退出码
    sys.exit(0 if result['success'] else 1)


if __name__ == "__main__":
    main()
