# frago 示例参考

[English](examples.md)

本文档给出使用 frago 核心能力（浏览器自动化 + Recipe + 知识域沉淀）完成各类自动化任务的实际示例。

---

## 示例 1：交互式探索并把经验沉淀下来

**目标**：逐步探索 YouTube 字幕提取方法，产出落进事务目录，经验存进知识域。

### 第 1 步：先查现成落点，再建事务目录

```bash
# 先查这件事以前有没有落点，别拍脑袋造目录
frago context data:youtube

# 没命中就新建。两层缺一不可：<主体>/<YYYYMMDD>-<语义 slug>
mkdir -p ~/.frago/data/youtube/20260813-subtitle-extraction/scripts
```

### 第 2 步：导航与探索

```bash
# 打开 YouTube 视频
frago browser navigate https://www.youtube.com/watch?v=dQw4w9WgXcQ --group youtube-subtitle

# 截初始页面——绝对路径，直接落进事务目录
frago browser screenshot ~/.frago/data/youtube/20260813-subtitle-extraction/initial_page.png --group youtube-subtitle

# 检查页面结构
frago browser exec-js 'document.querySelector("button[aria-label*=\"transcript\"]")' --return-value --group youtube-subtitle
```

### 第 3 步：验证选择器可用

```bash
# 点击按钮并验证
frago browser click 'button[aria-label*="transcript"]' --group youtube-subtitle
frago browser screenshot ~/.frago/data/youtube/20260813-subtitle-extraction/transcript_opened.png --group youtube-subtitle
```

### 第 4 步：保存验证过的脚本

```bash
cat > ~/.frago/data/youtube/20260813-subtitle-extraction/scripts/extract_transcript.js <<'EOF'
(async () => {
  const button = document.querySelector('button[aria-label*="transcript"]');
  if (button) button.click();
  await new Promise(r => setTimeout(r, 1000));

  const segments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  return Array.from(segments).map(s => s.textContent.trim()).join('\n');
})();
EOF
```

### 第 5 步：把经验沉淀进知识域

```bash
# 先看有哪些域、域里已经有什么，别重复存
frago def list
frago browser-automation find

# 存成一篇文档，同名再存即更新
frago browser-automation save \
  --name=youtube-transcript-extraction \
  --data='{"tags": ["youtube", "transcript", "dom"]}' \
  --content='["[[[sequence]]][[点击 transcript 按钮]][[等 1 秒后读取 .ytd-transcript-segment-renderer 节点]]", "[[[constraint]]][[YouTube 字幕面板懒加载]][[不等待直接查询会拿到空列表]]"]'
```

**产出落点**：
```
~/.frago/data/youtube/20260813-subtitle-extraction/
├── session-id.yaml          # 落第一个文件时就写，追加不覆盖
├── initial_page.png
├── transcript_opened.png
└── scripts/
    └── extract_transcript.js
```

下次再碰同类问题：`frago context data:youtube` 找回这个目录，
`frago browser-automation find` 调出当时的经验。

---

## 示例 2：把探索成果固化为 Recipe

**目标**：把探索结果变成可复用的 Recipe。

### 用 CLI 创建

