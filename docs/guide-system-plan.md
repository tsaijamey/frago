# frago Web UI Guide System - 完整规划

> **规划日期**: 2026-01-17
> **目标**: 在Web UI中集成FAQ式教程系统，帮助用户理解配置、概念和使用方法

---

## 一、设计原则

### 1.1 用户导向
- **从困惑出发**: 回答用户真实的疑问，而非自说自话
- **即时可用**: 用户看完能立即操作，不需要额外学习
- **渐进式**: 新手到进阶，分层次引导

### 1.2 技术原则
- **内容与代码分离**: 内容易于更新，不需要重新编译前端
- **i18n优先**: 中英文同步支持
- **格式统一**: 与Recipe、Skill保持一致的Markdown + YAML frontmatter格式
- **可扩展**: 支持未来添加新章节、视频、交互式演示

### 1.3 维护原则
- **版本化**: 教程内容跟随frago版本迭代
- **社区贡献**: 可接受社区PR更新FAQ
- **自动同步**: 类似recipes，支持从仓库拉取最新内容

---

## 二、内容存储方案

### 2.1 目录结构

```
src/frago/resources/guide/
├── meta.json                    # 教程元数据（版本、更新时间）
├── en/                          # 英文教程
│   ├── 01-getting-started.md    # 刚开始使用
│   ├── 02-interface-faq.md      # 界面功能FAQ
│   ├── 03-configuration.md      # 配置相关
│   ├── 04-usage-tips.md         # 使用技巧
│   └── 05-troubleshooting.md    # 故障排查
└── zh-CN/                       # 中文教程
    ├── 01-getting-started.md
    ├── 02-interface-faq.md
    ├── 03-configuration.md
    ├── 04-usage-tips.md
    └── 05-troubleshooting.md
```

### 2.2 内容格式规范

每个Markdown文件遵循统一格式：

```markdown
---
id: getting-started
title: 刚打开frago，我该干什么？
category: getting-started
order: 1
version: 0.38.1
last_updated: 2026-01-17
tags: [beginner, first-time, quick-start]
---

# 刚打开frago，我该干什么？

## Q: 我刚装完frago，进入了Web UI，现在该从哪开始？

**A**: 建议这样开始：

1. **先看看有什么现成的工具** → 点击左侧"Recipes"
   - 这里有一些已经写好的自动化脚本
   ...

## Q: 下一个问题...

...
```

**YAML frontmatter字段说明**:
- `id`: 唯一标识符
- `title`: 章节标题（显示在目录）
- `category`: 分类（getting-started, interface, config, usage, troubleshooting）
- `order`: 章节顺序
- `version`: 适用的frago版本
- `last_updated`: 最后更新日期
- `tags`: 标签（用于搜索）

### 2.3 元数据文件 (meta.json)

```json
{
  "version": "0.38.1",
  "last_updated": "2026-01-17T10:00:00Z",
  "languages": ["en", "zh-CN"],
  "categories": [
    {
      "id": "getting-started",
      "title": {
        "en": "Getting Started",
        "zh-CN": "开始使用"
      },
      "order": 1
    },
    {
      "id": "interface",
      "title": {
        "en": "Interface FAQ",
        "zh-CN": "界面功能FAQ"
      },
      "order": 2
    },
    {
      "id": "config",
      "title": {
        "en": "Configuration",
        "zh-CN": "配置相关"
      },
      "order": 3
    },
    {
      "id": "usage",
      "title": {
        "en": "Usage Tips",
        "zh-CN": "使用技巧"
      },
      "order": 4
    },
    {
      "id": "troubleshooting",
      "title": {
        "en": "Troubleshooting",
        "zh-CN": "故障排查"
      },
      "order": 5
    }
  ],
  "chapters": [
    {
      "id": "getting-started",
      "category": "getting-started",
      "order": 1,
      "files": {
        "en": "en/01-getting-started.md",
        "zh-CN": "zh-CN/01-getting-started.md"
      }
    }
    // ... 其他章节
  ]
}
```

---

## 三、资源更新机制

### 3.1 开发时（类似dev pack）

```bash
# 源文件位置
guide_source/
├── en/
│   └── *.md
└── zh-CN/
    └── *.md

# 打包到resources
frago dev pack-guide  # 新增命令

# 结果
src/frago/resources/guide/
├── meta.json
├── en/
└── zh-CN/
```

