# interactive-recipe

分类: 效率（AVAILABLE）

## 解决什么问题
agent 需要构建人机协作的 Recipe（用户审核、标注、选择），不知道如何组织 Web UI 架构、launcher 脚本、API 交互模式。

## 适用场景

| 场景 | 为什么需要交互 |
|------|---------------|
| 媒体标注 | 用户选择片段、标记时间戳 |
| 多步创作流程 | 用户在步骤间审核/调整 |
| 参考素材分配 | 用户指定图片用途 |
| 质量控制 | 用户审批/拒绝结果 |

不适合：全自动任务、无头环境、无需审核的批处理。

## 架构概览

  ~/.frago/recipes/workflows/<name>/
  ├── recipe.md           # 元数据（type: workflow, runtime: python）
  ├── recipe.py           # Launcher 脚本
  └── assets/
      ├── index.html      # 入口
      ├── app.js          # 应用逻辑
      └── style.css       # 样式

  运行流程：
  1. recipe.py 扫描工作目录
  2. recipe.py 生成 config.json
  3. recipe.py 复制 assets 到 viewer/content/{id}/
  4. recipe.py 通过 {{frago_launcher}} chrome navigate 打开浏览器
  5. UI 通过 HTTP API 与 frago server 交互

## recipe.md 要求

必须包含 interactive tag：

  tags:
    - interactive
    - workflow

inputs 中通常需要 dir（工作目录路径）。
outputs 中通常有 url 和 content_id。

## recipe.py 核心结构

  FRAGO_HOME = Path.home() / '.frago'
  VIEWER_CONTENT_DIR = FRAGO_HOME / 'viewer' / 'content'
  UI_ASSETS_DIR = Path(__file__).parent / 'assets'

  关键函数：
  - generate_content_id(dir_path) — 用 sha256 生成唯一 ID
  - setup_viewer_content(content_id, dir_path, files) — 复制 assets + 生成 config.json
  - ensure_chrome_running() — 确认 Chrome CDP 可用
  - open_browser(url) — 通过 {{frago_launcher}} chrome navigate 打开

  标准输出格式：
  {"success": true, "url": "http://127.0.0.1:8093/viewer/content/{id}/index.html", "content_id": "...", "browser_opened": true}

## API 交互模式

API 基地址：http://127.0.0.1:8093/api

### 读文件

  const resp = await fetch(`${API_BASE}/file?path=${encodeURIComponent(filePath)}`);
  const data = await resp.json();

  // 二进制文件（图片等）直接作为 src
  img.src = `${API_BASE}/file?path=${encodeURIComponent(imagePath)}`;

### 写文件

  await fetch(`${API_BASE}/file?path=${encodeURIComponent(filePath)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON.stringify(data, null, 2) })
  });

### 调用 Recipe

  const resp = await fetch(`${API_BASE}/recipes/${recipeName}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params: { key: 'value' } })
  });

## UI 状态管理

### Auto-Save 模式

  let autoSaveTimeout = null;
  function autoSave() {
    if (autoSaveTimeout) clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(saveProject, 2000);
  }
  // 每次状态变更后调用 autoSave()

### 键盘快捷键

  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    switch (e.key.toLowerCase()) {
      case 's': if (e.ctrlKey || e.metaKey) { e.preventDefault(); saveProject(); } break;
    }
  });

## 前置条件

1. frago server 运行中：{{frago_launcher}} server（端口 8093）
2. Chrome CDP 可用：{{frago_launcher}} chrome start
3. 工作目录存在：recipe.py 启动时验证

## 创建检查清单

- recipe.md 含 interactive tag
- recipe.py 用标准 content_id 生成
- recipe.py 复制 assets 到 viewer/content/
- recipe.py 生成含 apiBase 的 config.json
- UI 在 DOMContentLoaded 加载 config.json
- UI 用 /api/file 读写数据
- UI 实现 auto-save
- UI 有常用操作的键盘快捷键
- 从 UI 调用的 recipe 声明在 dependencies 中
