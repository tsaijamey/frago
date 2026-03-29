# selector-priority

分类: 效率（AVAILABLE）

## 是什么
选择器优先级规则，确保元素定位的稳定性和可维护性。优先使用语义化选择器，避免脆弱的路径依赖。

## 优先级（从高到低）
  1. aria-label    — 最稳定，不受布局变化影响
  2. data-testid   — 专为测试/自动化设计的属性
  3. id            — 唯一标识，但可能随构建变化
  4. role + text   — 语义化匹配，如 [role="button"]:has-text("Submit")
  5. class         — 最不稳定，频繁变化

## 怎么用
  frago chrome click '[aria-label="Submit"]'
  frago chrome click '[data-testid="login-btn"]'
  frago chrome click '#submit-button'

## 不要做
- 不要使用深层 CSS 路径（如 div > div > span.class > button）
- 不要使用 nth-child 选择器，除非没有其他选择
- 不要使用随构建工具变化的 hash class（如 .css-1a2b3c）