```bash
# 探索完成后
# 提取验证过的逻辑，创建 Recipe 文件

# 1. 创建 Recipe 脚本
mkdir -p ~/.frago/recipes/atomic/browser/youtube_extract_video_transcript
cat > ~/.frago/recipes/atomic/browser/youtube_extract_video_transcript/recipe.js <<'EOF'
(async () => {
  const button = document.querySelector('button[aria-label*="transcript"]');
  if (button) {
    button.click();
    await new Promise(r => setTimeout(r, 1000));
  }

  const segments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  const transcript = Array.from(segments).map(s => s.textContent.trim()).join('\n');

  return { transcript, segmentCount: segments.length };
})();
EOF

# 2. 创建 Recipe 元数据
cat > ~/.frago/recipes/atomic/browser/youtube_extract_video_transcript/recipe.md <<'EOF'
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
version: "1.0.0"
description: "从 YouTube 视频页面提取完整字幕内容"
use_cases:
  - "提取字幕用于翻译"
  - "创建字幕文件"
  - "分析视频内容"
tags: ["youtube", "transcript", "web-scraping"]
output_targets: [stdout, file]
inputs:
  url:
    type: string
    description: "YouTube 视频 URL"
    required: true
outputs:
  transcript:
    type: string
    description: "完整字幕文本"
  segmentCount:
    type: integer
    description: "字幕段数量"
---

# 功能说明
从 YouTube 视频页面提取完整字幕文本。

## 用法
\`\`\`bash
frago recipe run youtube_extract_video_transcript \\
  --params '{"url": "https://youtube.com/watch?v=..."}' \\
  --output-file transcript.txt
\`\`\`

## 前置条件
- 浏览器后端在运行——默认 extension 后端，或 `frago browser -b cdp start`
- 已打开 YouTube 视频页面
- 视频必须有字幕
EOF
```

### 用 Claude Code 创建

```
/frago.recipe create "提取 YouTube 视频字幕" from ~/.frago/data/youtube/20260813-subtitle-extraction/
```

AI 会：
1. 查看事务目录下的 scripts/ 与产出文件
2. 提取验证过的选择器
3. 生成 Recipe 文件（脚本 + 元数据）
4. 测试 Recipe 执行

---

## 示例 3：执行 Recipe

**目标**：用现成 Recipe 快速提取字幕。

### CLI 方式

```bash
# 发现可用 Recipe
frago recipe list

# 查看 Recipe 详情
frago recipe info youtube_extract_video_transcript

# 执行 Recipe
frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.txt

# 输出到剪贴板
frago recipe run youtube_extract_video_transcript \
  --params '{"url": "..."}' \
  --output-clipboard
```

### Claude Code 方式

```
/frago.run 提取 https://www.youtube.com/watch?v=dQw4w9WgXcQ 的字幕
```

AI 会自动：
1. 发现 `youtube_extract_video_transcript` Recipe
2. 带上 URL 参数执行
3. 把结果保存到文件

---

## 示例 4：用 Workflow Recipe 做批量处理

**目标**：批量提取多个 YouTube 视频的字幕。

### 创建 Workflow Recipe

```python
# ~/.frago/recipes/workflows/youtube_batch_extract/recipe.py
import sys, json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    urls = params.get('urls', [])

    runner = RecipeRunner()
    results = []

    for i, url in enumerate(urls, 1):
        print(f"Processing {i}/{len(urls)}...", file=sys.stderr)
        try:
            result = runner.run('youtube_extract_video_transcript', {'url': url})
            results.append({
                'url': url,
                'data': result['data'],
                'status': 'success'
            })
        except Exception as e:
            results.append({
                'url': url,
                'error': str(e),
                'status': 'failed'
            })

    output = {
        'total': len(urls),
        'success': sum(1 for r in results if r['status'] == 'success'),
        'failed': sum(1 for r in results if r['status'] == 'failed'),
        'results': results
    }
    print(json.dumps(output))

if __name__ == '__main__':
    main()
```

### 创建 Workflow 元数据

```yaml
---
# ~/.frago/recipes/workflows/youtube_batch_extract/recipe.md
name: youtube_batch_extract
type: workflow
runtime: python
version: "1.0.0"
description: "批量提取多个 YouTube 视频的字幕"
use_cases:
  - "批量字幕提取"
  - "构建字幕存档"
tags: ["youtube", "batch", "workflow"]
output_targets: [stdout, file]
inputs:
  urls:
    type: array
    description: "YouTube 视频 URL 列表"
    required: true
outputs:
  results:
    type: array
    description: "字幕结果数组"
dependencies:
  - youtube_extract_video_transcript
---
```

### 执行 Workflow

