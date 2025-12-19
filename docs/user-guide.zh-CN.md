# Frago 使用指南

## 概述

Frago 是为 AI agent 设计的多运行时自动化基础设施，提供四个核心系统协同工作：

- **🧠 Run 系统**：AI 的工作记忆 - 持久化上下文和结构化日志
- **📚 Recipe 系统**：AI 的"肌肉记忆" - 可复用的自动化脚本
- **🔍 Session 系统**：Agent 监控 - 实时执行跟踪
- **⚡ 原生 CDP**：轻量级执行引擎 - 直连 Chrome 控制

## 核心使用场景

Frago 适用于各类浏览器自动化和数据采集任务：

1. **交互式探索与调试**
   - 探索未知页面同时保持完整上下文
   - 示例：`"研究 YouTube 字幕提取方法"`

2. **网页数据采集** - 批量提取结构化信息
   - 示例：`"从 Upwork 提取职位详情并导出为 Markdown"`

3. **社交媒体分析** - 收集和分析社交内容
   - 示例：`"提取 Twitter/X 帖子及评论"`

4. **内容转录** - 提取视频/音频的文本内容
   - 示例：`"下载 YouTube 视频的字幕文本"`

5. **自定义工作流** - 组合多个 Recipe 完成复杂任务
   - 示例：`"批量处理表单提交、截图归档"`

**典型工作流程**：
1. AI 分析任务需求，选择合适的方法（Run 探索 vs Recipe 执行）
2. 调用 CDP 命令控制 Chrome 执行操作
3. 记录执行日志到 JSONL 文件（100% 可解析、可审计）
4. 输出结构化数据（JSON/Markdown/文本）
5. 持久化任务上下文到 Run 实例供未来参考

## 环境要求

- **Python**：3.9+（核心功能必需）
- **Chrome 浏览器**：用于 chrome-js Recipe 执行
- **操作系统**：macOS、Linux、Windows
- **包管理器**：`uv`（推荐）或 `pip`

## 安装

详见 [安装指南](installation.zh-CN.md)。

**快速开始**：
```bash
uv tool install frago-cli
frago --version
```

## CDP 命令使用指南

### 基础CDP命令

所有CDP功能通过统一的CLI接口（`frago chrome <command>`）访问。

```bash
# 导航网页
frago chrome navigate <url>

# 点击元素
frago chrome click <selector>

# 执行JavaScript
frago chrome exec-js <expression>

# 截图
frago chrome screenshot <output_file>

# 其他命令
frago --help
```

### 代理配置

Frago的CDP集成支持代理配置，适用于需要通过代理访问网络的环境。

#### 环境变量配置

通过环境变量设置全局代理：

```bash
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1
```

#### CLI参数配置

所有CDP命令都支持代理参数：

```bash
# 使用代理
frago chrome navigate https://example.com \
    --proxy-host proxy.example.com \
    --proxy-port 8080

# 绕过代理
frago chrome navigate https://example.com --no-proxy
```

### 重试机制

CDP连接支持智能重试机制，特别针对代理环境优化：

- **默认重试策略**：最多3次，指数退避延迟
- **代理连接重试策略**：最多5次，更短延迟，适用于代理环境
- **连接超时**：默认30秒
- **命令超时**：默认60秒

重试机制会自动识别代理连接失败并提供诊断信息。

## Recipe管理和使用

Recipe系统提供元数据驱动的自动化脚本管理。

### Recipe管理命令

```bash
# 列出所有可用的Recipe
frago recipe list

# 以JSON格式列出（便于AI解析）
frago recipe list --format json

# 查看Recipe详细信息
frago recipe info youtube_extract_video_transcript

# 执行Recipe（推荐方式）
frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt

# 输出到剪贴板
frago recipe run upwork_extract_job_details_as_markdown \
    --params '{"url": "..."}' \
    --output-clipboard
```

**支持选项**：
- `--format [table/json/names]` - 输出格式（list命令）
- `--source [project/user/example/all]` - 过滤Recipe来源（list命令）
- `--type [atomic/workflow/all]` - 过滤Recipe类型（list命令）
- `--params '{...}'` - JSON参数（run命令）
- `--params-file <path>` - 从文件读取参数（run命令）
- `--output-file <path>` - 保存输出到文件
- `--output-clipboard` - 复制输出到剪贴板
- `--timeout <seconds>` - 执行超时时间

### 使用Recipe的三种方式

