# Quick Start: Vite React 前端开发

## 前置要求

- Node.js >= 18.x
- Python >= 3.9
- uv（Python 包管理器）

## 开发环境设置

### 1. 初始化前端项目

```bash
cd src/frago/gui/frontend

# 使用 pnpm（推荐）
pnpm install

# 或使用 npm
npm install
```

### 2. 启动开发服务器

需要两个终端：

**终端 1：Vite 开发服务器**
```bash
cd src/frago/gui/frontend
pnpm dev
# 运行在 http://localhost:5173
```

**终端 2：pywebview GUI**
```bash
FRAGO_GUI_DEV=1 uv run frago --gui --debug
```

### 3. 开发流程

1. 修改 `frontend/src/` 下的组件
2. 保存后 Vite HMR 自动刷新界面
3. TypeScript 类型错误在编辑器中实时显示

## 生产构建

```bash
cd src/frago/gui/frontend

# 构建
pnpm build
# 输出到 ../assets/

# 测试生产版本
uv run frago --gui
```

## 目录结构

```
frontend/
├── src/
│   ├── main.tsx           # React 入口
│   ├── App.tsx            # 根组件
│   ├── api/
│   │   └── pywebview.ts   # API 封装
│   ├── stores/
│   │   └── appStore.ts    # Zustand 状态
│   ├── components/
│   │   ├── layout/        # 布局组件
│   │   ├── tasks/         # 任务相关
│   │   ├── recipes/       # 配方相关
│   │   ├── skills/        # 技能相关
│   │   ├── settings/      # 设置页面
│   │   └── ui/            # 通用 UI
│   ├── hooks/             # 自定义 Hooks
│   └── styles/            # 全局样式
├── package.json
├── vite.config.ts
├── tsconfig.json
└── tailwind.config.js
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `pnpm dev` | 启动开发服务器 |
| `pnpm build` | 生产构建 |
| `pnpm preview` | 预览构建结果 |
| `pnpm lint` | 代码检查 |
| `pnpm type-check` | TypeScript 类型检查 |

## API 使用

```typescript
// 等待 pywebview 就绪
useEffect(() => {
  const handleReady = async () => {
    if (window.pywebview?.api) {
      const config = await window.pywebview.api.get_config();
      setConfig(config);
    }
  };

  window.addEventListener('pywebviewready', handleReady);
  return () => window.removeEventListener('pywebviewready', handleReady);
}, []);

// 调用 API
const tasks = await window.pywebview?.api.get_tasks();
const detail = await window.pywebview?.api.get_task_detail(sessionId);
```

## 主题切换

```typescript
// 应用主题
const applyTheme = (theme: 'dark' | 'light') => {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  localStorage.setItem('theme', theme);
};

// 初始化主题
const initTheme = () => {
  const saved = localStorage.getItem('theme');
  const system = window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
  applyTheme(saved || system);
};
```

## 注意事项

1. **类型安全**：所有 API 调用使用 `contracts/pywebview-api.ts` 中定义的类型
2. **异步调用**：所有 `window.pywebview.api` 方法都是异步的
3. **日期处理**：后端返回 ISO 8601 字符串，前端用 `new Date()` 转换
4. **错误处理**：API 返回 `{ error: string }` 表示错误
