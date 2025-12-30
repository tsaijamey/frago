# 安装指南

> [!IMPORTANT]
> ## ⚠️ 安装前必读
>
> **frago 需要 Python + Node.js + Chrome。** 不同系统的准备工作不同：
>
> - **Linux**：可能没有预装 Python
> - **macOS**：部分依赖需要 Xcode 命令行工具
> - **Windows**：什么都没有 — Python、Node.js、Chrome 全要手动装
>
> **现在花 2 分钟准备，省得之后花 20 分钟排错。**
>
> | 你的操作系统 | 先看这里 |
> |-------------|----------|
> | **Linux** | → [Linux 安装前提条件](#linux-安装前提条件) |
> | **macOS** | → [macOS 安装前提条件](#macos-安装前提条件) |
> | **Windows** | → [Windows 安装前提条件](#windows-安装前提条件) |

> [!WARNING]
> **Windows 用户 — 跳过这步必定报错**
>
> macOS/Linux 上，`frago init` 能帮你自动装 Node.js。**Windows 上不行。**
>
> 如果你没装 Node.js 就运行 `frago init`，会看到：
> ```
> Error: Windows 不支持自动安装 Node.js
> ```
>
> → [先装 Node.js](#安装-nodejsfrago-init-之前必须安装)（只要 2 分钟）

---

## 第一步：安装 uv（包管理器）

**为什么用 uv？** 更快、更干净、环境管理更省心。别直接用 pip。

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装后，**重启终端** 让 `uv` 命令生效。

验证：
```bash
uv --version
```

---

## 第二步：安装 frago

```bash
uv tool install frago-cli
```

就这一行，完事。

> **Windows 用户**：如果你安装了 Python 3.14+，必须指定 Python 3.13：
> ```powershell
> uv tool install frago-cli --python 3.13
> ```
> 这是因为 GUI 后端 (pywebview) 使用的 pythonnet 还不支持 Python 3.14。

<details>
<summary>非要用 pip？（不推荐）</summary>

```bash
# macOS
pip3 install frago-cli

# Linux / Windows
pip install frago-cli
```

虚拟环境的问题你自己解决。
</details>

---

## 第三步：初始化环境

安装包后，运行 init 命令配置环境：

```bash
frago init
```

### `frago init` 做了什么

init 命令执行以下步骤：

1. **依赖检查**
   - 检测 Node.js（要求版本 ≥20.0.0）及其路径
   - 检测 Claude Code CLI 及其版本
   - 用 ✅/❌ 显示检查状态

2. **自动安装**（如果缺少依赖）
   - Node.js：通过 nvm（Node Version Manager）安装
   - Claude Code：通过 `npm install -g @anthropic-ai/claude-code` 安装

3. **认证配置**
   - **默认**：使用 Claude Code 内置认证（Anthropic 账号或已有配置）
   - **自定义端点**：配置支持 Anthropic API 兼容的第三方服务商：
     - DeepSeek（deepseek-chat）
     - 阿里云百炼（qwen3-coder-plus）
     - Kimi K2（kimi-k2-turbo-preview）
     - MiniMax M2
     - 自定义 URL/Key/Model

4. **资源安装**
   - 安装 Claude Code slash 命令到 `~/.claude/commands/`
   - 安装示例 Recipe 到 `~/.frago/recipes/`

### init 命令选项

```bash
# 显示当前配置和已安装资源
frago init --show-config

# 跳过依赖检查（仅更新配置）
frago init --skip-deps

# 重置配置并重新初始化
frago init --reset

# 非交互模式（使用默认值，适合 CI/CD）
frago init --non-interactive

# 跳过资源安装
frago init --skip-resources

# 强制更新所有资源（覆盖已存在的 recipe）
frago init --update-resources
```

### 配置文件说明

| 文件 | 用途 |
|------|------|
| `~/.frago/config.json` | frago 配置（认证方式、资源状态） |
| `~/.claude/settings.json` | Claude Code 设置（自定义 API 端点配置） |
| `~/.claude/commands/frago.*.md` | 已安装的 slash 命令 |
| `~/.frago/recipes/` | 用户级 Recipe |

### 多设备资源同步

**为什么需要私有仓库？** 你的 skills 和 recipes 是个人资产——你发现的工作流模式、你构建的自动化脚本。它们不应该被绑定在单台机器上，也不应该在重装系统时丢失。

初始配置完成后，在多台设备间同步资源：

```bash
# 首次：配置你的私有仓库
frago sync --set-repo git@github.com:you/my-frago-resources.git

# 日常使用：同步变更
frago sync              # 推送本地变更并拉取远程更新
frago sync --dry-run    # 预览将要同步的内容
frago sync --no-push    # 仅拉取，不推送
```

---

## Web 服务模式

frago 通过本地 Web 服务提供基于浏览器的 GUI。无需额外安装——只需 Chrome 浏览器。

**启动 Web 服务**：
```bash
# 启动后台服务（推荐）
frago server start      # 在端口 8093 启动

# 或在前台启动（用于调试）
frago server --debug    # 运行直到 Ctrl+C，带日志
```

**服务命令**：
```bash
frago server start      # 启动后台服务
frago server stop       # 停止后台服务
frago server status     # 检查服务是否运行
```

**访问 GUI**：
- 启动服务后，在浏览器中打开 `http://127.0.0.1:8093`

**平台说明**：
- 适用于任何有 Chrome/Edge/Firefox 的平台
- 无需平台特定依赖
- 服务默认运行在端口 8093

---

## 开发环境

参与开发：

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```

**开发依赖**：pytest、pytest-cov、ruff、mypy、black

---

## 系统要求

- **Python**: 3.9 - 3.13
- **操作系统**: macOS, Linux, Windows
- **Chrome 浏览器**: 用于 CDP 浏览器自动化

---

## Linux 安装前提条件

在 Linux 上安装 frago 之前，请确保系统满足以下要求。

### 需要准备的依赖

| 依赖 | 用途 | 是否必须 |
|------|------|----------|
| **Python 3.9+** | frago 运行时 | 是 |
| **Node.js 20+** | Claude Code 依赖 | 是（使用 Claude Code 集成时） |
| **Chrome 浏览器** | CDP 浏览器自动化 | 是（使用 CDP 功能时） |
| **curl 或 wget** | 下载安装脚本（nvm） | 是（自动安装时） |
| **git** | 克隆仓库 | 开发时需要 |

### frago 不会帮你做的事情

1. **安装系统级软件** - frago 无法执行 `sudo apt/dnf/pacman` 命令
2. **配置网络代理** - 如需代理访问 npm/pip，需要你自行配置
3. **处理权限问题** - npm 全局目录权限问题需要手动解决
4. **选择发行版特定命令** - 你需要根据自己的发行版选择正确的命令

### 各发行版系统依赖安装

#### Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv curl git
```

#### Fedora/RHEL

```bash
sudo dnf install -y python3 python3-pip curl git
```

#### Arch Linux

```bash
sudo pacman -S python python-pip curl git
```

#### openSUSE

```bash
sudo zypper install -y python3 python3-pip curl git
```

### Chrome 浏览器安装

Chrome 是 CDP（Chrome DevTools Protocol）功能的必要依赖。

#### Ubuntu/Debian (64位)

```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt -f install  # 如有依赖问题则修复
```

#### Fedora/RHEL

```bash
sudo dnf install https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
```

#### Arch Linux

```bash
# 使用 yay（AUR 助手）
yay -S google-chrome

# 或使用 paru
paru -S google-chrome
```

### 安装前检查清单

安装 frago 之前，请验证：

```bash
# Python 3.9+ 已安装
python3 --version

# Chrome 已安装（用于 CDP 功能）
google-chrome --version

# Node.js 20+ 已安装（用于 Claude Code 集成）
node --version
```

---

## macOS 安装前提条件

在 macOS 上安装 frago 之前，请确保系统满足以下要求。

### 系统要求

- **macOS**: 10.15 (Catalina) 或更高版本
- **架构**: Apple Silicon (M1/M2/M3) 和 Intel 均完全支持

### 安装 Xcode 命令行工具

编译某些 Python 包需要此工具：

```bash
xcode-select --install
```

### 安装 uv

```bash
# 方法 1：官方安装脚本
curl -LsSf https://astral.sh/uv/install.sh | sh

# 方法 2：Homebrew
brew install uv
```

然后按照 [第二步](#第二步安装-frago) 安装 frago。

### Chrome 浏览器

Chrome 通常已预装或可从 [google.com/chrome](https://www.google.com/chrome/) 下载。验证安装：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
```

### 安装前检查清单

安装 frago 之前，请验证：

```bash
# Python 3.9+ 已安装（macOS 12+ 自带 Python 3）
python3 --version

# Xcode 命令行工具已安装
xcode-select -p

# Chrome 已安装（用于 CDP 功能）
ls /Applications/Google\ Chrome.app

# Node.js 20+ 已安装（用于 Claude Code 集成）
node --version
```

---

## Windows 安装前提条件

在 Windows 上安装 frago 之前，请确保系统满足以下要求。

> **重要**：与 macOS/Linux 不同，Windows 不支持通过 nvm 自动安装 Node.js。你必须在运行 `frago init` 之前手动安装 Node.js。

### 系统要求

- **Windows**: 10 (1809+) 或 Windows 11
- **架构**: x64 和 ARM64 均支持

### 安装 Python

Windows 默认不包含 Python：

```powershell
# 方法 1：Microsoft Store（最简单）
# 在 Microsoft Store 搜索 "Python 3.13" 并安装

# 方法 2：winget（推荐）
winget install Python.Python.3.13

# 方法 3：官方安装程序
# 从 https://www.python.org/downloads/ 下载
# 重要：安装时勾选 "Add Python to PATH"！
```

> **重要**：请使用 Python 3.9 - 3.13。由于 pywebview/pythonnet 兼容性问题，Windows 上暂不支持 Python 3.14+。

### 安装 Node.js（frago init 之前必须安装）

```powershell
# 使用 winget（推荐）
winget install OpenJS.NodeJS.LTS

# 或从 https://nodejs.org/ 下载
# 选择 LTS 版本（20.x）
```

### 安装 Chrome 浏览器

```powershell
# 使用 winget
winget install Google.Chrome

# 或从 https://www.google.com/chrome/ 下载
```

### 安装 uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

然后按照 [第二步](#第二步安装-frago) 安装 frago。

### GUI 支持 (WebView2)

GUI 功能需要 WebView2 Runtime：

```powershell
# Windows 11 通常已预装
# Windows 10 需要手动安装：
winget install Microsoft.EdgeWebView2Runtime
```

> **Python 版本要求**：GUI 模式需要 Python 3.13 或更早版本。如果使用 Python 3.14+，请这样安装：
> ```powershell
> uv tool install frago-cli --python 3.13
> ```

### 安装前检查清单

安装 frago 之前，在 PowerShell 中验证：

```powershell
# Python 3.9+ 已安装
python --version

# Node.js 20+ 已安装（frago init 之前必须安装）
node --version

# Chrome 已安装（用于 CDP 功能）
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --version
```

---

## 验证安装

安装后验证：

```bash
# 检查版本
frago --version

# 列出可用 Recipe
frago recipe list

# 查看帮助
frago --help
```

---

## 升级

```bash
uv tool upgrade frago-cli
```

---

## 卸载

```bash
uv tool uninstall frago-cli
```
