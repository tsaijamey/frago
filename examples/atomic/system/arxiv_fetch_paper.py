#!/usr/bin/env python3
"""
Recipe: arxiv_fetch_paper
Platform: arXiv
Description: 直接下载 arXiv 论文 PDF（最稳健的方式）
Created: 2025-11-25
Version: 2.0.0
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path


def extract_arxiv_id(identifier: str) -> str:
    """
    从各种格式中提取 arXiv ID

    支持格式:
    - 纯 ID: 2411.12345, hep-th/0601001
    - URL: http://arxiv.org/abs/2411.12345
    - PDF URL: https://arxiv.org/pdf/2411.12345.pdf

    Args:
        identifier: arXiv 论文标识符

    Returns:
        标准化的 arXiv ID
    """
    # 移除 URL 前缀
    if 'arxiv.org' in identifier:
        # 匹配 abs/xxx 或 pdf/xxx
        match = re.search(r'(?:abs|pdf)/([^/\s]+?)(?:\.pdf)?$', identifier)
        if match:
            return match.group(1)

    # 直接是 ID 格式
    # 新格式: YYMM.NNNNN (如 2411.12345)
    # 旧格式: category/YYMMNNN (如 hep-th/0601001)
    if re.match(r'^(\d{4}\.\d{4,5}|[a-z-]+/\d{7})$', identifier):
        return identifier

    return identifier


def download_pdf(arxiv_id: str, output_dir: str) -> dict:
    """
    直接下载 arXiv PDF

    这是最稳健的下载方式，无需 API 调用，直接通过 URL 获取 PDF。

    Args:
        arxiv_id: arXiv ID
        output_dir: 输出目录

    Returns:
        下载结果字典
    """
    pdf_url = f'https://arxiv.org/pdf/{arxiv_id}.pdf'

    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 生成安全的文件名（旧格式 ID 中的 / 替换为 _）
    safe_id = arxiv_id.replace('/', '_')
    file_path = output_path / f'{safe_id}.pdf'

    # 下载 PDF
    req = urllib.request.Request(pdf_url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Frago/1.0; academic-research)'
    })

    with urllib.request.urlopen(req, timeout=60) as response:
        content = response.read()

    # 验证 PDF 格式
    if not content.startswith(b'%PDF'):
        raise ValueError(f'下载的内容不是有效的 PDF 文件')

    with open(file_path, 'wb') as f:
        f.write(content)

    return {
        'format': 'pdf',
        'file_path': str(file_path),
        'file_size': len(content),
        'file_size_mb': round(len(content) / 1024 / 1024, 2),
        'url': pdf_url
    }


def fetch_paper(identifier: str, output_dir: str = '.') -> dict:
    """
    获取 arXiv 论文 PDF

    Args:
        identifier: arXiv 论文标识符（ID 或 URL）
        output_dir: 输出目录

    Returns:
        获取结果
    """
    try:
        # 提取 ID
        arxiv_id = extract_arxiv_id(identifier)

        # 直接下载 PDF
        content = download_pdf(arxiv_id, output_dir)

        return {
            'success': True,
            'source': 'arXiv',
            'arxiv_id': arxiv_id,
            'content': content
        }

    except urllib.error.HTTPError as e:
        return {
            'success': False,
            'error': {
                'type': 'HTTPError',
                'code': e.code,
                'message': f'HTTP {e.code}: {e.reason}'
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'type': type(e).__name__,
                'message': str(e)
            }
        }


def main():
    """主函数：解析参数并执行下载"""

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
    identifier = params.get('identifier') or params.get('url') or params.get('arxiv_id')
    if not identifier:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: identifier, url 或 arxiv_id"
        }), file=sys.stderr)
        sys.exit(1)

    output_dir = params.get('output_dir', '.')

    # 执行下载
    result = fetch_paper(identifier, output_dir)

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 设置退出码
    sys.exit(0 if result['success'] else 1)


if __name__ == "__main__":
    main()
