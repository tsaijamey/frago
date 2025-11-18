---
name: auvima-browser-automation
description: 使用AuViMa CLI自动化浏览器操作。当需要网页数据采集、视频素材收集、UI测试或任何需要与浏览器交互的任务时使用此skill。核心原则：每个操作后必须验证结果，先探索DOM结构，适当等待页面加载。
---

# AuViMa Browser Automation Skill

## 快速参考

**在动手前必读**：

1. ⚠️ **先分析任务**：理解关键概念，分解子任务，规划路径（见"任务理解与执行策略"）
2. 👁️ **你是瞎子**：必须通过工具感知，禁止凭经验猜测
3. 🎯 **目标导向**：每步操作都要问"这是为了什么目标？是否更接近了？"
4. 🔍 **系统性感知**：页面跳转后必须 `get-content` + `screenshot`
5. 🚫 **禁止原地踏步**：失败时分析原因，调整策略，不要重复无效操作

---

## 核心理念

### 1. 你是一个瞎子

**CRITICAL**: 你实际上是个瞎子，对浏览器中显示的内容一无所知。

- ❌ **禁止凭经验判断**：不要假设页面结构、元素位置、加载状态
- ✅ **必须通过工具感知**：每一步操作前，先用工具获取精确信息
- ✅ **验证每个假设**：想要点击某个按钮？先确认它存在、可见、可点击

### 2. 你必须理解任务目标

**CRITICAL**: 在开始操作前，必须正确理解用户的真实需求。

- ❌ **禁止盲目操作**：不要看到关键词就开始点击
- ✅ **先分析任务**：识别关键概念、理解最终目标、规划路径
- ✅ **每步对齐目标**：操作后检查"这是否让我更接近目标？"

---

## 任务理解与执行策略

### 步骤 0: 任务分析（在动手前完成）

**目的**：避免理解错误导致南辕北辙

#### 分析清单

1. **识别关键概念**
   - 用户提到的专有名词是什么意思？
   - 这些概念在目标平台上的对应功能是什么？

   示例：
   ```
   用户需求："检查我的提醒消息，帮我看看最近的3个提醒"

   关键概念分析：
   - "提醒消息" ≠ "历史记录"
   - "提醒消息" = YouTube 的通知功能（Notifications）
   - 需要找的是通知列表，不是观看历史
   ```

2. **识别平台特定功能**
   - 用户描述的功能在平台上叫什么？
   - 如何访问这个功能？

   示例：
   ```
   用户需求："切换到内容台词，然后把内容台词扒下来"

   功能分析：
   - "内容台词" = YouTube 视频的字幕/转录文本（Transcript）
   - 功能位置：视频下方，"Show transcript" 或 "···" 菜单中的 "Show transcript"
   - 输出形式：带时间戳的文本列表
   ```

3. **分解子任务**
   - 最终目标是什么？
   - 需要哪些中间步骤？
   - 每个步骤的成功标准是什么？

   示例：
   ```
   最终目标：获取最近3个通知对应视频的完整台词，并总结

   子任务分解：
   1. 打开 YouTube 通知页面（成功：看到通知列表）
   2. 识别最近3个通知（成功：提取到3个视频链接）
   3. 逐个打开视频（成功：进入视频播放页）
   4. 找到并打开 Transcript 功能（成功：看到字幕文本）
   5. 提取完整台词文本（成功：获得完整文本）
   6. 重复步骤3-5，共3次
   7. 分析台词并总结
   ```

4. **识别未知领域**
   - 我是否熟悉这个平台？
   - 我是否知道如何访问用户提到的功能？
   - 如果不知道，需要先探索学习

   示例：
   ```
   未知领域：
   - ❓ YouTube 通知在哪里？ → 需要先打开 YouTube，感知界面，找到通知入口
   - ❓ Transcript 功能如何打开？ → 需要打开任意视频，探索界面，找到 Transcript
   ```

### 执行策略：目标导向

**核心原则**：每个操作都要回答"这一步是为了什么目标？完成后如何验证？"

#### 执行流程

```
对于每个子任务：
  1. 明确目标：这一步要达成什么？
  2. 感知现状：我现在在哪里？
  3. 规划操作：需要做什么才能达成目标？
  4. 执行操作：使用工具完成操作
  5. 验证结果：是否达成目标？
  6. 如果失败：
     - 分析原因：为什么没达成目标？
     - 调整策略：需要换个思路吗？
     - 重新尝试或求助
```

