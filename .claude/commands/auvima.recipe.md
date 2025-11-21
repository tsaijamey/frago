---
description: "创建可复用的浏览器操作配方脚本（支持 Atomic 和 Workflow Recipe）"
---

# /auvima.recipe - 配方创建指令

## 你的任务

引导用户创建可复用的 Recipe（配方）。根据任务类型自动选择：
- **Atomic Recipe**: 单一原子操作（浏览器交互、系统任务）
- **Workflow Recipe**: 编排多个 Atomic Recipe 完成复杂任务

通过实际执行 CDP 操作来探索步骤，然后生成代码和元数据文件。

---

## 可用的AuViMa原子操作

```bash
# --- 基础导航 ---
# 导航到URL (可选等待元素出现)
uv run auvima navigate <url> [--wait-for <selector>]
# 获取页面标题
uv run auvima get-title

# --- 交互操作 ---
# 点击元素
uv run auvima click <selector> [--wait-timeout 10]
# 滚动页面 (正数向下，负数向上)
uv run auvima scroll <pixels>
# 等待指定时间
uv run auvima wait <seconds>

# --- 信息提取与调试 ---
# 执行JavaScript (加 --return-value 获取结果)
uv run auvima exec-js <expression> [--return-value]
# 获取文本内容 (默认body)
uv run auvima get-content [selector]
# 截图 (加 --full-page 截全屏)
uv run auvima screenshot <output_file> [--full-page]

# --- 视觉确认 (用于验证选择器) ---
# 高亮元素
uv run auvima highlight <selector>
# 显示鼠标指针
uv run auvima pointer <selector>
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
- 在哪个网站操作？
- 要完成什么任务？
- 前置条件是什么？（如：已打开某页面、已登录）

**文件命名思考**：
根据任务目标，构思一个能自我解释的**短句文件名**。
- 格式：`<平台>_<动词>_<对象>_<补充>.js`
- 目的：让AI仅看文件名就能理解脚本用途
- 示例：
  - `youtube_extract_video_transcript.js` (好：清晰明了)
  - `youtube_transcript.js` (差：是提取？显示？还是隐藏？)
  - `github_star_repository_if_not_starred.js` (好：逻辑完整)

### 2. 逐步探索（带结果验证）

引导用户描述每个步骤，**你实际执行CDP命令并验证结果**：

```
你: 第一步需要做什么？
用户: 点击"作者声明"展开详情
你: [执行] uv run auvima click '[aria-label="作者声明"]'
你: [等待] uv run auvima wait 0.5
你: [验证] uv run auvima screenshot /tmp/step1_result.png
你: [查看截图，确认详情已展开]
    ✓ 成功。记录：ARIA选择器（优先级5）
    ✓ 验证通过：页面出现了详情内容区域
    下一步呢？
```

**关键原则：每步必须验证**

对于每个操作步骤，必须验证其**结果特征**：

1. **导航操作**（navigate/click导致页面跳转）
   - 验证URL是否变化：`uv run auvima exec-js "window.location.href" --return-value`
   - 验证页面标题：`uv run auvima get-title`
   - 验证关键元素出现：`uv run auvima exec-js "document.querySelector('<特征元素>') !== null" --return-value`

2. **UI交互操作**（点击按钮/菜单）
   - 截图对比：`uv run auvima screenshot /tmp/stepN.png`
   - 验证目标元素出现/消失
   - 检查文本内容变化

3. **表单/输入操作**
   - 验证输入值已填充
   - 验证错误提示/成功提示

**记录每步的执行信息**：
- 使用的选择器（及其优先级）
- 执行的操作
- **等待时间**（根据页面响应速度调整）
- **验证方法**（如何确认步骤成功）
- **预期的页面特征变化**（用于生成验证代码）

**验证失败时的处理**：
如果某步验证失败（点击无效、元素未出现等）：
1. 尝试其他选择器
2. 增加等待时间
3. 检查是否需要滚动到元素位置
4. 记录哪些选择器失败了（避免写入配方）

### 3. 判断 Recipe 类型

**在生成文件前，判断任务类型**：

| 任务特征 | Recipe 类型 | 目录 | 运行时 |
|---------|------------|------|--------|
| 单一页面操作、数据提取 | Atomic | `examples/atomic/chrome/` | chrome-js |
| 系统操作（文件、剪贴板） | Atomic | `examples/atomic/system/` | python/shell |
| 需要调用多个 Recipe | Workflow | `examples/workflows/` | python |
| 批量处理、复杂编排 | Workflow | `examples/workflows/` | python |

**示例判断**：
- ❌ "批量提取10个Upwork职位" → Workflow（需要循环调用atomic Recipe）
- ✅ "提取单个Upwork职位信息" → Atomic（单一页面操作）
- ✅ "读取剪贴板内容" → Atomic（系统操作）
- ❌ "批量下载YouTube视频并生成字幕" → Workflow（多步骤编排）

### 4. 生成 Atomic Recipe 文件（chrome-js）

对话结束后，**使用Write工具**创建两个文件。**注意：Markdown元数据文件必须与脚本文件同名！**

#### 文件1: `examples/atomic/chrome/<自解释文件名>.js`

JavaScript配方脚本：

```javascript
/**
 * Recipe: <自解释文件名>
 * Platform: <平台名>
 * Description: <功能描述>
 * Created: <YYYY-MM-DD>
 * Version: 1
 */

