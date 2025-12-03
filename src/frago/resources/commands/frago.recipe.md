---
description: "创建可复用的浏览器操作配方脚本（支持 Atomic 和 Workflow Recipe）"
---

# /frago.recipe - 配方创建指令

创建可复用的 Recipe（配方）。

## 参考文档

| 类型 | 文档 | 说明 |
|------|------|------|
| **规则** | [SCREENSHOT_RULES.md](frago/rules/SCREENSHOT_RULES.md) | 截图规范 |
| **指南** | [SELECTOR_PRIORITY.md](frago/guides/SELECTOR_PRIORITY.md) | 选择器优先级 |
| **指南** | [RECIPE_FIELDS.md](frago/guides/RECIPE_FIELDS.md) | 配方字段规范 |
| **示例** | [recipe_workflow.sh](frago/scripts/recipe_workflow.sh) | 工作流示例 |
| **示例** | [common_commands.sh](frago/scripts/common_commands.sh) | 通用命令 |

---

## 核心定位

| 类型 | 适用场景 | 运行时 | 目录 |
|------|---------|--------|------|
| **Atomic** | 单一原子操作 | chrome-js / python / shell | `examples/atomic/` |
| **Workflow** | 编排多个 Recipe | python | `examples/workflows/` |

---

## 执行流程

### 1. 目标澄清

问清楚：
- 在哪个网站操作？
- 要完成什么任务？
- 前置条件是什么？

### 2. 文件命名

**格式**：`<平台>_<动词>_<对象>_<补充>`

| 示例 | 质量 |
|------|------|
| `youtube_extract_video_transcript` | ✅ 好 |
| `youtube_transcript` | ❌ 差（是提取还是显示？） |

### 3. 逐步探索（带验证）

```bash
# 执行操作
frago chrome click '[aria-label="提交"]'

# 等待
frago chrome wait 0.5

# 验证结果
frago chrome screenshot /tmp/step1.png
# 或验证元素
frago chrome exec-js "document.querySelector('.success') !== null" --return-value
```

**关键**：每步必须验证结果

### 4. 判断 Recipe 类型

| 任务特征 | 类型 |
|---------|------|
| 单一页面操作、数据提取 | Atomic |
| 系统操作（文件、剪贴板） | Atomic |
| 需要调用多个 Recipe | Workflow |
| 批量处理、复杂编排 | Workflow |

### 5. 生成文件

**目录结构**：
```
examples/atomic/chrome/<recipe_name>/
├── recipe.md      # 元数据 + 文档
└── recipe.js      # 执行脚本

examples/workflows/<workflow_name>/
├── recipe.md      # 元数据 + 文档
├── recipe.py      # 执行脚本
└── examples/      # 示例数据（可选）
```

### 6. 验证配方

创建或修改配方后，**必须运行验证**：

```bash
frago recipe validate <配方目录>
```

详见 [RECIPE_FIELDS.md](frago/guides/RECIPE_FIELDS.md)

---

## 选择器优先级

详见 [SELECTOR_PRIORITY.md](frago/guides/SELECTOR_PRIORITY.md)

| 优先级 | 类型 | 稳定性 |
|--------|------|--------|
| **5** | ARIA / data 属性 | ✅ 很稳定 |
| **4** | 稳定 ID | ✅ 稳定 |
| **3** | 语义化类名 / HTML5 标签 | ⚠️ 中等 |
| **2** | 结构选择器 | ⚠️ 脆弱 |
| **1** | 生成的类名 `.css-*` | ❌ 很脆弱 |

```javascript
// 提供 2-3 个降级选择器
const elem = findElement([
  { selector: '[aria-label="提交"]', priority: 5 },
  { selector: '#submit-button', priority: 4 },
  { selector: '.btn-submit', priority: 3 }
], '提交按钮');
```

---

## 截图规范

详见 [SCREENSHOT_RULES.md](frago/rules/SCREENSHOT_RULES.md)

| 用途 | 正确 | 错误 |
|------|------|------|
| 验证操作结果 | ✅ | - |
| 调试问题 | ✅ | - |
| 读取内容 | - | ❌ 用 get-content |
| 提取数据 | - | ❌ 用 exec-js |

---

## Atomic Recipe 模板

### recipe.js

```javascript
(async () => {
  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`无法找到${description}`);
  }

  async function waitForElement(selector, description, timeout = 5000) {
    const startTime = Date.now();
    while (Date.now() - startTime < timeout) {
      const elem = document.querySelector(selector);
      if (elem) return elem;
      await new Promise(r => setTimeout(r, 100));
    }
    throw new Error(`等待超时：${description}`);
  }

  // 步骤1
  const elem = findElement([
    { selector: '[aria-label="..."]', priority: 5 }
  ], '元素描述');
  elem.click();
  await waitForElement('.result', '结果出现');

  return result;
})();
```

### recipe.md

```yaml
---
name: recipe_name
type: atomic
runtime: chrome-js
description: "一句话描述"
inputs: {}
outputs: {}
version: "1.0.0"
---

# recipe_name

## 功能描述
## 使用方法
## 前置条件
## 预期输出
## 注意事项
## 更新历史
```

---

## Workflow Recipe 模板

### recipe.py

```python
from frago.recipes import RecipeRunner, RecipeExecutionError

def main():
    runner = RecipeRunner()

    result = runner.run('atomic_recipe_name', params={...})
    if not result["success"]:
        raise RecipeExecutionError(...)

    print(json.dumps(output))

if __name__ == "__main__":
    main()
```

### recipe.md

```yaml
---
name: workflow_name
type: workflow
runtime: python
dependencies:
  - atomic_recipe_1
  - atomic_recipe_2
version: "1.0.0"
---
```

---

## 命令模式

| 命令 | 说明 |
|------|------|
| `/frago.recipe create "<描述>"` | 创建 Atomic |
| `/frago.recipe create workflow "<描述>"` | 创建 Workflow |
| `/frago.recipe update <名称> "<原因>"` | 更新配方 |
| `/frago.recipe list` | 列出所有配方 |
| `/frago.recipe validate <路径>` | 验证配方完整性 |

---

## 必需字段速查

详见 [RECIPE_FIELDS.md](frago/guides/RECIPE_FIELDS.md)

| 字段 | 要求 |
|------|------|
| `name` | `[a-zA-Z0-9_-]` |
| `type` | `atomic` / `workflow` |
| `runtime` | `chrome-js` / `python` / `shell` |
| `version` | `1.0` 或 `1.0.0` |
| `description` | ≤200 字符 |
| `use_cases` | 至少一个 |
| `output_targets` | `stdout` / `file` / `clipboard` |