#### 示例：目标导向执行

```bash
# 子任务 1: 打开 YouTube 通知页面
# 目标：看到通知列表

# 步骤 1: 感知现状
uv run auvima navigate https://youtube.com
uv run auvima get-content > youtube_home.html
uv run auvima screenshot youtube_home.png

# 步骤 2: 分析 youtube_home.html 和 youtube_home.png
# 问：通知入口在哪里？
# 答：通常是右上角的铃铛图标

# 步骤 3: 尝试定位通知按钮
uv run auvima exec-js "Array.from(document.querySelectorAll('button, a')).filter(el => el.getAttribute('aria-label')?.includes('Notification') || el.getAttribute('title')?.includes('Notification')).map(el => ({tag: el.tagName, aria: el.getAttribute('aria-label'), class: el.className}))" --return-value
# 输出：找到 aria-label="Notifications" 的按钮

# 步骤 4: 点击通知按钮
uv run auvima click "button[aria-label='Notifications']"

# 步骤 5: 验证结果
uv run auvima screenshot notifications_opened.png
uv run auvima exec-js "document.querySelector('[role=\"menu\"]') || document.querySelector('.notification') ? 'notifications panel opened' : 'not found'" --return-value

# 如果失败：
# - 检查截图，通知面板是否打开？
# - 如果没打开，尝试其他 selector
# - 如果找不到通知按钮，可能需要先登录
```

### 探索未知功能策略

**场景**：不知道某个功能在哪里 / 如何访问

#### 策略 1: 视觉搜索

```bash
# 1. 截图整个页面
uv run auvima screenshot full_page.png --full-page

# 2. 搜索包含关键词的元素
uv run auvima exec-js "
Array.from(document.querySelectorAll('button, a, [role=\"button\"]')).filter(el =>
  el.textContent.toLowerCase().includes('transcript') ||
  el.textContent.toLowerCase().includes('字幕') ||
  el.getAttribute('aria-label')?.toLowerCase().includes('transcript')
).map(el => ({
  text: el.textContent.trim().substring(0, 50),
  aria: el.getAttribute('aria-label'),
  class: el.className
}))
" --return-value

# 3. 如果找到，验证并点击
# 4. 如果没找到，尝试打开菜单（通常是 "···" 或 "More" 按钮）
```

#### 策略 2: 菜单探索

```bash
# 1. 找到所有菜单按钮
uv run auvima exec-js "
Array.from(document.querySelectorAll('button')).filter(el =>
  el.textContent.includes('···') ||
  el.textContent.includes('More') ||
  el.getAttribute('aria-label')?.includes('More') ||
  el.getAttribute('aria-label')?.includes('menu')
).map(el => ({text: el.textContent, aria: el.getAttribute('aria-label')}))
" --return-value

# 2. 点击菜单
uv run auvima click "button[aria-label*='More']"

# 3. 截图查看菜单内容
uv run auvima screenshot menu_opened.png

# 4. 提取菜单项
uv run auvima exec-js "
Array.from(document.querySelectorAll('[role=\"menuitem\"], [role=\"option\"]')).map(el => ({
  text: el.textContent.trim()
}))
" --return-value
```

#### 策略 3: HTML 深度搜索

```bash
# 搜索 HTML 中包含关键词的所有元素
uv run auvima exec-js "
document.body.innerHTML.match(/transcript/gi) ? 'found keyword in HTML' : 'not found'
" --return-value

# 如果找到，进一步定位
uv run auvima exec-js "
Array.from(document.querySelectorAll('*')).filter(el =>
  el.innerHTML.toLowerCase().includes('transcript') && el.children.length < 5
).map(el => ({
  tag: el.tagName,
  text: el.textContent.substring(0, 100),
  class: el.className
})).slice(0, 10)
" --return-value
```

### 失败恢复策略

**当操作没有达成目标时**

#### 检查清单

1. **重新感知**
   ```bash
   uv run auvima screenshot current_state.png
   uv run auvima get-content > current_page.html
   ```

2. **分析偏差**
   - 预期：应该看到 X
   - 实际：看到了 Y
   - 原因：可能是 Z

3. **调整策略**
   - 策略 A 失败 → 尝试策略 B
   - 示例：找不到按钮 → 尝试键盘快捷键 → 尝试 URL 直达

