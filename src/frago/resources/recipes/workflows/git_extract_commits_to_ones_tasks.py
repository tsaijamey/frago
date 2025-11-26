#!/usr/bin/env python3
"""
Workflow: git_extract_commits_to_ones_tasks
Description: 从 Git 日志提取 commit 信息，生成 ONES 任务 Markdown 文档
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


def parse_conventional_commit(commit_message: str) -> Dict[str, Any]:
    """
    解析 Conventional Commits 格式的 commit message

    格式: <type>(<scope>): <description>

    Body (可选)

    Footer (可选)
    """
    lines = commit_message.strip().split('\n')
    first_line = lines[0]

    # 正则匹配: type(scope): description 或 type: description
    pattern = r'^(\w+)(?:\(([^)]+)\))?: (.+)$'
    match = re.match(pattern, first_line)

    if match:
        commit_type = match.group(1)
        scope = match.group(2) or ""
        description = match.group(3)
    else:
        # 不符合 Conventional Commits 格式，整行作为 description
        commit_type = "unknown"
        scope = ""
        description = first_line

    # 提取 body 和 footer
    body_lines = []
    footer_lines = []
    in_footer = False

    for i, line in enumerate(lines[1:], 1):
        # 检测 footer 关键字
        if re.match(r'^(Closes|Fixes|Resolves|Ref|Related to|Depends on|Blocked by|BREAKING CHANGE):', line):
            in_footer = True

        if in_footer:
            footer_lines.append(line)
        elif line.strip():  # 忽略空行
            body_lines.append(line)

    body = '\n'.join(body_lines).strip()
    footer = '\n'.join(footer_lines).strip()

    # 提取关联 issue
    linked_issues = []
    dependencies = []

    for footer_line in footer_lines:
        # Closes #123, Fixes #456
        if re.match(r'^(Closes|Fixes|Resolves|Ref|Related to):', footer_line):
            issues = re.findall(r'#(\d+)', footer_line)
            linked_issues.extend(issues)

        # Depends on #789, Blocked by #101
        if re.match(r'^(Depends on|Blocked by):', footer_line):
            deps = re.findall(r'#(\d+)', footer_line)
            dependencies.extend(deps)

    return {
        'type': commit_type,
        'scope': scope,
        'description': description,
        'body': body,
        'footer': footer,
        'linked_issues': list(set(linked_issues)),
        'dependencies': list(set(dependencies))
    }


def map_commit_type_to_issue_type(commit_type: str) -> str:
    """将 Git commit type 映射到 ONES Issue type"""
    mapping = {
        'feat': 'Task',
        'fix': 'Bug',
        'docs': 'Task',
        'refactor': 'Task',
        'test': 'Task',
        'chore': 'Task',
        'style': 'Task',
        'perf': 'Task',
        'ci': 'Task',
        'build': 'Task'
    }
    return mapping.get(commit_type.lower(), 'Task')


def map_commit_type_to_category(commit_type: str) -> str:
    """将 Git commit type 映射到任务类型"""
    mapping = {
        'feat': '新功能开发',
        'fix': '问题修复',
        'refactor': '代码重构',
        'docs': '文档更新',
        'test': '测试',
        'chore': '杂务',
        'style': '代码格式',
        'perf': '性能优化',
        'ci': 'CI/CD',
        'build': '构建'
    }
    return mapping.get(commit_type.lower(), '其他')


def estimate_hours_from_stats(lines_added: int, lines_deleted: int) -> float:
    """根据代码行数估算工时（简单规则）"""
    total_lines = lines_added + lines_deleted

    if total_lines < 50:
        return 0.5
    elif total_lines < 200:
        return 2.0
    elif total_lines < 500:
        return 4.0
    else:
        return 8.0


def infer_module_from_files(files_changed: List[str]) -> str:
    """从修改的文件路径推断模块"""
    # 简单规则：取第一个文件的顶层目录
    if not files_changed:
        return "未知"

    first_file = files_changed[0]
    parts = first_file.split('/')

    if len(parts) > 1:
        return parts[0]

    return "根目录"


def load_author_mapping(mapping_file: Optional[str]) -> Dict[str, str]:
    """加载作者映射表"""
    if not mapping_file or not Path(mapping_file).exists():
        return {}

    try:
        import yaml
        with open(mapping_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get('author_mapping', {})
    except ImportError:
        # 如果没有 yaml 库，使用 json 格式
        with open(mapping_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('author_mapping', {})


def extract_commits_from_git(project_path: str, commit_range: str) -> List[Dict[str, Any]]:
    """从 Git 仓库提取 commit 信息"""
    try:
        # 切换到项目目录
        original_cwd = Path.cwd()
        Path(project_path).resolve()

        # 提取 commit 基本信息
        cmd = [
            'git', 'log',
            '--pretty=format:%H|%an|%ae|%ad|%s',
            '--date=iso',
            '--no-merges',
            commit_range
        ]

        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )

        commits = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split('|')
            if len(parts) < 5:
                continue

            commit_hash = parts[0]
            author_name = parts[1]
            author_email = parts[2]
            commit_date = parts[3]
            subject = parts[4]

            # 提取完整 commit message（含 body 和 footer）
            show_result = subprocess.run(
                ['git', 'show', '--stat', '--format=%B', commit_hash],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True
            )

            full_message = show_result.stdout

            # 分离 message 和 stat
            message_lines = []
            stat_lines = []
            in_stat = False

            for msg_line in full_message.split('\n'):
                if re.match(r'^\s+\S+\s+\|\s+\d+', msg_line):  # 文件统计行
                    in_stat = True

                if in_stat:
                    stat_lines.append(msg_line)
                else:
                    message_lines.append(msg_line)

            full_commit_message = '\n'.join(message_lines).strip()

            # 解析 Conventional Commit
            parsed = parse_conventional_commit(full_commit_message)

            # 提取文件变更信息
            files_changed = []
            lines_added = 0
            lines_deleted = 0

            for stat_line in stat_lines:
                file_match = re.match(r'^\s+(\S+)\s+\|\s+(\d+)\s+([+-]+)?', stat_line)
                if file_match:
                    filename = file_match.group(1)
                    changes = int(file_match.group(2))
                    symbols = file_match.group(3) or ''

                    files_changed.append(filename)

                    # 计算增删行数（粗略估计）
                    plus_count = symbols.count('+')
                    minus_count = symbols.count('-')
                    lines_added += plus_count
                    lines_deleted += minus_count

            # 如果没有从符号提取到，尝试从最后的汇总行提取
            summary_match = re.search(r'(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?', '\n'.join(stat_lines))
            if summary_match:
                if summary_match.group(2):
                    lines_added = int(summary_match.group(2))
                if summary_match.group(3):
                    lines_deleted = int(summary_match.group(3))

            commits.append({
                'hash': commit_hash,
                'hash_short': commit_hash[:7],
                'author_name': author_name,
                'author_email': author_email,
                'date': commit_date,
                'subject': subject,
                'type': parsed['type'],
                'scope': parsed['scope'],
                'description': parsed['description'],
                'body': parsed['body'],
                'footer': parsed['footer'],
                'linked_issues': parsed['linked_issues'],
                'dependencies': parsed['dependencies'],
                'files_changed': files_changed,
                'files_count': len(files_changed),
                'lines_added': lines_added,
                'lines_deleted': lines_deleted
            })

        return commits

    except subprocess.CalledProcessError as e:
        raise Exception(f"Git 命令执行失败: {e.stderr}")
    except Exception as e:
        raise Exception(f"提取 commit 失败: {str(e)}")


def generate_task_markdown(commits: List[Dict[str, Any]], author_mapping: Dict[str, str], project_name: str = None) -> str:
    """生成 ONES 任务 Markdown 文档"""

    lines = []
    lines.append("# ONES 任务列表")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 共 {len(commits)} 个任务")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, commit in enumerate(commits, 1):
        lines.append(f"## 任务 {idx}: {commit['description']}")
        lines.append("")

        # 基本信息
        lines.append("### 基本信息")
        lines.append("")
        lines.append(f"- **Title**: {commit['description']}")

        if project_name:
            lines.append(f"- **Project**: {project_name}")

        issue_type = map_commit_type_to_issue_type(commit['type'])
        lines.append(f"- **Issue type**: {issue_type}")

        task_category = map_commit_type_to_category(commit['type'])
        lines.append(f"- **任务类型**: {task_category}")

        # 负责人
        assignee = author_mapping.get(commit['author_email'], commit['author_name'])
        lines.append(f"- **负责人**: {assignee}")

        # 所属模块
        module = commit['scope'] or infer_module_from_files(commit['files_changed'])
        lines.append(f"- **所属模块**: {module}")

        # 预估工时
        estimated_hours = estimate_hours_from_stats(commit['lines_added'], commit['lines_deleted'])
        lines.append(f"- **预估工时**: {estimated_hours} 小时")

        # 当前步骤
        lines.append(f"- **当前步骤**: 已完成")

        lines.append("")

        # 描述
        lines.append("### 描述")
        lines.append("")

        if commit['body']:
            lines.append(commit['body'])
            lines.append("")

        lines.append("#### 技术细节")
        lines.append("")

        lines.append("**修改文件**:")
        if commit['files_changed']:
            for file in commit['files_changed']:
                lines.append(f"- `{file}`")
        else:
            lines.append("- (无)")
        lines.append("")

        lines.append("**变更统计**:")
        lines.append(f"- 新增: {commit['lines_added']} 行")
        lines.append(f"- 删除: {commit['lines_deleted']} 行")
        lines.append(f"- 修改文件数: {commit['files_count']}")
        lines.append("")

        lines.append("**Commit 信息**:")
        lines.append(f"- Hash: `{commit['hash_short']}`")
        lines.append(f"- Author: {commit['author_name']} <{commit['author_email']}>")
        lines.append(f"- Date: {commit['date']}")
        lines.append("")

        # 关联信息
        if commit['linked_issues'] or commit['dependencies']:
            lines.append("### 关联信息")
            lines.append("")

            if commit['linked_issues']:
                lines.append(f"- **关联问题**: {', '.join(['#' + issue for issue in commit['linked_issues']])}")

            if commit['dependencies']:
                lines.append(f"- **依赖/阻塞**: {', '.join(['#' + dep for dep in commit['dependencies']])}")

            lines.append("")

        # Footer（如果有额外信息）
        if commit['footer'] and not (commit['linked_issues'] or commit['dependencies']):
            lines.append("### 备注")
            lines.append("")
            lines.append("```")
            lines.append(commit['footer'])
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    return '\n'.join(lines)


def main():
    """主函数"""

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
    if 'project_path' not in params:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: project_path"
        }), file=sys.stderr)
        sys.exit(1)

    project_path = params['project_path']
    commit_range = params.get('commit_range', 'HEAD~10..HEAD')
    output_file = params.get('output_file', None)
    author_mapping_file = params.get('author_mapping_file', None)
    project_name = params.get('project_name', None)

    # 验证项目路径
    if not Path(project_path).exists():
        print(json.dumps({
            "success": False,
            "error": f"项目路径不存在: {project_path}"
        }), file=sys.stderr)
        sys.exit(1)

    if not Path(project_path, '.git').exists():
        print(json.dumps({
            "success": False,
            "error": f"不是 Git 仓库: {project_path}"
        }), file=sys.stderr)
        sys.exit(1)

    try:
        # 加载作者映射
        author_mapping = load_author_mapping(author_mapping_file)

        # 提取 commits
        print(f"正在从 {project_path} 提取 commit 信息...", file=sys.stderr)
        print(f"Commit 范围: {commit_range}", file=sys.stderr)

        commits = extract_commits_from_git(project_path, commit_range)

        if not commits:
            print(json.dumps({
                "success": False,
                "error": "未找到任何 commit"
            }), file=sys.stderr)
            sys.exit(1)

        print(f"找到 {len(commits)} 个 commit", file=sys.stderr)

        # 生成 Markdown
        markdown_content = generate_task_markdown(commits, author_mapping, project_name)

        # 输出结果
        if output_file:
            output_path = Path(output_file)
            output_path.write_text(markdown_content, encoding='utf-8')

            print(json.dumps({
                "success": True,
                "commits_count": len(commits),
                "output_file": str(output_path.absolute()),
                "message": f"已生成 {len(commits)} 个任务到 {output_file}"
            }), file=sys.stdout)
        else:
            # 输出到 stdout
            print(markdown_content, file=sys.stdout)

        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
