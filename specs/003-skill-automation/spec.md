# Feature Specification: 技能自动化生成系统

**Feature Branch**: `003-skill-automation`
**Created**: 2025-11-18
**Status**: Draft
**Input**: 通过自然语言指令生成可复用的操作技能脚本

## 澄清

### 会话 2025-11-18

- Q: 为避免与Claude Code的"skills"语义冲突，应该使用什么目录名称来存储自动生成的可复用脚本？ → A: recipes/
- Q: 在扁平的 `recipes/` 目录中，脚本文件名应该遵循什么命名约定来确保AI和人类都能快速理解其用途？ → A: 使用平台/网站前缀（如 `youtube_extract_subtitles.js`、`github_clone_repo_info.js`）
- Q: 当对配方脚本进行迭代更新时，应该如何管理版本以保留历史并识别最新版本？ → A: 覆盖原文件并在知识文档中记录历史，文件名保持不变，版本信息仅在.md中体现
- Q: 知识文档应该包含哪些固定章节以确保信息完整且结构一致？ → A: 标准6章节 - 功能描述、使用方法、前置条件、预期输出、注意事项、更新历史
- Q: 当探索过程中无法定位关键元素或页面结构过于复杂导致探索失败时，系统应该如何处理？ → A: 交互式引导 - 探索失败时暂停，实时向用户询问下一步操作或提供候选元素让用户选择

### 会话 2025-11-19（架构根本性简化）

- Q: 探索引擎的实现方式是什么？ → A: Claude Code本身就是智能探索引擎，通过prompt模板引导使用frago原子操作，无需独立的RecipeExplorer类
- Q: `/frago.recipe` 命令是否需要 `create` 子命令？ → A: 不需要，直接 `/frago.recipe "描述"` 即可进入对话流程，create是多余的
- Q: 探索过程如何进行？ → A: 用户通过自然对话描述步骤（如"先点击作者声明展开"），Claude Code执行CDP原子命令（如 `uv run frago click`），记录操作历史后生成JavaScript脚本
- Q: ExplorationSession等复杂状态管理是否必要？ → A: 不必要，Claude Code的对话历史即为探索记录，只需从对话中提取关键选择器和操作序列即可生成脚本
- Q: 数据模型需要保留哪些？ → A: 不需要任何Python数据模型。Claude Code会直接写JavaScript和Markdown文件
- Q: 如何生成配方JavaScript脚本？ → A: Claude Code在对话结束后，使用Write工具直接写.js和.md文件到src/frago/recipes/，不需要Python代码来"生成代码"
- Q: 是否需要conversation_parser.py、generator.py等Python模块？ → A: 完全不需要。提示词教会Claude Code如何做，Claude Code本身会写代码
- Q: 选择器优先级规则如何提供给Claude Code？ → A: 整合在.claude/commands/frago_recipe.md提示词中，作为规则表格供Claude Code参考
- Q: 需要哪些代码仓库文件？ → A: 只需要两个：1) .claude/commands/frago_recipe.md（提示词） 2) src/frago/recipes/（空目录，存放生成的配方）
- Q: specs/003-skill-automation/目录的作用是什么？ → A: 纯开发文档目录（通过/speckit.specify创建），不是代码目录，不包含任何源代码

### 补充说明

**用户交互接口**: 通过 `/frago.recipe` 命令提供场景化的配方管理入口：
- `/frago.recipe "操作描述"` 或 `/frago.recipe` - 进入配方创建对话流程
- `/frago.recipe update <配方名>` - 更新现有配方
- `/frago.recipe list` - 列出所有配方

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 通过自然语言指令创建快捷操作脚本 (Priority: P1)

用户通过 `/frago.recipe` 命令进入对话流程，逐步描述操作步骤。Claude Code（被prompt模板引导）使用frago的CDP原子操作（如click、exec-js、screenshot）实际执行每一步，记录操作历史和关键选择器，最后生成包含完整逻辑的JavaScript配方脚本。

**Why this priority**: 这是核心功能，是整个系统的基础价值所在——将复杂的多步骤操作转化为可复用的自动化脚本，节省用户重复劳动的时间。

**Independent Test**: 用户执行 `/frago.recipe "提取YouTube视频字幕"`，在对话中描述步骤（如"点击视频下方的作者声明展开" → "点击内容转文字按钮" → "提取字幕文本"），Claude Code执行CDP命令并生成 `youtube_extract_transcript.js` 脚本，执行脚本后能够成功提取字幕。

**Acceptance Scenarios**:

