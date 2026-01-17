---
id: troubleshooting
title: 故障排查
category: troubleshooting
order: 5
version: 0.38.1
last_updated: 2026-01-17
tags:
  - troubleshooting
  - errors
  - debugging
  - chrome
---

# 故障排查

## Q: 为什么我在Console里发送消息，没有任何输出？

**A**: 最常见的4个原因：API Key未配置、任务还在执行中、Chrome未启动、任务描述不够清楚。按顺序排查。

**排查步骤**：

### 1. 检查API Key配置（最常见）

**症状**: 发送消息后，什么都没显示，或显示Authentication错误

**解决**:
1. Settings → General
2. 确认已填写API Key
3. Key格式：`sk-ant-...`（Anthropic）或第三方格式
4. 测试：发送简单消息"hello"

**相关问题**: 我在哪里填写API Key？（见配置相关章节）

---

### 2. 任务正在执行（耐心等待）

**症状**: 发送消息后，显示"Connecting..."或转圈，但无输出

**原因**: AI可能在：
- 🌐 访问网页（网页加载慢）
- 🔍 探索解决方案（首次任务需要思考）
- 📸 等待页面渲染完成

**解决**:
- ⏰ 等待30秒-1分钟
- 👀 观察右上角状态：Running/Thinking
- 💡 复杂网页可能需要更长时间

**提示**: 首次执行新类型任务比重复执行慢，这是正常的。

---

### 3. Chrome未连接（CDP未启动）

**症状**: 任务报错"Chrome not connected"或"CDP connection failed"

**原因**: frago需要Chrome DevTools Protocol (CDP)来操作浏览器

**解决**:
1. **启动Chrome**（推荐方法）:
   ```bash
   # 命令行启动（自动启用CDP）
   uv run frago chrome start
   ```

2. **检查Chrome是否已启动**:
   - 看任务栏/Dock是否有Chrome图标
   - 打开的Chrome是否显示"frago正在控制..."提示

3. **手动启动（高级）**:
   ```bash
   # Mac/Linux
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 --user-data-dir=~/.frago/chrome_profile

   # Windows
   "C:\Program Files\Google\Chrome\Application\chrome.exe" \
     --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\.frago\chrome_profile
   ```

**相关问题**: Chrome not connected详细排查（见下一个FAQ）

---

### 4. 任务描述不清楚

**症状**: AI回复了，但说"不理解"或"需要更多信息"

**原因**: 任务描述太模糊

**示例**:
```
❌ 不好: "帮我处理这个"
✅ 好: "帮我从 https://example.com 提取商品标题和价格"

❌ 不好: "自动化这个网站"
✅ 好: "每天早上9点访问 https://news.com，提取头条，发邮件给我"
```

**相关问题**: 如何提取网页数据？（见使用技巧章节）

---

## Q: Console显示"Chrome not connected"怎么办？

**A**: 按照以下步骤依次排查：启动Chrome → 检查端口 → 检查配置 → 重启服务。

### 快速解决（90%情况）

**1. 使用frago命令启动Chrome**
```bash
uv run frago chrome start
```

这会自动：
- ✅ 启动Chrome with CDP
- ✅ 使用正确的端口(9222)
- ✅ 使用frago专用profile

**2. 验证连接**
- 浏览器顶部会显示："frago正在控制此浏览器"
- Console应该能正常工作

---

### 详细排查步骤

**步骤1: 确认Chrome进程是否存在**

```bash
# Mac/Linux
ps aux | grep chrome | grep remote-debugging-port

# Windows（PowerShell）
Get-Process chrome | Where-Object {$_.CommandLine -like "*remote-debugging-port*"}
```

如果没有输出 → Chrome未以CDP模式启动，执行 `uv run frago chrome start`

---

**步骤2: 检查端口9222是否被占用**

```bash
# Mac/Linux
lsof -i :9222

# Windows（PowerShell）
netstat -ano | findstr :9222
```

**如果端口被占用**:
1. 杀死占用进程
2. 或者修改frago配置使用其他端口（高级）

---

**步骤3: 检查防火墙**

**Mac**: 系统设置 → 安全性 → 防火墙，确保允许Chrome

**Windows**: 控制面板 → Windows Defender防火墙 → 允许应用，勾选Chrome

---

**步骤4: 清理Chrome profile（最后手段）**

```bash
# 备份旧的profile
mv ~/.frago/chrome_profile ~/.frago/chrome_profile.bak

# 重新启动Chrome
uv run frago chrome start
```

---

### 高级配置（可选）

