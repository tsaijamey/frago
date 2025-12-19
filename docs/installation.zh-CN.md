# 安装指南

> [!IMPORTANT]
> ## ⚠️ 先看这里 — 不要跳过！
>
> **跳过前提条件会导致安装失败。**
>
> | 你的操作系统 | 先做什么 | 耗时 |
> |-------------|----------|------|
> | **Linux** | → [Linux 安装前提条件](#linux-安装前提条件) | 2 分钟 |
> | **macOS** | → [macOS 安装前提条件](#macos-安装前提条件) | 2 分钟 |
> | **Windows** | → [Windows 安装前提条件](#windows-安装前提条件) | 5 分钟 |

> [!WARNING]
> **Windows 用户：必须手动安装 Node.js！**
>
> 与 macOS/Linux 不同，Windows 无法自动安装 Node.js。跳过这一步会导致 `frago init` 失败。
>
> → [立即安装 Node.js](#安装-nodejsfrago-init-之前必须安装)

---

## 基础安装

安装核心功能（CDP 操作 + Recipe 系统核心）：

```bash
# 使用 pip
pip install frago-cli

# 使用 uv（推荐）
uv tool install frago-cli
```

**核心功能包含**：
- ✅ Chrome DevTools Protocol (CDP) 操作
- ✅ Recipe 系统（列表、执行、元数据管理）
- ✅ 输出到 stdout 和 file
- ✅ Python/Shell Recipe 执行
- ✅ Workflow 编排

---

## 环境初始化

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
| `~/.frago/config.json` | Frago 配置（认证方式、资源状态） |
| `~/.claude/settings.json` | Claude Code 设置（自定义 API 端点配置） |
| `~/.claude/commands/frago.*.md` | 已安装的 slash 命令 |
| `~/.frago/recipes/` | 用户级 Recipe |

### 多设备资源同步

初始配置完成后，可以通过你自己的 Git 仓库在多台设备间同步个性化资源（skills、recipes、commands）：

```bash
# 配置你的私有仓库（仅首次）
frago sync --set-repo git@github.com:you/my-frago-resources.git

# 从仓库部署资源
frago deploy

# 修改后同步回仓库
frago publish && frago sync
```

详见 [使用指南 - 资源管理](user-guide.zh-CN.md#资源管理)。

---

## 可选功能

### GUI 支持

如果需要使用桌面 GUI 界面：

```bash
# 使用 pip
pip install frago-cli[gui]

# 使用 uv
uv tool install "frago-cli[gui]"
```

**平台特定要求**：

| 平台 | 后端 | 系统依赖 |
|------|------|----------|
| **Linux** | WebKit2GTK | `sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1` |
| **macOS** | WKWebView | 无（内置） |
| **Windows** | WebView2 | Edge WebView2 Runtime（推荐） |

**Linux 安装示例（Ubuntu/Debian）**：
```bash
# 先安装系统依赖
sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1

# 然后安装带 GUI 支持的 frago
pip install frago-cli[gui]

# 或者一行命令支持 PyGObject 编译
sudo apt install -y libcairo2-dev libgirepository1.0-dev gir1.2-webkit2-4.1
pip install frago-cli[gui] PyGObject
```

**启动 GUI**：
```bash
frago gui
frago gui --debug  # 带开发者工具
```

---

### 剪贴板支持

如果需要将 Recipe 结果输出到剪贴板：

```bash
# 使用 pip
pip install frago-cli[clipboard]

# 使用 uv
uv tool install "frago-cli[clipboard]"
```

**提供的额外功能**：
- ✅ `--output-clipboard` 选项
- ✅ `clipboard_read` Recipe（系统剪贴板读取）

---

### 完整安装（所有可选功能）

安装所有功能：

```bash
# 使用 pip
pip install frago-cli[all]

# 使用 uv
uv tool install "frago-cli[all]"
```

---

## 开发环境安装

如果要参与开发或运行测试：

```bash
# 克隆仓库
git clone https://github.com/frago/frago.git
cd frago

# 使用 uv 安装开发依赖（推荐）
uv sync --all-extras --dev

# 或使用 pip
pip install -e ".[dev,all]"
```

**开发依赖包含**：
- pytest（测试框架）
- pytest-cov（覆盖率）
- ruff（代码检查）
- mypy（类型检查）
- black（代码格式化）

---

## 依赖说明

### 强制依赖（所有用户都会安装）

```toml
dependencies = [
    "websocket-client>=1.9.0",  # CDP WebSocket 连接
    "click>=8.1.0",             # CLI 框架
    "pydantic>=2.0.0",          # 数据验证
    "python-dotenv>=1.0.0",     # 环境变量
    "pyyaml>=6.0.0",            # Recipe 元数据解析
]
```

### 可选依赖（按需安装）

```toml
[project.optional-dependencies]
clipboard = ["pyperclip>=1.8.0"]   # 剪贴板功能
gui = ["pywebview>=5.0.0"]         # 桌面 GUI 界面
all = ["pyperclip>=1.8.0", "pywebview>=5.0.0"]  # 所有可选功能
dev = ["pytest>=7.4.0", ...]       # 开发工具
```

---

## 系统要求

- **Python**: 3.9+
- **操作系统**: macOS, Linux, Windows
- **Chrome 浏览器**: 用于 chrome-js Recipe 执行

---

## Linux 安装前提条件

在 Linux 上安装 frago 之前，请确保系统满足以下要求。

### 需要准备的依赖

| 依赖 | 用途 | 是否必须 |
|------|------|----------|
| **Python 3.9+** | Frago 运行时 | 是 |
| **Node.js 20+** | Claude Code 依赖 | 是（使用 Claude Code 集成时） |
| **Chrome 浏览器** | CDP 浏览器自动化 | 是（使用 CDP 功能时） |
| **curl 或 wget** | 下载安装脚本（nvm） | 是（自动安装时） |
| **git** | 克隆仓库 | 开发时需要 |

### Frago 不会帮你做的事情

1. **安装系统级软件** - Frago 无法执行 `sudo apt/dnf/pacman` 命令
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

在运行 `pip install frago-cli` 之前，请验证：

```bash
# Python 3.9+ 已安装
python3 --version

# pip 可用
pip --version  # 或：python3 -m pip --version

# 网络可以访问 PyPI
pip index versions frago-cli

# Chrome 已安装（如使用 CDP 功能）
google-chrome --version

# Node.js 20+ 已安装（如使用 Claude Code 集成）
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

### 包管理器

**使用 pip（内置）**:
```bash
# macOS 使用 pip3，而非 pip
pip3 install frago-cli

# 或使用 python3 -m pip（更可靠）
python3 -m pip install frago-cli
```

**使用 uv（推荐）**:
```bash
# 先安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或通过 Homebrew
brew install uv

# 然后安装 frago
uv tool install frago-cli
```

### Chrome 浏览器

Chrome 通常已预装或可从 [google.com/chrome](https://www.google.com/chrome/) 下载。验证安装：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
```

### 安装前检查清单

在运行 `pip3 install frago-cli` 之前，请验证：

```bash
# Python 3.9+ 已安装（macOS 12+ 自带 Python 3）
python3 --version

# pip3 可用
pip3 --version

# Xcode 命令行工具已安装
xcode-select -p

# Chrome 已安装（如使用 CDP 功能）
ls /Applications/Google\ Chrome.app

# Node.js 20+ 已安装（如使用 Claude Code 集成）
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
# 在 Microsoft Store 搜索 "Python 3.11" 并安装

# 方法 2：winget
winget install Python.Python.3.11

# 方法 3：官方安装程序
# 从 https://www.python.org/downloads/ 下载
# 重要：安装时勾选 "Add Python to PATH"！
```

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

### 包管理器

**使用 pip**：
```powershell
# Python 安装后，pip 应该可用
pip install frago-cli

# 如果 pip 找不到，使用：
python -m pip install frago-cli
```

**使用 uv（推荐）**：
```powershell
# 安装 uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 然后安装 frago
uv tool install frago-cli
```

### GUI 支持 (WebView2)

GUI 功能需要 WebView2 Runtime：

```powershell
# Windows 11 通常已预装
# Windows 10 需要手动安装：
winget install Microsoft.EdgeWebView2Runtime
```

### 安装前检查清单

在运行 `pip install frago-cli` 之前，在 PowerShell 中验证：

```powershell
# Python 3.9+ 已安装
python --version

# pip 可用
pip --version

# Node.js 20+ 已安装（frago init 之前必须安装）
node --version

# Chrome 已安装（如使用 CDP 功能）
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
# 使用 pip
pip install --upgrade frago-cli

# 使用 uv
uv tool upgrade frago-cli
```

---

## 卸载

```bash
# 使用 pip
pip uninstall frago-cli

# 使用 uv
uv tool uninstall frago-cli
```
