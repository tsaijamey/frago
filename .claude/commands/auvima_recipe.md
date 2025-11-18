---
description: "创建可复用的浏览器操作配方脚本"
---

# /auvima.recipe - 配方创建指令

## 你的任务

引导用户创建一个可复用的JavaScript配方脚本，通过实际执行CDP操作来探索步骤，然后将经验写成代码。

---

## 可用的AuViMa原子操作

```bash
# 导航到URL
uv run auvima navigate <url>

# 点击元素
uv run auvima click <selector>

# 执行JavaScript表达式
uv run auvima exec-js <expression>

# 截图
uv run auvima screenshot <output_file>
```

**选择器类型**：CSS选择器、ARIA标签（`[aria-label="..."]`）、ID（`#id`）、类名（`.class`）

---

## 选择器优先级规则

在生成JavaScript时，按此优先级排序选择器（5最高，1最低）：

| 优先级 | 类型 | 示例 | 稳定性 | 说明 |
|--------|------|------|--------|------|
| **5** | ARIA标签 | `[aria-label="按钮"]` | ✅ 很稳定 | 无障碍属性，极少改变 |
| **5** | data属性 | `[data-testid="submit"]` | ✅ 很稳定 | 专门用于测试 |
| **4** | 稳定ID | `#main-button` | ✅ 稳定 | 语义化ID名称 |
| **3** | 语义化类名 | `.btn-primary` | ⚠️ 中等 | BEM规范类名 |
| **3** | HTML5语义标签 | `button`, `nav` | ⚠️ 中等 | 标准语义标签 |
| **2** | 结构选择器 | `div > button` | ⚠️ 脆弱 | 依赖DOM结构 |
| **1** | 生成的类名 | `.css-abc123` | ❌ 很脆弱 | CSS-in-JS，随时变化 |

**脆弱选择器识别**：
- `.css-*` 或 `._*` 开头的类名
- 纯数字ID：`#12345`
- 过长的ID/类名（>20字符）

---

## 执行流程

### 1. 目标澄清

问清楚：
- 在哪个网站操作？（用于命名：`<平台>_<功能>.js`）
- 要完成什么任务？
- 前置条件是什么？（如：已打开某页面、已登录）

### 2. 逐步探索

引导用户描述每个步骤，**你实际执行CDP命令**：

```
你: 第一步需要做什么？
用户: 点击"作者声明"展开详情
你: [执行] uv run auvima click '[aria-label="作者声明"]'
    ✓ 成功。记录：ARIA选择器（优先级5）
    下一步呢？
```

**记住你执行的每个命令**：
- 使用了哪些选择器（及其优先级）
- 执行了什么操作
- 需要等待多久（观察执行间隔）

### 3. 生成配方文件

对话结束后，**使用Write工具**创建两个文件：

#### 文件1: `src/auvima/recipes/<平台>_<功能>.js`

JavaScript配方脚本：

```javascript
/**
 * Recipe: <平台>_<功能>
 * Platform: <平台名>
 * Description: <功能描述>
 * Created: <YYYY-MM-DD>
 * Version: 1
 */

(async function() {
  // 辅助函数：按优先级尝试多个选择器
  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`无法找到${description}`);
  }

  // 步骤1: <用户描述>
  const elem1 = findElement([
    { selector: '<ARIA或data属性>', priority: 5 },  // 最稳定
    { selector: '<稳定ID>', priority: 4 },           // 降级
    { selector: '<语义类名>', priority: 3 }          // 再降级
  ], '<元素描述>');
  elem1.click();
  await new Promise(r => setTimeout(r, 500));  // 等待DOM更新

  // 步骤2: <用户描述>
  const elem2 = findElement([
    { selector: '<选择器1>', priority: 5 }
  ], '<元素描述>');
  elem2.click();
  await new Promise(r => setTimeout(r, 500));

  // 步骤3: 提取数据
  const result = document.querySelector('.target').innerText;
  
  return result;
})();
```

