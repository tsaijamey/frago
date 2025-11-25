# CLI Command Contracts: frago init

**Feature**: 006-init-command
**Date**: 2025-11-25
**Related**: [spec.md](../spec.md) | [data-model.md](../data-model.md)

本文档定义 `frago init` 命令的完整接口契约，包括命令签名、选项、退出码和输出格式。

---

## 命令签名

```bash
frago init [OPTIONS]
```

### 描述

初始化 Frago 开发环境，检查并安装必要依赖（Node.js, Claude Code），配置认证方式和可选组件。

### 选项（Options）

| 选项 | 短选项 | 类型 | 默认值 | 说明 |
|------|--------|------|-------|------|
| `--reset` | | Flag | `False` | 清除临时状态，从头开始初始化 |
| `--show-config` | `-s` | Flag | `False` | 显示当前配置并退出（不执行 init） |
| `--skip-deps` | | Flag | `False` | 跳过依赖检查，仅更新配置 |
| `--non-interactive` | `-y` | Flag | `False` | 非交互模式，使用所有默认值 |
| `--help` | `-h` | Flag | | 显示帮助信息并退出 |

### 选项详细说明

#### `--reset`

- **用途**: 清除未完成的初始化状态，强制从头开始
- **行为**:
  1. 删除 `~/.frago/.init_state.json`（如果存在）
  2. 不删除 `~/.frago/config.json`（保留已有配置）
  3. 重新执行完整 init 流程
- **使用场景**: 上次 init 中断后不想恢复，或状态文件损坏

**示例**:
```bash
frago init --reset
```

#### `--show-config`

- **用途**: 查看当前配置而不执行初始化
- **行为**:
  1. 读取 `~/.frago/config.json`
  2. 以格式化方式显示配置内容（隐藏敏感信息）
  3. 退出（退出码 0）
- **输出格式**: 见"输出格式规范"章节

**示例**:
```bash
frago init --show-config

# 输出示例:
Frago Configuration
===================
Node.js:         20.11.0 (/usr/local/bin/node)
npm:             10.2.4
Claude Code:     0.5.0 (/usr/local/bin/claude-code)
Auth Method:     custom (Deepseek)
CCR Enabled:     No
Created:         2025-11-25 10:30:00
Last Updated:    2025-11-25 10:35:00
Init Completed:  Yes
```

#### `--skip-deps`

- **用途**: 假设依赖已安装，仅更新配置（认证方式、CCR 等）
- **行为**:
  1. 跳过 Node.js 和 Claude Code 的检查和安装
  2. 直接进入认证配置流程
  3. 更新 `~/.frago/config.json`
- **使用场景**: 依赖已手动安装，仅需更换 API 端点

**示例**:
```bash
frago init --skip-deps
```

#### `--non-interactive`

- **用途**: 非交互模式，适用于脚本/CI 环境
- **行为**:
  1. 所有交互式提示使用默认值
  2. 如果需要必填输入（如 API Key），报错并退出
  3. 不显示进度条或彩色输出（纯文本）
- **默认值**:
  - 认证方式: `official`
  - 安装确认: `Yes`
  - CCR 启用: `No`

**示例**:
```bash
frago init --non-interactive
```

---

## 退出码（Exit Codes）

| 退出码 | 名称 | 说明 | 用户操作 |
|-------|------|------|---------|
| `0` | `SUCCESS` | 成功完成初始化 | 无需操作 |
| `1` | `INSTALL_FAILED` | 安装步骤失败（Node.js 或 Claude Code） | 查看错误信息，手动修复后重试 |
| `2` | `USER_CANCELLED` | 用户主动取消（Ctrl+C 或选择 No） | 稍后重新运行 |
| `3` | `CONFIG_ERROR` | 配置文件错误（格式错误、权限问题） | 删除 `~/.frago/config.json` 或修复权限 |
| `10` | `ENV_CHECK_FAILED` | 环境检查失败（主目录不可写等） | 检查文件系统权限 |
| `11` | `VERSION_INSUFFICIENT` | 依赖版本不足且用户拒绝升级 | 手动升级依赖 |
| `12` | `PERMISSION_ERROR` | 权限不足（npm 全局安装失败） | 使用 sudo 或配置 npm prefix |
| `13` | `NETWORK_ERROR` | 网络错误（npm install 超时） | 检查网络连接/代理设置 |
| `130` | `SIGINT` | 强制退出（两次 Ctrl+C） | 无状态保存 |

### 退出码使用示例

