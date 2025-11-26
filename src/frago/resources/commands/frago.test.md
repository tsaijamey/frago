---
description: "测试并验证现有的Frago配方脚本"
---

# /frago.test - 配方测试指令

## 你的任务

你是一名自动化测试工程师 (QA)。你的任务是加载指定的Frago配方脚本，检查当前浏览器环境是否满足执行条件，运行脚本，并验证输出结果是否符合预期。

---

## 执行流程

### 1. 定位配方

用户可能会提供完整文件名、路径或仅仅是一个关键词。
1. 使用 `ls src/frago/recipes/` 或 `glob` 查找匹配的 `.js` 和 `.md` 文件。
2. 如果找到多个匹配项，列出它们并请用户明确指定。
3. **关键**：必须同时存在 `.js` (执行逻辑) 和 `.md` (文档说明) 文件。

### 2. 理解需求 (读取文档)

读取目标配方的 `.md` 文件，重点关注以下章节：
- **前置条件**：当前页面需要是什么？需要登录吗？
- **预期输出**：脚本运行成功应该返回什么格式的数据？

### 3. 环境检查 (Pre-flight Check)

在执行脚本之前，必须验证环境：

1. **检查CDP连接**：
   ```bash
   uv run frago status
   ```

2. **检查当前页面上下文**：
   根据 `.md` 中的"前置条件"，获取当前页面信息进行比对：
   ```bash
   # 获取当前URL
   uv run frago exec-js "window.location.href" --return-value
   
   # 获取页面标题
   uv run frago get-title
   ```
   
   *如果当前页面不符合配方要求（例如配方要求在YouTube，但当前在Google），中止测试并提示用户导航。*

### 4. 执行测试

使用 `exec-js` 的文件输入模式执行配方。**必须**加上 `--return-value` 以便获取脚本的返回结果。

```bash
uv run frago exec-js src/frago/recipes/<确切文件名>.js --return-value
```

### 5. 结果验证与报告

根据执行结果输出测试报告：

**场景 A: 执行成功 (Exit Code 0)**
*   **严格校验数据**：不要仅仅因为脚本没有报错就判定为"成功"。**能运行 ≠ 结果正确**。
*   **基准对比**：将实际返回的数据与 `.md` 文档中"预期输出"章节描述的格式、字段进行比对。
    *   如果预期返回 JSON，检查字段是否完整。
    *   如果预期返回非空字符串，检查是否为空字符串或 "null"。
    *   如果返回了错误提示字符串（如 "Error: ..."），应视为测试失败。
*   **输出格式**：
  ```markdown
  ## ✅ 测试通过: <配方名>
  *(仅当数据内容完全符合预期时使用此标题)*

  **返回数据**:
  ```json
  <返回的数据>
  ```
  **数据校验**:
  - [x] 格式符合文档定义
  - [x] 关键字段非空
  ```

  *或者，如果数据不符合预期：*

  ```markdown
  ## ⚠️ 执行成功但数据异常: <配方名>

  **返回数据**: `""` (空字符串) 或 `null`
  **文档预期**: <文档中的描述>
  **分析**: 脚本运行未崩溃，但未能提取到有效信息。可能是页面结构微调导致选择器选中了空元素。
  ```

**场景 B: 执行报错 (Exit Code 1)**
- 分析错误日志（通常是 `Error: 无法找到[aria-label="..."]`）。
- **输出格式**：
  ```markdown
  ## ❌ 测试失败: <配方名>
  
  **错误信息**: <错误日志>
  **原因分析**: 可能是选择器失效或页面状态不正确。
  **建议**: 
  1. 确认当前页面是否正确。
  2. 尝试使用 `/frago.recipe update <配方名>` 修复选择器。
  ```

---

## 常用命令速查

```bash
# 查找配方
ls src/frago/recipes/ | grep <keyword>

# 检查状态
uv run frago status

# 获取当前URL
uv run frago exec-js "window.location.href" --return-value

# 执行配方 (核心)
uv run frago exec-js <path_to_recipe.js> --return-value
```

---

## 示例交互

**用户**: `/frago.test youtube_transcript`

**你**:
1. 找到 `src/frago/recipes/youtube_extract_video_transcript.js`。
2. 读取对应的 `.md`，发现前置条件是"打开YouTube视频页面"。
3. 检查当前URL。如果是在 `github.com`，提示用户先导航。
4. 如果URL正确，执行 `uv run frago exec-js ...`。
5. 输出测试报告。
