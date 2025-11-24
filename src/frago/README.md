# Frago - Chrome DevTools Protocol CLI

Frago 是一个强大的命令行工具，通过 Chrome DevTools Protocol (CDP) 与浏览器进行交互，支持页面导航、元素操作、截图、JavaScript执行等功能。

## 快速开始

### 启动 Chrome CDP 服务

```bash
# 启动 Chrome CDP launcher（后台运行）
uv run python src/chrome_cdp_launcher.py &

# 或使用提供的脚本
./scripts/start_cdp.sh
```

### 基本使用

```bash
# 查看帮助
uv run frago --help

# 查看特定命令的帮助
uv run frago <命令> --help
```

---

## 全局选项

所有命令都支持以下全局选项：

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--debug` | flag | false | 启用调试模式，输出详细日志 |
| `--timeout` | int | 30 | 操作超时时间（秒） |
| `--host` | string | 127.0.0.1 | CDP主机地址 |
| `--port` | int | 9222 | CDP端口 |
| `--proxy-host` | string | - | 代理服务器主机地址 |
| `--proxy-port` | int | - | 代理服务器端口 |
| `--proxy-username` | string | - | 代理认证用户名 |
| `--proxy-password` | string | - | 代理认证密码 |
| `--no-proxy` | flag | false | 绕过代理连接 |

**示例：**

```bash
# 使用调试模式
uv run frago --debug navigate https://youtube.com

# 设置60秒超时
uv run frago --timeout 60 navigate https://youtube.com

# 使用代理
uv run frago --proxy-host 127.0.0.1 --proxy-port 7890 navigate https://youtube.com
```

---

## 命令列表

### 1. `navigate` - 页面导航

导航到指定URL。

**语法：**
```bash
uv run frago navigate <URL> [--wait-for SELECTOR]
```

**参数：**
- `URL` - 目标网址（必需）
- `--wait-for` - 等待选择器出现后再返回（可选）

**示例：**

```bash
# 基本导航
uv run frago navigate https://youtube.com

# 导航并等待搜索框出现
uv run frago navigate https://youtube.com --wait-for "input[name='search_query']"

# 导航到其他网站
uv run frago navigate https://github.com
uv run frago navigate https://google.com
```

---

### 2. `get-title` - 获取页面标题

获取当前页面的标题。

**语法：**
```bash
uv run frago get-title
```

**示例：**

```bash
# 获取YouTube页面标题
uv run frago get-title
# 输出: (15) YouTube

# 配合导航使用
uv run frago navigate https://youtube.com && uv run frago get-title
```

---

### 3. `get-content` - 获取页面内容

获取页面或指定元素的文本内容。

**语法：**
```bash
uv run frago get-content [SELECTOR]
```

**参数：**
- `SELECTOR` - CSS选择器，默认为 `body`（可选）

**示例：**

```bash
# 获取整个页面的文本内容
uv run frago get-content

# 获取特定元素的内容
uv run frago get-content "h1#video-title"
uv run frago get-content ".channel-name"
uv run frago get-content "#description"

# 获取搜索框的placeholder
uv run frago get-content "input[name='search_query']"
```

---

### 4. `click` - 点击元素

点击指定选择器的元素。

**语法：**
```bash
uv run frago click <SELECTOR> [--wait-timeout SECONDS]
```

**参数：**
- `SELECTOR` - CSS选择器（必需）
- `--wait-timeout` - 等待元素出现的超时时间（秒），默认10秒

**示例：**

```bash
# 点击YouTube搜索框
uv run frago click "input[name='search_query']"

# 点击搜索按钮
uv run frago click "button#search-icon-legacy"

# 点击第一个视频
uv run frago click "ytd-video-renderer:first-child"

# 等待30秒后点击
uv run frago click ".subscribe-button" --wait-timeout 30
```

---

### 5. `screenshot` - 页面截图

截取页面截图并保存到文件。

**语法：**
```bash
uv run frago screenshot <OUTPUT_FILE> [--full-page] [--quality QUALITY]
```

**参数：**
- `OUTPUT_FILE` - 输出文件路径（必需）
- `--full-page` - 截取整个页面（包括滚动区域）
- `--quality` - 图片质量（1-100），默认80

**示例：**

```bash
# 截取可见区域
uv run frago screenshot youtube_viewport.png

