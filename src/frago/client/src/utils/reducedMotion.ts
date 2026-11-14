/**
 * 系统「减弱动态效果」开关的 JS 侧读数。
 *
 * `globals.css` 里那条 `@media (prefers-reduced-motion: reduce)` 兜底只压得住 CSS 动画
 * 与 CSS 过渡。**JS 主动发起的平滑滚动它管不到**——`scrollTo({ behavior: 'smooth' })`
 * 与 `scrollIntoView({ behavior: 'smooth' })` 是浏览器自己走的一条动画，不经过样式表。
 * 记录流里三处「滚到某条记录」正是这么写的：开着减弱动效的人点一下跳转，屏幕照样
 * 滑过去一大段，是这一档里最晕人的那种动。
 *
 * 所以这里给一个读数，让 JS 侧也能问一句「现在要不要走动画」。
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  if (typeof window.matchMedia !== 'function') return false;
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    // 老浏览器或测试环境里 matchMedia 可能不接受这条查询：读不出来就当没开，
    // 走原来的动画，而不是把跳转整个吞掉。
    return false;
  }
}

/**
 * 平滑滚动的 `behavior` 取值：开着减弱动效时给 `'auto'`（一步到位，无动画），
 * 否则 `'smooth'`。
 *
 * 注意是 `'auto'` 不是 `'instant'`：`'auto'` 在所有浏览器里都受支持，`'instant'`
 * 是后加的，老引擎会当成无效值退回默认行为——那还不如直接写清楚。
 */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? 'auto' : 'smooth';
}