```bash
# 方式1: 推荐 - 元数据驱动（参数验证、输出处理）
frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file transcript.txt

# 方式2: 发现可用的Recipe
frago recipe list --format json

# 方式3: 传统方式 - 直接执行JS（绕过元数据系统）
frago chrome exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
```

### 可用的示例Recipe

当前提供4个示例Recipe：

| 名称 | 功能 | 支持输出 |
|------|------|----------|
| `test_inspect_tab` | 获取当前标签页诊断信息（标题、URL、DOM统计） | stdout |
| `youtube_extract_video_transcript` | 提取YouTube视频完整字幕 | stdout, file |
| `upwork_extract_job_details_as_markdown` | 提取Upwork职位详情为Markdown格式 | stdout, file |
| `x_extract_tweet_with_comments` | 提取X(Twitter)推文和评论 | stdout, file, clipboard |

### 创建和更新Recipe

通过 `/frago.recipe` 命令（Claude Code Slash Command）管理Recipe：

```
# 创建新Recipe（AI交互式引导）
/frago.recipe create "在YouTube视频页面提取完整字幕内容"

# 更新现有Recipe
/frago.recipe update youtube_extract_subtitles "YouTube改版后字幕按钮失效了"

# 列出所有Recipe
/frago.recipe list
```

### Recipe 存储结构

- **位置**：`src/frago/recipes/`（引擎代码），`examples/atomic/chrome/`（示例 Recipe）
- **命名约定**：`<平台>_<功能描述>.js`（例如 `youtube_extract_subtitles.js`）
- **配套文档**：每个 Recipe 脚本（.js）都有对应的 Markdown 文档（.md）
- **执行方式**：`frago recipe run <recipe_name>`

---

## 会话监控

Session 系统提供 AI agent 执行数据的实时监控和持久化。

### 会话命令

```bash
# 列出所有会话
frago session list
frago session list --status running   # 仅运行中的会话
frago session list --agent claude     # 仅 Claude Code 会话

# 显示会话详情
frago session show <session_id>
frago session show <session_id> --format json

# 实时监控会话
frago session watch                    # 监控最新会话
frago session watch <session_id>       # 监控指定会话
frago session watch --json             # JSON 输出格式
```

### 会话存储

会话数据存储在 `~/.frago/sessions/{agent_type}/{session_id}/`：

```
~/.frago/sessions/claude/abc123-def456/
├── metadata.json    # 会话元数据（项目、时间、状态）
├── steps.jsonl      # 执行步骤（消息、工具调用）
└── summary.json     # 会话摘要（工具调用统计）
```

### 与 frago agent 集成

运行 `frago agent "任务"` 时，会话监控自动：
1. 开始监控 `~/.claude/projects/...` 的文件变化
2. 通过时间戳关联新会话（10 秒窗口）
3. 增量解析 JSONL 记录
4. 显示实时执行状态
5. 持久化会话数据到 `~/.frago/sessions/`

```bash
# 执行带会话监控的任务
frago agent "从网站提取数据"

# 输出显示实时状态：
# [Session] 已启动: abc123
# [Step 1] 用户消息: 从网站提取数据
# [Tool] 读取文件: /home/user/project/README.md (成功)
# [Tool] WebFetch: https://example.com (成功)
# [Session] 已完成: 5 步骤, 3 工具调用
```

---

## GUI 模式

Frago 为偏好图形交互的用户提供桌面 GUI 界面。

### 启动 GUI

```bash
# 启动 GUI
frago gui

# 启动调试模式（启用开发者工具）
frago gui --debug
```

### GUI 要求

GUI 已默认包含——无需额外安装。

**平台特定系统依赖**：

| 平台 | 后端 | 额外依赖 |
|------|------|----------|
| Linux | WebKit2GTK | `sudo apt install python3-gi gir1.2-webkit2-4.1` |
| macOS | WKWebView | 无（内置） |
| Windows | WebView2 | Edge WebView2 Runtime（推荐） |

### GUI 功能

GUI 提供：

- **Recipe 浏览器**：列出、查看详情和执行 recipe
- **命令输入**：执行 frago 命令并可视化反馈
- **状态显示**：实时连接和执行状态
- **历史记录**：查看命令和执行历史

### GUI 设计

GUI 使用 GitHub Dark 配色方案，适合长时间使用：

- **背景**：深蓝灰色（`#0d1117`）
- **强调色**：柔和蓝色（`#58a6ff`）
- **文本**：高对比度但不刺眼
- **布局**：清晰的视觉层次，输入区域作为焦点

---

## 项目目录结构

每个 Run 实例会在 `projects/<run_id>/` 目录下创建以下结构：

