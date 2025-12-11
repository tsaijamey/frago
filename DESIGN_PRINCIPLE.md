# 设计原则

## 1. 设计理念
- **简洁高效**：界面元素精简，突出核心功能
- **一致性**：保持组件、交互和视觉风格的一致性
- **可访问性**：确保所有用户都能无障碍使用
- **响应式**：适配不同设备尺寸
- **暗黑模式**：提供完整的暗黑主题支持

## 2. 色彩系统
### 颜色变量使用规范
- 所有页面所使用的样式类，凡是涉及颜色的，仅允许使用`web/src/styles/globals.css`中预定义的颜色变量
- 禁止硬编码颜色值(如`#FFFFFF`、`rgb(255,255,255)`等)
- 禁止使用Tailwind预定义的颜色类(如`bg-red-500`、`text-blue-400`等)

### 主色系
- 前景色: `var(--foreground)` (文本)
- 背景色: `var(--background)` (背景)
- 强调色: `var(--accent)` (主按钮hover状态)

### 辅助色
- 代码块背景: `var(--code-bg)`
- 边框色: `var(--border)`
- 次按钮hover背景: `var(--secondary-hover)`

## 3. 排版系统
### 字体
- 主字体: Geist Sans (--font-geist-sans)
- 代码/辅助文本: Geist Mono (--font-geist-mono)

### 字号
- 正文: 14px/1.5 (移动端), 16px/1.5 (桌面端)
- 小文本: 12px/1.5
- 标题: 根据层级使用相应比例

## 4. 间距系统
- 基础单位: 4px
- 常用间距:
  - 小: 8px
  - 中: 16px
  - 大: 24px
  - 超大: 32px

## 5. 组件设计规范
### 按钮
- 主按钮:
  - 圆角: 9999px (完全圆形)
  - 内边距: 水平16px/垂直10px (移动端), 水平20px/垂直12px (桌面端)
  - 交互状态: 背景色变化 + 平滑过渡

### 链接
- 下划线: hover时显示，偏移4px
- 图标间距: 8px

### 列表
- 列表项: 左边距16px，项目符号为数字
- 行间距: 6px

## 6. 交互状态
- hover: 背景/颜色变化，持续时间200ms
- focus: 清晰可见的轮廓
- active: 适度的按压效果

## 7. 滚动条
- 宽度: 2px（超细）
- 颜色: 使用反差色
  - 深色模式: 滑块 `var(--text-muted)`，轨道透明
  - 浅色模式: 滑块 `var(--border-color)`，轨道透明
- hover: 宽度扩展至 6px
- 圆角: 1px

## 8. 响应式策略
- 断点: sm (640px), md (768px), lg (1024px)
- 布局变化:
  - 移动端: 垂直堆叠
  - 桌面端: 水平排列
- 字体大小: 根据视口调整

## 9. 图标系统
- **图标库**: Lucide React（唯一允许）
- **风格**: 扁平线条图标，禁止彩色图标和 emoji
- **尺寸**: 16px / 20px / 24px 三种标准尺寸
- **颜色**: 仅继承父级文本颜色（currentColor）
- **粗细**: strokeWidth 默认 2，可调整为 1.5

## 10. 开发实施
1. **样式方案**:
   - 使用TailwindCSS工具类优先
   - 复杂组件可使用CSS模块
   - 全局样式定义在`/web/src/styles/globals.css`

2. **设计标记**:
```tsx
// 按钮示例
<a className="rounded-full border border-solid border-transparent 
  transition-colors flex items-center justify-center 
  bg-foreground text-background gap-2 
  hover:bg-[#383838]
  font-medium text-sm sm:text-base 
  h-10 sm:h-12 px-4 sm:px-5 sm:w-auto">
  <Image className="dark:invert" />
  按钮文本
</a>
```

3. **设计资源**:
- Figma设计稿链接: [待补充]
- 图标库: 项目内`/public`目录
- 字体: 通过CSS变量引入