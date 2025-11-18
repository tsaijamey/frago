# Quickstart: 技能自动化生成系统

**Feature**: 003-skill-automation
**Date**: 2025-11-18
**Audience**: 开发者和功能测试人员

快速上手指南，帮助你在10分钟内理解并开始使用配方系统。

---

## 前提条件

1. **已安装AuViMa CLI**
   ```bash
   uv run auvima --help
   ```

2. **Chrome已通过CDP启动**
   ```bash
   # 检查连接状态
   uv run auvima status
   ```
   如果未启动，参考项目README中的CDP启动说明。

3. **Claude Code已安装并可用**
   - 已配置 `.claude/commands/auvima_recipe.md`
   - 可执行 `/auvima.recipe` 命令

---

## 5分钟快速体验

### 场景1: 创建你的第一个配方

假设你经常需要从YouTube视频页面提取字幕，每次手动操作很繁琐，希望自动化这个流程。

**步骤1: 打开目标页面**
```bash
# 在Chrome中打开一个有字幕的YouTube视频
uv run auvima navigate "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

**步骤2: 在Claude Code中执行创建命令**
```
/auvima.recipe create "在YouTube视频页面提取完整字幕内容"
```

**步骤3: 交互式引导**

Claude Code会进入交互式探索模式：

1. **确认配方名称**
   ```
   问题: 建议的配方名是 `youtube_extract_subtitles.js`，是否确认?
   选项:
   - ✅ 确认使用此名称
   - ✏️ 修改为其他名称
   - ❌ 取消创建
   ```

2. **元素定位引导**（如果需要）
   Claude Code会截图并询问：
   ```
   问题: 截图中哪个是字幕按钮?
   选项:
   - 🔵 右下角"CC"按钮
   - 📋 更多菜单中的"字幕"选项
   - ❓ 无法识别（需要更多信息）
   ```

3. **验证结果**
   ```
   问题: 配方执行结果符合预期吗?
   [显示提取的字幕内容]
   选项:
   - ✅ 符合，保存配方
   - 🔧 部分正确，需要微调
   - ❌ 失败，重新探索
   ```

**步骤4: 配方已生成**

生成的文件：
```
src/auvima/recipes/
├── youtube_extract_subtitles.js    # 可执行脚本
└── youtube_extract_subtitles.md    # 知识文档
```

**步骤5: 使用配方**

下次需要提取字幕时：
```bash
# 1. 导航到YouTube视频页面
uv run auvima navigate "https://www.youtube.com/watch?v=..."

# 2. 执行配方
uv run auvima exec-js recipes/youtube_extract_subtitles.js
```

输出示例：
```json
{
  "success": true,
  "data": {
    "subtitles": "这是字幕内容...",
    "language": "zh-CN",
    "timestamp": "2025-11-18T10:30:00Z"
  }
}
```

---

### 场景2: 更新失效的配方

假设YouTube改版后，你的配方失效了。

**步骤1: 检查错误**
```bash
uv run auvima exec-js recipes/youtube_extract_subtitles.js

# 输出:
{
  "success": false,
  "error": "无法定位字幕按钮，页面结构可能已变化"
}
```

**步骤2: 更新配方**
```
/auvima.recipe update youtube_extract_subtitles "YouTube改版后字幕按钮的选择器失效了"
```

**步骤3: 自动探索与修复**

Claude Code会：
1. 加载现有配方和知识文档
2. 重新探索页面，定位新的字幕按钮
3. 更新选择器
4. 覆盖原脚本文件
5. 在知识文档的"更新历史"章节添加记录

**步骤4: 验证修复**
```bash
uv run auvima exec-js recipes/youtube_extract_subtitles.js
# 成功返回字幕内容
```

---

### 场景3: 浏览配方库

查看所有可用配方：
```
/auvima.recipe list
```

输出示例：
```
📦 可用配方 (3个)

🔹 youtube_extract_subtitles
   功能: 提取YouTube视频完整字幕内容
   创建: 2025-11-15
   最后更新: 2025-11-18

🔹 github_clone_repo_info
   功能: 克隆GitHub仓库的README和项目元信息
   创建: 2025-11-16

🔹 twitter_collect_search_tweets
   功能: 从Twitter搜索页面收集最新推文
   创建: 2025-11-17
```

查看配方文档：
```bash
cat src/auvima/recipes/youtube_extract_subtitles.md
```

---

## 开发者工作流

### 1. 理解系统架构

```
用户 → Claude Code (/auvima.recipe) → 探索引擎 → CDP → Chrome浏览器
                                          ↓
                                    配方生成器
                                          ↓
                      配方脚本(.js) + 知识文档(.md)