4. **求助用户**（如果多次尝试失败）
   - 说明：尝试了 A、B、C 三种方法
   - 当前状态：截图展示
   - 请求：是否有其他访问方式？

---

## 实战案例对比

### 案例：获取 YouTube 最近3个通知对应视频的完整台词

#### ❌ 错误执行方式

```
问题 1: 概念混淆
- 看到"提醒"关键词，直接去找"历史记录"
- 没有理解"提醒消息" = "通知"（Notifications）
- 结果：南辕北辙，找错了地方

问题 2: 盲目操作
- 凭经验假设"台词"就是视频描述
- 直接去抓取视频描述文本
- 没有探索 YouTube 的 Transcript 功能
- 结果：抓取了错误的内容

问题 3: 原地踏步
- 发现抓取的不是台词，但继续在描述区域寻找
- 重复无效操作，不调整策略
- 结果：浪费时间，始终无法达成目标
```

#### ✅ 正确执行方式

**步骤 0: 任务分析**
```
用户需求分析：
- "提醒消息" → YouTube Notifications（不是历史记录）
- "内容台词" → 视频 Transcript/字幕文本（不是视频描述）
- "最近的3个提醒" → 通知列表中最新的3条

子任务分解：
1. 打开 YouTube 通知
2. 提取最近3个通知的视频链接
3. 对每个视频：
   a. 打开视频页面
   b. 找到并打开 Transcript 功能
   c. 提取完整台词文本
4. 汇总3个视频的台词
5. 分析并总结

未知领域：
- ❓ 通知在哪里？需要先感知 YouTube 首页
- ❓ Transcript 如何打开？需要探索视频页面
```

**步骤 1: 打开通知**
```bash
# 目标：找到并打开 YouTube 通知

# 1. 系统性感知
uv run auvima navigate https://youtube.com
uv run auvima get-content > youtube_home.html
uv run auvima screenshot youtube_home.png

# 2. 分析 youtube_home.html，找到通知按钮
# 通常是 aria-label="Notifications" 的按钮

# 3. 尝试定位
uv run auvima exec-js "Array.from(document.querySelectorAll('button')).filter(el => el.getAttribute('aria-label')?.includes('Notification')).map(el => el.getAttribute('aria-label'))" --return-value

# 4. 点击通知按钮
uv run auvima click "button[aria-label*='Notification']"

# 5. 验证成功
uv run auvima screenshot notifications_panel.png
uv run auvima exec-js "document.querySelector('[role=\"menu\"]') ? 'panel opened' : 'failed'" --return-value
```

**步骤 2: 提取最近3个通知的视频链接**
```bash
# 目标：获取3个视频 URL

# 1. 感知通知列表结构
uv run auvima exec-js "document.querySelectorAll('[role=\"menuitem\"]').length" --return-value

# 2. 提取前3个通知的视频链接
uv run auvima exec-js "
Array.from(document.querySelectorAll('[role=\"menuitem\"] a')).slice(0, 3).map(a => a.href)
" --return-value
# 输出：['url1', 'url2', 'url3']
```

**步骤 3: 探索 Transcript 功能（首个视频）**
```bash
# 目标：学习如何打开 Transcript

# 1. 打开第一个视频
uv run auvima navigate [url1]
uv run auvima get-content > video_page.html
uv run auvima screenshot video_page.png

# 2. 搜索 "transcript" 关键词
uv run auvima exec-js "
Array.from(document.querySelectorAll('button, [role=\"button\"]')).filter(el =>
  el.textContent.toLowerCase().includes('transcript') ||
  el.getAttribute('aria-label')?.toLowerCase().includes('transcript')
).map(el => ({text: el.textContent, aria: el.getAttribute('aria-label')}))
" --return-value

# 3. 如果没找到，尝试打开"More"菜单
uv run auvima exec-js "
Array.from(document.querySelectorAll('button')).filter(el =>
  el.textContent.includes('···') ||
  el.getAttribute('aria-label')?.includes('More')
).map(el => el.getAttribute('aria-label'))
" --return-value

# 4. 点击 More 菜单
uv run auvima click "button[aria-label*='More']"
uv run auvima screenshot menu_opened.png

# 5. 查找 "Show transcript" 选项
uv run auvima exec-js "
Array.from(document.querySelectorAll('[role=\"menuitem\"]')).map(el => el.textContent.trim())
" --return-value

# 6. 点击 "Show transcript"
uv run auvima click "[role='menuitem']:has-text('transcript')"
# 或者用 exec-js 点击
uv run auvima exec-js "
Array.from(document.querySelectorAll('[role=\"menuitem\"]')).find(el =>
  el.textContent.toLowerCase().includes('transcript')
)?.click()
" --return-value

# 7. 验证 Transcript 面板打开
uv run auvima screenshot transcript_opened.png
```