```bash
#!/bin/bash

frago init
exit_code=$?

case $exit_code in
  0)
    echo "Init successful!"
    ;;
  1)
    echo "Installation failed. Check logs above."
    exit 1
    ;;
  2)
    echo "User cancelled. Run 'frago init' again when ready."
    exit 0
    ;;
  3)
    echo "Config error. Try: rm ~/.frago/config.json && frago init"
    exit 1
    ;;
  *)
    echo "Unknown error (exit code: $exit_code)"
    exit $exit_code
    ;;
esac
```

---

## 输出格式规范

### 成功消息模板

#### 依赖检查阶段

```text
🔍 Checking dependencies...

✅ Node.js: 20.11.0 (/usr/local/bin/node)
✅ npm: 10.2.4
❌ Claude Code: Not installed

📦 Installation Plan:
  - Install Claude Code via npm

Continue with installation? [Y/n]:
```

#### 安装进度

```text
📥 Installing Claude Code...
  Running: npm install -g @anthropic-ai/claude-code
  ⠹ Installing... (this may take a few minutes)

✅ Claude Code installed successfully
   Version: 0.5.0
   Path: /usr/local/bin/claude-code
```

#### 认证配置

```text
🔐 Authentication Setup

Please choose authentication method:
  [1] Official Claude Code login (recommended)
  [2] Custom API endpoint

Your choice [1]:

✅ Authentication configured: Official
```

#### 完成消息

```text
✅ Initialization complete!

Configuration summary:
  Node.js:       20.11.0
  Claude Code:   0.5.0
  Auth Method:   official
  CCR Enabled:   No

Next steps:
  1. Run: frago recipe list
  2. Try: frago navigate https://example.com

Config saved to: /home/user/.frago/config.json
```

### 错误消息模板

#### 安装失败

```text
❌ Installation Failed

Component: Claude Code
Command: npm install -g @anthropic-ai/claude-code
Exit Code: 1

Error Details:
  npm ERR! code EACCES
  npm ERR! syscall mkdir
  npm ERR! path /usr/local/lib/node_modules/@anthropic-ai
  npm ERR! errno -13

Suggested Fix:
  This is a permission error. Try one of the following:

  Option 1: Use npm prefix (recommended)
    npm config set prefix ~/.npm-global
    export PATH=~/.npm-global/bin:$PATH
    frago init

  Option 2: Use sudo
    sudo npm install -g @anthropic-ai/claude-code
    frago init --skip-deps

For more help, see: https://docs.npmjs.com/resolving-eacces-permissions-errors
```

#### 网络错误

```text
❌ Network Error

Component: npm
Error: Connection timeout after 60s

Possible causes:
  1. No internet connection
  2. npm registry unreachable
  3. Proxy configuration needed

Troubleshooting:
  - Check internet: ping npmjs.org
  - Configure proxy:
      export HTTP_PROXY=http://proxy:port
      export HTTPS_PROXY=http://proxy:port
  - Try again: frago init

Exit Code: 13
```

### JSON 输出格式（--format json）

**未来扩展**: 支持 `--format json` 选项输出机器可读格式

```json
{
  "status": "success",
  "exit_code": 0,
  "config": {
    "node_version": "20.11.0",
    "claude_code_version": "0.5.0",
    "auth_method": "official",
    "ccr_enabled": false
  },
  "steps_completed": [
    "check_dependencies",
    "install_claude_code",
    "configure_auth",
    "save_config"
  ],
  "duration_seconds": 125
}
```

---

## 交互流程契约

### 标准流程（所有依赖缺失）

```
1. [依赖检查]
   Input: N/A
   Output: 依赖状态摘要
   Next: 询问是否安装

2. [安装确认]
   Prompt: "Continue with installation? [Y/n]:"
   Input: Y/n/Ctrl+C
   Output: 开始安装 OR 退出(exit 2)

3. [安装 Node.js]
   Input: N/A
   Output: 安装进度 + 结果
   Error: 失败则 exit 1

4. [安装 Claude Code]
   Input: N/A
   Output: 安装进度 + 结果
   Error: 失败则 exit 1

5. [认证方式选择]
   Prompt: "Choose authentication method [1/2]:"
   Input: 1=official, 2=custom
   Output: 进入对应配置流程

6. [官方登录流程]
   Prompt: "Run 'claude-code login' to authenticate"
   Input: 用户手动执行
   Output: 等待用户完成

7. [自定义端点流程]
   Prompt: "Select provider [deepseek/aliyun/m2/custom]:"
   Input: 端点类型
   Prompt: "Enter API Key:"
   Input: API Key (隐藏输入)
   Output: 保存配置

8. [CCR 配置（可选）]
   Prompt: "Enable Claude Code Router? [y/N]:"
   Input: y/N
   Output: 配置 CCR OR 跳过

9. [完成]
   Output: 配置摘要 + 下一步建议
   Exit: 0
```

