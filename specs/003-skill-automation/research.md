# Research: 技能自动化生成系统（简化架构）

**Feature**: 003-skill-automation
**Date**: 2025-11-18
**Updated**: 2025-11-19（架构简化调整）
**Status**: Phase 0 Research

## 概述

本文档研究基于简化架构的技能自动化生成系统的三个核心技术问题。核心思路是利用Claude Code本身作为智能探索引擎，通过prompt模板引导使用frago的CDP原子命令，从对话历史中提取关键信息生成JavaScript配方脚本，**无需构建独立的探索引擎类（RecipeExplorer）或复杂的状态管理（ExplorationSession）**。

基于2025-11-19的澄清：
- ✅ Claude Code本身就是智能探索引擎
- ✅ 对话历史即为探索记录
- ✅ 删除过度设计的RecipeExplorer和ExplorationSession
- ✅ 保留核心价值组件：Selector策略、模板系统、配方库管理

---

## 研究任务1: Prompt模板设计

### 问题陈述

如何设计 `.claude/commands/frago_recipe.md` 来引导Claude Code：
1. 理解用户的操作需求并提取关键信息（平台、操作、目标）
2. 逐步执行CDP命令与浏览器交互
3. 记录操作历史和关键选择器
4. 在探索失败时进行交互式澄清
5. 从对话历史生成配方脚本和知识文档

### 决策：分阶段引导流程

**选择方案**：采用5阶段结构化prompt模板，每个阶段有明确的输出要求和检查点。

**模板结构**：

```markdown
## 阶段1: 需求理解与配方命名
- 提取平台/网站（youtube/github/twitter等）
- 提取操作目标（提取字幕/克隆信息/收集推文）
- 生成建议的配方名：`<平台>_<操作简述>.js`
- 检查是否存在同名配方（使用Glob工具查看src/frago/recipes/目录）

## 阶段2: 交互式探索
- 确认Chrome已连接CDP（端口9222）
- 根据用户描述导航到目标页面
- 逐步执行用户描述的操作：
  - 使用 `uv run frago screenshot` 展示当前页面
  - 使用 `uv run frago click <selector>` 点击元素
  - 使用 `uv run frago exec-js <expression>` 提取内容
- **重要**：在对话中明确记录每一步使用的选择器和操作结果
- 探索失败时：截图 + 询问用户 + 提供候选元素（最多3次交互）

## 阶段3: 生成配方脚本
- 从对话历史提取操作序列（回顾阶段2的对话记录）
- 使用src/frago/recipe/templates.py的JavaScriptTemplate生成代码
- 包含降级逻辑（基于src/frago/recipe/selector.py的策略）
- 保存到 `src/frago/recipes/<配方名>.js`

## 阶段4: 生成知识文档
- 使用src/frago/recipe/templates.py的MarkdownTemplate生成6章节文档
- 从对话历史提取前置条件和操作步骤
- 标注脆弱的选择器（is_fragile=True）
- 保存到 `src/frago/recipes/<配方名>.md`

## 阶段5: 验证配方
- 在当前页面执行生成的配方：`uv run frago exec-js recipes/<配方名>.js`
- 检查输出是否符合预期
- 如有问题，询问用户是否需要调整
```

**关键引导策略**：

1. **明确的工具调用指令**：直接告诉Claude Code使用哪个CDP命令
   ```
   使用Bash工具执行：uv run frago screenshot /tmp/page.png
   使用Bash工具执行：uv run frago click '[aria-label="字幕"]'
   ```

2. **记录意识的强化**：在每个阶段强调记录的重要性
   ```
   在对话中明确记录：
   - 使用的选择器：'[aria-label="字幕"]'
   - 元素描述：字幕按钮
   - 操作结果：成功点击，字幕面板已展开

   这些信息将用于阶段3生成配方脚本。
   ```

3. **失败处理模板**：提供标准化的失败处理流程
   ```
   如果元素定位失败：
   1. 使用Bash执行：uv run frago screenshot /tmp/failed_step.png
   2. 使用AskUserQuestion询问："我无法定位<元素描述>，你能描述它的特征吗？"
      - 选项1：在页面的<位置>区域
      - 选项2：包含<文本内容>
      - 选项3：需要先执行其他操作
   3. 最多3次交互，仍失败则：
      - 记录已完成的部分步骤
      - 建议用户重新整理需求或提供更多细节
      - 不生成不完整的配方
   ```