(async () => {
  // 辅助函数：按优先级尝试多个选择器
  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`无法找到${description}`);
  }

  // 辅助函数：等待并验证元素出现
  async function waitForElement(selector, description, timeout = 5000) {
    const startTime = Date.now();
    while (Date.now() - startTime < timeout) {
      const elem = document.querySelector(selector);
      if (elem) return elem;
      await new Promise(r => setTimeout(r, 100));
    }
    throw new Error(`等待超时：${description} (${selector})`);
  }

  // 步骤1: <用户描述>
  const elem1 = findElement([
    { selector: '<ARIA或data属性>', priority: 5 },  // 最稳定
    { selector: '<稳定ID>', priority: 4 },           // 降级
    { selector: '<语义类名>', priority: 3 }          // 再降级
  ], '<元素描述>');
  elem1.click();

  // 验证步骤1成功：等待<预期特征>出现
  await waitForElement('<验证选择器>', '<预期特征描述>');
  await new Promise(r => setTimeout(r, 500));

  // 步骤2: <用户描述>
  const elem2 = findElement([
    { selector: '<选择器1>', priority: 5 }
  ], '<元素描述>');
  elem2.click();

  // 验证步骤2成功：检查<预期特征>
  await waitForElement('<验证选择器>', '<预期特征描述>');
  await new Promise(r => setTimeout(r, 500));

  // 步骤3: 提取数据
  const result = document.querySelector('.target').innerText;

  return result;
})();
```

**编写规则**：
- 使用箭头函数IIFE：`(async () => {...})()`（CDP才能正确等待Promise）
- 优先使用高优先级选择器（ARIA/data > ID > class）
- 每个元素提供2-3个降级选择器（如果探索中使用了多个）
- **每步操作后必须验证**：使用 `waitForElement()` 等待预期特征出现
- 操作后等待：点击/输入后500ms，导航后2000ms
- 清晰的错误消息（包含选择器信息）
- **验证选择器的选择**：选择步骤执行成功后"必然出现"的唯一元素

#### 文件2: `examples/atomic/chrome/<自解释文件名>.md`

**YAML Frontmatter 元数据** + **知识文档**：

```markdown
---
name: <recipe_name>
type: atomic
runtime: chrome-js
description: "<一句话描述功能>"
use_cases:
  - "<用例1：如'获取字幕用于翻译'>"
  - "<用例2：如'分析视频内容'>"
tags:
  - web-scraping
  - <平台名小写>
output_targets:
  - stdout
  - file
inputs: {}
outputs:
  result:
    type: object
    description: "提取的数据"
dependencies: []
version: "1.0.0"
---

# <自解释文件名>

## 功能描述
<详细说明这个配方的用途、适用场景和价值>

## 使用方法

**新架构执行方式**（推荐）：
```bash
# 使用 Recipe 系统统一接口
uv run auvima recipe run <recipe_name>
```

**传统方式**（兼容）：
```bash
# 直接通过 exec-js 执行
uv run auvima exec-js examples/atomic/chrome/<文件名>.js --return-value
```

**注意**：配方在浏览器上下文运行，可使用 `document`、`window` 等 API，但不能使用 Node.js 模块。

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

### 5. 生成 Workflow Recipe 文件（Python 编排）

