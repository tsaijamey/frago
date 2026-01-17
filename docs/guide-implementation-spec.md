# Guide System Implementation Specification

> **规划日期**: 2026-01-17
> **目标**: 提供详细的技术实现规范，供开发者参考

---

## 一、文件格式规范

### 1.1 Markdown文件结构

```markdown
---
# YAML Frontmatter（必需）
id: getting-started              # 唯一标识符（kebab-case）
title: 开始使用                   # 章节标题
category: getting-started        # 分类ID
order: 1                         # 排序序号
version: 0.38.1                  # 适用frago版本
last_updated: 2026-01-17         # 最后更新日期（YYYY-MM-DD）
tags:                            # 标签（用于搜索）
  - beginner
  - first-time
  - quick-start
---

# [章节标题]

## Q: [问题1]

**A**: [简短答案]

[详细说明...]

## Q: [问题2]

...
```

### 1.2 元数据文件规范 (meta.json)

```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
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
      "description": {
        "en": "First steps with frago",
        "zh-CN": "frago的第一步"
      },
      "order": 1,
      "icon": "rocket"  // lucide-react icon name
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
      },
      "question_count": 4  // FAQ数量（用于显示）
    }
  ]
}
```

---

## 二、API接口规范

### 2.1 获取元数据

```http
GET /api/guide/meta?lang=zh-CN
```

**Query Parameters**:
- `lang` (optional): 语言代码，默认`en`

**Response**:
```json
{
  "version": "0.38.1",
  "last_updated": "2026-01-17T10:00:00Z",
  "languages": ["en", "zh-CN"],
  "categories": [...],
  "chapters": [...]
}
```

**Status Codes**:
- `200`: 成功
- `404`: 元数据文件不存在
- `500`: 服务器错误

### 2.2 获取章节内容

```http
GET /api/guide/content?lang=zh-CN&chapter=getting-started
```

**Query Parameters**:
- `lang` (required): 语言代码
- `chapter` (required): 章节ID

**Response**:
```json
{
  "id": "getting-started",
  "title": "开始使用",
  "category": "getting-started",
  "content": "# 开始使用\n\n## Q: ...",
  "metadata": {
    "version": "0.38.1",
    "last_updated": "2026-01-17",
    "tags": ["beginner", "first-time", "quick-start"],
    "order": 1
  },
  "toc": [  // 目录（从Markdown标题提取）
    {
      "level": 2,
      "title": "Q: 我刚装完frago，现在该从哪开始？",
      "anchor": "q-我刚装完frago现在该从哪开始"
    }
  ]
}
```

**Status Codes**:
- `200`: 成功
- `400`: 参数缺失或无效
- `404`: 章节不存在
- `500`: 服务器错误

### 2.3 搜索内容

```http
GET /api/guide/search?q=console&lang=zh-CN
```

**Query Parameters**:
- `q` (required): 搜索关键词
- `lang` (optional): 语言代码，默认`en`

**Response**:
```json
{
  "query": "console",
  "total": 3,
  "results": [
    {
      "chapter_id": "interface-faq",
      "chapter_title": "界面功能FAQ",
      "matches": [
        {
          "question": "Console和Tasks有什么区别？",
          "snippet": "Console: Recipe开发专用，<mark>自动批准</mark>...",
          "anchor": "q-console和tasks有什么区别"
        }
      ]
    }
  ]
}
```

**Status Codes**:
- `200`: 成功
- `400`: 缺少搜索关键词
- `500`: 服务器错误

---

## 三、前端组件规范

### 3.1 组件层次结构

```
GuidePage (页面容器)
├── GuideSearch (搜索框)
├── GuideSidebar (左侧目录)
│   ├── CategorySection (分类)
│   │   └── ChapterItem (章节)
│   └── ProgressIndicator (进度)
└── GuideContent (右侧内容)
    ├── Breadcrumb (面包屑)
    ├── MarkdownRenderer (Markdown渲染)
    │   ├── CodeBlock (代码块)
    │   │   └── CopyButton (复制按钮)
    │   ├── Heading (标题)
    │   └── Link (链接)
    └── TableOfContents (右上角目录)
```

### 3.2 状态管理 (Zustand)