# 截取完整页面，高质量
uv run frago screenshot youtube_full.png --full-page --quality 95

# 截取中等质量
uv run frago screenshot youtube_medium.png --quality 50

# 截取特定时刻的页面
uv run frago navigate https://youtube.com && \
uv run frago wait 2 && \
uv run frago screenshot youtube_loaded.png
```

---

### 6. `exec-js` - 执行JavaScript

在页面上下文中执行JavaScript代码。

**语法：**
```bash
uv run frago exec-js <SCRIPT> [--return-value]
```

**参数：**
- `SCRIPT` - JavaScript代码（必需）
- `--return-value` - 返回JavaScript执行结果

**示例：**

```bash
# 执行简单脚本
uv run frago exec-js "console.log('Hello YouTube')"

# 获取页面标题
uv run frago exec-js "document.title" --return-value

# 修改搜索框的值
uv run frago exec-js "document.querySelector(\"input[name='search_query']\").value='Claude AI'"

# 获取视频数量
uv run frago exec-js "document.querySelectorAll('ytd-video-renderer').length" --return-value

# 滚动到页面底部
uv run frago exec-js "window.scrollTo(0, document.body.scrollHeight)"

# 检查元素是否存在
uv run frago exec-js "document.querySelector(\"input[name='search_query']\") ? 'exists' : 'not found'" --return-value

# 获取页面URL
uv run frago exec-js "window.location.href" --return-value
```

---

### 7. `scroll` - 页面滚动

滚动页面指定的像素距离。

**语法：**
```bash
uv run frago scroll <DISTANCE>
```

**参数：**
- `DISTANCE` - 滚动距离（像素），正数向下，负数向上

**示例：**

```bash
# 向下滚动500像素
uv run frago scroll 500

# 向上滚动300像素
uv run frago scroll -300

# 滚动到底部（多次滚动）
uv run frago scroll 1000 && \
uv run frago scroll 1000 && \
uv run frago scroll 1000

# 滚动后截图
uv run frago scroll 500 && \
uv run frago screenshot youtube_scrolled.png
```

---

### 8. `wait` - 等待

等待指定的秒数。

**语法：**
```bash
uv run frago wait <SECONDS>
```

**参数：**
- `SECONDS` - 等待秒数（可以是小数）

**示例：**

```bash
# 等待2秒
uv run frago wait 2

# 等待0.5秒
uv run frago wait 0.5

# 等待5秒让页面加载
uv run frago navigate https://youtube.com && \
uv run frago wait 5 && \
uv run frago screenshot youtube_loaded.png
```

---

### 9. `zoom` - 页面缩放

设置页面的缩放比例。

**语法：**
```bash
uv run frago zoom <FACTOR>
```

**参数：**
- `FACTOR` - 缩放因子（0.5-3.0），1.0为100%

**示例：**

```bash
# 放大到150%
uv run frago zoom 1.5

# 缩小到75%
uv run frago zoom 0.75

# 恢复100%
uv run frago zoom 1.0

# 放大后截图
uv run frago zoom 1.5 && \
uv run frago screenshot youtube_zoomed.png
```

---

### 10. `status` - 连接状态检查

检查CDP连接状态和Chrome浏览器信息。

**语法：**
```bash
uv run frago status
```

**示例：**

```bash
# 检查连接状态
uv run frago status

# 输出示例:
# ✓ CDP连接正常
# Browser: Chrome/120.0.6099.109
# Protocol-Version: 1.3
# WebKit-Version: 537.36
```

---

### 11. `highlight` - 高亮元素

高亮显示指定的页面元素。

**语法：**
```bash
uv run frago highlight <SELECTOR> [--color COLOR] [--width WIDTH]
```

**参数：**
- `SELECTOR` - CSS选择器（必需）
- `--color` - 高亮颜色，默认 `yellow`
- `--width` - 高亮边框宽度（像素），默认3

**示例：**

```bash
# 默认高亮（黄色，3像素）
uv run frago highlight "input[name='search_query']"

# 红色高亮，5像素边框
uv run frago highlight "input[name='search_query']" --color red --width 5

# 蓝色高亮搜索按钮
uv run frago highlight "button#search-icon-legacy" --color blue --width 3

