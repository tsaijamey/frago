[English](use-cases.md)

# Frago 使用场景

本文档展示 Frago 在实际场景中的应用方式，涵盖从 Recipe 创建到复杂 Workflow 编排的完整流程。

---

## 为什么用 Frago 驱动 AI 自动化

AI agent 执行浏览器自动化时面临一个根本问题：每次对话都从零开始，没有过去工作的记忆。Frago 通过三个机制解决这个问题：

**标准化上下文积累**

每个 AI 操作都遵循统一规范，记录到结构化的 JSONL 日志中。上下文跨会话持久化——AI 可以接续上次的进度，了解之前尝试过什么，在已有发现的基础上继续探索，而不是每次都从头开始。

**快速日志检索**

Run 系统为 AI 提供高效的方法来搜索和查询执行历史。AI 不需要重新探索访问过的页面，可以直接检索之前运行中验证过的选择器、有效脚本和观察到的行为。

**通过 Recipe 实现确定性执行**

探索成功后，有效的方法被固化为 Recipe——一个版本化、经过测试的自动化脚本。后续遇到类似任务时，AI 直接执行 Recipe，而不是重新推理问题。这消除了重复探索浪费的 token，也避免了 AI 每次「重新想办法」时因随机性导致的间歇性失败。

---

## 三种使用模式

| 模式 | 命令 | 目标 | 输出 |
|-----|------|------|------|
| **探索调研** | `/frago.run` | 收集信息以创建 Recipe | JSONL 日志 + 验证脚本 + Recipe 草稿 |
| **沉淀 Recipe** | `/frago.recipe` | 将探索结果转化为可复用脚本 | Recipe 文件（.js/.py + .md） |
| **任务执行** | `/frago.exec` | 完成具体业务目标 | 任务结果 + 执行日志 |

选择建议：
- **未知页面/流程**：使用 `/frago.run` 探索，积累上下文
- **重复性任务**：创建 Recipe 后使用 `/frago.exec` 或直接执行 Recipe
- **复杂业务流程**：创建 Workflow Recipe，编排多个 atomic Recipe

---

## 场景 1：Recipe 生成与沉淀

**目标**：将自然语言描述的任务转化为可复用的标准化 Recipe 脚本。

### Claude Code 方式

```
/frago.recipe 为这个页面生成一个提取脚本：https://news.ycombinator.com/，提取前10条新闻的标题和链接
```

### AI 执行流程

1. **分析页面**：自动通过 CDP 获取页面结构
2. **生成代码**：编写 `hn_extract.js` (Chrome Runtime) 和 `hn_extract.md` (元数据)
3. **验证与保存**：在临时环境中测试运行，成功后保存至 `.frago/recipes/project/`
4. **即时可用**：后续可通过 `/frago.run` 直接调用该 Recipe

### CLI 等效操作

```bash
# 手动创建 Recipe（需要人工编写代码）
cat > .frago/recipes/project/hn_extract.js <<'EOF'
(async () => {
  const items = Array.from(document.querySelectorAll('.athing')).slice(0, 10);
  return items.map(item => ({
    title: item.querySelector('.titleline a').textContent,
    url: item.querySelector('.titleline a').href
  }));
})();
EOF

# 创建元数据文件
cat > .frago/recipes/project/hn_extract.md <<'EOF'
---
name: hn_extract
type: atomic
runtime: chrome-js
description: "提取 Hacker News 首页前 10 条新闻"
...
EOF

# 执行 Recipe
uv run frago recipe run hn_extract --output-file news.json
```

---

## 场景 2：原子化任务自动化

**目标**：快速执行单一明确的任务，如提取特定页面数据。

### CLI 方式

```bash
# 直接执行 Recipe 提取 YouTube 视频字幕
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.md
```

### Claude Code 方式

```
/frago.run 提取这个视频的字幕：https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

AI 自动识别意图 → 匹配 `youtube_extract_video_transcript` Recipe → 执行并返回结果

### 适用场景

- 数据采集（抓取特定网站的结构化数据）
- 内容提取（视频字幕、文章正文、评论列表）
- 状态检查（页面加载状态、元素可见性）

---

## 场景 3：交互式调试与探索

**目标**：在保持上下文的情况下，分步排查问题或探索未知页面。

### CLI 时序操作

```bash
# 1. 初始化调试会话
uv run frago run init "排查登录页面布局偏移问题"