```typescript
// stores/guideStore.ts

interface GuideStore {
  // 数据
  meta: GuideMeta | null;
  currentChapter: string | null;
  currentContent: GuideContent | null;
  loading: boolean;
  error: string | null;

  // 搜索
  searchQuery: string;
  searchResults: SearchResult[];
  searching: boolean;

  // 阅读进度（LocalStorage持久化）
  readChapters: Set<string>;

  // Actions
  loadMeta: () => Promise<void>;
  loadChapter: (chapterId: string) => Promise<void>;
  search: (query: string) => Promise<void>;
  markAsRead: (chapterId: string) => void;
  clearSearch: () => void;
}

const useGuideStore = create<GuideStore>()(
  persist(
    (set, get) => ({
      // ... implementation
    }),
    {
      name: 'frago-guide-storage',
      partialize: (state) => ({
        readChapters: Array.from(state.readChapters),
      }),
    }
  )
);
```

### 3.3 路由配置

```typescript
// App.tsx

const renderPage = () => {
  switch (currentPage) {
    // ... existing cases
    case 'guide':
      return <GuidePage />;
    default:
      return <TaskList />;
  }
};
```

```typescript
// Sidebar.tsx

const menuItems: MenuItem[] = [
  { id: 'dashboard', labelKey: 'sidebar.dashboard', icon: <DashboardIcon /> },
  { id: 'guide', labelKey: 'sidebar.guide', icon: <BookOpenIcon /> },  // 新增
  { id: 'console', labelKey: 'sidebar.console', icon: <ConsoleIcon /> },
  // ...
];
```

### 3.4 Markdown渲染配置

使用 `react-markdown` + `react-syntax-highlighter`

```typescript
// GuideContent.tsx

import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

const GuideContent = ({ content }: { content: string }) => {
  return (
    <ReactMarkdown
      components={{
        code({ node, inline, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || '');
          return !inline && match ? (
            <CodeBlock language={match[1]} code={String(children)} />
          ) : (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
        h2({ children }) {
          const id = slugify(String(children));
          return <h2 id={id}>{children}</h2>;
        },
        // ... other components
      }}
    >
      {content}
    </ReactMarkdown>
  );
};
```

### 3.5 代码块组件

```typescript
// CodeBlock.tsx

interface CodeBlockProps {
  language: string;
  code: string;
}

const CodeBlock = ({ language, code }: CodeBlockProps) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="language-label">{language}</span>
        <button onClick={handleCopy} className="copy-button">
          {copied ? <CheckIcon /> : <CopyIcon />}
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={oneDark}
        customStyle={{
          margin: 0,
          borderRadius: '0 0 8px 8px',
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
};
```

---

## 四、后端实现规范

### 4.1 目录结构

```
src/frago/
├── server/
│   ├── routes/
│   │   └── guide.py           # Guide路由
│   └── services/
│       └── guide_service.py   # Guide服务
├── cli/
│   └── guide_commands.py      # CLI命令（未来）
└── resources/
    └── guide/                 # 打包后的资源
        ├── meta.json
        ├── en/
        └── zh-CN/
```

### 4.2 服务层实现