1. **Given** 用户执行 `/frago.recipe` 并描述操作步骤，**When** Claude Code使用 `uv run frago click/exec-js` 等命令逐步执行，**Then** 成功完成所有操作并记录关键DOM选择器
2. **Given** 探索完成，**When** Claude Code根据对话历史生成JavaScript脚本，**Then** 脚本包含正确的选择器、操作顺序、等待逻辑和错误处理，并保存到 `src/frago/recipes/` 目录
3. **Given** 已生成的配方脚本存在，**When** 用户在目标页面执行 `uv run frago exec-js recipes/<配方名>.js`，**Then** 脚本成功复现探索过程中的所有操作并返回预期结果
4. **Given** 探索过程中某个CDP命令失败（如元素未找到），**When** Claude Code检测到错误，**Then** 询问用户下一步操作或提供候选方案，继续探索直到成功

---

### User Story 2 - 将生成的脚本整理为知识文档 (Priority: P2)

系统不仅生成可执行脚本，还为每个技能创建配套的知识文档，记录脚本的用途、适用场景、输入输出、依赖条件和注意事项，便于后续查找和使用。

**Why this priority**: 知识管理是让技能库真正有价值的关键。没有文档的脚本很快会被遗忘或误用，文档确保了技能的可维护性和可传承性。

**Independent Test**: 生成 `youtube_extract_subtitles.js` 脚本后，系统自动创建 `youtube_extract_subtitles.md` 文档，文档包含清晰的使用说明、前置条件、预期输出和常见问题。

**Acceptance Scenarios**:

1. **Given** 系统成功生成配方脚本，**When** 脚本保存完成，**Then** 自动在同一目录生成对应的Markdown文档，包含标准6章节：功能描述、使用方法、前置条件、预期输出、注意事项、更新历史（初始为空）
2. **Given** 文档模板定义了标准章节结构，**When** 生成知识文档，**Then** 文档内容自动填充各章节，包括从用户原始描述提取的使用场景和从探索过程提取的技术细节
3. **Given** 用户在技能目录中查找可用脚本，**When** 查看脚本对应的Markdown文档，**Then** 能够快速理解脚本功能、判断是否适用当前场景、了解如何正确使用

---

### User Story 3 - 脚本版本管理和迭代优化 (Priority: P3)

当用户发现某个技能脚本在新场景中失效或需要改进时，可以通过自然语言描述问题或新需求，系统基于现有脚本进行迭代，生成改进版本并更新知识文档。

**Why this priority**: 技能脚本需要随着目标网站或应用的变化而更新。迭代优化能力确保技能库保持活力和准确性，避免脚本过时失效。

**Independent Test**: 用户反馈"YouTube改版后字幕按钮的选择器失效"，系统重新探索页面，更新 `youtube_extract_subtitles.js` 脚本中的选择器，并在文档中记录更新历史。

**Acceptance Scenarios**:

1. **Given** 用户执行某个配方脚本时遇到错误，**When** 用户提供错误描述和改进需求，**Then** 系统加载原有脚本，重新探索目标页面，覆盖原文件生成更新版本
2. **Given** 配方脚本被更新，**When** 更新完成，**Then** 知识文档自动在"更新历史"章节添加新条目，记录更新日期、原因和主要变更
3. **Given** 多次迭代后配方脚本被更新多次，**When** 用户查看知识文档，**Then** 能够在"更新历史"章节看到完整的版本演进记录

---

### Edge Cases