4. **代码生成触发器**：明确何时开始生成代码
   ```
   当所有操作成功完成后，使用以下步骤生成配方脚本：

   1. 回顾对话历史，提取所有CDP命令（grep对话中的 "uv run frago" 命令）
   2. 提取选择器和上下文（查找 "使用的选择器：" 标记）
   3. 读取 src/frago/recipe/templates.py 了解代码生成模板
   4. 读取 src/frago/recipe/selector.py 了解选择器优先级逻辑
   5. 生成JavaScript脚本并保存
   6. 生成Markdown文档并保存
   ```

**理由**：

- **利用Claude Code的对话能力**：Claude Code天然擅长理解结构化指令和维护对话上下文，prompt模板只需提供清晰的引导框架
- **减少实现复杂度**：不需要构建独立的探索引擎类（RecipeExplorer），所有逻辑在prompt中声明式表达
- **灵活性**：prompt模板易于迭代和调整，用户反馈可以快速集成到新版本中
- **记录意识**：通过在每个阶段强调记录，确保Claude Code在对话历史中保留生成脚本所需的所有信息

**考虑的替代方案**：

1. **方案A：单一长prompt**
   - 将所有指令写成一个长段落
   - ❌ 拒绝理由：缺乏结构，Claude Code难以跟踪当前处于哪个阶段

2. **方案B：用户主导探索**
   - Prompt只提供基础指令，让用户自行决定每一步
   - ❌ 拒绝理由：增加用户负担，与"通过自然语言快速生成配方"的目标不符

3. **方案C：硬编码探索逻辑**
   - 构建独立的Python探索引擎类（RecipeExplorer）
   - ❌ 拒绝理由：过度设计，违反简化架构原则（已在2025-11-19澄清中明确删除）

---

## 研究任务2: 从对话历史提取信息

### 问题陈述

如何从Claude Code的对话历史中提取生成JavaScript脚本所需的关键信息：
- DOM选择器列表（包含优先级）
- 操作序列（点击、提取、等待）
- 等待时间（显式或隐式）
- 错误处理逻辑
- 前置条件

### 决策：基于Pattern Matching的历史解析

**选择方案**：在generator.py中实现对话历史解析器（ConversationHistoryParser），使用正则表达式和启发式规则提取关键信息。

**实现策略**：

```python
class ConversationHistoryParser:
    """从对话历史提取配方生成所需的信息"""

    @staticmethod
    def extract_cdp_commands(conversation_text: str) -> List[Dict[str, str]]:
        """
        提取执行的CDP命令

        识别模式：
        - "uv run frago click <selector>"
        - "uv run frago exec-js <expression>"
        - "uv run frago screenshot <path>"
        - "uv run frago navigate <url>"
        """
        patterns = {
            'click': r'uv run frago click\s+[\'"]?(.+?)[\'"]?(?:\s|$)',
            'exec-js': r'uv run frago exec-js\s+[\'"]?(.+?)[\'"]?(?:\s|$)',
            'screenshot': r'uv run frago screenshot\s+(.+?)(?:\s|$)',
            'navigate': r'uv run frago navigate\s+(.+?)(?:\s|$)',
        }

        commands = []
        for action, pattern in patterns.items():
            matches = re.findall(pattern, conversation_text, re.MULTILINE)
            for match in matches:
                commands.append({'action': action, 'parameter': match})

        return commands

    @staticmethod
    def extract_selectors_with_context(conversation_text: str) -> List[Tuple[str, str]]:
        """
        提取选择器及其上下文描述

        识别模式：
        - "使用的选择器：<selector>"（prompt模板要求的标记格式）
        - "元素描述：<description>"
        - "点击<描述>: uv run frago click <selector>"
        - document.querySelector(<selector>) 调用
        """
        selector_contexts = []

        # 模式1: prompt模板标记的选择器（最优先）
        pattern1 = r'使用的选择器：\s*[\'"]?(.+?)[\'"]?\s*元素描述：\s*(.+?)(?:\n|$)'
        matches1 = re.findall(pattern1, conversation_text, re.MULTILINE)
        selector_contexts.extend([(desc, sel) for sel, desc in matches1])

        # 模式2: 命令前的描述
        pattern2 = r'(?:点击|提取|定位)(.+?)[:：]\s*uv run frago \w+\s+[\'"]?(.+?)[\'"]?'
        matches2 = re.findall(pattern2, conversation_text, re.MULTILINE)
        selector_contexts.extend(matches2)

        # 模式3: querySelector调用
        pattern3 = r'document\.querySelector\([\'"](.+?)[\'"]\)'
        matches3 = re.findall(pattern3, conversation_text)
        for sel in matches3:
            # 尝试在上下文中找到描述
            context = extract_context_around_selector(conversation_text, sel)
            selector_contexts.append((context or "元素", sel))

        return selector_contexts

    @staticmethod
    def extract_wait_times(conversation_text: str) -> Dict[str, int]:
        """
        提取等待时间（显式或隐式）

        识别模式：
        - "等待<N>秒"
        - "动态加载"、"异步加载" -> 默认5000ms
        - "点击后需要等待" -> 默认500ms
        """
        wait_times = {}

        # 显式等待
        explicit_wait = re.findall(r'等待\s*(\d+)\s*秒', conversation_text)
        if explicit_wait:
            wait_times['explicit'] = int(explicit_wait[0]) * 1000

        # 隐式等待提示
        if re.search(r'动态加载|异步加载|AJAX', conversation_text):
            wait_times['dynamic_content'] = 5000

        if re.search(r'点击后|操作后', conversation_text):
            wait_times['after_action'] = 500

        return wait_times

    @staticmethod
    def extract_prerequisites(conversation_text: str) -> List[str]:
        """
        提取前置条件

        识别模式：
        - "需要登录"
        - "需要打开<URL>"
        - "确保<条件>"
        """
        prerequisites = []

        if re.search(r'需要登录|登录状态', conversation_text):
            prerequisites.append("用户已登录目标网站")

        url_matches = re.findall(r'需要打开\s+(.+?)(?:\s|$)', conversation_text)
        if url_matches:
            prerequisites.append(f"浏览器已打开页面: {url_matches[0]}")

        # 通用前置条件（始终包含）
        prerequisites.insert(0, "Chrome已通过CDP启动（端口9222）")

        return prerequisites

    @staticmethod
    def extract_user_description(conversation_text: str) -> str:
        """
        提取用户原始需求描述

        识别第一条包含 "/frago.recipe" 的消息
        """
        pattern = r'/frago\.recipe\s+(?:create\s+)?[\'"]?(.+?)[\'"]?(?:\s|$)'
        match = re.search(pattern, conversation_text)
        if match:
            return match.group(1)
        return "未提供描述"
```

