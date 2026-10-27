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
# 先把浏览器和扩展桥拉起来（已经在跑就跳过）
frago browser start

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

配方不手写文件。定规格、生成模板、填逻辑、查完再跑，四步各有一条命令。

### 第 1 步：定规格

```bash
# 这条要等 worker 写十几分钟：agent 用 Bash 前台跑会被 10 分钟上限砍掉，所以后台起
frago recipe plan youtube_extract_video_transcript \
  --type atomic --runtime chrome-js \
  --prompt "从 YouTube 视频页提取完整字幕文本；输入 url，输出 transcript 与 segmentCount"
```

`--type` / `--runtime` 不写也行，worker 从需求里判断。命令自己建目录，把规格写成该目录下的
`spec.md`，回执里打印 `Directory:` 那一行——后面三步都认这个路径。

### 第 2 步：看一眼规格，再生成模板

```bash
frago recipe create youtube_extract_video_transcript
```

`create` 读不到规格里那段机器可读的 yaml 就直接退出，一个文件都不写，所以顺序不能反。
想一步做完用 `--prompt "<需求>"`，它照样先生成规格、再按规格生成模板。

### 第 3 步：在模板上填业务逻辑

模板给的是骨架。第 1 步验证过的选择器照抄进脚本——`runtime: chrome-js` 时脚本文件名是
`recipe.js`。

```javascript
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
```

### 第 4 步：查完再跑

```bash
# 校验字段完整性与脚本齐备，收目录或 recipe.md 路径都行
frago recipe validate <第 1 步回执里的 Directory>

# 出现在清单里，才说明注册表认了这个配方
frago recipe list

# 试跑
frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

**前置条件**：浏览器后端在运行（`frago browser start`），页面上确实有字幕面板，视频必须有字幕。

---

## 示例 3：执行 Recipe

**目标**：用现成 Recipe 快速提取字幕。

### CLI 方式

```bash
# 发现可用 Recipe
frago recipe list

# 清单里没有？frago 包里不带任何配方，去社区仓库找
frago recipe search 字幕
frago recipe install community:<找到的配方名>

# 查看 Recipe 详情
frago recipe info youtube_extract_video_transcript

# 执行 Recipe。--output-file 收绝对路径，产出落进事务目录
frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file ~/.frago/data/youtube/20260813-subtitle-extraction/transcript.txt

# 输出到剪贴板
frago recipe run youtube_extract_video_transcript \
  --params '{"url": "..."}' \
  --output-clipboard
```

### 让 agent 代跑

直接说要做的事，不用记命令：

```
提取 https://www.youtube.com/watch?v=dQw4w9WgXcQ 的字幕
```

AI 会自动：
1. `frago recipe list` 看有没有现成配方
2. 有就带上参数跑，没有就先 `frago recipe plan` / `create` 造一个
3. 把产出落进 `~/.frago/data/<主体>/<YYYYMMDD>-<slug>/`

---

## 示例 4：用 Workflow Recipe 做批量处理

**目标**：批量提取多个 YouTube 视频的字幕。

### 第 1 步：定规格并生成模板

```bash
frago recipe plan youtube_batch_extract --type workflow --runtime python \
  --prompt "批量提取多个 YouTube 视频的字幕：输入 urls 数组，逐个调用字幕配方，输出汇总结果"
frago recipe create youtube_batch_extract
```

下面是 create 生成的那份 `recipe.py` 里要填的编排逻辑：

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

### 元数据里多一段 flow

workflow 类型必填 `flow`：写清每一步做什么、输入从哪来、产出叫什么名。

```yaml
---
# recipe.md 的 frontmatter
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
flow:
  - step: 1
    action: "read_urls"
    description: "读入 URL 列表"
    inputs:
      - source: "params.urls"
    outputs:
      - name: "urls"
        type: "list"
  - step: 2
    action: "extract_each"
    description: "逐个调用字幕配方"
    recipe: "youtube_extract_video_transcript"
    inputs:
      - source: "step.1.urls"
    outputs:
      - name: "per_video"
        type: "object"
  - step: 3
    action: "aggregate"
    description: "汇总成功数与结果数组"
    inputs:
      - source: "step.2.per_video"
    outputs:
      - name: "results"
        type: "array"
---
```

### 第 2 步：跑起来

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

> 该示例展示编排层完成后的预期工作流。目前需要用户在「让 agent 现场探索」和
> `frago recipe run`（回放已有配方）之间手动选择。

**目标**：监控 Amazon 和 eBay 上的 iPhone 15 价格，生成对比报告。

### 直接说要做的事

```
监控 Amazon 和 eBay 上 iPhone 15 的价格，生成对比报告并保存为 Markdown
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

## 示例 6：浏览器日常用法

下面走默认的 extension 后端：驱动 frago 自己那份 Chrome for Testing，用它的真实 profile，
天然过得了反爬。`-b cdp` 是独立无头实例，只给 agent_os 的舞台与机位用，见文末排查一节。

### 基础导航与交互

```bash
# 拉起浏览器与扩展桥。零参数，自动挑浏览器；本机没有 CfT 会先去取一份
frago browser start

# 打开页面
frago browser navigate https://news.ycombinator.com/ --group hn

# 等待页面加载
frago browser wait --group hn 2

# 点击元素
frago browser click 'a.titlelink:first-child' --group hn

# 获取页面标题
frago browser exec-js 'document.title' --return-value --group hn

# 用完收工：关浏览器、停扩展桥
frago browser stop
```

### 截图与视觉效果

```bash
# 整页截图。绝对路径落进事务目录，别用相对路径——下次找不回来
frago browser screenshot ~/.frago/data/hn/20260813-hackernews/hackernews_page.png \
  --group hn --full-page

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
# 一句话说清要找什么，模型扩成关键词后同时扫 claude、opencode、codex 三个会话库
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
4. 探索定了就固化成 Recipe：frago recipe plan → create → validate
5. 对类似任务复跑这个 Recipe
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

# 启动 / 检查 / 停止 frago 管理的 CDP 实例。
# -b cdp 是 agent_os 使用的独立无头实例，日常浏览不走这条
frago browser -b cdp start --headless
frago browser status
frago browser -b cdp stop
```

默认 extension 后端连不上扩展桥时，`frago browser start` 是唯一动作：会弹出一扇浏览器窗口，
这是预期现象，不是降级到 `-b cdp` 的理由。

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