- **网站结构频繁变化**：当目标网站（如YouTube、Twitter）频繁改版导致DOM结构变化时，如何减少脚本失效频率？建议使用更稳定的定位策略（如ARIA标签、data属性），并在文档中标注脆弱性
- **动态加载内容**：当页面内容通过AJAX动态加载时，如何确保脚本等待元素出现后再操作？系统应在探索过程中检测异步加载模式，并在生成的脚本中加入适当的等待逻辑
- **探索过程中断**：在交互式引导过程中，如果用户多次无法提供有效信息或选择，如何优雅地终止探索？系统应在3次无效交互后建议用户重新整理需求，并保存已探索到的部分信息
- **多页面流程**：当操作步骤跨越多个页面或标签页时，如何管理页面切换和上下文？系统应支持多步骤流程，并在脚本中明确标注页面切换点
- **权限和登录状态**：某些操作需要用户已登录或具有特定权限，如何在脚本中处理这些前置条件？知识文档应明确列出前置条件，脚本应包含状态检查逻辑
- **脚本命名冲突**：当用户创建多个功能相似的技能时，如何避免命名冲突和混淆？系统应建议基于场景的命名规范，并在创建前检查重复
- **执行环境差异**：相同的脚本在不同浏览器窗口尺寸、缩放比例或网络速度下可能表现不同，如何提高脚本的鲁棒性？在探索过程中测试多种条件，并在文档中记录已知限制

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `/frago.recipe` slash command必须通过prompt模板（.claude/commands/frago_recipe.md）引导Claude Code进入配方创建对话流程，接收用户的自然语言操作描述
- **FR-002**: Claude Code必须能够使用frago的CDP原子命令（`uv run frago click/exec-js/screenshot/navigate`）与Chrome浏览器交互
- **FR-003**: 在对话过程中，Claude Code必须逐步执行用户描述的每个操作，实际体验整个流程
- **FR-004**: Claude Code必须使用Write工具直接生成JavaScript配方脚本，包含完整的选择器降级逻辑、操作序列和等待时间
- **FR-005**: Claude Code必须将生成的JavaScript脚本保存到 `src/frago/recipes/` 目录，文件名遵循"平台_功能"格式（例如 `youtube_extract_transcript.js`），使用小写字母和下划线分隔
- **FR-006**: Claude Code必须为每个配方脚本创建配套的Markdown知识文档，包含6个标准章节：功能描述、使用方法、前置条件、预期输出、注意事项、更新历史
- **FR-007**: 生成的配方脚本必须能够通过 `uv run frago exec-js recipes/<脚本名>.js` 独立执行
- **FR-008**: 当CDP命令执行失败时，Claude Code必须询问用户下一步操作或提供候选方案，而不是终止流程
- **FR-009**: `/frago.recipe update <配方名>` 必须读取现有脚本，重新探索，然后覆盖原文件生成改进版本
- **FR-010**: 更新配方时，Claude Code必须在知识文档的"更新历史"章节追加新记录（不是替换）
- **FR-011**: 生成的配方脚本必须包含选择器降级逻辑（按优先级5→1：ARIA/data→ID→class），提供2-3个备选选择器
- **FR-012**: 生成脚本前，Claude Code必须使用Read工具检查是否存在同名文件，如存在则通过对话确认覆盖

### Key Entities

- **配方脚本（Recipe Script）**：存储在 `src/frago/recipes/` 目录中的JavaScript文件，由Claude Code在对话结束后使用Write工具创建。文件头部包含Recipe元数据注释（名称、平台、描述、版本），脚本主体包含选择器降级逻辑和操作步骤
- **知识文档（Knowledge Document）**：与配方脚本配套的Markdown文件（同名.md），由Claude Code使用Write工具创建。固定包含6个章节：功能描述、使用方法、前置条件、预期输出、注意事项、更新历史
- **Prompt模板（Prompt Template）**：`.claude/commands/frago_recipe.md`文件，教会Claude Code如何引导对话、执行CDP命令、生成配方的完整指令。包含选择器优先级规则表格、JavaScript模板示例、知识文档章节格式
- **配方库（Recipe Library）**：`src/frago/recipes/`目录，扁平结构，通过描述性文件名（平台_功能.js）组织所有配方
- **选择器优先级规则（Selector Priority Rules）**：整合在prompt模板中的规则表格，定义5个优先级（ARIA/data=5, ID=4, class=3, structure=2, generated=1）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户能够在5分钟内通过自然语言描述生成一个可执行的配方脚本，无需手动编写任何代码
- **SC-002**: 生成的配方脚本在相同页面条件下执行成功率达到90%以上（即10次执行中至少9次成功完成操作）
- **SC-003**: 每个配方脚本的知识文档必须包含标准6章节（功能描述、使用方法、前置条件、预期输出、注意事项、更新历史），且内容完整可读
- **SC-004**: 用户能够在配方库中通过文档快速找到所需脚本，查找和理解一个配方脚本的时间不超过2分钟
- **SC-005**: 当目标网站DOM结构发生变化导致脚本失效时，用户能够在10分钟内通过系统迭代功能生成更新版本，恢复脚本可用性
- **SC-006**: 配方库中的脚本数量增长到20个以上时，仍然能够保持良好的组织结构和可维护性（通过描述性文件名和完整文档）
- **SC-007**: 探索过程中系统提出的澄清问题数量平均不超过3个，确保用户交互负担可控
- **SC-008**: 生成的配方脚本平均代码行数控制在50-200行之间，保持简洁性和可读性