**编写规则**：
- 优先使用高优先级选择器（ARIA/data > ID > class）
- 每个元素提供2-3个降级选择器（如果探索中使用了多个）
- 操作后等待：点击/输入后500ms，导航后2000ms
- 清晰的错误消息

#### 文件2: `src/auvima/recipes/<平台>_<功能>.md`

知识文档，**必须包含6个标准章节**：

```markdown
# <平台>_<功能>

## 功能描述
<详细说明这个配方的用途、适用场景和价值>

## 使用方法
1. <前置条件步骤>
2. 执行配方：
   ```bash
   uv run auvima exec-js recipes/<平台>_<功能>.js
   ```
3. <查看结果的方法>

## 前置条件
- <条件1：如"已打开YouTube视频页面">
- <条件2：如"视频字幕已开启">
- Chrome CDP已连接

## 预期输出
<说明脚本成功后返回什么数据，格式是什么>

## 注意事项
- **选择器稳定性**：使用了<N>个ARIA选择器，<M>个class选择器
- **脆弱选择器**（如有）：`<选择器>`（<原因>，可能随网站改版失效）
- 如<网站名>改版导致脚本失效，使用 `/auvima.recipe update <配方名>` 更新
- <其他注意事项>

## 更新历史
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| <YYYY-MM-DD> | v1 | 初始版本 |
```

---

## 更新模式

如果用户执行 `/auvima.recipe update <配方名> "原因"`：

1. **读取现有配方**：
   ```bash
   # 使用Read工具读取
   src/auvima/recipes/<配方名>.js
   src/auvima/recipes/<配方名>.md
   ```

2. **显示当前信息**：
   - 当前版本号（从.md的更新历史提取）
   - 当前选择器（从.js头部注释或代码提取）
   - 上次更新原因

3. **重新探索**：按照"逐步探索"流程，引导用户重新描述步骤

4. **覆盖写入**：
   - `.js` 文件：完全覆盖，版本号+1
   - `.md` 文件：覆盖全文，在"更新历史"表格**追加新行**（不是替换）

**更新历史示例**：
```markdown
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-20 | v2 | YouTube改版，更新字幕按钮选择器 |
| 2025-11-19 | v1 | 初始版本 |
```

---

## 列出模式

如果用户执行 `/auvima.recipe list`：

1. **扫描目录**：读取 `src/auvima/recipes/*.js` 所有文件

2. **提取元数据**：从每个.js文件头部注释读取：
   ```javascript
   /**
    * Recipe: youtube_extract_transcript
    * Platform: youtube
    * Description: 提取视频字幕内容
    * Version: 2
    */
   ```

3. **按平台分组显示**：
   ```
   配方库（src/auvima/recipes/）：

   【YouTube】
   1. youtube_extract_transcript.js - 提取视频字幕内容 (v2)
   2. youtube_download_video.js - 下载视频 (v1)

   【GitHub】  
   3. github_clone_info.js - 获取仓库克隆信息 (v1)

   总计：3个配方
   ```

---

## 重要提醒

1. **你会写代码**：直接用Write工具写.js和.md，不要调用任何Python函数
2. **你经历过整个过程**：你执行了CDP命令，所以你知道怎么写JavaScript
3. **文件命名规范**：`<平台>_<功能>.js`（小写字母、下划线分隔）
4. **6章节完整性**：知识文档必须包含全部6个章节
5. **选择器降级**：按优先级从高到低排列，提供2-3个备选
6. **等待时间**：根据实际执行经验设置（点击500ms，导航2000ms）

---

## 开始执行

根据用户输入判断模式：
- 如果是 `/auvima.recipe update <配方名> "原因"`：进入**更新模式**
- 如果是 `/auvima.recipe list`：进入**列出模式**
- 否则：进入**创建模式**（从目标澄清开始）
