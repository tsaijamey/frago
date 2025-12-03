# 选择器优先级规则

适用于：`/frago.recipe`

## 优先级排序

在生成 JavaScript 时，按此优先级排序选择器（5 最高，1 最低）：

| 优先级 | 类型 | 示例 | 稳定性 | 说明 |
|--------|------|------|--------|------|
| **5** | ARIA 标签 | `[aria-label="按钮"]` | ✅ 很稳定 | 无障碍属性，极少改变 |
| **5** | data 属性 | `[data-testid="submit"]` | ✅ 很稳定 | 专门用于测试 |
| **4** | 稳定 ID | `#main-button` | ✅ 稳定 | 语义化 ID 名称 |
| **3** | 语义化类名 | `.btn-primary` | ⚠️ 中等 | BEM 规范类名 |
| **3** | HTML5 语义标签 | `button`, `nav` | ⚠️ 中等 | 标准语义标签 |
| **2** | 结构选择器 | `div > button` | ⚠️ 脆弱 | 依赖 DOM 结构 |
| **1** | 生成的类名 | `.css-abc123` | ❌ 很脆弱 | CSS-in-JS，随时变化 |

## 脆弱选择器识别

以下选择器应**尽量避免**或作为**最后降级选项**：

- `.css-*` 或 `._*` 开头的类名（CSS-in-JS 生成）
- 纯数字 ID：`#12345`
- 过长的 ID/类名（>20 字符）
- 深层嵌套的结构选择器：`div > div > div > span`

## 在配方中使用降级选择器

```javascript
// 辅助函数：按优先级尝试多个选择器
function findElement(selectors, description) {
  for (const sel of selectors) {
    const elem = document.querySelector(sel.selector);
    if (elem) return elem;
  }
  throw new Error(`无法找到${description}`);
}

// 使用示例：提供 2-3 个降级选择器
const elem = findElement([
  { selector: '[aria-label="提交"]', priority: 5 },      // 最稳定
  { selector: '[data-testid="submit-btn"]', priority: 5 },
  { selector: '#submit-button', priority: 4 },           // 降级
  { selector: '.btn-submit', priority: 3 }               // 再降级
], '提交按钮');
```

## 探索时验证选择器

在创建配方前，使用 frago 命令验证选择器有效性：

```bash
# 验证选择器是否存在
frago chrome exec-js "document.querySelector('[aria-label=\"提交\"]') !== null" --return-value

# 高亮元素确认位置
frago chrome highlight '[aria-label="提交"]'

# 获取元素文本确认内容
frago chrome exec-js "document.querySelector('[aria-label=\"提交\"]')?.textContent" --return-value
```

## 配方中的验证等待

每个操作步骤后，使用 `waitForElement` 验证结果：

```javascript
// 辅助函数：等待并验证元素出现
async function waitForElement(selector, description, timeout = 5000) {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    const elem = document.querySelector(selector);
    if (elem) return elem;
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error(`等待超时：${description} (${selector})`);
}

// 使用示例
elem.click();
await waitForElement('.result-panel', '结果面板出现');
```

## 常见网站的选择器特征

| 网站 | 推荐选择器类型 | 注意事项 |
|------|---------------|---------|
| YouTube | `aria-label`, `data-*` | 类名多为生成的 |
| Twitter/X | `data-testid`, `aria-label` | 类名极不稳定 |
| GitHub | ID, 语义化类名 | 相对稳定 |
| Upwork | `data-*`, 语义化类名 | 部分生成类名 |
