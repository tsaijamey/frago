/**
 * 一个文件这一场是新建、改过，还是被删了——清单与浮窗顶上那枚标记的同一张表。
 *
 * 单独一个模块，是因为它在两个地方露脸：清单里是一枚字母（A / M / D），浮窗顶上写全称。
 * 同一个档次在两处的底色与名字若各写各的，改一处忘一处就会漂——一处说是新建、另一处还是
 * 老样子。放在这里，加一档只改这张表。
 *
 * 底色走的都是 CSS 变量（`--accent-info-10`、`--accent-error-10` 这些），不写死色值。
 * 颜色也从来不是唯一通道：字母、悬停里的全称、组头上那句「几个改的、几个新建的、几个删的」
 * 都在说同一件事。
 */

import type { SessionFileAction } from '@/types/api';

export interface FileBadge {
  /** 清单里的那一枚字母。 */
  letter: string;
  /** 全称的 i18n 键（`workbench.files.*`），悬停与浮窗顶上用它。 */
  label: string;
  /** 底色 + 字色，跟着上面那条 i18n 键一起换。 */
  tone: string;
}

export const FILE_BADGE: Record<SessionFileAction, FileBadge> = {
  created: {
    letter: 'A',
    label: 'workbench.files.created',
    tone: 'bg-accent-info-10 text-accent-info',
  },
  modified: {
    letter: 'M',
    label: 'workbench.files.modified',
    tone: 'bg-bg-hover text-text-secondary',
  },
  deleted: {
    letter: 'D',
    label: 'workbench.files.deleted',
    tone: 'bg-accent-error-10 text-accent-error',
  },
};