**步骤 4: 提取台词文本**
```bash
# 目标：获取完整台词

# 1. 感知 Transcript 面板结构
uv run auvima exec-js "document.querySelector('[aria-label*=\"transcript\"]')?.innerHTML.substring(0, 500)" --return-value

# 2. 提取所有台词文本
uv run auvima exec-js "
Array.from(document.querySelectorAll('.ytd-transcript-segment-renderer')).map(seg =>
  seg.querySelector('.segment-text')?.textContent?.trim()
).join('\\n')
" --return-value
# 保存到文件
> video1_transcript.txt

# 3. 验证提取成功
# 检查文本长度是否合理
```

**步骤 5: 重复步骤 3-4（对 url2 和 url3）**
```bash
# 已经知道如何打开 Transcript，直接执行
# ...
```

**步骤 6: 汇总和分析**
```
- 读取 video1_transcript.txt, video2_transcript.txt, video3_transcript.txt
- 分析台词内容
- 生成总结
```

**关键区别**：
1. ✅ 开始前先分析任务，识别关键概念
2. ✅ 遇到未知功能（Transcript）先探索学习
3. ✅ 每步都明确目标，验证是否接近目标
4. ✅ 失败时调整策略，不原地踏步

### 错误示范
```bash
# ❌ 错误：凭经验假设搜索框存在
uv run auvima click "input[name='search']"
```

### 正确示范
```bash
# ✅ 正确：先系统性感知整个页面
# 步骤 1: 获取页面内容，了解整体结构
uv run auvima get-content > page_content.html

# 步骤 2: 截图，获得视觉信息
uv run auvima screenshot current_page.png

# 步骤 3: 分析内容后，尝试定位搜索框（可能的 selector）
uv run auvima exec-js "document.querySelector('input[name=\"search\"]') ? 'found by name' : 'not found'" --return-value
uv run auvima exec-js "document.querySelector('input[type=\"search\"]') ? 'found by type' : 'not found'" --return-value
uv run auvima exec-js "document.querySelector('.search-input') ? 'found by class' : 'not found'" --return-value

# 步骤 4: 确认找到后，才执行点击
uv run auvima click "input[name='search']"
```

---

## 感知手段

### 手段 1: 获取页面内容（get-content）
- **用途**：了解页面整体 HTML 结构
- **使用时机**：
  - ✅ 页面首次加载后
  - ✅ 页面跳转后
  - ❌ 同一页面内的操作（不需要重复获取）
- **输出**：保存到文件分析，或直接查看
```bash
uv run auvima get-content > page.html
```

### 手段 2: 截图（screenshot）
- **用途**：视觉感知页面状态、元素位置
- **使用时机**：
  - ✅ 页面首次加载后
  - ✅ 关键操作前后（对比变化）
  - ✅ 调试时（确认元素位置）
- **输出**：PNG 图片
```bash
uv run auvima screenshot page.png
uv run auvima screenshot page_fullpage.png --full-page
```

### 手段 3: 获取页面标题（get-title）
- **用途**：快速确认页面身份、验证跳转
- **使用时机**：
  - ✅ 验证页面加载成功
  - ✅ 确认点击后页面是否跳转
- **输出**：页面标题文本
```bash
uv run auvima get-title
```

### 手段 4: Selector 尝试（exec-js）
- **用途**：探索元素，验证 selector 是否有效
- **使用时机**：在获取页面内容/截图后，分析出可能的 selector，逐个尝试
- **策略**：多种 selector 并行尝试，找到最可靠的
```bash
# 尝试多种可能的 selector
uv run auvima exec-js "document.querySelector('input[name=\"search\"]') ? 'found' : 'not found'" --return-value
uv run auvima exec-js "document.querySelector('input[type=\"search\"]') ? 'found' : 'not found'" --return-value
uv run auvima exec-js "document.querySelector('#search') ? 'found' : 'not found'" --return-value

# 获取元素详细信息
uv run auvima exec-js "const el = document.querySelector('input[name=\"search\"]'); el ? {tag: el.tagName, id: el.id, class: el.className, visible: el.offsetParent !== null} : null" --return-value
```