```python
# src/frago/server/services/guide_service.py

import json
from pathlib import Path
from typing import Dict, List, Optional

import frontmatter  # pip install python-frontmatter


class GuideService:
    """教程服务"""

    @staticmethod
    def get_guide_dir() -> Path:
        """获取教程目录"""
        # 优先级：~/.frago/guide/ > src/frago/resources/guide/
        user_guide = Path.home() / ".frago" / "guide"
        if user_guide.exists():
            return user_guide

        # Fallback to package resources
        import frago.resources.guide as guide_pkg
        return Path(guide_pkg.__file__).parent

    @staticmethod
    def load_meta() -> Dict:
        """加载元数据"""
        meta_file = GuideService.get_guide_dir() / "meta.json"
        if not meta_file.exists():
            raise FileNotFoundError("Guide metadata not found")

        return json.loads(meta_file.read_text(encoding="utf-8"))

    @staticmethod
    def load_chapter(lang: str, chapter_id: str) -> Dict:
        """加载章节内容"""
        meta = GuideService.load_meta()

        # 查找章节配置
        chapter = next(
            (c for c in meta["chapters"] if c["id"] == chapter_id),
            None
        )
        if not chapter:
            raise ValueError(f"Chapter '{chapter_id}' not found")

        # 获取文件路径
        file_path = GuideService.get_guide_dir() / chapter["files"][lang]
        if not file_path.exists():
            raise FileNotFoundError(f"Chapter file not found: {file_path}")

        # 解析Markdown + frontmatter
        with open(file_path, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)

        # 提取目录
        toc = GuideService._extract_toc(post.content)

        return {
            "id": chapter_id,
            "title": post.get("title", ""),
            "category": post.get("category", ""),
            "content": post.content,
            "metadata": {
                "version": post.get("version", ""),
                "last_updated": post.get("last_updated", ""),
                "tags": post.get("tags", []),
                "order": post.get("order", 0),
            },
            "toc": toc,
        }

    @staticmethod
    def _extract_toc(content: str) -> List[Dict]:
        """从Markdown提取目录"""
        import re

        toc = []
        heading_pattern = r"^(#{2,6})\s+(.+)$"

        for line in content.split("\n"):
            match = re.match(heading_pattern, line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                anchor = GuideService._slugify(title)
                toc.append({
                    "level": level,
                    "title": title,
                    "anchor": anchor,
                })

        return toc

    @staticmethod
    def _slugify(text: str) -> str:
        """生成锚点ID"""
        import re
        import unicodedata

        # 移除特殊字符，保留中文
        text = unicodedata.normalize("NFKD", text)
        text = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text.lower())
        text = re.sub(r"[\s_]+", "-", text)
        return text.strip("-")

    @staticmethod
    def search_content(query: str, lang: str) -> List[Dict]:
        """搜索教程内容"""
        meta = GuideService.load_meta()
        results = []

        for chapter in meta["chapters"]:
            try:
                content = GuideService.load_chapter(lang, chapter["id"])

                # 简单搜索：标题 + 内容
                matches = []
                for line in content["content"].split("\n\n"):
                    if query.lower() in line.lower():
                        # 提取问题标题
                        if line.startswith("## Q:"):
                            question = line.replace("## Q:", "").strip()
                            snippet = GuideService._highlight_snippet(
                                line, query, max_length=200
                            )
                            anchor = GuideService._slugify(line)
                            matches.append({
                                "question": question,
                                "snippet": snippet,
                                "anchor": anchor,
                            })

                if matches:
                    results.append({
                        "chapter_id": chapter["id"],
                        "chapter_title": content["title"],
                        "matches": matches,
                    })

            except Exception as e:
                print(f"Error searching chapter {chapter['id']}: {e}")
                continue

        return results

    @staticmethod
    def _highlight_snippet(text: str, query: str, max_length: int = 200) -> str:
        """高亮搜索关键词"""
        import re

        # 找到关键词位置
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        match = pattern.search(text)

        if not match:
            return text[:max_length] + "..."

        # 提取关键词周围的文本
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 50)
        snippet = text[start:end]

        # 高亮关键词
        snippet = pattern.sub(f"<mark>{match.group()}</mark>", snippet)

        return ("..." if start > 0 else "") + snippet + ("..." if end < len(text) else "")
```

### 4.3 路由实现

```python
# src/frago/server/routes/guide.py

from fastapi import APIRouter, HTTPException, Query

from frago.server.services.guide_service import GuideService

router = APIRouter()


@router.get("/guide/meta")
async def get_guide_meta(lang: str = Query("en", description="Language code")):
    """获取教程元数据"""
    try:
        meta = GuideService.load_meta()
        return meta
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guide/content")
async def get_guide_content(
    lang: str = Query(..., description="Language code"),
    chapter: str = Query(..., description="Chapter ID")
):
    """获取章节内容"""
    try:
        content = GuideService.load_chapter(lang, chapter)
        return content
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guide/search")
async def search_guide(
    q: str = Query(..., description="Search query"),
    lang: str = Query("en", description="Language code")
):
    """搜索教程内容"""
    try:
        results = GuideService.search_content(q, lang)
        return {
            "query": q,
            "total": sum(len(r["matches"]) for r in results),
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 五、开发工作流

### 5.1 本地开发

```bash
# 1. 创建教程内容源文件
mkdir -p guide_source/en guide_source/zh-CN
vim guide_source/en/01-getting-started.md

# 2. 编写meta.json
vim guide_source/meta.json