**关键启发式规则**：

1. **上下文窗口**：在识别选择器时，查看前后3行文本以获取描述性上下文
   ```python
   def extract_context_around_selector(text: str, selector: str, window=3) -> str:
       lines = text.split('\n')
       for i, line in enumerate(lines):
           if selector in line:
               start = max(0, i - window)
               end = min(len(lines), i + window + 1)
               context_lines = lines[start:end]
               # 查找描述性文本（中文名词或动词短语）
               for ctx_line in context_lines:
                   match = re.search(r'[\u4e00-\u9fa5]{2,}', ctx_line)
                   if match:
                       return match.group(0)
       return ""
   ```

2. **时间推断**：
   - 点击操作后默认等待500ms
   - 动态加载内容默认等待5000ms
   - 显式提到的时间优先

3. **选择器优先级**：使用selector.py的已有逻辑自动评估优先级
   ```python
   from frago.recipe.selector import create_selector_from_string

   selector_obj = create_selector_from_string(selector_str, element_description)
   # selector_obj.priority 已自动评估
   # selector_obj.is_fragile 已自动标记
   ```

4. **错误处理模式**：如果对话中出现"失败"、"未找到"等关键词，提取对应的降级策略

**理由**：

- **利用现有模块**：selector.py已实现选择器稳定性评估，generator只需提取字符串
- **简单有效**：对话历史是结构化文本，正则表达式足以处理大多数情况
- **容错性**：启发式规则可以在信息不完整时提供合理的默认值
- **可测试性**：每个提取函数独立，易于编写单元测试验证

**考虑的替代方案**：

1. **方案A：LLM自我反思**
   - 让Claude Code在生成脚本前总结对话历史
   - ❌ 拒绝理由：增加了额外的LLM调用开销，不如直接解析文本高效

2. **方案B：结构化日志**
   - 要求每个CDP命令返回结构化JSON，记录到日志文件
   - ❌ 拒绝理由：需要修改现有CDP命令模块，增加复杂度

3. **方案C：状态机管理**
   - 构建ExplorationSession对象实时跟踪探索状态
   - ❌ 拒绝理由：过度设计，违反简化架构原则（已在2025-11-19澄清中删除）

---

## 研究任务3: 代码生成策略

### 问题陈述

如何根据对话中执行的CDP命令序列生成结构良好、可维护、可复用的JavaScript代码：
- 代码结构（异步函数、错误处理、返回格式）
- 选择器降级逻辑（优先ARIA，降级到ID/class）
- 等待逻辑（动态内容加载）
- 可读性（注释、命名）

