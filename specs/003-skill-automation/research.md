# Research: 技能自动化生成系统

**Feature**: 003-skill-automation
**Date**: 2025-11-18
**Purpose**: 解决技术上下文中的未知项，为实施设计提供技术决策依据

---

## 研究任务

### 1. JavaScript解析和生成策略

**问题**: 是否需要引入JavaScript解析库（如AST工具）来生成配方脚本？

**研究发现**:

配方脚本生成有三种可选策略：

1. **模板字符串拼接**（推荐）
   - 无需额外依赖
   - 使用Python f-string或Jinja2模板生成JavaScript代码
   - 适合结构化、可预测的代码生成场景
   - 示例：定义固定的JavaScript模板，填充选择器、操作序列等参数

2. **基于AST的生成**（过度工程）
   - 需要引入如 `esprima`、`escodegen` 等JavaScript AST库
   - 增加复杂度和依赖，对于本项目收益有限
   - 仅在需要复杂代码转换或分析时才有必要

3. **混合策略**（平衡方案）
   - 核心使用模板，复杂场景（如条件分支、循环）使用代码片段组合
   - 无需引入外部库，保持灵活性

**决策**: **采用模板字符串拼接策略**

**理由**:
- 配方脚本结构相对固定：DOM查询 → 操作序列 → 结果提取 → 错误处理
- 探索过程记录的信息已经是结构化的（选择器、操作类型、参数）
- Python原生字符串操作足够，无需引入JavaScript解析库
- 保持项目依赖简洁，符合Constitution Check的简洁性原则

**替代方案**: 如果未来需要支持用户自定义复杂逻辑（如自定义循环、条件判断），可在Phase 2考虑引入轻量级代码生成工具

---

### 2. DOM选择器优化策略

**问题**: 在探索过程中如何选择稳定的DOM选择器？优先级和降级策略是什么？

**研究发现**:

网站DOM结构变化频繁，选择器稳定性直接影响配方脚本长期可用性。业界最佳实践如下：

**选择器稳定性排序**（从最稳定到最脆弱）:

1. **ARIA属性**（最稳定）
   - `[aria-label="..."]`、`[role="button"]`
   - 语义化强，网站改版时较少变动
   - 优先级：⭐⭐⭐⭐⭐

2. **data-*自定义属性**
   - `[data-testid="..."]`、`[data-action="..."]`
   - 专门用于测试和自动化，变更频率低
   - 优先级：⭐⭐⭐⭐⭐

3. **稳定的ID**
   - `#main-content`、`#user-profile`
   - 语义化的ID通常稳定，但动态生成的ID（如 `id="item-12345"`）不稳定
   - 优先级：⭐⭐⭐⭐（需判断是否动态生成）

4. **语义化类名**
   - `.btn-primary`、`.article-title`
   - BEM命名规范的类名较稳定
   - CSS框架类（如Tailwind的 `.flex .items-center`）不稳定
   - 优先级：⭐⭐⭐

5. **HTML5语义标签**
   - `<button>`、`<nav>`、`<article>`
   - 结合文本内容（如 `button:has-text("提交")`）可提高准确性
   - 优先级：⭐⭐⭐

6. **XPath或CSS组合选择器**
   - `//div[@class="container"]/button[2]`
   - 依赖DOM结构层次，结构变化时易失效
   - 优先级：⭐⭐

7. **自动生成的类名或ID**（最脆弱）
   - `.css-1x2y3z4`、`#__next_app_123`
   - 打包工具生成的哈希类名，每次构建都会变化
   - 优先级：⭐（避免使用）

**决策**: **实现多层级选择器降级策略**

**具体实现方案**:

```python
# 选择器优先级枚举
class SelectorPriority:
    ARIA = 5           # aria-label, role
    DATA_ATTR = 5      # data-testid, data-*
    STABLE_ID = 4      # 非动态生成的ID
    SEMANTIC_CLASS = 3 # BEM类名
    SEMANTIC_TAG = 3   # HTML5标签 + 文本内容
    STRUCTURE = 2      # XPath/组合选择器
    GENERATED = 1      # 自动生成的类名（避免）
```

**探索时的策略**:
1. 查询元素时，同时提取多个选择器（ARIA、data-*、ID、class）
2. 为每个选择器评估优先级分数
3. 在生成的配方脚本中，优先使用高优先级选择器
4. 在知识文档"注意事项"章节标注脆弱的选择器

**生成的JavaScript示例**:
```javascript
// 优先使用ARIA选择器
let button = document.querySelector('[aria-label="显示字幕"]');
if (!button) {
  // 降级到稳定ID
  button = document.querySelector('#subtitle-button');
}
if (!button) {
  // 最后使用类名（标注为脆弱）
  button = document.querySelector('.btn-subtitle');
}
if (!button) {
  throw new Error('无法定位字幕按钮，页面结构可能已变化');
}
```

**理由**:
- 多层降级策略提高脚本鲁棒性
- 明确标注选择器稳定性，便于后续维护
- 符合用户故事中"动态加载和网站改版"的边缘案例需求

**考虑的替代方案**: 使用机器学习模型预测选择器稳定性 → 拒绝理由：过度工程化，规则策略已足够

---

### 3. 探索引擎交互模式

**问题**: 交互式探索引擎如何与Claude Code的AskUserQuestion工具集成？

**研究发现**:

Claude Code提供 `AskUserQuestion` 工具，支持：
- 1-4个问题，每个问题2-4个选项
- 多选模式（`multiSelect: true`）
- 自动提供"Other"选项用于自定义输入

**决策**: **设计三阶段交互流程**