```
projects/<run_id>/
├── logs/
│   └── execution.jsonl      # 结构化执行日志
├── screenshots/             # 带时间戳的截图
│   └── 20250124_143022.png
├── scripts/                 # 已验证的工作脚本
│   └── extract_transcript.js
└── outputs/                 # 结果文件
    ├── result.json
    └── report.md
```

## 资源管理

你的 skills 和 recipes 是个人资产——你发现的工作流模式、你构建的自动化脚本。它们不应该被绑定在单台机器上。

### Sync 命令

`sync` 命令处理本地系统和私有 Git 仓库之间的双向同步：

```bash
# 首次使用：配置你的私有仓库
frago sync --set-repo git@github.com:you/my-frago-resources.git

# 日常使用
frago sync              # 推送本地变更并拉取远程更新
frago sync --dry-run    # 预览将要同步的内容
frago sync --no-push    # 仅拉取，不推送
frago sync -m "message" # 自定义提交信息
```

### 同步范围

| 资源类型 | 模式 | 位置 |
|---------|------|------|
| Skills | `frago-*` 前缀 | `~/.claude/skills/` |
| Recipes | 所有配方 | `~/.frago/recipes/` |

你的个人非 Frago 的 Claude 命令和 skills **永远不会被触及**。

---

## 故障排除

### 常见问题

**问题**：CDP 连接超时
```
Error: Failed to connect to Chrome CDP at ws://localhost:9222
```

**解决方案**：
1. 检查 Chrome 是否以 CDP 模式运行：
   ```bash
   # macOS
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
       --remote-debugging-port=9222 \
       --user-data-dir=./chrome_profile

   # Linux
   google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug
   ```
2. 验证端口 9222 可访问：`lsof -i :9222`
3. 检查代理配置（如使用代理）

---

**问题**：Recipe 未找到
```
Error: Recipe 'youtube_extract_subtitles' not found
```

**解决方案**：
1. 列出可用 Recipe：`frago recipe list`
2. 检查 Recipe 名称拼写（需精确匹配）
3. 确认元数据文件（.md）与脚本文件配对存在

---

**问题**：截图保存失败
```
Error: Failed to save screenshot to /path/to/screenshot.png
```

**解决方案**：
1. 使用绝对路径保存截图文件
2. 确保目标目录存在：`mkdir -p screenshots/`
3. 检查文件写入权限

---

### Linux 特定问题

**问题**：`pip: command not found`

**解决方案**：
```bash
# Ubuntu/Debian
sudo apt install python3-pip

# Fedora
sudo dnf install python3-pip

# Arch Linux
sudo pacman -S python-pip

# 替代方案：使用 python -m pip
python3 -m pip install frago-cli
```

---

**问题**：`npm EACCES permission denied`
```
npm ERR! Error: EACCES: permission denied, mkdir '/usr/local/lib/node_modules'
```

**解决方案**：
```bash
# 方法 1：使用 nvm（推荐）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc  # 或 ~/.zshrc
nvm install --lts

# 方法 2：修改 npm 全局目录
mkdir -p ~/.npm-global
npm config set prefix ~/.npm-global
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```

---

**问题**：安装后 `nvm: command not found`

**解决方案**：
```bash
# 确保 nvm 在当前 shell 中加载
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 添加到 ~/.bashrc 或 ~/.zshrc 以持久化
echo 'export NVM_DIR="$HOME/.nvm"' >> ~/.bashrc
echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> ~/.bashrc
source ~/.bashrc
```

---

**问题**：Linux 上 Chrome CDP 连接问题

**解决方案**：
```bash
# 1. 验证 Chrome 已安装
google-chrome --version

# 2. 以 CDP 模式启动 Chrome
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# 3. 验证 CDP 端口正在监听
lsof -i :9222 | grep LISTEN
curl http://localhost:9222/json/version

# 4. 如果端口 9222 被占用
# 查找占用端口的进程
lsof -i :9222
# 终止进程或使用其他端口
google-chrome --remote-debugging-port=9223 --user-data-dir=/tmp/chrome-debug
```

---

**问题**：Node.js 版本不匹配
```
Error: Node.js version 18.x detected, but 20.0.0 or higher is required
```

**解决方案**：
```bash
# 使用 nvm
nvm install 20
nvm use 20
nvm alias default 20

# 验证
node --version
```

---

### macOS 特定问题

**问题**：`pip: command not found`

**解决方案**：
```bash
# macOS 使用 pip3，而非 pip
pip3 install frago-cli

# 或使用 python3 -m pip（最可靠）
python3 -m pip install frago-cli
```