### 决策：模板驱动的分层代码生成

**选择方案**：基于templates.py的JavaScriptTemplate系统，分层生成代码片段并组装。

**生成流程**：

```python
class RecipeGenerator:
    """从对话历史生成配方脚本和知识文档"""

    def __init__(self):
        self.parser = ConversationHistoryParser()

    def generate_recipe_from_conversation(
        self,
        conversation_text: str,
        recipe_name: str,
        description: str
    ) -> Tuple[str, str]:
        """
        从对话历史生成配方脚本和知识文档

        Returns:
            (javascript_code, markdown_document) 元组
        """
        # 1. 提取信息
        commands = self.parser.extract_cdp_commands(conversation_text)
        selectors_with_context = self.parser.extract_selectors_with_context(conversation_text)
        wait_times = self.parser.extract_wait_times(conversation_text)
        prerequisites = self.parser.extract_prerequisites(conversation_text)

        # 2. 构建Selector对象（使用selector.py的工具函数）
        from frago.recipe.selector import create_selector_from_string, sort_selectors_by_priority

        selectors = []
        for context, selector_str in selectors_with_context:
            selector = create_selector_from_string(selector_str, context)
            selectors.append(selector)

        # 按优先级排序
        selectors = sort_selectors_by_priority(selectors)

        # 3. 生成操作步骤代码
        from frago.recipe.selector import generate_fallback_logic
        from frago.recipe.templates import JavaScriptTemplate

        steps_code = []
        for cmd in commands:
            if cmd['action'] == 'click':
                # 为这个选择器生成降级逻辑
                selector_obj = find_selector_for_parameter(selectors, cmd['parameter'])
                if selector_obj:
                    related_selectors = find_related_selectors(selectors, selector_obj)
                    fallback_code = generate_fallback_logic(related_selectors)
                    click_code = JavaScriptTemplate.render_click_action(
                        selector_obj.selector,
                        selector_obj.element_description
                    )
                    steps_code.append(fallback_code + "\n" + click_code)
                else:
                    # 降级：直接使用提取的选择器
                    click_code = JavaScriptTemplate.render_click_action(
                        cmd['parameter'],
                        "元素"
                    )
                    steps_code.append(click_code)

            elif cmd['action'] == 'exec-js':
                extract_code = JavaScriptTemplate.render_extract_content(
                    cmd['parameter'],
                    "内容"
                )
                steps_code.append(extract_code)

        # 4. 生成结果提取代码
        last_extract_step = find_last_extract_step(commands)
        if last_extract_step:
            result_extraction = f"const result = {last_extract_step['parameter']};"
        else:
            result_extraction = "const result = { message: '操作完成' };"

        # 5. 组装完整脚本
        javascript_code = JavaScriptTemplate.render_complete_recipe(
            recipe_name=recipe_name,
            description=description,
            steps_code=steps_code,
            result_extraction=result_extraction
        )

        # 6. 生成知识文档
        from frago.recipe.templates import MarkdownTemplate

        fragile_selectors = [s for s in selectors if s.is_fragile]
        user_description = self.parser.extract_user_description(conversation_text)

        markdown_document = MarkdownTemplate.render_complete_document(
            recipe_name=recipe_name,
            description=description,
            user_description=user_description,
            prerequisites=prerequisites,
            fragile_selectors=fragile_selectors,
            created_at=datetime.now()
        )

        return javascript_code, markdown_document
```

**代码结构设计**：

