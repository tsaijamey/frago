# 安装指南

[English](installation.md)

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.13+ | 核心运行时 |
| **Node.js** | 20+ | Claude Code 集成 |
| **Chrome** | 最新版 | CDP 浏览器自动化 |

## 快速安装（推荐）

一键安装并启动：

```bash
# macOS/Linux
curl -fsSL https://frago.ai/install.sh | sh

# Windows
powershell -c "irm https://frago.ai/install.ps1 | iex"
```

自动完成：
- 安装 uv 和 frago
- 启动 Web 服务
- 在浏览器中打开 http://127.0.0.1:8093

---

<details>
<summary><b>手动安装（高级）</b></summary>

如果你希望逐步控制安装过程：

```bash
# 1. 安装 uv（包管理器）
curl -LsSf https://astral.sh/uv/install.sh | sh      # macOS/Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows

# 2. 安装 frago
uv tool install frago-cli

# 3. 初始化
frago init

# 4. 启动 Web 服务
frago server start
```

然后在浏览器中打开 http://127.0.0.1:8093

</details>

## 验证

```bash
frago --version
frago recipe list
```

## 升级 / 卸载

```bash
uv tool upgrade frago-cli    # 升级
uv tool uninstall frago-cli  # 卸载
```

---

<details>
<summary><b>Linux 前置条件</b></summary>

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y python3 python3-pip curl git
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb && sudo apt -f install

# Fedora/RHEL
sudo dnf install -y python3 python3-pip curl git
sudo dnf install https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm

# Arch Linux
sudo pacman -S python python-pip curl git
yay -S google-chrome
```

</details>

<details>
<summary><b>macOS 前置条件</b></summary>

```bash
# 安装 Xcode 命令行工具
xcode-select --install

# Chrome 通常已预装，或从 google.com/chrome 下载
```

</details>

<details>
<summary><b>Windows 前置条件</b></summary>

> **重要**：Windows 不支持自动安装 Node.js。必须在 `frago init` 之前手动安装 Node.js。

```powershell
# 安装 Python
winget install Python.Python.3.13

# 安装 Node.js（frago init 之前必须安装）
winget install OpenJS.NodeJS.LTS

# 安装 Chrome
winget install Google.Chrome
```

</details>

---

## `frago init` 做了什么

1. **检查依赖** — Node.js 20+、Claude Code CLI
2. **自动安装** — 通过 nvm 安装 Node.js（仅 macOS/Linux）、通过 npm 安装 Claude Code
3. **配置认证** — 默认或自定义 API 端点
4. **安装资源** — Slash 命令到 `~/.claude/commands/`，配方到 `~/.frago/recipes/`

### init 选项

```bash
frago init --show-config      # 显示当前配置
frago init --reset            # 重置并重新初始化
frago init --skip-deps        # 跳过依赖检查
frago init --update-resources # 强制更新资源
```

## 开发环境

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```