### 恢复流程（检测到临时状态）

```
1. [检测临时状态]
   Output: "⚠️  Detected unfinished initialization..."
   Prompt: "Resume from last checkpoint? [Y/n]:"
   Input: Y/n

2a. [选择恢复]
   Output: "Resuming from: {current_step}"
   Next: 跳过已完成步骤，继续执行

2b. [选择重新开始]
   Output: "Starting fresh..."
   Next: 删除临时状态，执行标准流程
```

### 更新配置流程（所有依赖已满足）

```
1. [检测已有配置]
   Output: 当前配置摘要
   Prompt: "Update configuration? [y/N]:"
   Input: y/N

2a. [选择更新]
   Prompt: "What to update? [auth/ccr/all]:"
   Next: 进入对应更新流程

2b. [选择不更新]
   Output: "No changes made."
   Exit: 0
```

---

## 环境变量

| 变量名 | 类型 | 说明 | 示例 |
|-------|------|------|------|
| `FRAGO_CONFIG_DIR` | `str` | 覆盖默认配置目录 | `export FRAGO_CONFIG_DIR=/custom/path` |
| `HTTP_PROXY` | `str` | HTTP 代理（npm 使用） | `export HTTP_PROXY=http://proxy:8080` |
| `HTTPS_PROXY` | `str` | HTTPS 代理（npm 使用） | `export HTTPS_PROXY=http://proxy:8080` |
| `FRAGO_INIT_TIMEOUT` | `int` | 安装超时秒数（默认 120） | `export FRAGO_INIT_TIMEOUT=300` |

---

## 兼容性

### 最低要求

- **Python**: 3.9+
- **Click**: 8.1+
- **操作系统**: Linux (Ubuntu 20.04+), macOS (11+), Windows 10+ (仅检测，不自动安装)

### 终端要求

- **字符集**: UTF-8（支持 emoji）
- **彩色输出**: 自动检测 TTY，非 TTY 环境禁用颜色
- **宽度**: 最小 80 列（自适应换行）

---

## 测试契约

### 单元测试覆盖

- [ ] 所有选项的参数解析
- [ ] 退出码的正确返回
- [ ] 错误消息的格式化
- [ ] JSON 输出的结构验证

### 集成测试场景

1. **全新安装**：无依赖 → 安装全部 → 配置官方登录 → 成功（exit 0）
2. **部分已装**：有 Node.js 无 Claude Code → 仅安装 Claude Code → 成功
3. **全部已装**：所有依赖满足 → 跳过安装 → 询问更新配置
4. **Ctrl+C 恢复**：中断后恢复 → 从断点继续 → 成功
5. **安装失败**：npm install 失败 → 显示错误 → exit 1
6. **权限错误**：无 sudo → EACCES 错误 → 提示解决方案 → exit 12
7. **网络超时**：无网络 → 超时错误 → exit 13
8. **非交互模式**：--non-interactive → 使用默认值 → 成功

---

## 附录：命令示例

### 基础用法

```bash
# 标准初始化
frago init

# 查看当前配置
frago init --show-config

# 重新开始（清除临时状态）
frago init --reset

# 仅更新配置（跳过依赖安装）
frago init --skip-deps

# 非交互模式（CI/脚本）
frago init --non-interactive
```

### 组合用法

```bash
# 清除状态 + 非交互模式
frago init --reset --non-interactive

# 跳过依赖 + 显示配置
frago init --skip-deps --show-config  # ⚠️ 冲突：--show-config 会直接退出
```

### 错误处理示例

```bash
# 处理安装失败
frago init || {
  exit_code=$?
  if [ $exit_code -eq 12 ]; then
    echo "Permission error detected. Retrying with sudo..."
    sudo npm install -g @anthropic-ai/claude-code
    frago init --skip-deps
  fi
}
```

---

## 总结

- ✅ **5 个命令选项**：--reset, --show-config, --skip-deps, --non-interactive, --help
- ✅ **9 个退出码**：0-3, 10-13, 130
- ✅ **3 个主要流程**：标准初始化、恢复流程、更新配置
- ✅ **标准化输出**：成功消息、错误消息、JSON 格式（未来）
- ✅ **8 个集成测试场景**：覆盖主要用例

**下一步**: 生成 `quickstart.md` 开发快速入门文档。