### 手段 5: HTML 片段提取（exec-js）
- **用途**：精确提取页面某个区域的 HTML
- **使用时机**：get-content 内容太长，需要聚焦特定区域
```bash
# 提取 body 前 2000 字符
uv run auvima exec-js "document.body.innerHTML.substring(0, 2000)" --return-value

# 提取特定区域的 HTML
uv run auvima exec-js "document.querySelector('.main-content')?.innerHTML.substring(0, 1000)" --return-value
```

### 手段 6: 文本搜索（exec-js）
- **用途**：通过文本内容反向找到元素
- **使用时机**：不知道 selector，但知道元素包含特定文本
```bash
# 搜索包含"搜索"文本的元素
uv run auvima exec-js "Array.from(document.querySelectorAll('*')).filter(el => el.textContent.includes('搜索') && el.children.length === 0).map(el => ({tag: el.tagName, class: el.className, id: el.id})).slice(0, 10)" --return-value
```

---

## 感知策略

### 策略：何时需要重新感知

| 情况 | 需要 get-content | 需要 screenshot | 需要 selector 尝试 |
|------|-----------------|----------------|-------------------|
| 首次打开页面 | ✅ 必须 | ✅ 建议 | ✅ 必须 |
| 页面跳转后 | ✅ 必须 | ✅ 建议 | ✅ 必须 |
| 同一页面操作（点击按钮、填写表单） | ❌ 不需要 | ⚠️ 调试时 | ❌ 不需要 |
| 动态内容加载（AJAX、滚动加载） | ❌ 不需要 | ✅ 建议 | ✅ 验证新元素 |
| 操作失败需要调试 | ⚠️ 可选 | ✅ 必须 | ✅ 必须 |

### 完整感知流程示例

```bash
# 场景：首次打开 YouTube 并搜索视频

# === 第一次感知（打开页面）===
uv run auvima navigate https://youtube.com

# 1. 获取页面内容
uv run auvima get-content > youtube_homepage.html

# 2. 截图
uv run auvima screenshot youtube_homepage.png

# 3. 分析 youtube_homepage.html 和 youtube_homepage.png
#    发现搜索框可能的 selector: input[name="search_query"]

# 4. 验证 selector
uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]') ? 'exists' : 'not found'" --return-value
# 输出: exists

# 5. 获取搜索框详细信息
uv run auvima exec-js "const el = document.querySelector('input[name=\"search_query\"]'); ({visible: el.offsetParent !== null, value: el.value})" --return-value

# === 在同一页面操作（不需要重新 get-content）===
# 6. 点击搜索框
uv run auvima click "input[name='search_query']"

# 7. 填写搜索内容
uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]').value='AI tutorial'"

# 8. 验证填写成功
uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]').value" --return-value

# 9. 点击搜索按钮（已知 selector，直接操作）
uv run auvima click "button#search-icon-legacy"

# === 第二次感知（页面跳转到搜索结果）===
# 10. 验证页面跳转
uv run auvima get-title
# 输出包含: AI tutorial

# 11. 重新获取页面内容（因为页面已跳转）
uv run auvima get-content > youtube_search_results.html

# 12. 截图新页面
uv run auvima screenshot youtube_search_results.png

# 13. 分析搜索结果页结构，找到视频列表的 selector
uv run auvima exec-js "document.querySelectorAll('ytd-video-renderer').length" --return-value
# 输出: 20

# 14. 提取数据
uv run auvima exec-js "Array.from(document.querySelectorAll('ytd-video-renderer')).slice(0, 5).map(v => v.querySelector('#video-title')?.textContent?.trim()).join('\n')" --return-value
```

---

## 两种操作模式

### 模式 1: 探索模式（AI 自己操作）

**场景**：探索网站结构、提取数据、测试功能

**特点**：
- **不需要 wait 命令**：每次工具调用之间自然有 time gap，浏览器有足够时间响应
- 操作流程：感知 → 分析 → 操作 → 验证 → 重复