# 高亮所有视频标题
uv run frago highlight "ytd-video-renderer h3" --color green --width 2

# 高亮后截图
uv run frago highlight "input[name='search_query']" --color red --width 5 && \
uv run frago screenshot youtube_highlighted.png
```

---

### 12. `pointer` - 显示鼠标指针

在指定元素上显示鼠标指针动画。

**语法：**
```bash
uv run frago pointer <SELECTOR>
```

**参数：**
- `SELECTOR` - CSS选择器（必需）

**示例：**

```bash
# 在搜索框上显示指针
uv run frago pointer "input[name='search_query']"

# 在订阅按钮上显示指针
uv run frago pointer ".subscribe-button"

# 显示指针后截图
uv run frago pointer "button#search-icon-legacy" && \
uv run frago wait 1 && \
uv run frago screenshot youtube_pointer.png
```

---

### 13. `spotlight` - 聚光灯效果

使用聚光灯效果突出显示元素（其他区域变暗）。

**语法：**
```bash
uv run frago spotlight <SELECTOR>
```

**参数：**
- `SELECTOR` - CSS选择器（必需）

**示例：**

```bash
# 聚光灯显示搜索框
uv run frago spotlight "input[name='search_query']"

# 聚光灯显示第一个视频
uv run frago spotlight "ytd-video-renderer:first-child"

# 聚光灯后截图
uv run frago spotlight "input[name='search_query']" && \
uv run frago screenshot youtube_spotlight.png
```

---

### 14. `annotate` - 添加标注

在元素上添加文本标注。

**语法：**
```bash
uv run frago annotate <SELECTOR> <TEXT> [--position POSITION]
```

**参数：**
- `SELECTOR` - CSS选择器（必需）
- `TEXT` - 标注文本（必需）
- `--position` - 标注位置（`top`/`bottom`/`left`/`right`），默认 `top`

**示例：**

```bash
# 顶部标注
uv run frago annotate "input[name='search_query']" "这是搜索框"

# 右侧标注
uv run frago annotate "button#search-icon-legacy" "点击搜索" --position right

# 底部标注
uv run frago annotate ".subscribe-button" "订阅频道" --position bottom

# 左侧标注
uv run frago annotate "#logo" "YouTube Logo" --position left

# 标注后截图
uv run frago annotate "input[name='search_query']" "搜索框" --position top && \
uv run frago screenshot youtube_annotated.png
```

---

### 15. `clear-effects` - 清除视觉效果

清除所有由Frago添加的视觉效果（高亮、指针、聚光灯、标注）。

**语法：**
```bash
uv run frago clear-effects
```

**示例：**

```bash
# 清除所有视觉效果
uv run frago clear-effects

# 添加多个效果后清除
uv run frago highlight "input[name='search_query']" --color red --width 5 && \
uv run frago annotate "input[name='search_query']" "搜索框" && \
uv run frago wait 2 && \
uv run frago clear-effects
```

---

## 完整示例：YouTube搜索流程

以下是一个完整的YouTube搜索操作流程示例：

```bash
# 1. 导航到YouTube首页
uv run frago navigate https://youtube.com

# 2. 等待页面加载
uv run frago wait 2

# 3. 检查页面标题
uv run frago get-title

# 4. 高亮搜索框
uv run frago highlight "input[name='search_query']" --color blue --width 3

# 5. 添加标注
uv run frago annotate "input[name='search_query']" "在这里输入搜索关键词" --position top

# 6. 截图（带高亮和标注）
uv run frago screenshot youtube_step1.png

# 7. 清除视觉效果
uv run frago clear-effects

# 8. 点击搜索框
uv run frago click "input[name='search_query']"

# 9. 输入搜索关键词
uv run frago exec-js "document.querySelector(\"input[name='search_query']\").value='Claude AI'"

# 10. 等待输入完成
uv run frago wait 0.5

# 11. 点击搜索按钮
uv run frago click "button#search-icon-legacy"

# 12. 等待搜索结果加载
uv run frago wait 3

# 13. 获取页面标题（验证搜索成功）
uv run frago get-title

# 14. 截取搜索结果页面
uv run frago screenshot youtube_search_results.png --full-page

# 15. 滚动查看更多结果
uv run frago scroll 1000