**当任务需要调用多个 Atomic Recipe 时**，生成 Python Workflow。

#### 文件1: `examples/workflows/<workflow_name>.py`

Python 编排脚本：

```python
#!/usr/bin/env python3
"""
Workflow: <workflow_name>
Description: <任务描述>
Created: <YYYY-MM-DD>
Version: 1
"""

import json
import sys
from pathlib import Path
from auvima.recipes import RecipeRunner, RecipeExecutionError


def main():
    """主函数：编排多个 Atomic Recipe"""

    # 解析输入参数
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"参数 JSON 解析失败: {e}"
            }), file=sys.stderr)
            sys.exit(1)

    # 验证必需参数
    if '<必需参数名>' not in params:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: <参数名>"
        }), file=sys.stderr)
        sys.exit(1)

    # 初始化 Recipe Runner
    runner = RecipeRunner()
    results = []

    try:
        # 步骤1: 调用第一个 Atomic Recipe
        print(f"步骤1: <描述>", file=sys.stderr)
        result1 = runner.run('<atomic_recipe_name_1>', params={
            "param1": params.get("param1")
        })

        if not result1["success"]:
            raise RecipeExecutionError(
                recipe_name="<atomic_recipe_name_1>",
                runtime="chrome-js",
                exit_code=-1,
                stderr=result1.get("error", "Unknown error")
            )

        results.append(result1["data"])

        # 步骤2: 基于步骤1结果调用第二个 Recipe
        print(f"步骤2: <描述>", file=sys.stderr)
        result2 = runner.run('<atomic_recipe_name_2>', params={
            "input": result1["data"]["output_field"]
        })

        if not result2["success"]:
            raise RecipeExecutionError(
                recipe_name="<atomic_recipe_name_2>",
                runtime="python",
                exit_code=-1,
                stderr=result2.get("error", "Unknown error")
            )

        results.append(result2["data"])

        # 返回汇总结果
        output = {
            "success": True,
            "workflow": "<workflow_name>",
            "results": results,
            "summary": {
                "total": len(results),
                "completed": len([r for r in results if r])
            }
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))
        sys.exit(0)

    except RecipeExecutionError as e:
        print(json.dumps({
            "success": False,
            "error": {
                "type": "RecipeExecutionError",
                "recipe_name": e.recipe_name,
                "message": e.stderr
            }
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**编写规则**：
- 导入 `RecipeRunner` 和 `RecipeExecutionError`
- 使用 `runner.run(recipe_name, params)` 调用 Atomic Recipe
- 检查每个步骤的 `success` 字段
- 步骤间传递数据（前一步输出 → 后一步输入）
- 输出 JSON 格式结果到 stdout
- 错误信息输出到 stderr

#### 文件2: `examples/workflows/<workflow_name>.md`

**YAML Frontmatter 元数据** + **知识文档**：

```markdown
---
name: <workflow_name>
type: workflow
runtime: python
description: "<Workflow 功能描述>"
use_cases:
  - "<用例1>"
  - "<用例2>"
tags:
  - batch-processing
  - <相关标签>
output_targets:
  - stdout
  - file
inputs:
  <param_name>:
    type: <string|array|object>
    required: true
    description: "<参数描述>"
outputs:
  results:
    type: array
    description: "所有步骤的执行结果"
  summary:
    type: object
    description: "汇总统计"
dependencies:
  - <atomic_recipe_name_1>
  - <atomic_recipe_name_2>
version: "1.0.0"
---

# <workflow_name>

## 功能描述
<详细说明 Workflow 的编排逻辑、处理流程和价值>

## 使用方法

```bash
# 执行 Workflow
uv run auvima recipe run <workflow_name> \
  --params '{"<param_name>": "<value>"}' \
  --output-file results.json
```

## 前置条件
- 依赖的 Atomic Recipe 已存在
- Chrome CDP 已连接（如果依赖 chrome-js Recipe）

## 执行流程
1. **步骤1**: <描述调用哪个 Recipe 做什么>
2. **步骤2**: <描述调用哪个 Recipe 做什么>
3. **步骤N**: 汇总所有结果并输出

## 预期输出
```json
{
  "success": true,
  "workflow": "<workflow_name>",
  "results": [
    { "step1": "..." },
    { "step2": "..." }
  ],
  "summary": {
    "total": 2,
    "completed": 2
  }
}
```