**示例**：
```bash
# 探索 YouTube 搜索功能
uv run auvima navigate https://youtube.com
uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]') ? 'found' : 'not found'" --return-value
# 如果返回 'found'，继续
uv run auvima click "input[name='search_query']"
uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]').value='AI tutorial'"
# 验证输入成功
uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]').value" --return-value
# 确认后点击搜索
uv run auvima click "button#search-icon-legacy"
# 验证页面跳转
uv run auvima get-title
```

### 模式 2: 录制模式（生成 pipeline 脚本）

**场景**：录制视频素材、自动化演示、重复执行流程

**特点**：
- **必须使用 wait 命令**：脚本是固定步骤序列，不会动态等待，必须预留时间
- AI 的职责：通过探索模式摸索流程 → 总结经验 → 撰写包含 wait 的 pipeline 脚本

**工作流程**：
1. **探索阶段**（不用 wait）：AI 自己操作，摸清所有步骤
2. **分析阶段**：总结每个步骤需要多少等待时间
3. **脚本生成阶段**：将经验固化为带 wait 的脚本

**示例**（生成的脚本）：
```bash
#!/bin/bash
# 这是 AI 探索后生成的录制脚本

uv run auvima navigate https://youtube.com
uv run auvima wait 3  # 页面加载需要3秒

uv run auvima click "input[name='search_query']"
uv run auvima wait 0.5  # 搜索框获得焦点需要0.5秒

uv run auvima exec-js "document.querySelector('input[name=\"search_query\"]').value='AI tutorial'"
uv run auvima wait 0.3  # 输入动画需要0.3秒

uv run auvima click "button#search-icon-legacy"
uv run auvima wait 2  # 搜索结果加载需要2秒

uv run auvima screenshot final_result.png
```

---

## 操作工具

#### `navigate`
- **用途**：导航到指定 URL
- **使用时机**：开始任务、切换页面
- **注意**：导航后必须验证页面加载成功（用 `get-title` 或 `exec-js`）

#### `click`
- **用途**：点击元素
- **使用时机**：已确认元素存在且可点击
- **注意**：点击前必须先用 `exec-js` 确认元素存在
- **参数**：CSS 选择器

#### `exec-js`（无 `--return-value`）
- **用途**：执行操作（填写表单、触发事件、修改 DOM）
- **使用时机**：需要复杂操作时
- **核心能力**：
  - 填写输入框：`element.value = 'text'`
  - 触发点击：`element.click()`
  - 修改样式：`element.style.xxx = 'value'`
  - 执行复杂逻辑：`if/else` 判断

#### `scroll`
- **用途**：滚动页面（触发懒加载、查看更多内容）
- **使用时机**：内容超出视口、需要加载更多数据
- **参数**：滚动距离（像素）

#### `highlight`
- **用途**：高亮元素（调试、确认选择器正确）
- **使用时机**：不确定选择器是否准确时
- **参数**：选择器、颜色、边框宽度

#### `wait`
- **用途**：在脚本中插入固定等待时间
- **使用时机**：**仅在生成 pipeline 脚本时使用**
- **探索模式**：❌ 不需要使用，工具调用间隔自然提供等待时间
- **录制模式**：✅ 必须使用，脚本不会动态等待

---

## 数据提取模式

### 渐进式探索

```bash
# 步骤 1: 先测试单个元素
uv run auvima exec-js "document.querySelector('.item')?.textContent" --return-value

# 步骤 2: 确认有效后，批量提取
uv run auvima exec-js "Array.from(document.querySelectorAll('.item')).map(el => el.textContent.trim()).join('\n')" --return-value
```

### 错误处理

```bash
# 操作前先验证元素存在
uv run auvima exec-js "const el = document.querySelector('.button'); if (el) { el.click(); 'clicked'; } else { 'element not found'; }" --return-value
```

### 列表和表格数据

```bash
# 提取列表数据
uv run auvima exec-js "
Array.from(document.querySelectorAll('.product-card')).slice(0, 10).map((card, i) => {
  const name = card.querySelector('.name')?.textContent?.trim() || 'N/A';
  const price = card.querySelector('.price')?.textContent?.trim() || 'N/A';
  return (i+1) + '. ' + name + ' | ' + price;
}).join('\n')
" --return-value

# 提取表格数据
uv run auvima exec-js "
Array.from(document.querySelectorAll('table tbody tr')).map((row, i) => {
  const cells = Array.from(row.querySelectorAll('td')).map(td => td.textContent.trim());
  return (i+1) + '. ' + cells.join(' | ');
}).join('\n')
" --return-value
```

