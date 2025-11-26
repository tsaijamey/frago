#!/usr/bin/env python3
"""
Recipe: project_specific_task
Type: workflow
Description: 项目专属任务示例 - 演示项目级 Recipe 的使用
Created: 2025-11-21
Version: 1
"""

import json
import sys
from pathlib import Path


def main():
    """主函数：执行项目专属任务"""

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
            }))
            sys.exit(1)

    # 获取项目名称
    project_name = params.get("project_name")
    if not project_name:
        # 使用当前目录名作为项目名称
        project_name = Path.cwd().name

    # 检查是否在项目级环境中
    project_recipe_dir = Path.cwd() / '.frago' / 'recipes'
    is_project_level = project_recipe_dir.exists()

    # 收集项目信息
    project_info = {
        "name": project_name,
        "cwd": str(Path.cwd()),
        "recipe_source": "Project" if is_project_level else "User or Example",
        "has_project_recipes": is_project_level
    }

    if is_project_level:
        # 统计项目 Recipe 数量
        recipe_count = 0
        for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
            dir_path = project_recipe_dir / subdir
            if dir_path.exists():
                recipe_count += len(list(dir_path.glob('*.md')))

        project_info["project_recipe_count"] = recipe_count

    # 输出结果
    result = {
        "success": True,
        "message": f"项目任务执行成功: {project_name}",
        "project_info": project_info
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