```bash
# 建事务目录，写 URL 列表
mkdir -p ~/.frago/data/youtube/20260813-batch-subtitles
cat > ~/.frago/data/youtube/20260813-batch-subtitles/video_urls.json <<'EOF'
{
  "urls": [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=oHg5SJYRHA0",
    "https://www.youtube.com/watch?v=..."
  ]
}
EOF

# 直接执行工作流，产出显式指定落进事务目录
frago recipe run youtube_batch_extract \
  --params-file ~/.frago/data/youtube/20260813-batch-subtitles/video_urls.json \
  --output-file ~/.frago/data/youtube/20260813-batch-subtitles/subtitles.json
```

**输出**（`subtitles.json`）：
```json
{
  "total": 3,
  "success": 3,
  "failed": 0,
  "results": [
    {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "data": {
        "title": "Rick Astley - Never Gonna Give You Up",
        "transcript": "...",
        "language": "en"
      },
      "status": "success"
    }
  ]
}
```

---

## 示例 5：跨平台复杂任务（愿景）

> 该示例展示编排层完成后的预期工作流。目前需要用户在 `/frago.run`（探索）和
> `frago recipe run`（回放）之间手动选择。

**目标**：监控 Amazon 和 eBay 上的 iPhone 15 价格，生成对比报告。

### 用 Claude Code

```
/frago.run 监控 Amazon 和 eBay 上 iPhone 15 的价格，生成对比报告并保存为 Markdown
```

AI 会：
1. 建事务目录：`~/.frago/data/iphone/20260813-price-monitor/`
2. 发现或创建 Recipe：
   - `amazon_search_product`
   - `ebay_search_product`
3. 执行工作流：
   ```
   ├─ 打开 Amazon → 搜索 "iPhone 15"
   ├─ 提取价格数据 → $799
   ├─ 打开 eBay → 搜索 "iPhone 15"
   ├─ 提取价格数据 → $749
   └─ 生成对比报告
   ```
4. 生成 Markdown 报告

**生成报告**（`~/.frago/data/iphone/20260813-price-monitor/price_comparison.md`）：
```markdown
# iPhone 15 价格对比

**日期**: 2025-01-24

## Amazon
- **价格**: $799
- **库存**: 有货
- **配送**: Prime 免运费

## eBay
- **价格**: $749
- **成色**: 二手 - 接近全新
- **运费**: $15

## 建议
eBay 便宜 $50，但要考虑成色与运费。eBay 总价 $764（仍便宜 $35）。

---
Generated with frago | ~/.frago/data/iphone/20260813-price-monitor/
```

---

## 示例 6：CDP 命令用法

### 基础导航与交互

```bash
# 启动独立无头 CDP 实例（端口 9222）
frago browser -b cdp start --headless

# 打开页面
frago browser navigate https://news.ycombinator.com/ --group hn

# 等待页面加载
frago browser wait --group hn 2

# 点击元素
frago browser click 'a.titlelink:first-child' --group hn

# 获取页面标题
frago browser exec-js 'document.title' --return-value --group hn

# 用完拆除实例
frago browser -b cdp stop
```

### 截图与视觉效果

```bash
# 整页截图
frago browser screenshot hackernews_page.png --group hn --full-page

# 高亮元素
frago browser highlight '.storylink' --color "#FF6B6B" --life-time 3 --group hn

# 聚光灯效果（压暗周围）
frago browser spotlight '.athing:first-child' --life-time 5 --group hn

# 添加标注
frago browser annotate '.score' "Top story" --position top --group hn
```

### JavaScript 执行

```bash
# 提取所有链接
frago browser exec-js 'Array.from(document.querySelectorAll("a")).map(a => a.href)' \
  --return-value --group hn

# 滚动到底部
frago browser exec-js 'window.scrollTo(0, document.body.scrollHeight)' --group hn

# 检查元素是否存在
frago browser exec-js 'document.querySelector(".pagetop") !== null' \
  --return-value --group hn
```

---

## 示例 7：找回从前做过的事

三条路各管一段：找**产出物**、翻**原始对话**、查**已沉淀的经验**。

### 找上次那份东西存哪了

```bash
# 按关键词直接定位落点，别列目录挨个猜
frago context data:youtube

# 带 data: 前缀只搜 ~/.frago/data；不带前缀是搜整个 ~/.frago，慢且噪音大，需显式确认
frago context youtube --yes

# 机器可读
frago context data:iphone --json
```

