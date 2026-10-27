# 安装指南

[English](installation.md)

frago 以命令行工具的形式安装；给人用的界面是它提供的网页（`frago server start` 之后打开 http://127.0.0.1:8093）。安装需要 Python 3.13+。

> frago 没有桌面客户端。GitHub Releases 页面上旧版本附带的安装包已停止维护。

### 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.13+ | 核心运行时 |
| **Node.js** | 20+ | Claude Code 集成 |
| **浏览器** | Chrome for Testing（frago 自己取） | 自动化默认浏览器；本机没有时 frago 会自己下载一份到 `~/.frago/tools/chrome-for-testing/`，取不到才退到已装的 Edge / Chromium / Chrome 等 |

### 快速安装

```bash
# macOS/Linux
curl -fsSL https://frago.ai/install.sh | sh

# Windows
powershell -c "irm https://frago.ai/install.ps1 | iex"
```

> 一键脚本不替人装 Node.js：`install.sh` / `install.ps1` 发现没有 `node` 会报错停下，装之前先按下面各平台前置条件把 Node.js 装好。

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
# 以下三行可选：Edge 只在 frago 取不到自带 Chrome for Testing 时当后备
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" | sudo tee /etc/apt/sources.list.d/microsoft-edge.list
sudo apt update && sudo apt install -y microsoft-edge-stable

# Fedora/RHEL
sudo dnf install -y python3 python3-pip curl git
# 以下三行可选：Edge 后备（同上）
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo dnf config-manager --add-repo https://packages.microsoft.com/yumrepos/edge
sudo dnf install -y microsoft-edge-stable

# Arch Linux
sudo pacman -S python python-pip curl git
yay -S microsoft-edge-stable   # 可选：Edge 后备
```

</details>

<details>
<summary><b>macOS 前置条件</b></summary>

```bash
# 安装 Xcode 命令行工具
xcode-select --install

# 浏览器不用预备：frago 会自己取 Chrome for Testing；想用 Edge 当后备才手动装——microsoft.com/edge
```

</details>

<details>
<summary><b>Windows 前置条件</b></summary>

> **重要**：安装脚本不会替你装 Node.js——缺 `node` 时 `install.ps1` 直接报错停下。所以 Node.js 要在跑一键脚本**之前**装好。

```powershell
# 安装 Python
winget install Python.Python.3.13

# 安装 Node.js（跑 install.ps1 之前必须装好）
winget install OpenJS.NodeJS.LTS

# 可选：Edge 随 Windows 10/11 预装；被卸载过就显式装回来
winget install Microsoft.Edge
```

</details>

---

## `frago init` 做了什么

1. **检查依赖** — 只报 Claude Code；Node.js 20+ 一并检查，但不替你装
2. **安装 Claude Code** — 走官方安装器；任何平台都不会替人装 Node.js
3. **配置模型 profile** — 官方端点或自定义端点（DeepSeek、代理、本地模型）
4. **任务接入（可选）** — 需要外部任务源时，走 channel 向导
5. **询问开机自启** — 可选让 frago 服务随系统启动，之后用 `frago autostart` 改

### init 选项

```bash
frago init --show-config      # 显示当前配置
frago init --reset            # 重置并重新初始化
frago init --skip-deps        # 跳过依赖检查
frago init --non-interactive  # 非交互模式（全部走默认值，适合 CI/CD）
```

### `frago server start` 之后才发生的事

`frago init` 不往 `~/.claude/` 里铺东西。提示引擎是服务启动时落的：

1. **铺知识** — 手册主题、宪法与代理纪律、hook 规则与判读说明、CoreAgent 指令落到 `~/.frago/`
2. **部署提示引擎** — `frago-core` 落到本地，并把 hook 事件登记给 Claude Code、opencode、codex、agy
3. **清旧账** — 老版本留在 `~/.claude/` 的 hook 脚本、slash 命令、skills 会被收走

## 开发环境

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```