# 16. 截图
uv run frago screenshot youtube_scrolled.png
```

---

## 组合使用技巧

### 1. 使用Shell脚本自动化

```bash
#!/bin/bash
# youtube_search.sh - 自动化YouTube搜索

SEARCH_QUERY="$1"

if [ -z "$SEARCH_QUERY" ]; then
    echo "用法: $0 <搜索关键词>"
    exit 1
fi

# 导航到YouTube
uv run frago navigate https://youtube.com
uv run frago wait 2

# 搜索
uv run frago click "input[name='search_query']"
uv run frago exec-js "document.querySelector(\"input[name='search_query']\").value='$SEARCH_QUERY'"
uv run frago click "button#search-icon-legacy"
uv run frago wait 3

# 截图
uv run frago screenshot "youtube_search_${SEARCH_QUERY// /_}.png"

echo "搜索完成: $SEARCH_QUERY"
```

使用：
```bash
chmod +x youtube_search.sh
./youtube_search.sh "Claude AI"
```

### 2. 使用 `&&` 链式调用

```bash
# 一行完成多个操作
uv run frago navigate https://youtube.com && \
uv run frago wait 2 && \
uv run frago highlight "input[name='search_query']" --color red --width 5 && \
uv run frago screenshot youtube.png
```

### 3. 调试模式

```bash
# 使用调试模式查看详细信息
uv run frago --debug navigate https://youtube.com
uv run frago --debug exec-js "document.title" --return-value
```

---

## 常见选择器（YouTube）

以下是YouTube页面的常用CSS选择器：

| 元素 | 选择器 |
|------|--------|
| 搜索框 | `input[name='search_query']` |
| 搜索按钮 | `button#search-icon-legacy` |
| 视频渲染器 | `ytd-video-renderer` |
| 视频标题 | `#video-title` |
| 频道名称 | `.channel-name` |
| 订阅按钮 | `.subscribe-button` |
| Logo | `#logo` |
| 导航栏 | `#masthead` |

---

## 故障排查

### 问题：命令超时

**解决方案：**
```bash
# 增加超时时间
uv run frago --timeout 60 navigate https://youtube.com
```

### 问题：找不到元素

**解决方案：**
```bash
# 1. 先检查元素是否存在
uv run frago exec-js "document.querySelector('YOUR_SELECTOR') ? 'found' : 'not found'" --return-value

# 2. 获取页面HTML查看结构
uv run frago exec-js "document.body.innerHTML.substring(0, 2000)" --return-value

# 3. 等待元素加载
uv run frago wait 5
```

### 问题：CDP连接失败

**解决方案：**
```bash
# 1. 检查CDP服务是否运行
uv run frago status

# 2. 重启CDP服务
killall chrome
uv run python src/chrome_cdp_launcher.py &

# 3. 检查端口是否被占用
lsof -i :9222
```

---

## 代理配置

Frago支持通过代理访问网页。

### 使用命令行参数

```bash
uv run frago \
  --proxy-host 127.0.0.1 \
  --proxy-port 7890 \
  navigate https://youtube.com
```

### 使用环境变量

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
uv run frago navigate https://youtube.com
```

### 带认证的代理

```bash
uv run frago \
  --proxy-host proxy.example.com \
  --proxy-port 8080 \
  --proxy-username user \
  --proxy-password pass \
  navigate https://youtube.com
```

### 绕过代理

```bash
# 忽略环境变量和代理配置
uv run frago --no-proxy navigate https://youtube.com
```

---

## 性能优化建议

1. **复用连接**：尽量在一次会话中执行多个操作，减少连接开销
2. **合理设置超时**：根据网络情况调整 `--timeout`
3. **使用wait命令**：给页面足够的加载时间
4. **适当的截图质量**：根据需求调整 `--quality` 参数

---

## 技术栈

- Python 3.12+
- Click - CLI框架
- websocket-client - WebSocket通信
- Pydantic - 数据验证
- Chrome DevTools Protocol

---

## 相关链接

- [Chrome DevTools Protocol 文档](https://chromedevtools.github.io/devtools-protocol/)
- [项目仓库](https://github.com/yourusername/Frago)
- [问题反馈](https://github.com/yourusername/Frago/issues)

---

## 许可证

[在此添加许可证信息]

---

**最后更新**: 2025-11-18