### 3.2 安装时（PyPI → 用户目录）

```bash
# frago init时
# 复制 src/frago/resources/guide/ → ~/.frago/guide/
```

### 3.3 运行时更新（可选，未来功能）

```bash
# 类似community recipes
frago guide update    # 从官方仓库拉取最新教程
frago guide version   # 查看当前教程版本
```

**实现方式**:
- 官方仓库: `https://github.com/tsaijamey/frago-guides`
- 使用gh CLI拉取最新内容
- 覆盖 `~/.frago/guide/` 目录

---

## 四、Web UI展示方案

### 4.1 入口设计

#### 方案A：Sidebar独立菜单项（推荐）

**位置**: Sidebar菜单项，放在Dashboard和Console之间

```typescript
// Sidebar.tsx
const menuItems: MenuItem[] = [
  { id: 'dashboard', labelKey: 'sidebar.dashboard', icon: <DashboardIcon /> },
  { id: 'guide', labelKey: 'sidebar.guide', icon: <BookIcon /> },  // 新增
  { id: 'console', labelKey: 'sidebar.console', icon: <ConsoleIcon /> },
  // ...
];
```

**图标**: Book（书本）或HelpCircle（帮助圈）

**优点**:
- 显眼，容易发现
- 与其他页面同等地位
- 新手友好

#### 方案B：Dashboard快速入门卡片

**位置**: Dashboard页面，Stats Cards下方

**内容**:
- "需要帮助？"标题
- 3-4个常见问题快速链接
- "查看完整教程"按钮 → 跳转到Guide页面

**优点**:
- 首次进入Dashboard即可看到
- 不占用Sidebar空间

#### 推荐：两者结合
- Sidebar有独立入口
- Dashboard有快速链接卡片

### 4.2 页面布局

```
┌─────────────────────────────────────────────────┐
│  Guide                                    🔍搜索 │
├──────────┬──────────────────────────────────────┤
│          │                                      │
│ 目录侧边栏  │         内容区域                      │
│          │                                      │
│ • 开始使用 │  # Q: 我刚装完frago，现在该干什么？     │
│   ├─ Q1  │                                      │
│   ├─ Q2  │  **A**: 建议这样开始：                 │
│   └─ Q3  │                                      │
│          │  1. 先看看有什么现成的工具 → ...        │
│ • 界面FAQ │                                      │
│   ├─ Q1  │                                      │
│   └─ Q2  │                                      │
│          │                                      │
│ • 配置相关 │                                      │
│          │                                      │
└──────────┴──────────────────────────────────────┘
```

**组件结构**:
```
GuidePage.tsx
├── GuideSidebar.tsx      # 左侧目录
│   ├── 分类标题
│   ├── 章节列表
│   └── 搜索框
└── GuideContent.tsx      # 右侧内容
    ├── Markdown渲染
    ├── 代码高亮
    ├── 复制按钮
    └── 锚点导航
```

### 4.3 交互功能

#### 搜索功能
- 全文搜索（标题 + 内容）
- 高亮匹配关键词
- 快速跳转到匹配段落

#### 代码示例
- 语法高亮（react-syntax-highlighter）
- 一键复制按钮
- 可选：Run示例（直接执行，高级功能）

#### 进度追踪（可选）
- LocalStorage记录阅读进度
- 已读章节打勾
- 继续上次阅读

#### 反馈机制（可选）
- 每个FAQ下方："这个回答有帮助吗？👍 👎"
- 收集用户反馈，优化内容

---

## 五、前端实现细节

### 5.1 API设计

```typescript
// GET /api/guide/meta
// 获取教程元数据
interface GuideMeta {
  version: string;
  last_updated: string;
  languages: string[];
  categories: Category[];
  chapters: Chapter[];
}

// GET /api/guide/content?lang=zh-CN&chapter=getting-started
// 获取章节内容
interface GuideContent {
  id: string;
  title: string;
  category: string;
  content: string;  // Markdown文本
  metadata: {
    version: string;
    last_updated: string;
    tags: string[];
  };
}

// GET /api/guide/search?q=console&lang=zh-CN
// 搜索教程内容
interface SearchResult {
  chapter_id: string;
  chapter_title: string;
  matches: {
    question: string;
    snippet: string;  // 匹配片段
    highlight: string;  // 高亮关键词
  }[];
}
```

