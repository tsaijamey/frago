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

/** 摘要里的一段：普通文字，还是被反引号圈起来的词。 */
export interface SummaryPart {
  text: string;
  code: boolean;
}

/**
 * 把摘要里成对反引号圈起来的词切成代码段，其余照旧。
 *
 * 岗位说明里常写成「负责 `frago` 与 `frago-core` 两套代码」。这些反引号是 Markdown 的
 * 写法，铺到卡片上就成了字面量——屏幕上散着几个反引号字符，两行一截断更像排版漏了没清。
 * 这里把它们拆出来交给界面渲染成微样式代码词，卡片表面就只剩干净的词。
 *
 * **没有成对反引号时原样返回一段**，不做任何改动：摘要的纯文本分支必须是一个整体，
 * 拆成多个节点会让「按整句找这一段」的调用方找不到它。
 */
export function employeeSummaryParts(summary: string): SummaryPart[] {
  const raw = summary ?? '';
  if (!raw.includes('`')) return raw ? [{ text: raw, code: false }] : [];
  const parts: SummaryPart[] = [];
  const re = /`([^`]+)`/g;
  let at = 0;
  let hit: RegExpExecArray | null;
  while ((hit = re.exec(raw)) !== null) {
    if (hit.index > at) parts.push({ text: raw.slice(at, hit.index), code: false });
    parts.push({ text: hit[1], code: true });
    at = hit.index + hit[0].length;
  }
  if (at < raw.length) parts.push({ text: raw.slice(at), code: false });
  return parts;
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

/**
 * Employee 双色系映射色板（Chrome / Edge 外观主题选色技巧：深浅色分别配置两套独立颜色体系并建立 1:1 映射关系）。
 *
 * 与服务端 `frago.employee.store.VALID_EMPLOYEE_COLORS` 完全对齐。
 */
export type EmployeeColorId =
  | 'ocean'
  | 'violet'
  | 'amber'
  | 'coral'
  | 'cyan'
  | 'rose'
  | 'plum'
  | 'slate';

export interface EmployeeColorMeta {
  id: EmployeeColorId;
  labelKey: string;
  defaultLabel: string;
  darkBg: string;
  darkFg: string;
  darkBorder: string;
  lightBg: string;
  lightFg: string;
  lightBorder: string;
}

export const EMPLOYEE_COLORS: readonly EmployeeColorMeta[] = [
  {
    id: 'ocean',
    labelKey: 'employees.colors.ocean',
    defaultLabel: 'Ocean Blue',
    darkBg: '#1f3a68',
    darkFg: '#e2eeff',
    darkBorder: 'rgba(96, 152, 245, 0.28)',
    lightBg: '#d8e8ff',
    lightFg: '#15356e',
    lightBorder: 'rgba(37, 99, 235, 0.22)',
  },
  {
    id: 'violet',
    labelKey: 'employees.colors.violet',
    defaultLabel: 'Royal Violet',
    darkBg: '#362863',
    darkFg: '#ece4ff',
    darkBorder: 'rgba(158, 126, 248, 0.28)',
    lightBg: '#e7deff',
    lightFg: '#392075',
    lightBorder: 'rgba(109, 64, 212, 0.22)',
  },
  {
    id: 'amber',
    labelKey: 'employees.colors.amber',
    defaultLabel: 'Warm Amber',
    darkBg: '#523612',
    darkFg: '#ffebd0',
    darkBorder: 'rgba(235, 168, 68, 0.30)',
    lightBg: '#fde6be',
    lightFg: '#663806',
    lightBorder: 'rgba(180, 105, 14, 0.24)',
  },
  {
    id: 'coral',
    labelKey: 'employees.colors.coral',
    defaultLabel: 'Terracotta Coral',
    darkBg: '#58281e',
    darkFg: '#ffe3dc',
    darkBorder: 'rgba(240, 118, 92, 0.28)',
    lightBg: '#ffded4',
    lightFg: '#752312',
    lightBorder: 'rgba(204, 68, 40, 0.22)',
  },
  {
    id: 'cyan',
    labelKey: 'employees.colors.cyan',
    defaultLabel: 'Glacier Cyan',
    darkBg: '#17424d',
    darkFg: '#daf5fb',
    darkBorder: 'rgba(72, 184, 210, 0.28)',
    lightBg: '#d2f1f8',
    lightFg: '#0f4654',
    lightBorder: 'rgba(14, 132, 163, 0.22)',
  },
  {
    id: 'rose',
    labelKey: 'employees.colors.rose',
    defaultLabel: 'Crimson Rose',
    darkBg: '#54213a',
    darkFg: '#ffe0ee',
    darkBorder: 'rgba(236, 108, 168, 0.28)',
    lightBg: '#ffdbe9',
    lightFg: '#731842',
    lightBorder: 'rgba(194, 48, 114, 0.22)',
  },
  {
    id: 'plum',
    labelKey: 'employees.colors.plum',
    defaultLabel: 'Velvet Plum',
    darkBg: '#4a234f',
    darkFg: '#f8e0fc',
    darkBorder: 'rgba(208, 118, 222, 0.28)',
    lightBg: '#f6dcf9',
    lightFg: '#5e1d66',
    lightBorder: 'rgba(162, 56, 176, 0.22)',
  },
  {
    id: 'slate',
    labelKey: 'employees.colors.slate',
    defaultLabel: 'Nordic Slate',
    darkBg: '#2b3644',
    darkFg: '#e3eaf2',
    darkBorder: 'rgba(138, 162, 192, 0.26)',
    lightBg: '#dfe6ef',
    lightFg: '#243242',
    lightBorder: 'rgba(71, 95, 122, 0.22)',
  },
];

const EMPLOYEE_COLOR_IDS = EMPLOYEE_COLORS.map((c) => c.id);

const PRESET_EMPLOYEE_COLORS: Record<string, EmployeeColorId> = {
  stock: 'amber',
  'jira-guardian': 'ocean',
  'frago-developer': 'violet',
  'frago-webui': 'cyan',
  'feishu-ops': 'coral',
};

/** 与服务端 `default_employee_color` 完全同构的确定性默认色计算。 */
export function defaultEmployeeColor(memberPostId: string): EmployeeColorId {
  const cleaned = String(memberPostId ?? '').trim().toLowerCase();
  if (cleaned in PRESET_EMPLOYEE_COLORS) {
    return PRESET_EMPLOYEE_COLORS[cleaned];
  }
  if (!cleaned) return EMPLOYEE_COLOR_IDS[0];
  let h = 0;
  for (let i = 0; i < cleaned.length; i += 1) {
    h = (Math.imul(h, 31) + cleaned.charCodeAt(i)) >>> 0;
  }
  return EMPLOYEE_COLOR_IDS[h % EMPLOYEE_COLOR_IDS.length];
}

export function resolveEmployeeColor(
  color: string | null | undefined,
  memberPostId?: string | null
): EmployeeColorId {
  const cleaned = String(color ?? '').trim().toLowerCase() as EmployeeColorId;
  if (EMPLOYEE_COLOR_IDS.includes(cleaned)) {
    return cleaned;
  }
  return defaultEmployeeColor(memberPostId ?? '');
}

export function getEmployeeColorMeta(
  color: string | null | undefined,
  memberPostId?: string | null
): EmployeeColorMeta {
  const resolved = resolveEmployeeColor(color, memberPostId);
  return EMPLOYEE_COLORS.find((c) => c.id === resolved) ?? EMPLOYEE_COLORS[0];
}
