# Frago Development Guidelines

## 本文档维护原则

本文件仅用于指导 Claude Code 迭代本仓库代码，内容限于：
- 项目目录结构
- 资源更新流程与禁止操作
- 开发时的技术偏好

不应包含：
- frago 产品的使用说明、命令参考、API 文档
- Agent 使用 frago 工具时的行为规范
- 版本号、依赖列表等可从 pyproject.toml 获取的信息

## 目录结构

```
src/frago/              # 核心代码
src/frago/resources/    # PyPI 包资源（由 dev pack 生成）
```

## 项目的最终产物面对的人群
- 部分开发者：frago能够有效提升技术调研/API文档解读/实验性开发等，适合喜欢并重视这类工作的开发者
- 期望自动化的普通用户：大部分这类人群对技术没有丰富经验，无法搞清我们项目中所采用的关键技术方案、技术方案导致的依赖、技术实现
因此，**必须要**：
1. 在文档层面提供足够的、全面的、平易近人的、易于理解的帮助与说明；
2. 人们关心最好的是什么，而不是那些愚蠢呆板的技术开发者偏好的“选项一“、“选项二“，除非极有必要展示差异。项目说明文档和Tips文档中必须给出最佳选择，而不是你可以这样或那样。
3. 始终站在“用户是否很容易理解这一点“的基础上思考和实施“最佳实践“。

## 跨平台开发注意事项

项目需同时支持 Linux/macOS/Windows，其中 Windows 差异最大。

### 命令行参数

Windows 命令行参数会在换行符处截断，多行文本应通过 stdin 或临时文件传递：

```python
# 错误：多行 prompt 会被截断
subprocess.run(["claude", "-p", multi_line_prompt])

# 正确：使用 stdin
process = subprocess.Popen(["claude", "-p", "-"], stdin=subprocess.PIPE)
process.stdin.write(prompt.encode())
process.stdin.close()

# 正确：使用临时文件
prompt_file.write_text(prompt)
subprocess.run(["frago", "agent", "--prompt-file", str(prompt_file)])
```

### 路径编码

Claude Code 将项目路径编码为目录名，Windows 驱动器盘符需特殊处理：

| 原始路径 | 编码结果 |
|---------|---------|
| `/home/user/project` | `-home-user-project` |
| `C:\Users\yammi` | `C--Users-yammi` |

关键：Windows 的 `:` 转换为 `-`，产生双连字符 `C--`。参考 `frago/session/sync.py` 中的 `encode_project_path` 和 `decode_project_path`。

### subprocess 调用

使用 `frago.compat.prepare_command_for_windows` 处理 npm 全局命令：

```python
from frago.compat import prepare_command_for_windows

# 自动解析 claude.CMD 的完整路径
subprocess.run(prepare_command_for_windows(["claude", "-p", "test"]))
```

### 编码问题

Windows 控制台默认非 UTF-8，subprocess 调用需显式指定：

```python
subprocess.run(cmd, text=True, encoding='utf-8')
```

### 空设备重定向

**禁止**在代码中硬编码 `/dev/null`，Windows 上会创建名为 `nul` 的实际文件。

```python
import os
import platform

# 正确：跨平台获取空设备
NULL_DEVICE = 'nul' if platform.system() == 'Windows' else '/dev/null'

# 或使用 subprocess.DEVNULL
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

执行 shell 命令时，优先使用 `subprocess.DEVNULL` 而非重定向字符串。

## 资源统一到用户目录

所有资源均存放在用户目录：

```
~/.claude/
├── commands/
│   ├── frago.*.md       # Frago 命令
│   └── frago/           # 命令规则和脚本
└── skills/
    └── frago-*/         # Frago skills

~/.frago/
├── config.json          # 全局配置
├── current_run          # 当前 run 上下文
├── projects/            # run 实例目录
├── recipes/             # Recipe 库
│   ├── atomic/
│   └── workflows/
├── sessions/            # Session 存储
└── chrome_profile/      # Chrome 配置
```

## 资源更新流程

```
~/.claude/commands/frago.*.md  ──┐
~/.claude/skills/frago-*       ──┼──→  frago dev pack  ──→  src/frago/resources/
~/.frago/recipes/              ──┘
```

## 禁止事项

- ❌ 直接修改 `src/frago/resources/`（由 dev pack 自动生成）
- ✅ 在 `~/.claude/` 和 `~/.frago/` 编辑资源，再通过 `frago dev pack` 同步

## 文档索引（按需阅读）

| 文档 | 用途 |
|------|------|
| `docs/concepts.md` | 核心概念与架构设计 |
| `pyproject.toml` | 依赖版本、入口点配置 |
| `specs/*/spec.md` | 各功能的规格说明 |
| `~/.claude/commands/frago/` | Agent 使用 frago 的行为规范 |