### 5.2 组件层次

```
src/frago/server/web/src/components/guide/
├── GuidePage.tsx           # 主页面组件
├── GuideSidebar.tsx        # 左侧目录
├── GuideContent.tsx        # 右侧内容展示
├── GuideSearch.tsx         # 搜索组件
├── CodeBlock.tsx           # 代码块（带复制）
└── TableOfContents.tsx     # 内联目录（右上角）
```

### 5.3 状态管理

```typescript
// stores/guideStore.ts
interface GuideStore {
  // 元数据
  meta: GuideMeta | null;

  // 当前章节
  currentChapter: string | null;
  currentContent: GuideContent | null;

  // 阅读进度
  readChapters: Set<string>;

  // 搜索
  searchQuery: string;
  searchResults: SearchResult[];

  // Actions
  loadMeta: () => Promise<void>;
  loadChapter: (chapterId: string) => Promise<void>;
  search: (query: string) => Promise<void>;
  markAsRead: (chapterId: string) => void;
}
```

### 5.4 国际化

```json
// i18n/locales/en.json
{
  "guide": {
    "title": "Guide",
    "search": "Search...",
    "categories": {
      "getting-started": "Getting Started",
      "interface": "Interface FAQ",
      "config": "Configuration",
      "usage": "Usage Tips",
      "troubleshooting": "Troubleshooting"
    },
    "helpful": "Was this helpful?",
    "feedback": {
      "yes": "Yes, helpful",
      "no": "Not helpful"
    },
    "copy": "Copy",
    "copied": "Copied!",
    "readProgress": "{{count}}/{{total}} chapters read"
  }
}
```

---

## 六、后端实现细节

### 6.1 路由设计

```python
# src/frago/server/routes/guide.py

@router.get("/guide/meta")
async def get_guide_meta(lang: str = "en") -> GuideMeta:
    """获取教程元数据"""
    pass

@router.get("/guide/content")
async def get_guide_content(lang: str, chapter: str) -> GuideContent:
    """获取章节内容"""
    pass

@router.get("/guide/search")
async def search_guide(q: str, lang: str = "en") -> List[SearchResult]:
    """搜索教程内容"""
    pass
```

### 6.2 内容加载

```python
# src/frago/server/services/guide_service.py

class GuideService:
    """教程服务"""

    @staticmethod
    def get_guide_dir() -> Path:
        """获取教程目录 ~/.frago/guide/"""
        return Path.home() / ".frago" / "guide"

    @staticmethod
    def load_meta() -> dict:
        """加载元数据"""
        meta_file = GuideService.get_guide_dir() / "meta.json"
        return json.loads(meta_file.read_text())

    @staticmethod
    def load_chapter(lang: str, chapter_id: str) -> dict:
        """加载章节内容"""
        # 从meta.json找到文件路径
        meta = GuideService.load_meta()
        chapter = next(c for c in meta["chapters"] if c["id"] == chapter_id)
        file_path = GuideService.get_guide_dir() / chapter["files"][lang]

        # 解析Markdown + YAML frontmatter
        content = file_path.read_text()
        return parse_frontmatter(content)

    @staticmethod
    def search_content(query: str, lang: str) -> list:
        """全文搜索"""
        # 遍历所有章节，匹配关键词
        # 返回匹配片段
        pass
```

---

## 七、开发路线图

### Phase 1: 核心功能（MVP）
**目标**: 基本可用的教程系统

- [ ] 创建教程内容目录结构 `guide_source/`
- [ ] 编写5个核心章节的FAQ内容（中英文）
- [ ] 实现 `frago dev pack-guide` 命令
- [ ] 后端API: `/guide/meta`, `/guide/content`
- [ ] 前端: GuidePage基础布局
- [ ] Markdown渲染 + 代码高亮
- [ ] Sidebar添加Guide入口

**交付物**:
- 可浏览的教程页面
- 5个章节内容
- 中英文支持

### Phase 2: 增强体验
**目标**: 提升用户体验

- [ ] 搜索功能（全文搜索）
- [ ] 代码块复制按钮
- [ ] Dashboard快速入门卡片
- [ ] 章节内锚点导航
- [ ] 阅读进度追踪