命中分三档打印：目录名命中、文件名命中、可读文档的内容命中。
命令只报路径不打印文件内容——读哪个由你决定。

### 按意思翻从前干过的事

```bash
# 一句话说清要找什么，模型扩成关键词后同时扫 claude 与 opencode 两个会话库
frago session search "上次研究 YouTube 字幕提取那回"

# 已经知道该搜哪几个字面量时直接给词，省掉模型那一轮
frago session search "字幕提取" --terms "transcript,ytd-transcript-segment-renderer" --days 30

# 只要最相关的几场
frago session search "CDP 连不上" --top 5
```

结果按命中的**不同关键词个数**排序，每场给出会话 id、命中片段和一条可直接执行的续接命令。

### 查已经沉淀的经验

```bash
# 有哪些知识域
frago def list

# 某个域里存了什么
frago browser-automation find

# 看单篇完整内容
frago browser-automation find -- --name=youtube-transcript-extraction

# 按标签筛
frago browser-automation find -- --tags=youtube
```

---

## 常见模式与最佳实践

### 模式 1：探索 → 固化 → 自动化

```
1. frago context data:<关键词> 找现成落点，没有就建事务目录
2. 交互式探索页面（浏览器命令）
3. 脚本存进事务目录的 scripts/，经验存进 frago <域名> save
4. 从验证过的脚本创建 Recipe
5. 对类似任务复用 Recipe
```

### 模式 2：Workflow Recipe 组合

```python
# Workflow Recipe 结构
def main():
    runner = RecipeRunner()

    # 第 1 步：原子 Recipe
    data1 = runner.run('atomic_recipe_1', params1)

    # 第 2 步：处理结果
    processed = process_data(data1)

    # 第 3 步：另一个原子 Recipe
    data2 = runner.run('atomic_recipe_2', processed)

    # 第 4 步：合并结果
    final = combine(data1, data2)
    print(json.dumps(final))
```

### 模式 3：Workflow 中的错误处理

```python
def main():
    runner = RecipeRunner()
    results = []

    for item in items:
        try:
            result = runner.run('recipe_name', {'item': item})
            results.append({'item': item, 'status': 'success', 'data': result})
        except Exception as e:
            results.append({'item': item, 'status': 'failed', 'error': str(e)})
            # 记录错误并继续
            print(f"Warning: Failed to process {item}: {e}", file=sys.stderr)

    return {'total': len(items), 'results': results}
```

---

## 常见问题排查

### 示例：CDP 连接问题

```bash
# CDP 端口是白名单制：9222（默认）与 9223（agent_os 机位）
lsof -i :9222

# 虚拟桌面舞台在跑时，演员占着 9222——别碰它
frago desktop status

# 启动 / 检查 / 停止 frago 管理的 CDP 实例
frago browser -b cdp start --headless
frago browser status
frago browser -b cdp stop
```

### 示例：Recipe 未找到

```bash
# 列出所有可用 Recipe
frago recipe list

# 检查 Recipe 名称（区分大小写）
frago recipe info youtube_extract_video_transcript
```

### 示例：截图落盘位置

```bash
# ❌ 错误：相对路径，落在当次 shell 的工作目录里，下次找不回来
frago browser screenshot screenshot.png --group my-task

# ❌ 错误：事务目录直接建在 data 根下，缺了主体那一层
frago browser screenshot ~/.frago/data/20260813-subtitle-extraction/screenshot.png --group my-task

# ✅ 正确：绝对路径 + 两层落点 <主体>/<YYYYMMDD>-<slug>
frago browser screenshot ~/.frago/data/youtube/20260813-subtitle-extraction/screenshot.png --group my-task
```

---

## 下一步

- **学习核心概念**：阅读 [关键概念](concepts.zh-CN.md)
- **创建自己的 Recipe**：参见 [Recipe 系统指南](recipes.zh-CN.md)

---

Created with Claude Code | 2025-11
