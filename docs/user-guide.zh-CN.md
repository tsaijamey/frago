# 使用指南

[English](user-guide.md)

## CDP 命令

所有浏览器控制通过 `frago chrome <command>`：

```bash
# 导航
frago chrome navigate <url>
frago chrome status

# 交互
frago chrome click <selector>
frago chrome scroll <direction> <pixels>
frago chrome wait <seconds>

# JavaScript
frago chrome exec-js <expression> --return-value

# 截图
frago chrome screenshot <output_file>

# 视觉效果
frago chrome spotlight <selector> --duration 3
frago chrome highlight <selector> --color "#FF6B6B"
frago chrome annotate <selector> "text" --position top
```

### 代理配置

```bash
# 环境变量
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# CLI 参数
frago chrome navigate https://example.com --proxy-host proxy.example.com --proxy-port 8080
frago chrome navigate https://example.com --no-proxy
```

## Recipe 管理

```bash
# 发现
frago recipe list                    # 列出所有配方
frago recipe list --format json      # JSON 格式（供 AI 使用）
frago recipe list --source user      # 按来源过滤
frago recipe list --type atomic      # 按类型过滤

# 信息
frago recipe info <name>             # 查看详情
frago recipe info <name> --format json

# 执行
frago recipe run <name> --params '{"url": "..."}'
frago recipe run <name> --params-file params.json
frago recipe run <name> --output-file result.txt
frago recipe run <name> --output-clipboard
frago recipe run <name> --timeout 300
```

### Recipe 优先级

```
1. Project (.frago/recipes/)     ← 最高（项目级）
2. User (~/.frago/recipes/)      ← 中等（个人）
3. Example (examples/)           ← 最低（官方示例）
```

### 内置 Recipe

| 名称 | 功能 | 类型 |
|------|------|------|
| `x_extract_tweet_with_comments` | 提取 X/Twitter 帖子及评论 | chrome |
| `youtube_download_video_ytdlp` | 使用 yt-dlp 下载 YouTube 视频 | system |
| `bilibili_download_video` | 下载 B站视频 | system |
| `arxiv_search_papers` | 在 arXiv 搜索论文 | system |
| `volcengine_tts_with_emotion` | 带情感支持的文字转语音 | system |

> 使用 `frago recipe list` 查看完整列表

## Run 系统

```bash
# 生命周期
frago run init "任务描述"             # 创建 run 实例
frago run set-context <run_id>       # 设置工作上下文
frago run info <run_id>              # 查看详情
frago run list                       # 列出所有 run
frago run archive <run_id>           # 归档已完成的 run

# 日志
frago run log --step "描述" --status success --action-type "类型"
```

### Run 目录结构

```
projects/<run_id>/
├── logs/execution.jsonl      # 结构化日志
├── screenshots/              # 带时间戳的截图
├── scripts/                  # 已验证的脚本
└── outputs/                  # 结果文件
```

## 会话监控

```bash
frago session list                   # 列出会话
frago session list --status running  # 按状态过滤
frago session show <session_id>      # 显示详情
frago session watch                  # 监控最新会话
frago session watch <session_id>     # 监控指定会话
```

## Web 服务

```bash
frago server start      # 在端口 8093 启动
frago server stop       # 停止服务
frago server status     # 检查状态
frago server --debug    # 前台运行带日志
```

访问：`http://127.0.0.1:8093`

### 功能

- **仪表板**：最近会话概览
- **任务**：交互式 Claude Code 控制台
- **配方**：浏览和执行配方
- **技能**：管理已安装技能
- **设置**：模型、外观、同步选项

## 资源同步

```bash
# 首次使用
frago sync --set-repo git@github.com:you/my-resources.git

# 日常使用
frago sync              # 双向同步
frago sync --dry-run    # 预览变更
frago sync --no-push    # 仅拉取
frago sync -m "message" # 自定义提交信息
```

### 同步范围

| 类型 | 模式 | 位置 |
|------|------|------|
| Skills | `frago-*` | `~/.claude/skills/` |
| Recipes | 所有 | `~/.frago/recipes/` |

## 故障排除

### CDP 连接

```bash
# 以 CDP 模式启动 Chrome
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 --user-data-dir=~/.frago/chrome_profile

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# Windows
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 --user-data-dir="$env:USERPROFILE\.frago\chrome_profile"

# 验证
curl http://localhost:9222/json/version
```

### 常见问题

| 问题 | 解决方案 |
|------|----------|
| CDP 超时 | 确保 Chrome 以 `--remote-debugging-port=9222` 运行 |
| Recipe 未找到 | 用 `frago recipe list` 检查名称拼写 |
| 截图失败 | 使用绝对路径，确保目录存在 |
| Node.js 版本 | 使用 nvm：`nvm install 20 && nvm use 20` |

---

**下一步**：[概念](concepts.zh-CN.md) · [架构](architecture.zh-CN.md) · [Recipe 系统](recipes.zh-CN.md)