## 注意事项
- 依赖 Recipe 必须可用（检查: `uv run auvima recipe list`）
- 如果某步失败，Workflow 会中止并返回错误
- 大批量处理时注意超时设置

## 更新历史
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| <YYYY-MM-DD> | v1 | 初始版本 |
```

---

## 更新模式

如果用户执行 `/auvima.recipe update <配方名> "原因"`：

1. **查找配方位置**：
   ```bash
   # 使用 recipe info 找到配方位置
   uv run auvima recipe info <recipe_name> --format json
   ```

2. **读取现有配方**：
   ```bash
   # 使用Read工具读取
   examples/atomic/chrome/<配方名>.js
   examples/atomic/chrome/<配方名>.md
   # 或
   examples/workflows/<配方名>.py
   examples/workflows/<配方名>.md
   ```

3. **显示当前信息**：
   - 当前版本号（从 YAML frontmatter 的 `version` 字段）
   - 当前选择器（从.js代码提取）
   - 上次更新原因（从"更新历史"表格）

4. **重新探索**（Atomic Recipe）或**重新设计**（Workflow）：
   - Atomic: 按照"逐步探索"流程
   - Workflow: 重新分析需要调用哪些 Atomic Recipe

5. **覆盖写入**：
   - 脚本文件（.js/.py）：完全覆盖
   - 元数据文件（.md）：
     - 更新 YAML frontmatter 的 `version` 字段（如 "1.0.0" → "1.1.0"）
     - 在"更新历史"表格**追加新行**

**更新历史示例**：
```markdown
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-21 | v1.1.0 | YouTube改版，更新字幕按钮选择器 |
| 2025-11-20 | v1.0.0 | 初始版本 |
```

---

## 列出模式

如果用户执行 `/auvima.recipe list`：

**直接使用 Recipe CLI**：
```bash
uv run auvima recipe list
```

**输出示例**：
```
SOURCE   TYPE      NAME                                    RUNTIME    VERSION
─────────────────────────────────────────────────────────────────────────────
Example  atomic    upwork_extract_job_details_as_markdown  chrome-js  1.0.0
Example  atomic    youtube_extract_video_transcript        chrome-js  1.2.0
Example  workflow  upwork_batch_extract                    python     1.0.0
User     workflow  custom_workflow                         python     2.0.0

总计: 4 个 Recipe
```

**AI 格式**（用于自动化）：
```bash
uv run auvima recipe list --format json
```

---

## 重要提醒

### Atomic Recipe (chrome-js)
1. **验证是核心**：每步操作后必须验证结果
2. **你会写代码**：直接用 Write 工具写 .js 和 .md 文件
3. **文件位置**：`examples/atomic/chrome/` 目录
4. **元数据格式**：YAML frontmatter + 知识文档（6章节）
5. **选择器降级**：提供 2-3 个备选选择器
6. **异步语法**：使用 `(async () => {...})()`

### Workflow Recipe (python)
1. **导入 RecipeRunner**：`from auvima.recipes import RecipeRunner`
2. **调用 Atomic Recipe**：`runner.run(recipe_name, params)`
3. **检查成功状态**：每步检查 `result["success"]`
4. **文件位置**：`examples/workflows/` 目录
5. **元数据格式**：YAML frontmatter（包含 `dependencies`）
6. **错误处理**：捕获 `RecipeExecutionError`

### 通用规则
- **文件命名规范**：`<平台>_<动词>_<对象>.js/py`（全小写，snake_case）
- **同名元数据文件**：脚本文件和元数据文件必须同名（仅后缀不同）
- **YAML frontmatter**：必须包含 `name`, `type`, `runtime`, `description`, `version` 等字段
- **知识文档**：Frontmatter 后必须包含完整的知识文档（6个章节）

---

## 开始执行

根据用户输入判断模式：
- 如果是 `/auvima.recipe create workflow "<任务描述>"`：进入 **Workflow 创建模式**
- 如果是 `/auvima.recipe create "<任务描述>"`：进入 **Atomic 创建模式**
- 如果是 `/auvima.recipe update <配方名> "原因"`：进入**更新模式**
- 如果是 `/auvima.recipe list`：调用 `uv run auvima recipe list`
- 否则：询问用户是创建 Atomic 还是 Workflow Recipe
