# Quickstart: 技能自动化生成系统（简化架构）

**Feature**: 003-skill-automation | **Date**: 2025-11-19

**核心理念**: Claude Code 本身就是智能探索引擎，无需构建复杂的状态管理系统。通过对话历史驱动配方生成。

---

## 快速开始（5分钟）

### 前置条件

1. **Chrome浏览器已连接CDP**
   ```bash
   # 检查CDP连接状态
   uv run frago exec-js "console.log('CDP connected')"
   ```

2. **Python环境已配置**
   ```bash
   # 验证Frago安装
   uv run frago --help
   ```

---

## 创建第一个配方

### 场景：提取YouTube视频字幕

**第1步：进入配方创建对话流程**

```bash
/frago.recipe "提取YouTube视频字幕内容"
```

Claude Code会通过prompt模板引导你完成以下流程：

**第2步：描述操作步骤**

你会被询问：*"请描述第一步操作是什么？"*

回答示例：
```
点击视频下方的"作者声明"展开详情区域
```

Claude Code会执行CDP命令：
```bash
uv run frago click '[aria-label="作者声明"]'
```

**第3步：继续描述后续步骤**

询问：*"下一步呢？"*

回答：
```
点击"内容转文字"按钮
```

Claude Code执行：
```bash
uv run frago click '[aria-label="内容转文字"]'
```

**第4步：提取数据**

询问：*"需要提取什么数据？"*

回答：
```
提取字幕文本内容
```

Claude Code执行：
```bash
uv run frago exec-js "document.querySelector('.subtitle-text').innerText"
```

**第5步：生成配方**

Claude Code从对话历史中提取：
- 使用的DOM选择器（`[aria-label="作者声明"]`, `[aria-label="内容转文字"]`, `.subtitle-text`）
- 操作序列（click → click → exec-js）
- 等待逻辑（根据CDP执行延迟自动推断）

自动生成：
- `src/frago/recipes/youtube_extract_transcript.js`（可执行脚本）
- `src/frago/recipes/youtube_extract_transcript.md`（知识文档）

---

## 生成的配方结构

### JavaScript脚本示例（简化版）

```javascript
/**
 * Recipe: youtube_extract_transcript
 * Platform: youtube
 * Description: 提取YouTube视频字幕内容
 * Created: 2025-11-19
 * Version: 1
 */
(async function() {
  // 选择器降级逻辑（优先ARIA，降级到class/id）
  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`无法找到元素: ${description}`);
  }

  // 步骤1: 展开作者声明
  const authorBtn = findElement([
    { selector: '[aria-label="作者声明"]', priority: 5 },
    { selector: '#author-statement', priority: 4 }
  ], '作者声明按钮');
  authorBtn.click();
  await new Promise(r => setTimeout(r, 500));

  // 步骤2: 点击内容转文字
  const transcriptBtn = findElement([
    { selector: '[aria-label="内容转文字"]', priority: 5 },
    { selector: '.transcript-button', priority: 3 }
  ], '字幕按钮');
  transcriptBtn.click();
  await new Promise(r => setTimeout(r, 1000));

  // 步骤3: 提取字幕文本
  const subtitle = document.querySelector('.subtitle-text');
  if (!subtitle) throw new Error('字幕内容未找到');

  return subtitle.innerText;
})();
```

### 知识文档示例（简化版）

```markdown
# youtube_extract_transcript

## 功能描述
从YouTube视频页面提取完整字幕内容。

## 使用方法
1. 打开YouTube视频页面
2. 执行配方脚本：
   ```bash
   uv run frago exec-js recipes/youtube_extract_transcript.js
   ```

## 前置条件
- 已打开YouTube视频页面
- 视频包含字幕内容
- Chrome CDP已连接

## 预期输出
纯文本格式的字幕内容（字符串）

## 注意事项
- 字幕按钮选择器使用ARIA标签，稳定性较高
- 如YouTube改版可能需要更新选择器
- 脆弱选择器：`.subtitle-text`（CSS类名）

## 更新历史
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-19 | v1 | 初始版本 |
```

---

## 更新现有配方

### 场景：YouTube改版导致选择器失效

```bash
/frago.recipe update youtube_extract_transcript "字幕按钮选择器失效了"
```

Claude Code会：
1. 加载原有脚本内容
2. 重新探索页面，找到新的选择器
3. 覆盖原文件生成更新版本
4. 在知识文档的"更新历史"章节添加新记录：

```markdown
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-20 | v2 | 更新字幕按钮选择器（YouTube改版） |
| 2025-11-19 | v1 | 初始版本 |
```

---

## 列出所有配方

```bash
/frago.recipe list
```

输出示例：
```
配方库（src/frago/recipes/）：
1. youtube_extract_transcript.js - 提取YouTube视频字幕内容
2. github_clone_repo_info.js - 获取GitHub仓库克隆信息
3. twitter_export_thread.js - 导出Twitter完整线程

总计：3个配方
```

