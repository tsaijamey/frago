---
id: configuration
title: 配置相关
category: config
order: 3
version: 0.38.1
last_updated: 2026-01-17
tags:
  - configuration
  - settings
  - api-key
  - model
  - sync
---

# 配置相关

## Q: 我在哪里填写Anthropic API Key？

**A**: 进入 **Settings → General → API Key** 填写。首次使用frago必须配置API Key才能让AI工作。

**详细步骤**：

1. **获取API Key**
   - 访问 [https://console.anthropic.com/](https://console.anthropic.com/)
   - 登录你的Anthropic账号（没有则注册）
   - 进入 API Keys 页面
   - 点击 "Create Key" 创建新密钥
   - 复制生成的Key（格式：`sk-ant-...`）

2. **在frago中配置**
   - 打开frago Web UI
   - 点击左侧 **Settings**
   - 选择 **General** 标签
   - 在 "API Endpoint" 区域，确保选择 **"Official Claude API"**
   - 在 "API Key" 输入框粘贴你的密钥
   - 点击 **"Save Configuration"**

3. **验证配置**
   - 进入 Console 或 Tasks
   - 发送一个简单消息，如 "hello"
   - 如果AI回复了，说明配置成功

**常见问题**：

❌ **显示 "Authentication failed"**
   - 检查Key是否完整复制（sk-ant-开头）
   - 检查账号是否有额度
   - 检查网络是否能访问Anthropic API

❌ **保存后没有反应**
   - 刷新页面重试
   - 检查浏览器Console是否有错误

**安全提示**：
⚠️ API Key是敏感信息，不要分享给他人。如果泄露，立即在Anthropic控制台删除该Key并创建新的。

**费用说明**：
💰 使用Anthropic API会产生费用，按Token计费。建议在Anthropic控制台设置使用限额避免意外花费。

**相关问题**: Authentication failed怎么办？（见故障排查章节）

---

## Q: Settings里的"Model Override"是什么？我该选哪个？

**A**: Model Override允许你覆盖默认的AI模型选择。新手建议保持默认（留空），frago会自动选择最合适的模型。

**模型对比**：

| 模型 | 速度 | 能力 | 成本 | 适用场景 |
|------|------|------|------|----------|
| **Sonnet** (默认) | ⚡⚡ 快 | 💪💪 强 | 💵 中等 | 日常任务、平衡性能 |
| **Opus** | ⚡ 较慢 | 💪💪💪 最强 | 💵💵💵 昂贵 | 复杂推理、代码生成 |
| **Haiku** | ⚡⚡⚡ 最快 | 💪 基础 | 💵 便宜 | 简单任务、快速响应 |

**字段说明**：

1. **Sonnet Model (optional override)**
   - 默认为空 → frago使用预设的Sonnet版本
   - 填写 → 覆盖为指定版本（如 `claude-sonnet-4-5-20251101`）

2. **Haiku Model (optional override)**
   - 用于快速任务（如生成任务标题）
   - 默认为空 → frago使用预设的Haiku版本

**使用建议**：

✅ **保持默认（推荐）**：
   - 让frago自动选择合适的模型版本
   - frago会跟随官方推荐更新

⚠️ **手动指定模型**：
   - 仅当你需要测试特定模型版本时
   - 需要了解模型版本命名规则
   - 例如：`claude-sonnet-4-5-20251101`

**示例场景**：

```
场景1: 日常使用
  Sonnet Model: [留空]
  Haiku Model: [留空]
  → frago使用默认配置，省心

场景2: 测试新模型
  Sonnet Model: claude-sonnet-4-5-20251101
  Haiku Model: [留空]
  → 主任务用指定Sonnet版本，辅助任务用默认Haiku

场景3: 降低成本
  Sonnet Model: [留空]
  Haiku Model: [留空]
  → 考虑使用Custom Endpoint接入第三方API（见下一问题）
```

**费用参考**（2026年1月）：
- Haiku: ~$0.25/M tokens (输入)
- Sonnet: ~$3/M tokens (输入)
- Opus: ~$15/M tokens (输入)

💡 **提示**: 不确定怎么选？保持默认就好！frago会根据任务类型自动选择。

---

## Q: "Endpoint Type"有什么区别？

**A**: Official Claude API是使用Anthropic官方API（推荐），Custom Endpoint用于接入第三方兼容API（高级用户）。

**两种模式对比**：

### 1. Official Claude API（官方API）

**特点**：
- ✅ 使用Anthropic官方服务
- ✅ 稳定可靠，功能完整
- ✅ 新手友好，配置简单
- ⚠️ 需要国际支付方式（信用卡）
- ⚠️ 可能需要科学上网

**配置方法**：
1. 选择 "Official Claude API"
2. 填写 API Key（从Anthropic获取）
3. 保存

### 2. Custom API Endpoint（自定义端点）

**特点**：
- ✅ 可接入第三方兼容服务（DeepSeek、Kimi、国内代理等）
- ✅ 支持本地部署的模型
- ⚠️ 需要自行配置URL和Key
- ⚠️ 功能可能不完整（取决于第三方实现）

**配置方法**：
1. 选择 "Custom API Endpoint"
2. 填写以下信息：
   - **API URL**: 第三方API地址（如 `https://api.example.com/v1`）
   - **API Key**: 第三方提供的密钥
   - **Default Model**: 主模型名称（如 `deepseek-chat`）
   - **Sonnet Model**: Sonnet模型名称（可选）
   - **Haiku Model**: Haiku模型名称（可选）
3. 保存

**切换风险提示**：

⚠️ **从Official切换到Custom会清除你的API Key配置，此操作不可撤销！**

在切换前请确认：
- 你有第三方API的完整信息
- 了解第三方API的限制和费用
- 已备份当前配置

**使用场景**：

| 场景 | 建议 |
|------|------|
| 首次使用frago | 使用Official Claude API |
| 无法访问Anthropic | 使用Custom Endpoint + 国内代理 |
| 降低成本 | 使用Custom Endpoint + 兼容的便宜模型 |
| 本地部署 | 使用Custom Endpoint + 本地模型 |
| 企业内网 | 使用Custom Endpoint + 内网代理 |

**示例配置（Custom Endpoint）**：

```
使用DeepSeek API:
  API URL: https://api.deepseek.com/v1
  API Key: sk-xxxxxxxxxxxxxxxx
  Default Model: deepseek-chat

使用中转代理:
  API URL: https://your-proxy.com/v1
  API Key: [代理提供的Key]
  Default Model: claude-sonnet-4-5
```

💡 **新手建议**: 优先使用Official Claude API，避免配置问题。

**相关问题**: API Key配置了但还是报错？（见故障排查章节）

---

## Q: Sync是干什么的？什么时候需要？

**A**: Sync用于跨设备同步你的Recipes和Skills，通过Git仓库实现。单机使用frago不需要配置Sync。

**Sync的作用**：

自动同步以下内容到Git仓库：
- ✅ 你的Recipes（`~/.frago/recipes/`）
- ✅ 你的Skills（`~/.frago/skills/`）
- ✅ Claude Code Commands配置
- ❌ 不同步Secrets（密钥）
- ❌ 不同步Session历史
- ❌ 不同步项目文件

**使用场景**：

| 场景 | 需要Sync？ |
|------|-----------|
| 只用一台电脑 | ❌ 不需要 |
| 多台电脑使用frago | ✅ 需要 |
| 团队协作开发Recipes | ✅ 需要 |
| 备份Recipes防丢失 | ✅ 需要（可选） |
| 分享Recipes给他人 | ❌ 用Community Recipes |

**配置步骤**：

1. **创建私有Git仓库**
   - 在GitHub创建私有仓库（如 `frago-sync`）
   - 确保仓库是私有的（因为可能包含敏感配置）

2. **在frago中配置**
   - Settings → Sync
   - 填写仓库URL
   - 配置GitHub认证（需要gh CLI）
   - 点击 "Sync Now" 测试

3. **自动同步**
   - 配置完成后，frago会在启动时自动同步
   - 也可以手动点击 "Sync Now"

**工作原理**：

```
设备A的修改 → Push到Git仓库 → Pull到设备B
     ↓                              ↓
~/.frago/recipes/            ~/.frago/recipes/
└── my-recipe.py            └── my-recipe.py
```

**安全注意事项**：

⚠️ **务必使用私有仓库！**
- Recipes可能包含敏感信息（URL、逻辑）
- 配置文件可能暴露你的使用习惯

⚠️ **Secrets不会同步**
- API密钥等敏感信息默认被排除
- 需要在每台设备单独配置

**新手建议**：

💡 如果你：
- 只用一台电脑
- 刚开始使用frago
- 还没创建自己的Recipes

**那就暂时不需要配置Sync**。等你创建了有价值的Recipes后再考虑备份和同步。

**相关问题**: Sync配置了但不工作？（检查gh CLI配置和仓库权限）

---

## Q: Secrets页面是干什么的？

**A**: Secrets用于安全存储API密钥、数据库密码等敏感信息，供Recipes使用。新手可以暂时跳过，等需要运行特定Recipes时再配置。

**为什么需要Secrets？**

很多Recipes需要访问外部服务，比如：
- 📧 发送邮件 → 需要SMTP密码
- 🗄️ 查询数据库 → 需要数据库密码
- 🤖 调用OpenAI → 需要OPENAI_API_KEY
- ☁️ 上传到S3 → 需要AWS凭证

**Secrets不会被同步或分享**，保证安全性。

**如何使用Secrets？**

**1. 在Secrets页面添加**：
```
Name: OPENAI_API_KEY
Value: sk-xxxxxxxxxxxxxxxx
```

**2. Recipe中引用**：
```python
import os

# frago会自动将Secrets注入环境变量
api_key = os.getenv("OPENAI_API_KEY")
```

**3. 运行Recipe**：
   - frago自动注入环境变量
   - Recipe可以直接使用
   - 不会在日志中显示密钥

**常见环境变量**：

| 变量名 | 用途 | 示例值 |
|--------|------|--------|
| `OPENAI_API_KEY` | OpenAI API | sk-... |
| `GITHUB_TOKEN` | GitHub API | ghp_... |
| `SMTP_PASSWORD` | 邮件发送 | your_password |
| `DATABASE_URL` | 数据库连接 | postgresql://... |

**何时需要配置？**

✅ **需要配置**：
- Recipe运行时报错 "Missing required environment variable"
- Recipe文档明确说明需要某个API Key
- Secrets页面显示"未配置"警告

❌ **不需要配置**：
- 只用frago的Console和Tasks
- 运行不需要外部服务的Recipes
- 刚开始学习frago

**安全提示**：

✅ **安全**：
- Secrets存储在本地（`~/.frago/secrets.json`）
- 不会同步到Git仓库
- 不会在Web UI中明文显示

⚠️ **注意**：
- 不要在Recipe代码中硬编码密钥
- 不要在日志中打印密钥
- 定期更换重要密钥

**示例场景**：

```
场景: 运行社区Recipe "send-email-report"

1. 查看Recipe文档，发现需要：
   - SMTP_HOST
   - SMTP_PORT
   - SMTP_USERNAME
   - SMTP_PASSWORD

2. 进入Settings → Secrets，添加这4个变量

3. 运行Recipe，填写其他参数（收件人、主题等）

4. Recipe自动使用Secrets中的SMTP配置发送邮件
```

**相关问题**: Recipe提示缺少环境变量怎么办？（按提示在Secrets页面添加）

---

## Q: "Working Directory"是什么？可以改吗？

**A**: Working Directory是AI执行任务的默认工作目录。通常不需要修改，除非你想让AI在特定目录下工作。

**Working Directory的作用**：

当AI执行文件操作时，相对路径基于这个目录：

```python
# Working Directory: /Users/you/projects

# AI执行: 读取 "data.json"
# 实际读取: /Users/you/projects/data.json

# AI执行: 创建 "output/result.csv"
# 实际创建: /Users/you/projects/output/result.csv
```

**默认值**：

- **Desktop模式**（pywebview）: `~/Desktop`
- **Server模式**（Web UI）: `~/.frago/projects/current_run/workspace`

**何时需要修改？**

✅ **适合修改**：
- 你有固定的项目目录（如 `~/my-project`）
- 需要让AI在特定目录下工作
- 便于管理AI生成的文件

❌ **不建议修改**：
- 刚开始使用frago
- 不确定设置什么目录
- 经常切换不同项目

**如何修改？**

1. Settings → General
2. 找到 "Working Directory"
3. 点击 "Edit" 按钮
4. 选择或输入目录路径
5. 保存

**注意事项**：

⚠️ **目录必须存在**：
- frago不会自动创建不存在的目录
- 设置前请确保目录已创建

⚠️ **权限问题**：
- 确保frago有读写权限
- 避免设置系统保护目录（如 `/System`）

⚠️ **路径格式**：
- **Mac/Linux**: `/Users/you/project` 或 `~/project`
- **Windows**: `C:/Users/you/project` 或使用正斜杠

**使用建议**：

💡 **推荐做法**：
1. 为frago创建专门的工作目录: `~/frago-workspace`
2. 在Settings中设置为Working Directory
3. 所有AI生成的文件都会在这里，方便管理

💡 **高级用法**：
- Run项目会创建在 `~/.frago/projects/[run_id]/`
- Working Directory不影响Run项目位置
- 可以在Console中临时切换目录：`cd /path/to/dir`

**示例**：

```
场景: 你在开发一个网站项目

1. 创建项目目录: ~/my-website
2. 设置Working Directory为: ~/my-website
3. 在Console中说: "帮我生成一个index.html"
4. AI会在~/my-website/index.html创建文件
```

**相关问题**: AI生成的文件找不到？（检查Working Directory设置和Workspace）
