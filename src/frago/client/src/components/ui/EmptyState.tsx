import { Inbox, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  Icon?: LucideIcon;
  title: string;
  /** 一行说明。超过一行的长句不收在这里，收进详情。 */
  description?: string;
  /** 可选主动作槽位：空态里唯一那个能点出去的地方。 */
  action?: ReactNode;
}

/**
 * 全站统一空态。
 *
 * 尺度由 `.empty-state*` 那一组类定：40px 微边框图标容器 + 13px 标题 + 12px 说明。
 * 各页不要再自己画空态——此前会话栏、文件栏、工作区各有一套尺寸，
 * 同一个「这儿暂时没东西」在三个页面上长得三样，人每换一页都要重新认一遍。
 */
export default function EmptyState({ Icon = Inbox, title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        <Icon size={20} strokeWidth={1.5} />
      </div>
      <div className="empty-state-title">{title}</div>
      {description && <div className="empty-state-description">{description}</div>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