### 分页处理

```bash
# 检查是否有下一页
uv run auvima exec-js "document.querySelector('.next-page') ? 'has next' : 'last page'" --return-value

# 提取当前页数据
uv run auvima exec-js "Array.from(document.querySelectorAll('.item')).map(el => el.textContent.trim()).join('\n')" --return-value

# 点击下一页
uv run auvima click ".next-page"

# 验证页面切换
uv run auvima exec-js "window.location.href" --return-value
```

---

## 常见场景决策树

### 场景：需要提取页面数据

1. **系统性感知**
   ```bash
   uv run auvima get-content > page.html
   uv run auvima screenshot page.png
   ```

2. **分析并尝试 selector**
   ```bash
   # 根据 page.html 和 page.png 分析出可能的 selector
   uv run auvima exec-js "document.querySelector('TARGET_SELECTOR') ? 'found' : 'not found'" --return-value
   ```

3. **验证选择器精确性**
   ```bash
   uv run auvima exec-js "document.querySelectorAll('TARGET_SELECTOR').length" --return-value
   ```

4. **批量提取数据**
   ```bash
   uv run auvima exec-js "Array.from(document.querySelectorAll('TARGET_SELECTOR')).map(...)" --return-value
   ```

### 场景：需要填写表单

1. **系统性感知**
   ```bash
   uv run auvima get-content > form_page.html
   uv run auvima screenshot form_page.png
   ```

2. **分析并探索表单字段**
   ```bash
   # 根据 form_page.html 分析表单结构
   uv run auvima exec-js "Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({name: el.name, type: el.type, id: el.id}))" --return-value
   ```

3. **填写每个字段**
   ```bash
   uv run auvima exec-js "document.querySelector('input[name=\"email\"]').value='test@example.com'"
   ```

4. **验证填写成功**
   ```bash
   uv run auvima exec-js "document.querySelector('input[name=\"email\"]').value" --return-value
   ```

5. **提交前截图确认**
   ```bash
   uv run auvima screenshot form_before_submit.png
   ```

### 场景：需要录制视频素材

1. **探索模式**：AI 自己操作，摸清所有步骤（不用 wait）
2. **分析时间**：记录每个步骤实际需要多久
3. **生成脚本**：创建包含 wait 命令的 bash 脚本
4. **测试脚本**：运行脚本验证时间是否合理
5. **录制视频**：用脚本控制浏览器，同时录制屏幕

---

## 调试技巧

### 高亮元素定位
```bash
uv run auvima highlight "YOUR_SELECTOR" --color red --width 5
uv run auvima screenshot debug.png
```

### 检查元素可见性
```bash
uv run auvima exec-js "const el = document.querySelector('YOUR_SELECTOR'); el && el.offsetParent !== null ? 'visible' : 'hidden'" --return-value
```

### 获取所有链接
```bash
uv run auvima exec-js "Array.from(document.querySelectorAll('a')).map(a => a.href).slice(0, 20).join('\n')" --return-value
```

### 搜索包含特定文本的元素
```bash
uv run auvima exec-js "Array.from(document.querySelectorAll('*')).filter(el => el.textContent.includes('关键词') && el.children.length === 0).map(el => el.tagName + '.' + (el.className || 'no-class')).join('\n')" --return-value
```

---

## 核心原则总结

### 在开始前

1. **先理解任务，再动手**
   - 识别关键概念（"提醒消息" ≠ "历史记录"）
   - 分解子任务，明确每步目标
   - 识别未知领域，规划探索策略

2. **你是瞎子**
   - 每个假设都要通过工具验证
   - 系统性感知：get-content + screenshot
   - 永远不要凭经验猜测

### 执行中

3. **目标导向执行**
   - 每步操作前：这是为了达成什么目标？
   - 每步操作后：是否让我更接近目标？
   - 失败时：分析原因，调整策略，不要原地踏步

4. **感知 → 分析 → 操作 → 验证**
   - 页面跳转后：必须重新 get-content + screenshot
   - 同一页面操作：不需要重复感知
   - 遇到未知功能：先探索（视觉搜索/菜单探索/HTML 搜索）

### 两种模式

5. **探索模式（AI 操作）**：不需要 wait，工具调用间隔足够
6. **录制模式（生成脚本）**：必须有 wait，脚本不会动态等待

---

**最后更新**: 2025-11-18