**交付物**:
- 搜索功能
- Dashboard引导卡片
- 进度记录

### Phase 3: 高级功能（可选）
**目标**: 社区化和自动化

- [ ] `frago guide update` 命令（从仓库拉取）
- [ ] 官方教程仓库 `frago-guides`
- [ ] 用户反馈收集（有用/无用）
- [ ] 交互式示例（点击运行）
- [ ] 视频教程嵌入

**交付物**:
- 自动更新机制
- 社区贡献流程

---

## 八、关键决策点

### 8.1 内容存储位置

**决策**: 跟随PyPI包分发

**理由**:
- 用户安装后即可使用，无需额外下载
- 内容随版本更新
- 离线可用

**未来优化**:
- 可选从仓库拉取最新版本（类似community recipes）

### 8.2 格式选择

**决策**: Markdown + YAML frontmatter

**理由**:
- 与Recipe、Skill保持一致
- 易于编辑和版本控制
- 前端直接渲染，无需编译

### 8.3 国际化方案

**决策**: 独立文件夹（en/, zh-CN/）

**理由**:
- 翻译独立，互不影响
- 易于社区贡献不同语言版本
- 可按需加载，减少传输

### 8.4 更新机制

**决策**: 初期跟随PyPI，后期可选仓库拉取

**理由**:
- 简单可靠，不依赖网络
- 后期添加更新功能，提升灵活性

---

## 九、文件清单

### 9.1 新增文件

```
# 教程源文件（开发时）
guide_source/
├── meta.json
├── en/
│   ├── 01-getting-started.md
│   ├── 02-interface-faq.md
│   ├── 03-configuration.md
│   ├── 04-usage-tips.md
│   └── 05-troubleshooting.md
└── zh-CN/
    └── (同上)

# 打包后的资源
src/frago/resources/guide/
├── meta.json
├── en/
└── zh-CN/

# 前端组件
src/frago/server/web/src/components/guide/
├── GuidePage.tsx
├── GuideSidebar.tsx
├── GuideContent.tsx
├── GuideSearch.tsx
├── CodeBlock.tsx
└── TableOfContents.tsx

# 后端路由
src/frago/server/routes/guide.py

# 后端服务
src/frago/server/services/guide_service.py

# CLI命令
src/frago/cli/guide_commands.py

# 国际化
src/frago/server/web/src/i18n/locales/en.json  # 添加guide.*
src/frago/server/web/src/i18n/locales/zh.json  # 添加guide.*
```

### 9.2 修改文件

```
# Sidebar添加Guide菜单项
src/frago/server/web/src/components/layout/Sidebar.tsx

# App.tsx添加路由
src/frago/server/web/src/App.tsx

# Dashboard添加快速入门卡片
src/frago/server/web/src/components/dashboard/DashboardPage.tsx

# 路由注册
src/frago/server/routes/__init__.py

# CLI命令注册
src/frago/cli/__init__.py
```

---

## 十、关键词索引

### 技术栈
- Markdown + YAML frontmatter
- React + TypeScript
- FastAPI (后端)
- react-markdown (渲染)
- react-syntax-highlighter (代码高亮)

### 核心概念
- FAQ式教程
- 渐进式引导
- 内容与代码分离
- i18n优先
- 社区贡献

### 功能模块
- 目录导航
- 全文搜索
- 代码复制
- 进度追踪
- 反馈收集

---

## 十一、参考资料

### 相关文档
- `docs/recipes.md` - Recipe系统设计（格式参考）
- `CLAUDE.md` - 项目开发规范
- `src/frago/resources/` - 资源打包机制
- `src/frago/cli/dev_commands.py` - dev pack实现

### 设计灵感
- Docusaurus (文档框架)
- GitBook (知识库)
- MDN Web Docs (技术文档)
- Stack Overflow (FAQ格式)

---

## 十二、下一步行动

1. **Review规划** - 与团队确认方案
2. **编写内容** - 完成5个核心章节的FAQ（见`content-outline.md`）
3. **实现后端** - API + 服务层
4. **实现前端** - 页面 + 组件
5. **测试** - 功能测试 + 用户测试
6. **迭代** - 根据反馈优化内容

---

**规划完成日期**: 2026-01-17
**预计开发周期**: Phase 1 约3-5天，Phase 2 约2-3天
**责任人**: [待定]