---

**问题**：`xcrun: error: invalid active developer path`
```
xcrun: error: invalid active developer path (/Library/Developer/CommandLineTools)
```

**解决方案**：
```bash
# 安装 Xcode 命令行工具
xcode-select --install

# 如果已安装但损坏，重置
sudo xcode-select --reset
```

---

**问题**：macOS 上的 Chrome CDP 连接

**解决方案**：
```bash
# 1. 以 CDP 模式启动 Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=~/.frago/chrome_profile

# 2. 验证 CDP 正在运行
lsof -i :9222 | grep LISTEN
curl http://localhost:9222/json/version

# 3. 如果端口被占用，查找并终止进程
lsof -i :9222
kill -9 <PID>
```

---

**问题**：Homebrew Node.js 与 nvm 冲突

**解决方案**：
```bash
# 如果你有 Homebrew 的 Node.js 并想使用 nvm：
brew uninstall node

# 如果想保留 Homebrew 的 Node.js，确保版本为 20+
node --version

# 通过 Homebrew 安装特定版本
brew install node@20
```

---

**问题**：Gatekeeper 阻止下载的应用

**解决方案**：
```bash
# 如果 Chrome 或其他应用被阻止，在系统偏好设置中允许：
# 系统偏好设置 → 安全性与隐私 → 通用 → "允许从以下位置下载的应用"

# 或移除隔离属性（谨慎使用）
xattr -d com.apple.quarantine /path/to/app
```

---

### Windows 特定问题

**问题**：`python` 或 `pip` 无法识别
```
'python' is not recognized as an internal or external command
```

**解决方案**：
```powershell
# 方法 1：使用 py 启动器（如已安装）
py -m pip install frago-cli

# 方法 2：将 Python 添加到 PATH
# 重新安装 Python 并勾选 "Add Python to PATH"
# 或手动添加到系统环境变量：
# C:\Users\<用户名>\AppData\Local\Programs\Python\Python311\
# C:\Users\<用户名>\AppData\Local\Programs\Python\Python311\Scripts\

# 方法 3：使用 Microsoft Store 的 Python
# 在 Microsoft Store 搜索 "Python 3.11"
```

---

**问题**：安装后 `node` 无法识别
```
'node' is not recognized as an internal or external command
```

**解决方案**：
```powershell
# Node.js 安装后重启 PowerShell

# 如果仍然不行，手动添加到 PATH：
# C:\Program Files\nodejs\

# 验证安装
node --version
```

---

**问题**：npm 全局包找不到（如 claude）
```
'claude' is not recognized as an internal or external command
```

**解决方案**：
```powershell
# 将 npm 全局目录添加到 PATH
$env:PATH += ";$env:APPDATA\npm"

# 永久生效，添加到用户环境变量：
# 系统属性 → 环境变量 → 用户变量 → Path → 添加：
# %APPDATA%\npm

# 然后重启 PowerShell
```

---

**问题**：PowerShell 脚本执行被禁用
```
cannot be loaded because running scripts is disabled on this system
```

**解决方案**：
```powershell
# 为当前用户启用脚本执行
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 验证
Get-ExecutionPolicy -List
```

---

**问题**：Windows 上的 Chrome CDP 连接

**解决方案**：
```powershell
# 1. 以 CDP 模式启动 Chrome
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="$env:USERPROFILE\.frago\chrome_profile"

# 2. 验证 CDP 正在运行
Test-NetConnection -ComputerName localhost -Port 9222
Invoke-WebRequest -Uri "http://localhost:9222/json/version"

# 3. 如果端口被占用，查找进程
netstat -ano | findstr :9222
# 然后按 PID 终止：
taskkill /PID <PID> /F
```

---

**问题**：Windows 不支持自动安装 Node.js
```
Error: Windows 不支持自动安装 Node.js
```

**解决方案**：
```powershell
# 必须在运行 frago init 之前手动安装 Node.js
winget install OpenJS.NodeJS.LTS

# 或从 https://nodejs.org/ 下载

# 验证安装
node --version  # 应为 20.x 或更高版本
```

---

## 注意事项

1. Chrome 必须启用 CDP 模式运行，保持 9222 端口可用
2. 所有截图和输出文件必须使用绝对路径
3. Recipe 执行前确保元数据文件（.md）与脚本文件配对
4. GUI 模式已默认包含，Linux 需要安装系统依赖（WebKit2GTK）
5. 会话监控依赖 watchdog，自动随基础包安装
