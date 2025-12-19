# HTML/reveal.js 详细参考

## CSS 高级设计技巧

### 1. 背景设计

#### 纯色背景

```html
<section data-background="#4d7e65">
```

#### 渐变背景

```html
<section data-background="linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
```

#### 图片背景

```html
<section
    data-background="./images/bg.jpg"
    data-background-size="cover"
    data-background-opacity="0.3">
```

#### 视频背景

```html
<section data-background-video="./videos/bg.mp4" data-background-video-loop>
```

---

### 2. 层次感设计

#### 多层叠加（z-index）

```html
<section>
    <style>
        .layer-bg { position: absolute; inset: 0; z-index: 1; }
        .layer-decoration { position: absolute; z-index: 5; }
        .layer-content { position: relative; z-index: 10; }
    </style>
    <div class="layer-bg">背景层</div>
    <div class="layer-decoration">装饰层</div>
    <div class="layer-content">内容层</div>
</section>
```

#### 景深效果

```html
<style>
    .slides { transform-style: preserve-3d; perspective: 1000px; }
    .front { transform: translateZ(50px); }
    .back { transform: translateZ(-50px); opacity: 0.5; }
</style>
```

---

### 3. 多边形元素（clip-path）

#### 三角形

```css
.triangle {
    clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
}
```

#### 六边形

```css
.hexagon {
    clip-path: polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%);
}
```

#### 斜角

```css
.skewed {
    clip-path: polygon(0 0, 100% 0, 100% 80%, 0 100%);
}
```

#### 圆角矩形

```css
.rounded-box {
    clip-path: inset(0 round 20px);
}
```

---

### 4. 遮罩效果

#### 渐变遮罩

```css
.mask-gradient {
    -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
    mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
}
```

#### 径向遮罩

```css
.mask-radial {
    -webkit-mask-image: radial-gradient(circle, black 30%, transparent 70%);
    mask-image: radial-gradient(circle, black 30%, transparent 70%);
}
```

---

### 5. 动画效果

#### Auto-Animate（页间自动动画）

```html
<section data-auto-animate>
    <h1 style="margin-top: 100px;">标题</h1>
</section>
<section data-auto-animate>
    <h1 style="margin-top: 0;">标题</h1>
    <p>新内容自动出现</p>
</section>
```

#### 自定义 CSS 动画

```html
<style>
    @keyframes float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-10px); }
    }
    .floating { animation: float 3s ease-in-out infinite; }
</style>
<div class="floating">漂浮元素</div>
```

#### 脉冲效果

```css
@keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.05); opacity: 0.8; }
}
.pulse { animation: pulse 2s ease-in-out infinite; }
```

---

### 6. 响应式布局

#### r-stack（居中叠加）

```html
<div class="r-stack">
    <img class="fragment" src="1.png">
    <img class="fragment" src="2.png">
    <img class="fragment" src="3.png">
</div>
```

#### r-hstack（横向排列）

```html
<div class="r-hstack">
    <div>左</div>
    <div>中</div>
    <div>右</div>
</div>
```

#### r-vstack（纵向排列）

```html
<div class="r-vstack">
    <div>上</div>
    <div>中</div>
    <div>下</div>
</div>
```

#### Grid 布局

```css
.grid-2x2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 20px;
    height: 80%;
}
```

---

### 7. 装饰元素

#### 发光圆点

```css
.glow-dot {
    width: 200px;
    height: 200px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(233,69,96,0.4) 0%, transparent 70%);
    filter: blur(40px);
    position: absolute;
}
```

#### 渐变边框

```css
.gradient-border {
    border: 3px solid transparent;
    background:
        linear-gradient(#0d1117, #0d1117) padding-box,
        linear-gradient(90deg, #e94560, #58a6ff) border-box;
    border-radius: 12px;
}
```

#### 玻璃态效果

```css
.glass {
    background: rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 16px;
}
```

---

## pywebview 限制清单

### 与标准浏览器的核心差异

| 类别 | 限制 | 影响 |
|------|------|------|
| **渲染引擎** | 平台不统一 | macOS 用 WebKit，Windows 用 Edge，Linux 用 GTK WebKit |
| **调试工具** | 无 DevTools | 无法 F12 调试 |
| **控制台** | console.log 不可见 | 无法查看日志 |
| **热重载** | 不支持 | 需退出重启预览 |
| **脚本注入** | 受限 | frago view 自动注入所需库 |
| **iframe** | 安全限制 | 无法嵌入外部页面 |
| **跨域请求** | 受限 | Ajax 调用不可用 |
| **外部字体** | CDN 可能失败 | 使用本地字体 |

### 规避方案

| 需求 | 规避方式 |
|------|---------|
| 调试 CSS/HTML | 先在 Chrome 中调试，确认后再 `frago view` |
| 查看日志 | 使用 `alert()` 或写入页面元素 |
| 跨平台一致性 | 使用标准 CSS，避免实验性特性 |
| 字体一致性 | 使用系统字体栈或本地 Web 字体 |
| 复杂交互 | CSS 动画替代 JavaScript |

### 推荐做法

1. **CSS 优先**：复杂效果用 CSS 实现，避免依赖 JavaScript
2. **本地资源**：图片、字体放在 `images/`、`assets/` 目录
3. **相对路径**：使用 `./images/xxx.png` 而非绝对路径
4. **标准特性**：使用广泛支持的 CSS 特性
5. **静态内容**：frago view 适合静态展示，不适合交互式应用

---

## 颜色参考

### 常用配色

| 用途 | 颜色 | Hex |
|------|------|-----|
| 强调色（红） | 珊瑚红 | `#e94560` |
| 强调色（蓝） | 天蓝 | `#58a6ff` |
| 强调色（紫） | 紫罗兰 | `#a855f7` |
| 强调色（绿） | 翡翠绿 | `#10b981` |
| 强调色（橙） | 琥珀橙 | `#f59e0b` |
| 背景深色 | 深灰 | `#0d1117` |
| 背景次深 | 中灰 | `#161b22` |
| 文字主色 | 浅灰 | `#c9d1d9` |
| 文字次色 | 暗灰 | `#8b949e` |
| 边框 | 边框灰 | `#30363d` |

### 渐变组合

```css
/* 紫红渐变 */
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

/* 深蓝渐变 */
background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);

/* 日落渐变 */
background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);

/* 海洋渐变 */
background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
```

---

## 字体栈

### 系统字体（推荐）

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Helvetica Neue", Arial, sans-serif;
```

### 代码字体

```css
font-family: "SF Mono", "Fira Code", Consolas, "Liberation Mono",
             Menlo, monospace;
```