# 2. 执行一系列操作（上下文自动关联到当前 Run）
frago chrome navigate https://staging.example.com/login
frago chrome exec-js "window.innerWidth"
frago chrome screenshot before_click.png
frago chrome click "#login-btn"
frago chrome screenshot after_click.png

# 3. 记录人工观察结果
uv run frago run log \
  --step "观察到点击后布局右移 20px" \
  --status "failure" \
  --action-type "analysis" \
  --execution-method "manual" \
  --data '{"observation": "登录按钮点击后，整个表单右移 20px"}'

# 4. 归档会话
uv run frago run archive "排查登录页面布局偏移问题"
```

### Claude Code 方式

```
/frago.run 排查 staging.example.com/login 的布局偏移问题，先截图，点击登录按钮后再截图，对比差异
```

AI 将自动：
1. 创建 Run 实例
2. 执行导航、截图、点击操作
3. 分析两张截图差异
4. 生成带有诊断信息的报告

### Run 系统的价值

- **上下文持久化**：所有操作记录在 `execution.jsonl`，可随时回溯
- **截图归档**：关键步骤的截图自动保存到 `screenshots/`
- **脚本积累**：探索过程中生成的验证脚本保存到 `scripts/`
- **可复用**：后续遇到类似问题，可以继续该 Run 实例

---

## 场景 4：复杂工作流编排

**目标**：执行跨平台、多步骤的复杂业务流程。

### CLI 方式（Python Recipe 编排）

```bash
# 执行一个包含多个步骤的复杂 Recipe
uv run frago recipe run competitor_price_monitor \
  --params '{"product": "iPhone 15", "sites": ["amazon", "ebay"]}' \
  --output-file price_report.json
```

### Claude Code 方式

```
/frago.run 监控 Amazon 和 eBay 上 iPhone 15 的价格，生成对比报告并保存为 markdown
```

### AI 执行流程

1. **意图识别**：识别为多平台比价任务
2. **任务拆解**：
   - 子任务 A: Amazon 搜索与提取（调用 `amazon_search` Recipe）
   - 子任务 B: eBay 搜索与提取（调用 `ebay_search` Recipe）
   - 子任务 C: 数据聚合与报告生成（调用 Python 数据处理逻辑）
3. **执行与反馈**：依次执行子任务，最终生成 `price_comparison.md`

### Workflow Recipe 示例结构

```python
# examples/workflows/competitor_price_monitor.py
from frago.recipes import RecipeRunner

runner = RecipeRunner()

# 步骤 1: 提取 Amazon 数据
amazon_data = runner.run('amazon_search', params={
    'keyword': params['product']
})

# 步骤 2: 提取 eBay 数据
ebay_data = runner.run('ebay_search', params={
    'keyword': params['product']
})

# 步骤 3: 数据聚合
result = {
    'product': params['product'],
    'amazon': amazon_data['data'],
    'ebay': ebay_data['data'],
    'comparison': analyze_prices(amazon_data, ebay_data)
}

print(json.dumps(result))
```

---

## 场景 5：批量处理与数据采集

**目标**：批量执行重复性任务，提取大量数据。

### 示例：批量提取 Upwork 职位

```bash
# 使用 Workflow Recipe 批量处理
uv run frago recipe run upwork_batch_extract \
  --params '{"keyword": "Python", "count": 20}' \
  --output-file jobs.json
```

### Workflow 内部逻辑

```python
# examples/workflows/upwork_batch_extract.py
runner = RecipeRunner()

# 调用 atomic Recipe 提取职位列表
job_list = runner.run('upwork_search_jobs', params={
    'keyword': params['keyword']
})

# 循环调用 atomic Recipe 提取详情
results = []
for job_url in job_list['data']['urls'][:params['count']]:
    job_detail = runner.run('upwork_extract_job_details', params={
        'url': job_url
    })
    results.append(job_detail['data'])

print(json.dumps({'jobs': results, 'total': len(results)}))
```
