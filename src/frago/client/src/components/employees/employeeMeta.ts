/**
 * 员工卡片上那点「从已有数据推出来」的判读，全是纯函数。
 *
 * 独立成文件而不塞进页面：页面本身已经很长，这几样又要单测，放在不碰 React 的地方才好
 * 直接喂字符串。
 */

import type { EmployeePost } from '@/hooks/useEmployees';

/**
 * 卡片左上那个缩写。
 *
 * 编号是英文 slug（`stock`、`a_stock_dma`），所以缩写稳定、换一版界面也不会变；拿标题去算
 * 则会随人改名字一起变，而人改名字只是换个说法，不是换一个岗位。
 *
 * 两段以上取各段首字母（`a_stock_dma` → `ASD`），一段的取前三个字符（`stock` → `STO`）。
 * 一个字母数字都没有时退回编号本身的大写形式，兜底到空串会让卡片上出现一个空白方块。
 */
export function employeeInitials(memberPostId: string): string {
  const raw = String(memberPostId ?? '').trim();
  const parts = raw.split(/[_\-.]/).filter(Boolean);
  if (parts.length >= 2) {
    const letters = parts.map((p) => p.replace(/[^a-zA-Z0-9]/g, '').charAt(0)).filter(Boolean);
    if (letters.length >= 2) return letters.slice(0, 3).join('').toUpperCase();
  }
  const single = (parts[0] ?? '').replace(/[^a-zA-Z0-9]/g, '');
  if (single.length >= 3) return single.slice(0, 3).toUpperCase();
  if (single.length > 0) return single.toUpperCase();
  return raw.replace(/[^a-zA-Z0-9]/g, '').slice(0, 3).toUpperCase();
}

/**
 * 卡片上那一行职责摘要。
 *
 * **卡片表面只放一行。** 从前那一版把 `work_scope` 原文整段铺在卡片上——那段文字是几百字的
 * 岗位说明，一铺上去每张卡片都变成一堵墙，人一眼扫不出本机有几个岗位、各管什么。摘要取
 * `description` 的第一句（到第一个句号/分号/冒号/换行截断），它本来就是照着「一句话说清这个
 * 人管什么」写的。
 *
 * 冒号也算断句：中文职责常常写成「总述：①…②…」，冒号后面是列举，前面那一截才是那句话。
 * 不在这里断的话，卡片上那一行会被 CSS 从列举中间切开，读起来像半句话。
 *
 * 没有 `description` 时退回 `work_scope` 的第一句；两栏都空就回空串，卡片上那一行整个不渲染
 * ——留一行占位的灰字只会让人以为没加载出来。
 */
export function employeeSummary(post: Pick<EmployeePost, 'description' | 'work_scope'>): string {
  const source = (post.description || '').trim() || (post.work_scope || '').trim();
  if (!source) return '';
  const cut = source.search(/[。；;：:.!\n]/);
  const first = cut === -1 ? source : source.slice(0, cut);
  return first.trim();
}

/** 内核名字显示成人看得懂的样子。认不出的原样返回，不猜近似的。 */
const KERNEL_LABEL: Record<string, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  opencode: 'opencode',
  agy: 'Antigravity',
  coreagent: 'CoreAgent',
  gemini: 'Gemini',
  cursor: 'Cursor',
};

export function kernelLabel(kernel: string): string {
  const key = String(kernel ?? '').trim();
  return KERNEL_LABEL[key] ?? key;
}