---

## 核心设计原则

### 1. Claude Code = 探索引擎

**错误理解**：需要构建独立的RecipeExplorer类来管理探索状态

**正确理解**：Claude Code通过prompt模板引导用户描述步骤，对话历史即为探索记录

### 2. Claude Code直接写代码

**Claude Code会写代码**：在对话结束后，Claude Code使用Write工具直接创建.js和.md文件

**无需Python生成器**：
- 不需要conversation_parser.py来解析对话 → Claude Code自己经历了对话
- 不需要generator.py来生成代码 → Claude Code直接写JavaScript
- 不需要Pydantic模型 → Claude Code写文件头部注释即可

### 3. 选择器降级策略

保留Phase 1-2已完成的核心价值组件：

**优先级排序**（5→1）：
1. ARIA标签/data属性（最稳定）
2. 稳定ID
3. 语义化类名
4. HTML5语义标签
5. 结构选择器
6. 生成的类名（最脆弱）

**降级逻辑生成**：
```javascript
// 自动生成多层降级查询
const elem = document.querySelector('[aria-label="按钮"]')  // 优先级5
  || document.querySelector('#submit-btn')                  // 优先级4
  || document.querySelector('.btn-submit')                  // 优先级3
  || null;
```

### 4. 扁平文件系统存储

**无数据库**：所有配方和文档存储在 `src/frago/recipes/` 扁平目录

**命名约定**：`<平台>_<功能描述>.js`（例如 `youtube_extract_transcript.js`）

**版本管理**：覆盖原文件，历史记录在.md的"更新历史"章节

---

## 架构简化对比

### 删除的过度设计组件（完全不需要）

❌ **RecipeExplorer类** → Claude Code本身就是探索引擎
❌ **ExplorationSession/Step模型** → 对话历史即为状态
❌ **Selector模型（selector.py）** → 规则整合在prompt中
❌ **Recipe/KnowledgeDocument模型（models.py）** → Claude Code不需要Python数据模型
❌ **模板系统（templates.py）** → Prompt中提供JavaScript模板示例
❌ **对话解析器（conversation_parser.py）** → Claude Code读自己的对话历史
❌ **代码生成器（generator.py）** → Claude Code用Write工具直接写文件
❌ **配方库管理（library.py）** → Claude Code用Glob/Read工具扫描目录
❌ **所有单元测试（51个）** → 测试的代码已删除

### 唯一保留的组件

✅ **Prompt模板**（`.claude/commands/frago_recipe.md`）：完整的指令集
✅ **配方库目录**（`src/frago/recipes/`）：存放生成的.js和.md文件
✅ **配方执行器**：通过 `uv run frago exec-js` 执行配方

---

## 后续开发路径

### Phase 4：验证和优化（进行中）

**任务列表**（参考 tasks.md）：
- T004-T007: 手动测试创建、更新、列出配方的完整流程
- T008-T009: 优化prompt模板的引导语言和错误处理
- T010: 更新CLAUDE.md项目文档
- T011: 验证配方脚本执行成功率 >90%

**重点**:
- 测试真实场景（YouTube、GitHub等）
- 优化prompt模板的引导效果
- 改进Claude Code生成的脚本质量
- 完善错误处理指令

---

## 常见问题

### Q1: 如何确保生成的配方脚本稳定？

**A**: 使用选择器优先级策略，优先ARIA标签和data属性（稳定性5级），降级到class/id（3-4级），避免生成的类名（1级）。脆弱选择器会在知识文档的"注意事项"中标注。

### Q2: 配方脚本执行失败怎么办？

**A**: 使用 `/frago.recipe update <配方名>` 重新探索页面，系统会覆盖原文件生成更新版本，并在文档中记录更新原因。

### Q3: 如何避免命名冲突？

**A**: 遵循 `<平台>_<功能描述>` 命名约定，创建前系统会检查同名文件，如存在则询问是否覆盖更新。

### Q4: 配方脚本可以跨页面使用吗？

**A**: 可以。在对话中描述页面切换步骤，Claude Code会在脚本中生成对应的导航逻辑和等待条件。

### Q5: 为什么不需要ExplorationSession？

**A**: Claude Code的对话历史已经包含所有探索信息（用户描述、CDP执行记录、选择器），无需额外的状态管理系统。这是架构简化的核心理念。

---

## 技术参考

- **数据模型**：[data-model.md](./data-model.md)
- **实施计划**：[plan.md](./plan.md)
- **需求规格**：[spec.md](./spec.md)
- **研究决策**：[research.md](./research.md)
- **JSON Schema契约**：[contracts/](./contracts/)

---

**下一步**：阅读 [tasks.md](./tasks.md) 了解具体实施任务，或直接运行 `/frago.recipe` 体验配方创建流程（Phase 3完成后）。
