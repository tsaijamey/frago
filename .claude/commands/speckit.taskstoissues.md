---
description: 基于可用的设计文档，将现有任务转换为可操作的、按依赖关系排序的 GitHub issues。
tools: ['github/github-mcp-server/issue_write']
---

## 用户输入

```text
$ARGUMENTS
```

在继续之前，你**必须**考虑用户输入（如果不为空）。你应该全程使用中文来撰写所有文档内容或代码注释。

## 大纲

1. 从仓库根目录运行 `.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` 并解析 FEATURE_DIR 和 AVAILABLE_DOCS 列表。所有路径必须是绝对路径。对于参数中的单引号，如 "I'm Groot"，使用转义语法：例如 'I'\''m Groot'（或者如果可能的话使用双引号："I'm Groot"）。
1. 从执行的脚本中，提取 **tasks** 的路径。
1. 通过运行以下命令获取 Git 远程仓库：

```bash
git config --get remote.origin.url
```

**仅在远程仓库是 GITHUB URL 时才继续下一步**

1. 对于列表中的每个任务，使用 GitHub MCP 服务器在与 Git 远程仓库对应的仓库中创建新 issue。

**在任何情况下都绝不能在与远程 URL 不匹配的仓库中创建 issues**