```javascript
/**
 * 配方: youtube_extract_subtitles
 * 描述: 从YouTube视频页面提取完整字幕内容
 * 生成时间: 2025-11-18T10:30:00
 */

(async function() {
  try {
    // 等待元素加载辅助函数
    function waitForElement(selector, timeout = 5000) {
      return new Promise((resolve, reject) => {
        const startTime = Date.now();
        const checkInterval = setInterval(() => {
          const element = document.querySelector(selector);
          if (element) {
            clearInterval(checkInterval);
            resolve(element);
          } else if (Date.now() - startTime > timeout) {
            clearInterval(checkInterval);
            reject(new Error(`元素未在${timeout}ms内加载: ${selector}`));
          }
        }, 100);
      });
    }

    // 步骤1: 点击作者声明展开按钮
    // 尝试定位: 展开按钮
    let expandButton = document.querySelector('[aria-label="展开作者声明"]'); // 优先级5: aria
    if (!expandButton) {
      expandButton = document.querySelector('[data-testid="expand-description"]'); // 降级: 优先级5: data
    }
    if (!expandButton) {
      expandButton = document.querySelector('#expand-btn'); // 降级: 优先级4: id
    }
    if (!expandButton) {
      throw new Error('无法定位展开按钮，页面结构可能已变化');
    }
    expandButton.click();
    await new Promise(resolve => setTimeout(resolve, 500)); // 等待操作生效

    // 步骤2: 点击"内容转文字"按钮
    const transcriptButton = await waitForElement('[aria-label="显示文字记录"]');
    transcriptButton.click();
    await new Promise(resolve => setTimeout(resolve, 1000)); // 等待字幕面板加载

    // 步骤3: 提取字幕文本
    const transcriptPanel = await waitForElement('[id="transcript-scrollbox"]');
    const transcriptSegments = transcriptPanel.querySelectorAll('.segment-text');
    const subtitles = Array.from(transcriptSegments).map(seg => seg.innerText).join('\n');

    // 返回成功结果
    return {
      success: true,
      data: {
        subtitles: subtitles,
        segmentCount: transcriptSegments.length
      },
      timestamp: new Date().toISOString()
    };

  } catch (error) {
    // 返回错误信息
    return {
      success: false,
      error: error.message,
      stack: error.stack,
      timestamp: new Date().toISOString()
    };
  }
})();
```

**生成原则**：

1. **自包含性**：生成的脚本包含所有必要的辅助函数（waitForElement）
2. **统一错误处理**：所有操作包裹在try-catch中，返回标准化JSON格式
3. **可读性优先**：
   - 每个步骤前注释说明操作目的
   - 降级逻辑明确标注优先级和选择器类型
   - 变量命名清晰（expandButton、transcriptPanel）
4. **鲁棒性**：
   - 使用waitForElement处理动态加载
   - 降级逻辑确保元素定位失败时有备选方案
   - 返回详细的错误信息便于调试

**理由**：

- **复用模板系统**：templates.py（已实现并测试通过）提供基础代码片段生成，generator只需组装
- **复用选择器策略**：selector.py（已实现并测试通过）提供稳定性评估和降级逻辑生成
- **标准化输出**：统一的返回格式（{success, data/error, timestamp}）便于调用方处理
- **可维护性**：分层生成（辅助函数 -> 步骤 -> 错误处理 -> 组装）使代码结构清晰
- **测试友好**：每个生成层级可以独立测试，确保代码质量

**考虑的替代方案**：

1. **方案A：字符串拼接**
   - 直接拼接JavaScript代码字符串
   - ❌ 拒绝理由：难以维护，容易出现语法错误，无法复用

2. **方案B：AST操作**
   - 使用JavaScript AST库（如esprima）构建代码
   - ❌ 拒绝理由：过度工程化，增加依赖和复杂度，Python生态缺少成熟的JS AST工具

3. **方案C：机器学习生成**
   - 训练模型从操作序列生成代码
   - ❌ 拒绝理由：需要大量训练数据，响应延迟高，可解释性差

---

## 研究总结

### 关键技术决策对比表

| 技术选择点 | 决策 | 替代方案 | 拒绝理由 |
|-----------|------|---------|---------|
| **探索引擎** | Claude Code原生对话能力 | 独立RecipeExplorer类 | 过度设计，违反简化原则 |
| **状态管理** | 对话历史即探索记录 | ExplorationSession状态机 | 过度设计，增加复杂度 |
| **Prompt设计** | 5阶段结构化引导 | 单一长prompt | 缺乏结构，难以跟踪 |
| **历史解析** | 正则表达式+启发式规则 | LLM自我反思 | 效率更高，成本更低 |
| **代码生成** | 模板驱动分层组装 | AST操作 | 保持简洁，无需额外依赖 |
| **选择器策略** | 多层降级（ARIA优先） | 单一CSS选择器 | 提高鲁棒性 |

### 核心创新点

1. **利用Claude Code原生能力**：不构建独立探索引擎，通过prompt引导实现探索逻辑
2. **对话历史即数据源**：从对话文本提取关键信息，无需复杂状态管理
3. **模块复用**：selector.py和templates.py已实现并测试通过，generator只需组装

### 未解决的开放问题

**无** - 所有架构决策已在2025-11-19澄清中确定

### 依赖与环境需求

**新增依赖**: 无
**Python依赖**: 使用现有依赖（websocket-client、click、pydantic）
**系统依赖**: Chrome + CDP（已有）

### 下一步行动

进入 **Phase 1: 设计与契约**，生成：
1. `data-model.md` - 简化后的实体和数据结构定义（删除ExplorationSession相关模型）
2. `contracts/` - 配方脚本和文档的JSON Schema
3. `quickstart.md` - 快速开始指南