```

核心模块：
- `src/auvima/recipe/explorer.py` - 交互式探索引擎
- `src/auvima/recipe/generator.py` - 配方脚本生成器
- `src/auvima/recipe/knowledge.py` - 知识文档生成器
- `src/auvima/recipe/library.py` - 配方库管理

### 2. 数据模型

关键实体：
- **Recipe**: 配方元数据（名称、平台、选择器等）
- **Selector**: DOM选择器（优先级、稳定性评估）
- **ExplorationSession**: 探索会话记录
- **KnowledgeDocument**: 6章节知识文档

详见 `specs/003-skill-automation/data-model.md`

### 3. JSON Schema契约

所有数据结构已形式化为JSON Schema：
```
specs/003-skill-automation/contracts/
├── recipe.schema.json
├── selector.schema.json
├── exploration_session.schema.json
├── exploration_step.schema.json
├── knowledge_document.schema.json
└── update_record.schema.json
```

用于：
- Pydantic模型验证
- 单元测试数据生成
- API文档自动生成

### 4. 测试策略

**单元测试**（`tests/unit/recipe/`）:
```python
# 测试选择器优先级排序
def test_selector_priority_sorting():
    selectors = [
        Selector(selector=".btn", priority=3, type=SelectorType.CLASS, ...),
        Selector(selector="[aria-label='button']", priority=5, type=SelectorType.ARIA, ...),
    ]
    sorted_selectors = sort_by_priority(selectors)
    assert sorted_selectors[0].priority == 5  # ARIA在前
```

**集成测试**（`tests/integration/recipe/`）:
```python
# 测试完整配方创建流程
def test_recipe_creation_e2e(cdp_session):
    explorer = RecipeExplorer(cdp_session)
    session = explorer.create_recipe(
        description="提取YouTube字幕",
        target_url="https://youtube.com/watch?v=..."
    )
    assert session.status == SessionStatus.COMPLETED
    assert os.path.exists(session.recipe.script_path)
    assert os.path.exists(session.recipe.doc_path)
```

运行测试：
```bash
# 单元测试（快速）
pytest tests/unit/recipe/ -v

# 集成测试（需要Chrome + CDP）
pytest tests/integration/recipe/ -v

# 全部测试
pytest tests/ --cov=auvima.recipe
```

### 5. 调试技巧

**启用调试日志**:
```bash
export AUVIMA_DEBUG=1
uv run auvima exec-js recipes/youtube_extract_subtitles.js
```

**查看探索会话记录**:
```bash
# 探索会话序列化为JSON，便于调试
cat /tmp/explorations/550e8400-e29b-41d4-a716-446655440000.json
```

**手动测试配方脚本**:
```bash
# 在CDP中直接执行JavaScript
uv run auvima exec-js - <<'EOF'
(async function() {
  // 你的配方脚本内容
  const button = document.querySelector('[aria-label="字幕"]');
  return { found: !!button };
})();
EOF
```

---

## 常见问题

### Q1: 配方执行失败，返回"元素未找到"错误

**原因**: 页面结构已变化，或页面未完全加载。

**解决方案**:
1. 检查是否在正确的页面：`uv run auvima get-title`
2. 等待页面加载完成：`uv run auvima wait --selector "[aria-label='字幕']"`
3. 更新配方：`/auvima.recipe update <配方名> "描述问题"`

### Q2: 创建配方时探索过程卡住

**原因**: 交互次数超过3次，或用户输入不明确。

**解决方案**:
1. 取消当前探索（回复"❌ 取消"）
2. 重新整理需求描述，提供更明确的元素特征
3. 手动在浏览器中确认元素位置，然后再次尝试

### Q3: 如何处理需要登录的操作？

**方案**: 配方脚本不负责登录流程。

**最佳实践**:
1. 在探索前手动登录账户
2. 在配方的知识文档"前置条件"章节标注"已登录"
3. 配方脚本添加登录状态检查：
   ```javascript
   if (!document.querySelector('.user-avatar')) {
     throw new Error('请先登录账户');
   }
   ```

### Q4: 配方库太多，如何快速查找？

**当前方案**: 使用 `grep` 或文件名搜索
```bash
# 搜索平台
ls src/auvima/recipes/ | grep youtube

# 搜索功能关键词
grep -l "字幕" src/auvima/recipes/*.md
```

**未来改进**: 在Phase 2实现标签系统和配方搜索功能。

---

## 下一步

1. **阅读完整文档**:
   - `specs/003-skill-automation/spec.md` - 功能规格
   - `specs/003-skill-automation/data-model.md` - 数据模型
   - `specs/003-skill-automation/research.md` - 技术研究

2. **开始实施**:
   - 运行 `/speckit.tasks` 生成任务列表
   - 按照TDD流程编写测试并实现功能

3. **贡献配方**:
   - 使用 `/auvima.recipe create` 创建新配方
   - 分享常用配方到项目配方库

---

## 支持与反馈

- **问题报告**: 项目GitHub Issues
- **功能建议**: 通过 `/auvima.recipe` 命令的"Other"选项提交
- **文档改进**: 直接编辑 `specs/003-skill-automation/` 下的Markdown文件

**Happy Automating! 🤖**