# 3. 打包到resources（未来实现）
# frago dev pack-guide

# 临时方案：手动复制
cp -r guide_source/* src/frago/resources/guide/

# 4. 开发前端组件
cd src/frago/server/web
npm run dev

# 5. 测试API
curl http://localhost:8093/api/guide/meta
curl http://localhost:8093/api/guide/content?lang=en&chapter=getting-started
```

### 5.2 内容更新流程

```bash
# 1. 修改源文件
vim guide_source/zh-CN/02-interface-faq.md

# 2. 更新版本和日期
# - meta.json: version, last_updated
# - Markdown: YAML frontmatter last_updated

# 3. 打包
frago dev pack-guide

# 4. 提交
git add guide_source/ src/frago/resources/guide/
git commit -m "docs(guide): update interface FAQ"
git push
```

---

## 六、样式规范

### 6.1 CSS类命名

遵循BEM命名规范:

```css
/* 页面容器 */
.guide-page { }

/* 侧边栏 */
.guide-sidebar { }
.guide-sidebar__category { }
.guide-sidebar__chapter { }
.guide-sidebar__chapter--active { }

/* 内容区 */
.guide-content { }
.guide-content__breadcrumb { }
.guide-content__body { }

/* 代码块 */
.code-block { }
.code-block__header { }
.code-block__copy-btn { }

/* 搜索 */
.guide-search { }
.guide-search__input { }
.guide-search__results { }
```

### 6.2 主题变量

使用CSS变量，支持深色/浅色主题:

```css
:root {
  --guide-sidebar-bg: var(--bg-secondary);
  --guide-content-bg: var(--bg-primary);
  --guide-code-bg: var(--bg-tertiary);
  --guide-accent: var(--accent-primary);
  --guide-text: var(--text-primary);
  --guide-text-secondary: var(--text-secondary);
}
```

---

## 七、性能优化

### 7.1 内容缓存

```typescript
// 前端：React Query缓存
import { useQuery } from '@tanstack/react-query';

const useGuideChapter = (lang: string, chapterId: string) => {
  return useQuery({
    queryKey: ['guide', 'chapter', lang, chapterId],
    queryFn: () => fetchGuideContent(lang, chapterId),
    staleTime: 1000 * 60 * 5,  // 5分钟缓存
    cacheTime: 1000 * 60 * 30,  // 30分钟保留
  });
};
```

```python
# 后端：LRU缓存
from functools import lru_cache

class GuideService:
    @staticmethod
    @lru_cache(maxsize=128)
    def load_chapter(lang: str, chapter_id: str) -> Dict:
        # ... implementation
```

### 7.2 代码分割

```typescript
// 懒加载Guide页面
const GuidePage = lazy(() => import('@/components/guide/GuidePage'));

// App.tsx
<Suspense fallback={<Loading />}>
  {currentPage === 'guide' && <GuidePage />}
</Suspense>
```

---

## 八、测试策略

### 8.1 单元测试

```python
# tests/test_guide_service.py

def test_load_meta():
    meta = GuideService.load_meta()
    assert "version" in meta
    assert "chapters" in meta

def test_load_chapter():
    content = GuideService.load_chapter("en", "getting-started")
    assert content["id"] == "getting-started"
    assert "content" in content

def test_search():
    results = GuideService.search_content("console", "en")
    assert len(results) > 0
```

### 8.2 前端测试

```typescript
// GuidePage.test.tsx

import { render, screen } from '@testing-library/react';
import GuidePage from './GuidePage';

test('renders guide page', () => {
  render(<GuidePage />);
  expect(screen.getByText(/guide/i)).toBeInTheDocument();
});

test('loads chapter content', async () => {
  render(<GuidePage />);
  // Mock API
  // Assert content loaded
});
```

---

## 九、部署清单

### 9.1 PyPI发布

```bash
# 确保guide资源打包
ls src/frago/resources/guide/

# 构建包
python -m build

# 发布
twine upload dist/*
```

### 9.2 用户安装

```bash
# 安装frago
uv tool install frago-cli

# 初始化（会复制guide资源到~/.frago/guide/）
frago init

# 启动web服务
frago server start

# 访问 http://localhost:8093
# 点击左侧Guide菜单
```

---

**规范完成日期**: 2026-01-17
**适用版本**: frago 0.38.1+