**阶段1: 需求理解与配方命名**
```python
# 示例：用户输入 "/auvima.recipe create 在YouTube视频页面提取完整字幕内容"
问题1: 建议的配方名是 `youtube_extract_subtitles.js`，是否确认？
  - 选项1: 确认使用此名称
  - 选项2: 修改为其他名称（请在"Other"中输入）
  - 选项3: 取消创建
```

**阶段2: 元素定位引导**（在CDP探索失败时触发）
```python
问题1: 截图中哪个是字幕按钮？
  - 选项1: 右下角"CC"按钮
  - 选项2: 更多菜单中的"字幕"选项
  - 选项3: 无法识别（需要更多信息）
```

**阶段3: 配方验证与调整**
```python
问题1: 配方执行结果符合预期吗？
  - 选项1: 符合，保存配方
  - 选项2: 部分正确，需要微调
  - 选项3: 失败，重新探索
```

**实现策略**:
- 在 `explorer.py` 中封装 `ask_user()` 方法调用 `AskUserQuestion`
- 最多3次交互（符合用户故事约束）
- 截图通过CDP自动生成，嵌入到交互界面

---

### 4. 配方脚本执行环境

**问题**: 配方脚本如何在CDP Runtime环境中执行？有哪些限制？

**研究发现**:

配方脚本通过 `Runtime.evaluate` CDP命令在浏览器上下文中执行。

**执行环境特性**:
- JavaScript运行在当前页面的上下文中，可访问 `document`、`window`
- 支持ES6+语法（取决于浏览器版本）
- 不支持Node.js模块系统（无 `require`、`import`）
- 不支持跨域请求（受同源策略限制）
- 异步操作需使用 `Promise` 或 `async/await`

**限制与解决方案**:

| 限制 | 解决方案 |
|------|---------|
| 无法直接读写文件系统 | 结果通过 `Runtime.evaluate` 返回值传递给Python CLI |
| 动态内容需等待加载 | 配方脚本包含等待逻辑（轮询或 `MutationObserver`） |
| 跨域数据获取 | 配方仅提取当前页面DOM内容，不执行跨域请求 |
| 第三方库依赖 | 避免依赖外部库，使用原生JavaScript API |

**决策**: **配方脚本仅使用原生JavaScript，结果以JSON格式返回**

**示例配方脚本结构**:
```javascript
(async function() {
  try {
    // 1. 等待元素加载
    await waitForElement('[aria-label="字幕"]');

    // 2. 执行操作
    const button = document.querySelector('[aria-label="字幕"]');
    button.click();

    // 3. 提取结果
    const subtitles = document.querySelector('.subtitle-text').innerText;

    // 4. 返回JSON
    return { success: true, data: subtitles };
  } catch (error) {
    return { success: false, error: error.message };
  }
})();
```

---

### 5. 知识文档模板设计

**问题**: 6章节知识文档模板的具体内容结构是什么？

**决策**: **标准化Markdown模板**

```markdown
# [配方名称]

## 功能描述

[从用户原始需求提取的功能说明，1-2段]

## 使用方法

```bash
# 前置步骤（如需要）
uv run auvima navigate "https://example.com"

# 执行配方
uv run auvima exec-js recipes/[配方名].js
```

## 前置条件

- [ ] Chrome已通过CDP启动（端口9222）
- [ ] 已导航到目标页面：[URL模式]
- [ ] [如需要] 已登录账户
- [ ] [如需要] 特定页面状态（如视频正在播放）

## 预期输出

**数据格式**: JSON

```json
{
  "success": true,
  "data": {
    "字段1": "值",
    "字段2": ["数组值"]
  }
}
```

**失败情况**:
```json
{
  "success": false,
  "error": "错误信息描述"
}
```

## 注意事项

- ⚠️ **脆弱选择器**: `.css-abc123`（如果网站改版失效，请运行 `/auvima.recipe update`）
- ⚠️ **动态加载**: 字幕内容需等待2-3秒加载完成
- ⚠️ **已知限制**: 仅支持已展开的字幕内容，折叠状态下无法提取

## 更新历史

### 2025-11-18（初始版本）
- 创建配方脚本
- 测试环境：Chrome 120, YouTube 2025-11版本

### [未来更新日期]
- **原因**: [问题描述]
- **变更**: [具体修改内容]
- **测试**: [验证结果]
```

**模板实现**: 在 `knowledge.py` 中使用Jinja2或Python f-string生成

---

## 研究总结

### 关键技术决策对比表

| 技术选择点 | 决策 | 替代方案 | 拒绝理由 |
|-----------|------|---------|---------|
| JavaScript生成 | 模板字符串拼接 | AST代码生成库 | 过度工程，依赖过重 |
| 选择器策略 | 多层降级（ARIA优先） | 单一CSS选择器 | 稳定性不足 |
| 交互模式 | AskUserQuestion三阶段 | CLI问答输入 | 已有工具更优 |
| 脚本执行环境 | CDP Runtime.evaluate | Node.js子进程 | 与现有架构一致 |
| 知识文档 | 标准6章节模板 | 自由格式Markdown | 缺乏一致性 |

### 未解决的开放问题

**无** - 所有"NEEDS CLARIFICATION"项已解决

### 依赖与环境需求

**新增依赖**: 无
**Python依赖**: 使用现有依赖（websocket-client、click、pydantic）
**系统依赖**: Chrome + CDP（已有）

### 下一步行动

进入 **Phase 1: 设计与契约**，生成：
1. `data-model.md` - 实体和数据结构定义
2. `contracts/` - 配方脚本和文档的JSON Schema
3. `quickstart.md` - 快速开始指南