**自定义CDP端口**（如9222被占用）:

编辑 `~/.frago/config.json`:
```json
{
  "chrome": {
    "cdp_port": 9333  // 改为其他端口
  }
}
```

然后重启frago服务。

---

**常见错误信息**:

| 错误信息 | 原因 | 解决 |
|----------|------|------|
| `Connection refused` | Chrome未启动 | `frago chrome start` |
| `Port 9222 in use` | 端口被占用 | 杀死占用进程或换端口 |
| `Timeout connecting` | 防火墙阻止 | 检查防火墙设置 |
| `Protocol error` | Chrome版本太旧 | 更新Chrome到最新版 |

---

## Q: 我在Tasks里看到任务"Error"了，怎么调试？

**A**: 点击任务查看详细日志，根据错误类型采取对应解决方案。大部分错误可以通过查看执行步骤定位问题。

### 查看错误详情

**步骤1: 打开任务详情**
1. Tasks页面
2. 点击显示"Error"的任务
3. 查看"Execution Steps"部分

**步骤2: 定位错误位置**
- 🔴 红色标记的步骤 = 出错位置
- 📝 展开查看详细错误信息
- ⚠️ 注意Tool Call类型（Read/Bash/CDP等）

---

### 常见错误类型与解决

### 1. 文件/路径错误

**错误信息**:
```
FileNotFoundError: [Errno 2] No such file or directory: '/path/to/file.txt'
```

**原因**: 文件不存在或路径错误

**解决**:
- ✅ 检查文件是否存在
- ✅ 确认路径是否正确（绝对路径 vs 相对路径）
- ✅ 检查Working Directory设置

---

### 2. 权限错误

**错误信息**:
```
PermissionError: [Errno 13] Permission denied: '/System/...'
```

**原因**: 没有读写权限

**解决**:
- ✅ 避免操作系统保护目录
- ✅ 修改Working Directory到有权限的位置
- ✅ 检查文件权限: `ls -l filename`

---

### 3. 网页元素未找到

**错误信息**:
```
selector not found: .product-title
TimeoutError: Waiting for selector .product-title failed
```

**原因**:
- 网页结构改变
- 元素加载慢
- 选择器错误

**解决**:
```
重新让AI探索:
"请重新访问 https://example.com，检查页面结构，更新提取逻辑"
```

---

### 4. API/网络错误

**错误信息**:
```
requests.exceptions.ConnectionError
HTTPError: 403 Forbidden
```

**原因**: 网络问题或被网站屏蔽

**解决**:
- ✅ 检查网络连接
- ✅ 网站可能有反爬虫机制
- ✅ 尝试添加延时或模拟真实用户行为

---

### 5. Chrome/CDP错误

**错误信息**:
```
chrome not connected
CDP connection error
```

**解决**: 见上一个FAQ "Chrome not connected怎么办？"

---

### 调试技巧

**1. 复制错误信息问AI**

在Console中：
```
我在执行任务时遇到这个错误：
[粘贴完整错误信息]

请帮我分析原因并提供解决方案
```

**2. 查看完整日志**

```bash
# 命令行查看会话日志
uv run frago session view [session_id]
```

**3. 简化任务重试**

将复杂任务拆分：
```
原任务: "访问网站 → 登录 → 提取数据 → 保存"
拆分:
  步骤1: "访问网站并登录"（先验证这步OK）
  步骤2: "提取数据"
  步骤3: "保存数据"
```

**4. 截图辅助调试**

```
"请截图当前页面状态，我看看哪里出问题了"
```

---

### 错误类型速查表

| 错误关键词 | 常见原因 | 快速解决 |
|-----------|----------|----------|
| `FileNotFoundError` | 文件不存在 | 检查路径 |
| `PermissionError` | 无权限 | 改Working Directory |
| `selector not found` | 元素未找到 | 重新探索页面 |
| `ConnectionError` | 网络问题 | 检查网络 |
| `chrome not connected` | CDP未连接 | `frago chrome start` |
| `Authentication failed` | API Key错误 | 重新配置Key |
| `TimeoutError` | 等待超时 | 增加等待时间或检查网页 |

---

### 提交Bug报告（最后手段）

如果以上都无法解决：

1. **收集信息**:
   - 完整错误信息
   - 任务描述
   - frago版本: `uv run frago --version`
   - 操作系统

2. **提交Issue**:
   - GitHub: https://github.com/your-org/frago/issues
   - 包含上述信息
   - 如可能，提供复现步骤

**相关问题**: Authentication failed怎么办？（见配置相关章节）
