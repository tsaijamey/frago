/**
 * 事务状态的圆圈记号，清单行首和详情属性表共用一套。
 *
 * 形状本身就分得开四档（空圈、带点、打勾、斜杠），不靠颜色也认得出；圆圈旁边没有字的
 * 地方（清单行首），状态名留给读屏和悬停提示。
 */

import { useTranslation } from 'react-i18next';
import { Circle, CircleCheck, CircleDot, CircleSlash } from 'lucide-react';
import type { TodoStatus } from '@/api';

const ICONS = {
  todo: Circle,
  doing: CircleDot,
  done: CircleCheck,
  dropped: CircleSlash,
} satisfies Record<TodoStatus, typeof Circle>;

interface TodoStatusIconProps {
  status: TodoStatus;
  /** 旁边已经写了状态名时传 true，免得读屏念两遍。 */
  decorative?: boolean;
}

export default function TodoStatusIcon({ status, decorative = false }: TodoStatusIconProps) {
  const { t } = useTranslation();
  const Icon = ICONS[status];
  const label = t(`todos.status.${status}`);

  return (
    <span className={`tdp-status tdp-status--${status}`} title={decorative ? undefined : label}>
      <Icon size={16} strokeWidth={2} aria-hidden="true" />
      {!decorative && <span className="sr-only">{label}</span>}
    </span>
  );
}
