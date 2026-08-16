# 安装指南

[English](installation.md)

## 桌面客户端

下载，安装，从应用菜单打开。

| 平台 | 下载 |
|------|------|
| **macOS (Apple Silicon)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **macOS (Intel)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **Windows** | [.msi](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (deb)** | [.deb](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (rpm)** | [.rpm](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (AppImage)** | [.AppImage](https://github.com/tsaijamey/frago/releases/latest) |

> 所有下载见 [Releases 页面](https://github.com/tsaijamey/frago/releases/latest)

---

## CLI

frago 的命令行界面——相当于操作系统的 shell。桌面客户端能做的，CLI 都能做，还支持浏览器自动化、Recipe 开发和直接控制 agent。安装需要 Python 3.13+。

### 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.13+ | 核心运行时 |
| **Node.js** | 20+ | Claude Code 集成 |
| **Microsoft Edge** | 最新版 | 自动化默认浏览器（Chromium / 非 Stable 的 Chrome 可作为后备） |

### 快速安装

```bash
# macOS/Linux
curl -fsSL https://frago.ai/install.sh | sh

# Windows
powershell -c "irm https://frago.ai/install.ps1 | iex"
```

<details>
<summary><b>手动安装</b></summary>

```bash
# 1. 安装 uv（包管理器）
curl -LsSf https://astral.sh/uv/install.sh | sh      # macOS/Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows

# 2. 安装 frago
uv tool install frago-cli

# 3. 初始化
frago init

# 4. 启动服务
frago server start
```

</details>

### 验证

```bash
frago --version
frago recipe list
```

### 升级 / 卸载

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
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" | sudo tee /etc/apt/sources.list.d/microsoft-edge.list
sudo apt update && sudo apt install -y microsoft-edge-stable

# Fedora/RHEL
sudo dnf install -y python3 python3-pip curl git
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo dnf config-manager --add-repo https://packages.microsoft.com/yumrepos/edge
sudo dnf install -y microsoft-edge-stable

# Arch Linux
sudo pacman -S python python-pip curl git
yay -S microsoft-edge-stable
```

</details>

<details>
<summary><b>macOS 前置条件</b></summary>

```bash
# 安装 Xcode 命令行工具
xcode-select --install

# Edge 可能需要手动安装——microsoft.com/edge
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

# Edge 随 Windows 10/11 预装；被卸载过就显式装回来
winget install Microsoft.Edge
```

</details>

---

## `frago init` 做了什么

1. **检查依赖** — Python 3.13+、Node.js 20+、Claude Code CLI、浏览器
2. **自动安装** — 通过 nvm 安装 Node.js（仅 macOS/Linux）、通过 npm 安装 Claude Code
3. **配置模型 profile** — 官方端点或自定义端点（DeepSeek、代理、本地模型）
4. **安装提示引擎** — 部署 `frago-core` 并为 Claude Code / opencode 注册 hook
   （静态规则 + 轻量 AI）
5. **安装资源** — Slash 命令到 `~/.claude/commands/`，配方到 `~/.frago/recipes/`

### init 选项

```bash
frago init --show-config      # 显示当前配置
frago init --reset            # 重置并重新初始化
frago init --skip-deps        # 跳过依赖检查
frago init --non-interactive  # 非交互模式（全部走默认值，适合 CI/CD）
```

## 开发环境

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```
