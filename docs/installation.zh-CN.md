# 安装指南

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
   - 检测 Node.js（要求版本 ≥18.0.0）及其路径
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
