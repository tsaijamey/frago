#!/usr/bin/env python3
"""
Recipe: upwork_batch_extract
Type: workflow
Description: 批量提取多个 Upwork 职位信息，生成汇总文档
Created: 2025-11-21
Version: 1
"""

import json
import sys
import time
from pathlib import Path

# 从 Frago 包导入 RecipeRunner
from frago.recipes import RecipeRunner, RecipeExecutionError


def main():
    """主函数：批量提取 Upwork 职位信息"""

    # 解析输入参数
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "缺少参数：需要提供 JSON 格式的参数",
            "usage": "upwork_batch_extract.py '{\"urls\": [\"url1\", \"url2\"], \"output_dir\": \"./jobs/\"}'"
        }))
        sys.exit(1)

    try:
        params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({
            "success": False,
            "error": f"参数 JSON 解析失败: {e}"
        }))
        sys.exit(1)

    # 验证参数
    if "urls" not in params or not isinstance(params["urls"], list):
        print(json.dumps({
            "success": False,
            "error": "参数缺少 'urls' 字段，或 'urls' 不是数组"
        }))
        sys.exit(1)

    urls = params["urls"]
    output_dir = Path(params.get("output_dir", "./jobs/"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化 RecipeRunner
    runner = RecipeRunner()

    # 批量提取结果
    results = []
    successful = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        print(f"处理第 {idx}/{len(urls)} 个职位: {url}", file=sys.stderr)

        try:
            # 1. 导航到 URL（使用 frago navigate 命令）
            import subprocess
            nav_result = subprocess.run(
                ["uv", "run", "frago", "navigate", url],
                capture_output=True,
                text=True,
                timeout=30
            )

            if nav_result.returncode != 0:
                raise Exception(f"导航失败: {nav_result.stderr}")

            # 2. 等待页面加载
            time.sleep(3)

            # 3. 调用原子 Recipe 提取职位信息
            result = runner.run(
                name="upwork_extract_job_details_as_markdown",
                params={},
                output_target="stdout"
            )

            if not result["success"]:
                raise Exception(f"Recipe 执行失败: {result['error']}")

            # 4. 保存结果到文件
            job_id = url.split("/")[-1].replace("~", "")
            output_file = output_dir / f"job_{job_id}.md"

            # 从返回数据中提取 markdown 文本
            markdown_text = result["data"]
            if isinstance(markdown_text, dict):
                markdown_text = markdown_text.get("result", str(markdown_text))

            output_file.write_text(markdown_text, encoding="utf-8")

            results.append({
                "url": url,
                "status": "success",
                "output_file": str(output_file),
                "execution_time": result["execution_time"]
            })
            successful += 1

            print(f"✓ 成功提取并保存到: {output_file}", file=sys.stderr)

        except RecipeExecutionError as e:
            results.append({
                "url": url,
                "status": "failed",
                "error": str(e),
                "error_type": "RecipeExecutionError"
            })
            failed += 1
            print(f"✗ 提取失败: {e}", file=sys.stderr)

        except Exception as e:
            results.append({
                "url": url,
                "status": "failed",
                "error": str(e),
                "error_type": type(e).__name__
            })
            failed += 1
            print(f"✗ 处理失败: {e}", file=sys.stderr)

    # 输出汇总结果（JSON 格式）
    summary = {
        "success": failed == 0,
        "total": len(urls),
        "successful": successful,
        "failed": failed,
        "results": results,
        "output_dir": str(output_dir)
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # 如果有失败的任务，返回非零退出码
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
